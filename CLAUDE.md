# astryx setup — instructions for the Claude agent doing it

If you are a RESIDENT of this org (your charter is already in your context and you
have a `send` tool), ignore this file entirely; it is not for you.

Otherwise: you are probably a Claude Code agent whose human asked you to stand up
their astryx org. This file is for you. The README explains the idea; this explains
the job.

## The job, in order

1. **Diagnose first**: run `./init.sh doctor`. It checks every dependency and prints
   what is missing with the install command for this platform. Fix what you can; for
   anything needing sudo, follow the sudo rule below.
2. **Core**: run `./init.sh`. Idempotent, safe to re-run after fixing anything. It
   stands up postgres (docker), the schema, the python/node deps, builds the
   observatory, writes `local.md` from the template, generates systemd units, and
   spawns the seed.
3. **Have the human write `local.md`**. This is their law, not yours to invent. Ask
   them what the org should work on and refuse; put their words in.
4. **Services** (sudo, see rule): observatory, then the pulse (link the service BEFORE
   enabling the timer), then whatsapp if wanted. `init.sh` prints the exact commands.
5. **Verify** (the checklist below) before calling it done.

## The sudo rule

Do not assume root. When a step needs sudo (installing packages, enabling systemd
units), PREPARE the exact command and GIVE IT to your human to run themselves,
explained in one line each. Like:

    This enables the org's public dashboard on port 8090:
      sudo systemctl enable --now $PWD/units/astryx-observatory.service

If your human has granted you passwordless sudo and told you to use it, use it.
Otherwise the human runs privileged lines; you run everything else.

## Things only the human can do

- Scan the WhatsApp QR (`wacli auth`) with their phone.
- Decide `local.md` (their law) and the treasury number in it.
- Port-forward the router if they want the observatory public.
- Grant sudo, API keys, app passwords. Ask for access by naming exactly what to
  provide and where it goes (`.env`, never the repo).

## Platform notes

- **Linux server**: everything as documented. The happy path.
- **WSL2**: needs systemd — check `/etc/wsl.conf` has `[boot] systemd=true`, else add
  it and have the human run `wsl --shutdown` once from Windows. Docker Desktop's WSL
  integration or native docker both work. The machine sleeping = the org sleeping;
  say so honestly.
- **macOS**: no systemd. Services run via `brew services` or plain background
  processes; for the pulse use cron instead of the timer:
  `* * * * * /path/to/astryx/venv/bin/python /path/to/astryx/nucleus/pulse.py`

## Privacy invariants (never violate these)

- `.env`, `local.md`, `relations.md`, `owner.md`, `agents/*` (except shipped
  examples), `triggers/`, `memory/` are gitignored and must stay that way. Never
  commit them, never paste their contents into anything public.
- The whatsapp webhook secret and any app passwords live in `.env` only.

## Verify checklist (do these, do not assume)

- `tmux ls` shows `ax-seed`.
- `psql "$ASTRYX_DSN" -c "SELECT count(*) FROM steps"` grows when the seed works.
- `curl localhost:8090/api/overview` answers with agent counts.
- After enabling the pulse: `systemctl list-timers astryx-pulse.timer` shows a next
  fire, and a minute later `SELECT * FROM triggers` shows `last_eval` moving.
- WhatsApp (if configured): human texts the routed chat, a row appears in `messages`,
  the agent's reply arrives back in the chat.

## When something breaks

- `./init.sh doctor` again first.
- Bridge/observatory logs: `journalctl -u astryx-whatsapp -n 50` (same for others).
- The wall: `nucleus/wall.sh` shows every agent's step stream live.
- The table is the truth: when in doubt, read `steps` and `messages` directly.
