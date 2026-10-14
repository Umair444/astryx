#!/usr/bin/env bash
# test_install_platform — goal 10224 S3, the platform pieces that bootstrap people up to `astryx init`:
#   (A) doctor's WSL detection (_wsl_kind) and PID-1 read (_pid1), through the real helpers with a stubbed /proc/version
#       and a stubbed `ps`;
#   (B) doctor's real WSL block, run with stubs: no systemd → the exact /etc/wsl.conf fix + `wsl --shutdown`; WSL1 → bad;
#   (C) the docker host address resolution order (nucleus/docker_host_ip.sh): env > .env > docker0 > host.docker.internal
#       > 172.17.0.1, with `ip`/`getent` stubbed, including the ones that can't answer;
#   (D) install.sh: parses, and --dry-run on this box and on a simulated bare Ubuntu-on-WSL runs NOTHING (a stub sudo,
#       git and curl-pipe would leave a marker), refuses root, prefers PyPI only when the package there is this repo,
#       and is idempotent (an existing clone is pulled, not re-cloned).
# Installs nothing, touches no database, restarts nothing.
set -u
cd "$(dirname "$0")/.."
ROOT=$PWD
fails=0
arm() { if [ "$2" = "$3" ]; then echo "  PASS  $1"; else echo "  FAIL  $1 — got '$2', want '$3'"; fails=$((fails+1)); fi; }
has() { case "$2" in *"$3"*) echo "  PASS  $1";; *) echo "  FAIL  $1 — output lacks '$3'"; fails=$((fails+1));; esac; }
hasnt() { case "$2" in *"$3"*) echo "  FAIL  $1 — output has '$3'"; fails=$((fails+1));; *) echo "  PASS  $1";; esac; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

# ── (A) _wsl_kind and _pid1 ─────────────────────────────────────────────────────────────────────────────────────
eval "$(sed -n '/^_wsl_kind() {/,/^}/p' init.sh)"
eval "$(sed -n '/^_pid1() {/,/^}/p' init.sh)"
pv() { printf '%s\n' "$1" > "$T/pv"; }
unset WSL_DISTRO_NAME
export ASTRYX_PROC_VERSION=$T/pv
pv 'Linux version 5.15.167.4-microsoft-standard-WSL2 (root@1234) (gcc (GCC) 11.2.0) #1 SMP'
arm "(A1) a WSL2 kernel → wsl2" "$(_wsl_kind)" wsl2
pv 'Linux version 4.19.128-microsoft-standard (oe-user@oe-host) (gcc version 8.2.0 (GCC)) #1 SMP'
arm "(A2) an older WSL2 kernel (no 'WSL2' in the string) → wsl2" "$(_wsl_kind)" wsl2
pv 'Linux version 4.4.0-19041-Microsoft (Microsoft@Microsoft.com) (gcc version 5.4.0 (GCC) ) #1237-Microsoft'
arm "(A3) WSL1's capital-M Microsoft → wsl1" "$(_wsl_kind)" wsl1
pv 'Linux version 6.8.0-45-generic (buildd@lcy02-amd64-115) (x86_64-linux-gnu-gcc-13 (Ubuntu 13.2.0)) #45-Ubuntu SMP'
arm "(A4) a plain Linux kernel → no" "$(_wsl_kind)" no
arm "(A5) unreadable /proc/version but WSL_DISTRO_NAME set → wsl2" "$(ASTRYX_PROC_VERSION=$T/absent WSL_DISTRO_NAME=Ubuntu _wsl_kind)" wsl2
arm "(A6) unreadable /proc/version, no WSL env → no" "$(ASTRYX_PROC_VERSION=$T/absent _wsl_kind)" no
ps() { [ "$*" = "-p 1 -o comm=" ] && echo systemd; }
arm "(A7) ps -p 1 says systemd → systemd" "$(_pid1)" systemd
ps() { [ "$*" = "-p 1 -o comm=" ] && echo init; }
arm "(A8) WSL without systemd: PID 1 is init → init" "$(_pid1)" init
ps() { [ "$*" = "-p 1 -o comm=" ] && echo /sbin/launchd; }
arm "(A9) macOS prints a path → launchd" "$(_pid1)" launchd
ps() { return 1; }
arm "(A10) ps can't answer → unknown, never systemd" "$(_pid1)" unknown

# ── (B) doctor's real WSL block ─────────────────────────────────────────────────────────────────────────────────
blk=$(sed -n '/# ── platform: WSL (goal 10224 S3)/,/# the address containers reach this host/p' init.sh | sed '$d')
[ -n "$blk" ] || { echo "  FAIL  (B) the doctor WSL block was not found in init.sh"; fails=$((fails+1)); }
ok() { echo -e "OK $*"; }; bad() { echo -e "BAD $*"; }; warn() { echo -e "WARN $*"; }
docker() { [ "$1" = info ] && return 1; }; timeout() { shift; "$@"; }
ps() { echo init; }
out=$(_wk=wsl2; WSL_DISTRO_NAME=Ubuntu; eval "$blk")
has   "(B1) WSL, no systemd: a BAD line names it" "$out" "BAD WSL: systemd is NOT PID 1 (PID 1 is init)"
has   "(B1) the exact /etc/wsl.conf fix, as a runnable line" "$out" "printf '[boot]\\nsystemd=true\\n' | sudo tee /etc/wsl.conf"
has   "(B1) then wsl --shutdown from Windows" "$out" "wsl --shutdown"
has   "(B1) docker unreachable → BAD with both remedies" "$out" "BAD WSL: docker is NOT reachable"
has   "(B1) the sleeping-machine line" "$out" "when Windows sleeps, the org sleeps"
ps() { echo systemd; }; docker() { [ "$1" = info ] && return 0; }
out=$(_wk=wsl2; WSL_DISTRO_NAME=Ubuntu; eval "$blk")
has   "(B2) WSL with systemd → OK" "$out" "OK WSL: systemd is PID 1"
has   "(B2) docker reachable → OK" "$out" "OK WSL: docker is reachable"
hasnt "(B2) a healthy WSL has no BAD line" "$out" "BAD"
out=$(_wk=wsl1; WSL_DISTRO_NAME=Ubuntu; eval "$blk")
has   "(B3) WSL1 → BAD with the convert command" "$out" "BAD WSL1 detected — astryx needs WSL2. From Windows PowerShell: wsl --set-version Ubuntu 2"
out=$(_wk=no; eval "$blk")
arm   "(B4) not WSL → the block prints nothing" "$out" ""
unset -f ok bad warn docker timeout ps

# ── (C) docker host address: resolution order ───────────────────────────────────────────────────────────────────
. nucleus/docker_host_ip.sh
unset ASTRYX_DOCKER_HOST_IP
ip() { [ "$*" = "-4 addr show docker0" ] && printf '6: docker0: <UP>\n    inet 172.18.0.1/16 brd 172.18.255.255 scope global docker0\n'; }
getent() { [ "$*" = "hosts host.docker.internal" ] && printf '192.168.65.254  host.docker.internal\n'; }
printf 'ASTRYX_DSN=x\n' > "$T/env"
arm "(C1) docker0 answers → its address (beats host.docker.internal)" "$(_docker_host_ip "$T/env")" 172.18.0.1
printf 'ASTRYX_DOCKER_HOST_IP=10.9.8.7\n' > "$T/env2"
arm "(C2) .env's ASTRYX_DOCKER_HOST_IP beats docker0" "$(_docker_host_ip "$T/env2")" 10.9.8.7
arm "(C3) the environment beats .env" "$(ASTRYX_DOCKER_HOST_IP=10.1.1.1 _docker_host_ip "$T/env2")" 10.1.1.1
ip() { [ "$*" = "-4 addr show docker0" ] && echo 'Device "docker0" does not exist.' >&2; return 1; }
arm "(C4) no docker0 (Docker Desktop) → host.docker.internal's address" "$(_docker_host_ip "$T/env")" 192.168.65.254
ip() { printf '6: docker0: <NO-CARRIER>\n'; }
arm "(C5) docker0 with no inet line → falls through to host.docker.internal" "$(_docker_host_ip "$T/env")" 192.168.65.254
getent() { return 2; }
arm "(C6) neither answers → 172.17.0.1 (the old literal)" "$(_docker_host_ip "$T/env")" 172.17.0.1
ip() { return 127; }; getent() { return 127; }
arm "(C7) ip and getent missing, no .env → 172.17.0.1" "$(_docker_host_ip "$T/nope")" 172.17.0.1
getent() { printf 'fe80::1  host.docker.internal\n'; }
arm "(C8) an IPv6-only answer is not used → 172.17.0.1" "$(_docker_host_ip "$T/env")" 172.17.0.1
unset -f ip getent
arm "(C9) init.sh's generated whatsapp unit binds the resolved address, not a literal" \
  "$(grep -c 'bridges.whatsapp:app --host $(_docker_host_ip) --port 8477' init.sh)" 1
# every remaining mention is inside a comment (the text after a '#')
arm "(C10) no hardcoded 172.17.0.1 left in init.sh's or deploy.sh's commands" \
  "$(grep -h '172\.17\.0\.1' init.sh nucleus/deploy.sh | grep -vc '#.*172\.17\.0\.1')" 0

# ── (D) install.sh ──────────────────────────────────────────────────────────────────────────────────────────────
bash -n install.sh; arm "(D1) install.sh parses (bash -n)" "$?" 0
grep -q '^set -euo pipefail' install.sh; arm "(D1) install.sh runs under set -euo pipefail" "$?" 0
# stubs that leave a marker if anything is actually executed: sudo, git, a curl-pipe installer
mkdir -p "$T/trap"
printf '#!/bin/sh\necho "sudo $*" >> "%s/RAN"\n' "$T" > "$T/trap/sudo"
# pipx: a read (`pipx list`) is allowed and answers "nothing installed"; anything else is an install and leaves the marker
printf '#!/bin/sh\n[ "$1" = list ] && exit 0\necho "pipx $*" >> "%s/RAN"\n' "$T" > "$T/trap/pipx"
chmod +x "$T/trap/sudo" "$T/trap/pipx"
unset ASTRYX_PROC_VERSION
printf '{"info":{"project_urls":{"Source":"https://github.com/someone-else/astryx"}}}\n' > "$T/pypi-other.json"
printf '{"info":{"project_urls":{"Source":"https://github.com/Umair444/astryx"}}}\n' > "$T/pypi-ours.json"

# D2: this box, as it is (whatever is installed), with sudo trapped. A deliberate tripwire: once the Python `astryx`
# CLI is installed on this host, the hand-over arm below should read "$ astryx init" and this arm goes red; update it then.
out=$(PATH="$T/trap:$PATH" ASTRYX_PYPI_URL="file://$T/absent.json" ./install.sh --dry-run --dir "$T/home/astryx" </dev/null 2>&1); rc=$?
arm   "(D2) dry-run on this box exits 0" "$rc" 0
has   "(D2) says it is a dry run" "$out" "DRY RUN: printing every command, running none"
has   "(D2) the dedicated-machine paragraph comes first" "$out" "agents get full control of this machine"
has   "(D2) installs from git while PyPI has no astryx" "$out" "git clone https://github.com/Umair444/astryx $T/home/astryx"
has   "(D2) hands over to ./init.sh (no CLI yet)" "$out" '$ ./init.sh'
arm   "(D2) nothing ran: no sudo/pipx call, no clone on disk" "$( [ -e "$T/RAN" ] || [ -e "$T/home" ]; echo $?)" 1

# D3: a bare Ubuntu inside WSL2: apt, nothing else installed. A minimal PATH with only core utils.
mkdir -p "$T/bare" "$T/osr"
for c in bash sh uname cat sed tr head grep cut readlink id dirname awk sort mktemp env; do
  p=$(command -v "$c") && ln -sf "$p" "$T/bare/$c"
done
cp "$T/trap/sudo" "$T/bare/sudo"; printf '#!/bin/sh\nexit 0\n' > "$T/bare/apt-get"; chmod +x "$T/bare/apt-get"
printf 'NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\n' > "$T/osr/os-release"
pv 'Linux version 5.15.167.4-microsoft-standard-WSL2 (root@1234) #1 SMP'
out=$(PATH="$T/bare" HOME="$T/h" WSL_DISTRO_NAME=Ubuntu ASTRYX_PROC_VERSION="$T/pv" ASTRYX_OS_RELEASE="$T/osr/os-release" \
      ASTRYX_PYPI_URL="file://$T/absent.json" "$T/bare/bash" ./install.sh --dry-run 2>&1); rc=$?
arm   "(D3) bare WSL2 Ubuntu dry-run exits 0" "$rc" 0
has   "(D3) detects WSL2 + Ubuntu and says the org sleeps with Windows" "$out" "platform: WSL2 (ubuntu). The org lives inside WSL: when Windows sleeps, the org sleeps."
has   "(D3) apt is refreshed once, shown" "$out" '$ sudo apt-get update'
has   "(D3) git via apt, the sudo line shown" "$out" '$ sudo apt-get install -y git'
has   "(D3) python 3.12+ with venv" "$out" '$ sudo apt-get install -y python3 python3-venv python3-pip'
has   "(D3) node 22 from NodeSource (distro node is too old)" "$out" "deb.nodesource.com/setup_22.x | sudo -E bash -"
has   "(D3) tmux" "$out" '$ sudo apt-get install -y tmux'
has   "(D3) docker-ce inside WSL, recommended" "$out" "WSL: installing docker-ce inside WSL (simplest; no Docker Desktop needed)"
has   "(D3) docker via Docker's convenience script" "$out" '$ bash -c curl -fsSL https://get.docker.com | sudo sh'
has   "(D3) Claude Code via the official native installer" "$out" '$ bash -c curl -fsSL https://claude.ai/install.sh | bash'
has   "(D3) the clone lands in ~/astryx by default" "$out" "git clone https://github.com/Umair444/astryx $T/h/astryx"
has   "(D3) joining the docker group → a calm pause before init (not a permission-denied crash)" "$out" "you were just added to the docker group"
has   "(D3) …with the WSL way to re-login" "$out" "run 'wsl --shutdown' in Windows PowerShell"
arm   "(D3) nothing ran" "$( [ -e "$T/RAN" ]; echo $?)" 1
arm   "(D3) apt-get update appears once (idempotent within a run)" "$(printf '%s\n' "$out" | grep -c 'sudo apt-get update')" 1

# D4: root is refused before anything
rm -f "$T/bare/id"   # it's a symlink to the real id: unlink first, never write through it
printf '#!/bin/sh\n[ "$1" = -u ] && echo 0 || echo root\n' > "$T/bare/id"; chmod +x "$T/bare/id"
out=$(PATH="$T/bare" HOME="$T/h" ASTRYX_PROC_VERSION="$T/pv" "$T/bare/bash" ./install.sh --dry-run 2>&1); rc=$?
arm   "(D4) as root: refused (non-zero)" "$( [ "$rc" != 0 ] && echo refused)" refused
has   "(D4) and says why" "$out" "don't run this as root"
hasnt "(D4) before any check ran" "$out" "checking what astryx needs"
ln -sf "$(command -v id)" "$T/bare/id"

# D5: never from PyPI, even when a package there names THIS repo: that metadata is written by the uploader, so a
#     squatter's JSON looks exactly like ours (a2 #51669 B2). The git path is taken either way.
cp "$T/trap/pipx" "$T/bare/pipx"
for f in pypi-other pypi-ours; do
  out=$(PATH="$T/bare:$(dirname "$(command -v curl)")" HOME="$T/h" ASTRYX_PROC_VERSION="$T/pv" ASTRYX_OS_RELEASE="$T/osr/os-release" \
        ASTRYX_PYPI_URL="file://$T/$f.json" "$T/bare/bash" ./install.sh --dry-run --no-init 2>&1)
  has   "(D5) $f.json on PyPI (a squatter can upload either) → git clone" "$out" "git clone https://github.com/Umair444/astryx"
  hasnt "(D5) $f.json → never pipx install astryx" "$out" '$ pipx install astryx'
done
arm   "(D5) nothing ran" "$( [ -e "$T/RAN" ]; echo $?)" 1

# D7: an org already running from the target dir is never pulled and re-inited by accident (a2 N4)
mkdir -p "$T/h4/astryx/homes/seed" && git -C "$T/h4/astryx" init -q
mkdir -p "$T/tm" && printf '#!/bin/sh\n[ "$1" = has-session ] && exit 0\nexit 1\n' > "$T/tm/tmux" && chmod +x "$T/tm/tmux"
out=$(PATH="$T/tm:$T/bare:$(dirname "$(command -v git)")" HOME="$T/h4" ASTRYX_PROC_VERSION="$T/pv" ASTRYX_OS_RELEASE="$T/osr/os-release" \
      "$T/bare/bash" ./install.sh --dry-run --no-init 2>&1); rc=$?
arm   "(D7) ax-seed up in the target dir → refused" "$( [ "$rc" != 0 ] && echo refused)" refused
has   "(D7) and names --upgrade" "$out" "--upgrade"
hasnt "(D7) no pull" "$out" "pull --ff-only"
out=$(PATH="$T/tm:$T/bare:$(dirname "$(command -v git)")" HOME="$T/h4" ASTRYX_PROC_VERSION="$T/pv" ASTRYX_OS_RELEASE="$T/osr/os-release" \
      "$T/bare/bash" ./install.sh --dry-run --no-init --upgrade 2>&1)
has   "(D7) --upgrade → the pull goes ahead" "$out" "pull --ff-only"

# D8: --help works under `curl | bash`, where $0 is "bash" (a2 N2)
out=$(bash -s -- --help < ./install.sh 2>&1)
has   "(D8) --help prints the flags when piped" "$out" "--dry-run"

# D9: deploy.sh's bridge table holds exactly the three bridges, each host:port (a2 #51669 B1: a missing space
#     glued telegram into whatsapp's address)
tbl=$(bash -c '_docker_host_ip() { echo 172.17.0.1; }; ROOT=/x; eval "$(command grep -m1 "^declare -A BADDR=" nucleus/deploy.sh)"; for k in "${!BADDR[@]}"; do printf "%s=%s\n" "$k" "${BADDR[$k]}"; done | sort')
keys=$(printf '%s\n' "$tbl" | cut -d= -f1 | tr '\n' ' ')
arm   "(D9) the bridge table's keys are exactly discord telegram whatsapp" "$keys" "discord telegram whatsapp "
bad=$(printf '%s\n' "$tbl" | command grep -cvE '^[a-z]+=[0-9.]+:[0-9]+$' || true)
arm   "(D9) every address is host:port" "$bad" 0

# D6: idempotent — an existing clone is pulled, never re-cloned; local changes are left alone
mkdir -p "$T/h2/astryx" && git -C "$T/h2/astryx" init -q && git -C "$T/h2/astryx" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
GITDIR=$(dirname "$(command -v git)")
out=$(PATH="$T/bare:$GITDIR" HOME="$T/h2" ASTRYX_PROC_VERSION="$T/pv" ASTRYX_OS_RELEASE="$T/osr/os-release" \
      ASTRYX_PYPI_URL="file://$T/absent.json" "$T/bare/bash" ./install.sh --dry-run --no-init 2>&1)
has   "(D6) an existing clone → git pull --ff-only" "$out" "git -C $T/h2/astryx pull --ff-only"
hasnt "(D6) not a second clone" "$out" "git clone"
mkdir -p "$T/h3/astryx"
out=$(PATH="$T/bare:$GITDIR" HOME="$T/h3" ASTRYX_PROC_VERSION="$T/pv" ASTRYX_OS_RELEASE="$T/osr/os-release" \
      ASTRYX_PYPI_URL="file://$T/absent.json" "$T/bare/bash" ./install.sh --dry-run --no-init 2>&1); rc=$?
arm   "(D6) ~/astryx exists but isn't a clone → stops, touches nothing" "$( [ "$rc" != 0 ] && echo stopped)" stopped
has   "(D6) and says so" "$out" "exists and isn't a git clone"

[ "$fails" = 0 ] && echo PASS || { echo "FAIL ($fails)"; exit 1; }
