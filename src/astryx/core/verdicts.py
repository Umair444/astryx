#!/usr/bin/env python3
"""astryx · verdicts — the review grammar's ONE tracked writer: the merge-ready marker and the prose verdicts.

A RULED LIFT (plan-11324 S2, consolidator ruling abstractor-4 #58286): the whole group is copied EXACTLY from
triggers/seed/merge_ready.py (:104-123), which is gitignored, so a tracked reader (src/astryx/influence/graph.py)
could not import it. seed re-imports from here later; until then the two copies must stay byte-identical, and a
change to either is a change to both.

  HEX            an abbreviated or full commit sha (7..40 lowercase hex)
  REF            a SYMBOLIC base (`main..c84543f`): a claim about the ref AS IT WAS when the marker was written.
                 Only the base's GRAMMAR is lifted here, never its MEANING: seed resolves a symbolic base from the
                 reflog at the marker's ts. A reader here that needs the base must report it as "unresolved base",
                 never `git rev-parse` today's ref (today's main is not the ref the reviewer read).
  READY_RE       `merge-ready: <branch> <base>..<head>` args, an optional trailing "(...)" note
  RANGE_RE       `<base>..<head>` args (supersedes)
  PROSE_PASS_RE  a prose PASS verdict ("NOT PASS" and "PASS/REVISE" are not one)
  REVISE_RE      a prose REVISE verdict
MARKER_RE is lifted beside them (same file, :107-109): it finds the marker LINES the args grammar above parses, so
the marker parse has one writer too.
"""
import re

HEX = r"[0-9a-f]{7,40}"
MARKER_RE = re.compile(r"^[ \t]*(merge-ready|supersedes|merge-retract|merge-hold|applied|review-request):"
                       r"[ \t]*(.*?)[ \t]*$",
                       re.M)
REF = r"[A-Za-z_][\w./-]*?"
READY_RE = re.compile(rf"^(\S+)\s+({HEX}|{REF})\.\.({HEX})(?:\s+\([^()]*\))?$")
RANGE_RE = re.compile(rf"^({HEX})\.\.({HEX})(?:\s+\([^()]*\))?$")
PROSE_PASS_RE = re.compile(r"(?<![A-Za-z/])(?<!NOT )PASS(?![A-Za-z/])")
REVISE_RE = re.compile(r"(?<![A-Za-z])REVISE(?![A-Za-z])")
