# ctxpack

pack a repo into one file so you can paste the whole thing into a coding agent.

respects your .gitignore, skips binaries, prints a file tree up top and a
rough token estimate so you know what you're about to paste.

## usage

```bash
# dump current repo to stdout
python ctxpack.py

# save it
python ctxpack.py -o context.md

# pack some other repo
python ctxpack.py ~/projects/myapp -o myapp.md

# only pack what you're working on (staged, unstaged, untracked vs git)
python ctxpack.py --diff -o wip.md

# just see what would get packed
python ctxpack.py --list

# only python files
python ctxpack.py --include "*.py"

# skip tests too
python ctxpack.py --exclude "tests/*"

# plain text instead of markdown
python ctxpack.py --format txt -o context.txt
```

also reads `.ctxignore` if you want pack-specific ignores on top of
`.gitignore`.

## notes

- single file, stdlib only, no install
- files over 200KB are skipped (change with `--max-bytes`)
- token estimate is chars/4, rough but fine for sizing a prompt

## license

do whatever you want with it
