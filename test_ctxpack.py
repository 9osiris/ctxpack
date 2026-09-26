#!/usr/bin/env python3
# tests for ctxpack. run with: python3 test_ctxpack.py

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import ctxpack

PY = sys.executable

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"ok - {name}")
    else:
        failed += 1
        print(f"FAIL - {name}")


def run_cli(*args, cwd=None, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([PY, str(HERE / "ctxpack.py"), *args],
                          capture_output=True, text=True, cwd=cwd, env=e)


def make_tree():
    d = Path(tempfile.mkdtemp())
    (d / "a.py").write_text("x = 1\n" * 100)  # 600 chars
    (d / "b.txt").write_text("hello\n" * 20)  # 120 chars
    sub = d / "sub"
    sub.mkdir()
    (sub / "c.py").write_text("y = 2\n")  # 6 chars
    return d


# unit: token table math and ordering
rows = [("small.py", "ab"), ("big.py", "x" * 400)]
table = ctxpack.token_table(rows)
lines = table.splitlines()
check("token table sorts biggest first",
      lines[0].split() == ["100", "big.py"])
check("token table total row",
      lines[-1].endswith("total (2 files)") and lines[-1].split()[0] == "100")
check("token table has separator", any(set(l.split()[0]) == {"-"} for l in lines))

# unit: matcher and collect still fine
d = make_tree()
skip = ctxpack.make_matcher(d, [])
files = ctxpack.collect(d, [], [], skip)
check("collect finds three files", len(files) == 3)
ok, skipped = ctxpack.filter_files(files, ctxpack.MAX_FILE_BYTES)
check("filter keeps text files", len(ok) == 3 and not skipped)

# cli: --tokens prints a per-file table, not the bundle
r = run_cli("--tokens", str(d))
check("--tokens exits 0", r.returncode == 0)
check("--tokens lists a.py", "a.py" in r.stdout)
check("--tokens total matches chars//4",
      r.stdout.strip().splitlines()[-1].split()[0] == str(726 // 4))
check("--tokens does not print the bundle", "```" not in r.stdout)

# cli: --tokens with -o does not write a file (alternate mode like --list)
out = d / "t.md"
r = run_cli("--tokens", "-o", str(out), str(d))
check("--tokens ignores -o", r.returncode == 0 and not out.exists())

# cli: --list still works
r = run_cli("--list", str(d))
check("--list shows files", "a.py" in r.stdout and r.returncode == 0)

# cli: --copy with a fake clipboard tool on PATH
bindir = Path(tempfile.mkdtemp())
clip_out = bindir / "clipboard.txt"
fake = bindir / "pbcopy"
fake.write_text(f"#!/bin/sh\n/bin/cat > {clip_out}\n")
fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
r = run_cli("--copy", str(d), env={"PATH": str(bindir)})
check("--copy exits 0", r.returncode == 0)
check("--copy put the bundle on the clipboard",
      clip_out.exists() and "## a.py" in clip_out.read_text())
check("--copy does not print the bundle", "## a.py" not in r.stdout)
check("--copy prints a confirmation", "copied to clipboard" in r.stdout)

# cli: --copy plus -o writes the file and copies
out = d / "bundle.md"
r = run_cli("--copy", "-o", str(out), str(d), env={"PATH": str(bindir)})
check("--copy with -o writes the file", out.exists())
check("--copy with -o still copies", "## a.py" in clip_out.read_text())

# cli: --copy with no clipboard tool anywhere is a clear error
emptydir = Path(tempfile.mkdtemp())
r = run_cli("--copy", str(d), env={"PATH": str(emptydir)})
check("--copy with no tool fails", r.returncode != 0)
check("--copy with no tool names the tried tools",
      "no clipboard tool found" in r.stderr
      and "pbcopy" in r.stderr and "xclip" in r.stderr)

# cli: --diff outside a git repo is a clear error
r = run_cli("--diff", str(d))
check("--diff outside git fails", r.returncode != 0)
check("--diff outside git says why", "not a git repo" in r.stderr)

# cli: --diff inside a git repo packs only changed files
if shutil.which("git"):
    g = Path(tempfile.mkdtemp())
    (g / "keep.py").write_text("k = 1\n")
    (g / "change.py").write_text("c = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=g, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=g, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=g, check=True)
    subprocess.run(["git", "add", "."], cwd=g, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=g, check=True)
    (g / "change.py").write_text("c = 2\n")
    (g / "new.py").write_text("n = 3\n")
    r = run_cli("--diff", "--list", str(g))
    check("--diff packs changed files",
          r.returncode == 0 and "change.py" in r.stdout and "new.py" in r.stdout)
    check("--diff skips unchanged files", "keep.py" not in r.stdout)
else:
    print("skip - git not on path (2 checks)")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
