---
name: org-vitals
description: One read-only pass over the org's health — doctor reds, gate-suite stamp, genuinely-dark triggers, stuck messages, service errors, backup and restore freshness. Read this when you need to know "is the org healthy right now?" before diagnosing or acting.
---

# org-vitals

```
bash skills/org-vitals/vitals.sh             # every panel but doctor
bash skills/org-vitals/vitals.sh --doctor    # + the doctor panel (or VITALS_DOCTOR=1)
```

Runs from any cwd, writes no state, prints metadata only (message ids/status/age, never bodies),
and always exits 0. It's a panel, not a gate. Its only side effect by default is `git fetch`.

**Why doctor is opt-in:** `./init.sh doctor` makes an authenticated model call (`claude -p --model
haiku`, spends plan quota, up to 30s), loads the faster-whisper model on CPU, and runs the deps and
media probes. Pass `--doctor` when you're actually diagnosing, not for a routine glance.

## What each panel means

| Panel | Healthy looks like | The trap it avoids |
|---|---|---|
| git | `0 ahead / 0 behind` on main | branching off a local main ahead of origin drags others' unpushed commits into your PR |
| doctor (`--doctor`) | only reds your baseline already explains | a doctor red is TWO claims (what failed, and why): reproduce both before acting |
| gate suite | the stamp's verdict line, `failed=0` | reads the stamp's CONTENT, not its age (a failed run writes a fresh stamp); lists UNVERIFIED gates by **name**, because a swapped skip hides behind an unchanged count |
| triggers | `(none overdue)` | probes `next_fire < now()-15min`, never `last_eval` age, which marks every weekly/monthly trigger stale by design |
| messages | `(none — nothing stuck)` | anything not `delivered`/`abandoned` |
| services | empty | error-shaped lines in the last 60 `astryx-*` journal lines. These are RAW log lines: if a bridge ever logs an identifier (a JID, a phone number) in an error, it lands in your context, so don't paste this panel onto the wire |
| backup | dump <30h, restore-ok <9d | reads the restore stamp's own timestamp, not the file mtime |

## What it can't see

The worst lesions are silent, not red. After the panel, still cross-check the high-value
guards against an independent oracle: org-news vs `goals WHERE state='done'`, a watcher's
`last_fired` vs whether its watched event actually happened, and "owned by X's guard" vs whether
X's guard is live on it.

Note: a trigger's `last_fired` can sit weeks stale while the work runs fine (run_check,
run_backup): trust the stamp or dump it produces, not the column.
