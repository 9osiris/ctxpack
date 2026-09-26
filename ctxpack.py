#!/usr/bin/env python3
"""ctxpack - bundle a repo into one file for pasting into a coding agent."""

import argparse
import fnmatch
import os
import subprocess
import sys
from pathlib import Path

CHARS_PER_TOKEN = 4  # rough guess, good enough for sizing a prompt
MAX_FILE_BYTES = 200 * 1024

DEFAULT_IGNORES = [
    ".git",
    "__pycache__",
    "*.pyc", "*.pyo",
    "node_modules",
    ".venv", "venv", ".env",
    "dist", "build", "*.egg-info",
    ".DS_Store", "Thumbs.db",
    "*.min.js", "*.map",
    ".idea", ".vscode",
]

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a",
    ".mp3", ".mp4", ".wav", ".ogg", ".flac",
    ".ttf", ".otf", ".woff", ".woff2",
    ".sqlite", ".db",
}

LANGS = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "jsx", ".tsx": "tsx", ".html": "html", ".css": "css",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".md": "markdown", ".sh": "bash", ".rs": "rust", ".go": "go",
    ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
    ".sql": "sql", ".xml": "xml", ".rb": "ruby",
}


def read_ignore_file(path):
    patterns = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line.rstrip("/"))
    except OSError:
        pass
    return patterns


def make_matcher(root, extra):
    # returns True if a relative path should be skipped
    patterns = list(DEFAULT_IGNORES)
    patterns += read_ignore_file(root / ".gitignore")
    patterns += read_ignore_file(root / ".ctxignore")
    patterns += extra

    def skip(rel):
        for pat in patterns:
            p = pat.lstrip("/")
            if "/" in p:
                if fnmatch.fnmatch(rel, p):
                    return True
            else:
                if any(fnmatch.fnmatch(part, p) for part in rel.split("/")):
                    return True
        return False

    return skip


def is_binary(path):
    if path.suffix.lower() in BINARY_EXTS:
        return True
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(8192)
    except OSError:
        return True


def collect(root, include, exclude, skip):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""
        # prune ignored dirs before descending
        dirnames[:] = [
            d for d in dirnames
            if not skip(f"{rel_dir}/{d}" if rel_dir else d)
        ]
        for name in filenames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if skip(rel):
                continue
            if include and not any(fnmatch.fnmatch(rel, p) for p in include):
                continue
            if exclude and any(fnmatch.fnmatch(rel, p) for p in exclude):
                continue
            full = Path(dirpath) / name
            try:
                size = full.stat().st_size
            except OSError:
                continue
            files.append((rel, full, size))
    files.sort(key=lambda t: t[0])
    return files


def filter_files(files, max_bytes):
    ok, skipped = [], []
    for rel, full, size in files:
        if size > max_bytes:
            skipped.append((rel, "too big"))
            continue
        if is_binary(full):
            skipped.append((rel, "binary"))
            continue
        try:
            text = full.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            skipped.append((rel, "unreadable"))
            continue
        ok.append((rel, text))
    return ok, skipped


def git_changed_files(root):
    # files changed vs HEAD: staged + unstaged + untracked
    if subprocess.run(["git", "-C", str(root), "rev-parse", "--git-dir"],
                      capture_output=True).returncode != 0:
        sys.exit(f"ctxpack: {root}: not a git repo, --diff needs one")
    changed = set()
    cmds = [
        ["git", "-C", str(root), "diff", "--name-only", "HEAD"],
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
    ]
    for cmd in cmds:
        r = subprocess.run(cmd, capture_output=True, text=True)
        changed.update(l for l in r.stdout.splitlines() if l)
    return changed


def render_tree(rels):
    lines = []
    seen = set()
    for rel in rels:
        parts = rel.split("/")
        for i in range(1, len(parts)):
            prefix = "/".join(parts[:i])
            if prefix not in seen:
                seen.add(prefix)
                lines.append("  " * (i - 1) + parts[i - 1] + "/")
        lines.append("  " * (len(parts) - 1) + parts[-1])
    return "\n".join(lines)


def pack(root, files, fmt, max_bytes, with_tree):
    ok, skipped = filter_files(files, max_bytes)
    total_chars = sum(len(text) for _, text in ok)

    out = []
    out.append(f"# context pack: {root.name}")
    out.append(f"{len(ok)} files, ~{total_chars // CHARS_PER_TOKEN} tokens (rough)")
    out.append("")
    if with_tree:
        out.append("## tree")
        out.append("")
        out.append(render_tree([rel for rel, _, _ in files]))
        out.append("")
    if skipped:
        out.append("## skipped")
        out.append("")
        for rel, why in skipped:
            out.append(f"- {rel} ({why})")
        out.append("")

    sep = "\n" if fmt == "md" else "\n\n"
    chunks = []
    for rel, text in ok:
        if fmt == "md":
            lang = LANGS.get(Path(rel).suffix.lower(), "")
            chunks.append(f"## {rel}\n\n```{lang}\n{text}\n```")
        else:
            chunks.append(f"===== {rel} =====\n\n{text}")
    return "\n".join(out).rstrip() + sep + sep.join(chunks)


def main():
    ap = argparse.ArgumentParser(
        description="pack a repo into one file for pasting into an agent")
    ap.add_argument("root", nargs="?", default=".",
                    help="repo root (default: cwd)")
    ap.add_argument("-o", "--out", help="write to file instead of stdout")
    ap.add_argument("--include", action="append", default=[],
                    help="only include files matching glob (repeatable)")
    ap.add_argument("--exclude", action="append", default=[],
                    help="also skip files matching glob (repeatable)")
    ap.add_argument("--no-ignore", action="store_true",
                    help="ignore .gitignore and defaults, pack everything")
    ap.add_argument("--no-tree", action="store_true",
                    help="skip the file tree in the header")
    ap.add_argument("--format", choices=["md", "txt"], default="md")
    ap.add_argument("--max-bytes", type=int, default=MAX_FILE_BYTES)
    ap.add_argument("--list", action="store_true",
                    help="just list the files that would be packed")
    ap.add_argument("--diff", action="store_true",
                    help="only pack files changed vs git (staged, unstaged, untracked)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"not a directory: {root}")

    skip = (lambda rel: False) if args.no_ignore else make_matcher(root, [])
    files = collect(root, args.include, args.exclude, skip)
    if args.diff:
        changed = git_changed_files(root)
        files = [f for f in files if f[0] in changed]

    if args.list:
        ok, skipped = filter_files(files, args.max_bytes)
        for rel, text in ok:
            print(f"{len(text):>8}  {rel}")
        for rel, why in skipped:
            print(f"   skipped  {rel} ({why})")
        return

    body = pack(root, files, args.format, args.max_bytes,
                with_tree=not args.no_tree)
    if args.out:
        Path(args.out).write_text(body, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(body)


if __name__ == "__main__":
    main()
