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

- **Stop an agent's phone:** `venv/bin/python nucleus/hands_desktop.py stop <agent>` refuses every phone action by
  that agent until `… resume <agent>`. `venv/bin/python nucleus/android.py shutdown` switches the phone off.
  The observatory's Hands stop button does **not** reach a phone yet: it stops a *desktop*, by the desktop's name.
- **Watch, join and stop from the observatory:** not in this release. The phone runs without a window; a live view
  with its own stop, gated to the owner's session, is the next slice.

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

What this can't promise: the model provider sees the screenshots an agent looks at (that's how it sees), and an
agent that has seen something can still mention it later in its own words.
