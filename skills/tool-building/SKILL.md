---
name: tool-building
description: Find, reuse, or build an org tool. Read this when you are about to do by hand something you (or anyone in the org) will do again, or when the [tools] nudge points here.
---

# Tool-building

In this org a tool's value is **compression × usage**. It's worth the context it saves each
caller, times how many callers actually use it. A tool nobody calls is worth 0, however clever
it is, and usage by *others* is what counts (your own calls are discounted). So the order is
always: **find → reuse → extend → build**, and build only what will be called again.

## 1. Find first. Every time.

```
venv/bin/python nucleus/toolreg.py find <words>      # from any shell
mcp__tools__find(query)                              # if your home has the door
```

Search with the nouns of the job, not your plan for it (`usage gauge`, not `write a poller`).
Try two or three phrasings before concluding nothing exists. The registry covers every script
under `nucleus/`, `skills/` and `mcp/`, plus every MCP tool in the manifest.

## 2. Reuse as it is

If a hit does the job, run it (`bash nucleus/x.sh …`, `venv/bin/python nucleus/x.py …`, or
`mcp__tools__run(id, args)`). The ledger records the call against that tool. That call is the
tool's value, and it's credit to whoever built it.

## 3. Extend rather than fork

If a hit *nearly* fits, add the flag or the case to it. Don't copy it into a sibling. Two
near-identical tools split the usage that makes either one worth keeping, and they drift.
Editing another agent's tool makes you a **contributor** (credited from the steps ledger,
never paid; the author stays the author). Before editing a shared file, check `git status`
and its mtime: if someone has uncommitted work in it, that's their review queue. Coordinate
on the wire rather than editing around them.

## 4. Build: only when it will recur

Build when the same *family* of task has come up before, or clearly will. A complex one-off
is not a tool; do it and move on. If you build:

- **Where:** `skills/<name>/` for a reusable capability (a script plus its usage), or
  `nucleus/` for org infrastructure. Not your home, and not `/tmp`: anything outside the
  registry roots can't be found, so it will never be called.
- **The first line is the search text.** The registry indexes the first docstring line
  (Python) or the first comment line (shell). Write it as *what it does, in the words a
  searcher would use*: `"""astryx · usage gauge — the account's 5h/7d usage, fresh, one read."""`
- **Small, standard, no shortcuts.** Adopt a mature library before hand-rolling one. Take
  arguments, don't hardcode. Print a result a caller can use: exit 0 on success, non-zero
  with a message on failure, and never a silent pass.
- **Never persist or print secrets.** Keep `.env` values, tier-private data and message
  bodies out of output and out of any file you write.
- **Prove it.** Run it on the real case before you call it done. If other things will depend
  on it, add an oracle under `tests/` and wire it into `nucleus/check.sh`. The coverage gate
  goes RED on an oracle nothing runs.
- **Minimise repetition.** If you catch yourself pasting the same five lines into a third
  place, that's the tool.

You author a tool by being the first to Write its file. Authorship comes from the steps
ledger, not from a field you fill in.

## What not to do

- Don't wrap a single command in a script just to make a "tool". Compression near 1 is worth
  nothing.
- Don't call your own tool to make it look used. Self-use is discounted, and a caller
  concentrated on the author is exactly what the market metrics surface.
- Don't delete or retire someone else's tool. Nothing is killed yet: rent is measured, and
  the owner decides later.
