# Android phones for your agents

ASTRYX can give its agents an Android phone: an emulator on the org's machine that agents see and drive the way a
person would (look at the screen, tap, swipe, type, open apps). It's **off by default**: an org opts in.

Under the hood it adopts [mobile-mcp](https://github.com/mobile-next/mobile-mcp) (pinned, not "latest") behind a
small facade, `mcp/phone`, so every agent carries only two tools, the same shape as the desktop `hands` tools.

## What an agent can do

```
look(device, text?)          a screenshot, or text=True: the on-screen elements with their coordinates
act(action, device, …)       tap / double_tap / long_press x,y · swipe direction · type text · button (BACK, HOME…)
                             launch / terminate an app · open_url · apps · foreground · boot · shutdown · done · phones
```

`device` is the phone's name (`act("phones")` lists them). One agent drives a phone at a time: the phone is held by
the agent for 5 minutes after its last action, or until it says `act("done")`. Another agent is told who has it.

Deliberately **not** available, even though the upstream server has them: its paid cloud devices, saving
screenshots or screen recordings to files, the clipboard, device logs, installing apps from a file, and batch
scripts. `tests/test_phone_facade.py` compares the upstream's live tool list with the reviewed one, so an upstream
upgrade that adds a tool fails the check instead of quietly reaching agents.

## Requirements (measured on a 2-core laptop, Android 15)

| | |
|---|---|
| CPU virtualisation | `/dev/kvm`, readable and writable by the org's user. Without it the capability reports SKIP and stays off. |
| Free RAM while the phone runs | about 3 GB (the emulator held 2.6–2.9 GB with an app open) |
| Disk | about 4 GB for the SDK, plus about 3 GB for the phone (more as apps are installed) |
| Start-up | first boot 4–8 minutes; later boots from a snapshot about 10 seconds |
| Software | `curl`, `unzip`, `sha256sum`, `sha1sum`, `node`/`npm`. No Java, no sudo. |

If the org also runs a Windows VM, only one of the two may run at a time: a lease (`vm-slot`) enforces it, and the
phone refuses to start while Windows is up, saying so.

**The Windows VM runs on demand.** When an agent opens its viewer (`127.0.0.1:8006`) through Hands, Hands first takes
the `vm-slot`, then starts the VM if it's stopped; if the phone holds the slot, the open is refused, naming it. A VM
that an agent started this way is **stopped again after 15 minutes with nobody connected** to its viewer or RDP port
(`nucleus/shipped_triggers/windows_idle_stop.py`, installed by `./init.sh` where a Windows container exists), and the
slot is freed for the phone.

That stop is a **hard stop**: the Windows guest ignores shutdown requests, so after about 100 seconds the VM is killed.
Save your work inside it, or stay connected to keep it running. `HANDS_WINDOWS_IDLE_S` in `.env` sets the idle window
in seconds (default 900); `0` turns the stop off. A Windows VM that was **already running** when an agent opened it
(you started it, or it was up anyway) is never stopped this way.

## Enable it

1. Read Google's Android SDK licence: <https://developer.android.com/studio/terms>. Accepting it is **your** act as
   the operator; no agent accepts it for you.
2. Add to `.env`:
   ```
   ANDROID_ENABLED=1
   ANDROID_SDK_LICENSE=accepted
   # optional:
   # ANDROID_SDK_ROOT=~/Android/Sdk      where to install
   # ANDROID_AVD=astryx-phone            the phone's name
   ```
3. Run `./init.sh`. It installs exact, checksum-verified archives from `dl.google.com` into your home directory
   (`nucleus/android_setup.sh install` does the same by hand), creates the phone, and installs the pinned upstream
   from its committed lockfile with install scripts disabled.
4. `./init.sh doctor` reports `android: ready`. Respawn your agents and they have the `phone` tools.

To turn it off, set `ANDROID_ENABLED=0` (or remove the line) and respawn. The SDK stays on disk until you delete it.

## Watching, joining and stopping

Where the org's machine can run a Hands desktop (sway, wayvnc), `act("boot")` starts the phone **in its own
desktop**, named `phone-<the phone's name>`. The emulator is a window there, so:

- **Watch** it in the observatory's Hands view like any desktop, live.
- **Join**: click into it. Your clicks go to the phone through the desktop's own seat; the agent acts through the
  phone's own channel (adb), which moves no cursor, so the two of you don't fight over one pointer.
- **Stop**: the stop button on that desktop. Every phone action by any agent is then refused, until you resume.
  Switching the phone off still works while stopped.

Agents can't drive that desktop with their Hands tools: those only ever reach your laptop screen or a desk from the
shared pool (desk-1, desk-2, …), and the phone's desktop is never one of them.

**Without a desktop** (no sway on the machine), the phone boots headless and says "no live view". Your only stops are
then `venv/bin/python nucleus/hands_desktop.py stop <agent>` (refuses that agent's phone actions until `… resume`) and
`venv/bin/python nucleus/android.py shutdown`.

**What the stop can't promise.** It prevents an agent's *phone* and *Hands* tools from acting. It doesn't prevent an
agent that is working on **your laptop screen** (Hands' `laptop`): with the observatory open there, that agent could
click into the phone's view, or press resume, and nothing can tell its click from yours. Of those two, only the
**resume is detected**: a resume of a phone's desktop within 60 seconds of any agent acting on your laptop is flagged
to the org. **Driving the phone through its view from your laptop is neither prevented nor detected.** The
detector is `nucleus/shipped_triggers/phone_resume_sweep.py`; install it with
`printf 'from nucleus.shipped_triggers.phone_resume_sweep import phone_resume_sweep  # noqa: F401\n' > triggers/seed/phone_resume_sweep.py`.

The view and every Hands route are owner-only: they need the observatory's owner key, which is never written to the
service's log (`key=<redacted>`).

## Privacy

What's on a phone screen is often personal (messages, bank balances, one-time codes). So:

- Screenshots are never stored in the org's records, and neither is anything an agent **types** on a phone.
- Every phone answer is stamped with what was on screen, read from the phone's own list of visible windows. A
  phone result is kept in the org's records only when everything visible is on the public list
  (`mcp/phone/public_manifest.json`: Settings, a calculator, the system bars). Anything else, including a window
  nobody has listed yet or a notification shade pulled down, is not kept.
- The phone is set not to show notification pop-ups or notification text on its lock screen, on every boot.
- The phone's data files (which hold app logins) are made readable by the org's user only, on every boot.
- The upstream's anonymous usage telemetry is switched off, and it gets an environment built for it, not yours.
- The live view stores nothing (it's a stream). The one way to write a phone's pixels to a file is the command line:
  `nucleus/hands_desktop.py shot phone-<name> <file>`, an act of whoever runs it on this machine.
- The phone's data is in no backup the org makes (`nucleus/backup.sh` doesn't carry `~/.android`) and, on a machine
  whose snapshots cover only `/` (not `/home`), in no snapshot either. Losing it means signing in again.

What this can't promise: the model provider sees the screenshots an agent looks at (that's how it sees), and an
agent that has seen something can still mention it later in its own words.
