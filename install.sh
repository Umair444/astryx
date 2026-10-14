#!/usr/bin/env bash
# astryx install — the one-line bootstrap for Linux, macOS and WSL2 (goal 10224 S3).
#
#   curl -fsSL https://raw.githubusercontent.com/Umair444/astryx/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/Umair444/astryx/main/install.sh | bash -s -- --dry-run
#
# It checks for git, python>=3.12, pipx, node>=20, tmux, docker and the Claude Code CLI, offers to install what's missing
# (each sudo line is shown before it runs), installs astryx, then hands over to `astryx init` (or ./init.sh until the
# CLI ships). Safe to re-run: every step checks first and only does what's missing.
#
# Flags:  --dry-run   print every command it would run, run none of them
#         --yes       say yes to every install prompt (for unattended VMs)
#         --dir DIR   where the clone lives (default ~/astryx; env ASTRYX_DIR)
#         --no-init   stop after installing; don't run astryx init
#         --upgrade   allow pulling into a directory where an org is already running
# Env (mostly for tests): ASTRYX_REPO, ASTRYX_PROC_VERSION, ASTRYX_OS_RELEASE.
set -euo pipefail

ASTRYX_REPO=${ASTRYX_REPO:-https://github.com/Umair444/astryx}
# Claude Code's official native installer (https://code.claude.com/docs/en/setup → "Native Install (Recommended)").
CLAUDE_INSTALL_URL=https://claude.ai/install.sh
DRY=0 YES=0 DO_INIT=1 UPGRADE=0
ASTRYX_DIR=${ASTRYX_DIR:-$HOME/astryx}
MISSING=()      # human-facing notes for what's still not right at the end

if [ -t 1 ]; then C_B=$'\033[36m' C_G=$'\033[32m' C_Y=$'\033[33m' C_R=$'\033[31m' C_0=$'\033[0m'
else C_B="" C_G="" C_Y="" C_R="" C_0=""; fi
say()  { printf '%s[astryx]%s %s\n' "$C_B" "$C_0" "$*"; }
ok()   { printf '  %s✓%s %s\n' "$C_G" "$C_0" "$*"; }
warn() { printf '  %s○%s %s\n' "$C_Y" "$C_0" "$*"; }
die()  { printf '%s[astryx]%s %s\n' "$C_R" "$C_0" "$*" >&2; exit 1; }

# Every command that changes the machine goes through run(): the human sees it first, and --dry-run stops there.
run() {
  printf '    %s$ %s%s\n' "$C_Y" "$*" "$C_0"
  [ "$DRY" = 1 ] && return 0
  "$@"
}

# Consent. Under `curl | bash` stdin IS the script, so the answer is read from the terminal. No terminal and no
# --yes: answer no, and the caller prints the command for the human instead.
ask() {
  [ "$DRY" = 1 ] && return 0
  [ "$YES" = 1 ] && return 0
  local a=""
  if { : </dev/tty; } 2>/dev/null; then
    printf '  ? %s [Y/n] ' "$1" >/dev/tty
    read -r a </dev/tty || a=n
    case "$a" in ""|y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
  fi
  return 1
}

# ── platform ────────────────────────────────────────────────────────────────────────────────────────────────────
# OS=linux|macos  WSL=wsl2|wsl1|no  PKG=apt|dnf|pacman|zypper|brew|none  DISTRO=<os-release ID or macos>
detect_platform() {
  local pv="" id="" like=""
  case "$(uname -s)" in
    Darwin) OS=macos ;;
    Linux)  OS=linux ;;
    *)      die "unsupported OS '$(uname -s)'. On Windows, use install.ps1 (it sets up WSL2 and runs this inside it)." ;;
  esac
  WSL=no
  if [ "$OS" = linux ]; then
    pv=$(cat "${ASTRYX_PROC_VERSION:-/proc/version}" 2>/dev/null || true)
    case "$pv" in
      *WSL2*|*microsoft-standard*) WSL=wsl2 ;;
      *Microsoft*) WSL=wsl1 ;;
      *microsoft*) WSL=wsl2 ;;
      *) [ -n "${WSL_DISTRO_NAME:-}" ] && WSL=wsl2 ;;
    esac
    if [ -r "${ASTRYX_OS_RELEASE:-/etc/os-release}" ]; then
      id=$(sed -n 's/^ID=//p' "${ASTRYX_OS_RELEASE:-/etc/os-release}" | tr -d '"' | head -1)
      like=$(sed -n 's/^ID_LIKE=//p' "${ASTRYX_OS_RELEASE:-/etc/os-release}" | tr -d '"' | head -1)
    fi
    DISTRO=${id:-unknown}
  else
    DISTRO=macos
  fi
  if   [ "$OS" = macos ]; then PKG=brew
  elif command -v apt-get >/dev/null 2>&1; then PKG=apt
  elif command -v dnf >/dev/null 2>&1;     then PKG=dnf
  elif command -v pacman >/dev/null 2>&1;  then PKG=pacman
  elif command -v zypper >/dev/null 2>&1;  then PKG=zypper
  else PKG=none; fi
  : "$like"
}

# The package names for a tool, per package manager. Empty = no sensible package (handled by the tool's own step).
pkg_names() {
  case "$PKG:$1" in
    *:git)          echo git ;;
    *:tmux)         echo tmux ;;
    apt:python)     echo "python3 python3-venv python3-pip" ;;
    dnf:python)     echo "python3 python3-pip" ;;
    pacman:python)  echo python ;;
    zypper:python)  echo "python3 python3-pip" ;;
    brew:python)    echo python@3.12 ;;
    pacman:pipx)    echo python-pipx ;;
    zypper:pipx)    echo python3-pipx ;;
    *:pipx)         echo pipx ;;
    apt:node)       echo "nodejs npm" ;;
    pacman:node)    echo "nodejs npm" ;;
    dnf:node|zypper:node) echo "nodejs npm" ;;
    brew:node)      echo node ;;
    pacman:docker)  echo "docker docker-compose" ;;
    *)              echo "" ;;
  esac
}
pkg_cmd() {   # the full install line for these packages (sudo only here, never for the whole script)
  case "$PKG" in
    apt)    echo "sudo apt-get install -y $*" ;;
    dnf)    echo "sudo dnf install -y $*" ;;
    pacman) echo "sudo pacman -S --needed --noconfirm $*" ;;
    zypper) echo "sudo zypper install -y $*" ;;
    brew)   echo "brew install $*" ;;
    *)      echo "" ;;
  esac
}
APT_UPDATED=0
pkg_install() {   # pkg_install <tool>: offer, then run the install line; on no/none, record the command for the human
  local names line
  names=$(pkg_names "$1"); line=$(pkg_cmd $names)
  if [ -z "$names" ] || [ -z "$line" ]; then MISSING+=("$1: install it with your package manager"); return 1; fi
  if [ "$PKG" != brew ] && ! command -v sudo >/dev/null 2>&1; then
    MISSING+=("$1: as root, run: ${line#sudo }"); warn "no sudo here; run as root: ${line#sudo }"; return 1
  fi
  if ask "install $1 ($line)"; then
    if [ "$PKG" = apt ] && [ "$APT_UPDATED" = 0 ]; then run sudo apt-get update; APT_UPDATED=1; fi
    # shellcheck disable=SC2086
    run $line && return 0
  fi
  MISSING+=("$1: $line"); return 1
}

# version_ge A B: is dotted version A >= B?
# Pure bash (macOS's bash 3.2 and BSD sort can't be trusted with sort -V): compares major, then minor, numerically.
version_ge() {
  local a1 a2 b1 b2 r
  a1=${1%%.*}; r=${1#"$a1"}; r=${r#.}; a2=${r%%.*}
  b1=${2%%.*}; r=${2#"$b1"}; r=${r#.}; b2=${r%%.*}
  a1=${a1//[!0-9]/}; a2=${a2//[!0-9]/}; b1=${b1//[!0-9]/}; b2=${b2//[!0-9]/}
  a1=${a1:-0}; a2=${a2:-0}; b1=${b1:-0}; b2=${b2:-0}
  [ "$a1" -gt "$b1" ] && return 0
  [ "$a1" -lt "$b1" ] && return 1
  [ "$a2" -ge "$b2" ]
}
# timeout(1) is GNU; macOS has none. Without it, run the command unbounded rather than reading "missing" as "down".
_t() { if command -v timeout >/dev/null 2>&1; then timeout "$@"; else shift; "$@"; fi; }
# Interactive steps need the terminal: under `curl | bash`, stdin is the script.
_tty_run() { if { : </dev/tty; } 2>/dev/null; then run "$@" </dev/tty; else run "$@"; fi; }

# ── the checks ──────────────────────────────────────────────────────────────────────────────────────────────────
need_simple() {   # git, tmux: present or offered
  if command -v "$1" >/dev/null 2>&1; then ok "$1"; else warn "$1 missing"; pkg_install "$1" || true; fi
}

PY=""
check_python() {
  local c v
  for c in python3.14 python3.13 python3.12 python3; do
    command -v "$c" >/dev/null 2>&1 || continue
    v=$("$c" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)
    if [ -n "$v" ] && version_ge "$v" 3.12; then PY=$c; ok "python $v ($c)"; return 0; fi
  done
  warn "python >= 3.12 missing${v:+ (found $v)}"
  pkg_install python || true
  [ "$DRY" = 1 ] && return 0
  for c in python3.14 python3.13 python3.12 python3; do
    v=$("$c" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)
    if [ -n "$v" ] && version_ge "$v" 3.12; then PY=$c; return 0; fi
  done
  MISSING+=("python>=3.12: your distro's python is older. On Ubuntu 22.04: sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt-get install python3.12 python3.12-venv. Or use uv: https://docs.astral.sh/uv/")
}

check_pipx() {
  if command -v pipx >/dev/null 2>&1; then ok "pipx"; return 0; fi
  warn "pipx missing"
  if [ "$PKG" = none ] && [ -n "$PY" ]; then
    ask "install pipx for your user ($PY -m pip install --user pipx)" && run "$PY" -m pip install --user pipx && return 0
    MISSING+=("pipx: $PY -m pip install --user pipx"); return 0
  fi
  pkg_install pipx || true
}

check_node() {
  local v=""
  if command -v node >/dev/null 2>&1; then v=$(node -v 2>/dev/null | sed 's/^v//'); fi
  if [ -n "$v" ] && version_ge "$v" 20; then ok "node $v"; return 0; fi
  warn "node >= 20 missing${v:+ (found $v)}"
  if [ "$PKG" = apt ]; then
    # Debian/Ubuntu's own nodejs is often older than 20; NodeSource is the standard route to a current LTS.
    if ask "install node 22 LTS from NodeSource (https://github.com/nodesource/distributions)"; then
      run bash -c "curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -" \
        && run sudo apt-get install -y nodejs && return 0
    fi
    MISSING+=("node>=20: curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt-get install -y nodejs")
    return 0
  fi
  pkg_install node || true
}

# Adding yourself to the docker group only counts from your next login, so this run can't use docker without sudo.
# RELOGIN makes run_init stop with that sentence instead of letting init.sh die on "permission denied".
RELOGIN=0
add_docker_group() {
  run sudo usermod -aG docker "$(id -un)" || return 1
  RELOGIN=1
  return 0
}
check_docker() {
  if command -v docker >/dev/null 2>&1; then
    if _t 10 docker info >/dev/null 2>&1; then
      if docker compose version >/dev/null 2>&1; then ok "docker (daemon reachable, compose plugin present)"
      else warn "docker works but 'docker compose' is missing — astryx's postgres is a compose file (infra/pg)"
           MISSING+=("docker compose plugin: https://docs.docker.com/compose/install/linux/"); fi
      return 0
    fi
    warn "docker is installed but the daemon isn't reachable by $(id -un)"
    if [ "$OS" = linux ]; then
      if ask "start docker at boot and let $(id -un) use it (systemctl enable --now docker; usermod -aG docker)"; then
        run sudo systemctl enable --now docker || true
        add_docker_group
      fi
    else
      warn "start Docker Desktop (or colima start), then re-run this."
    fi
    MISSING+=("docker daemon reachable without sudo"); return 0
  fi
  warn "docker missing"
  case "$OS:$PKG" in
    macos:*)
      MISSING+=("docker: install Docker Desktop (https://docs.docker.com/desktop/setup/install/mac-install/) or: brew install colima docker docker-compose && colima start")
      warn "install Docker Desktop, or: brew install colima docker docker-compose && colima start" ;;
    linux:apt|linux:dnf)
      # docker-ce from Docker's own repo, via Docker's convenience script (https://docs.docker.com/engine/install/ubuntu/#install-using-the-convenience-script).
      # It includes the compose plugin astryx needs. On WSL this is the recommended setup, not Docker Desktop:
      # one daemon inside the distro, managed by systemd like the rest of astryx, no Windows-side app to keep running.
      [ "$WSL" != no ] && warn "WSL: installing docker-ce inside WSL (simplest; no Docker Desktop needed). If you already use Docker Desktop, say no and turn on its WSL integration for this distro instead."
      if ask "install docker-ce (curl -fsSL https://get.docker.com | sudo sh)"; then
        run bash -c "curl -fsSL https://get.docker.com | sudo sh" \
          && run sudo systemctl enable --now docker \
          && add_docker_group && return 0
      fi
      MISSING+=("docker: curl -fsSL https://get.docker.com | sudo sh && sudo systemctl enable --now docker && sudo usermod -aG docker $(id -un)") ;;
    linux:pacman)
      if pkg_install docker; then
        run sudo systemctl enable --now docker || true
        add_docker_group
      fi ;;
    *)
      MISSING+=("docker: https://docs.docker.com/engine/install/") ;;
  esac
}

check_claude() {
  if command -v claude >/dev/null 2>&1; then ok "claude ($(claude --version 2>/dev/null | head -1))"; return 0; fi
  warn "Claude Code CLI missing"
  # The official native installer: no sudo, installs to ~/.local/bin, auto-updates (code.claude.com/docs/en/setup).
  if ask "install Claude Code (curl -fsSL $CLAUDE_INSTALL_URL | bash)"; then
    run bash -c "curl -fsSL $CLAUDE_INSTALL_URL | bash" && return 0
  fi
  MISSING+=("claude: curl -fsSL $CLAUDE_INSTALL_URL | bash   (docs: https://code.claude.com/docs/en/setup)")
}

# ── astryx itself ───────────────────────────────────────────────────────────────────────────────────────────────
# Always from git, the same root this script came from. A PyPI path waits for a release identified by something an
# uploader can't write (a sha pinned in this repo, or Trusted Publishing provenance): PyPI metadata naming this repo is
# written by whoever uploads, so it can't tell us from a squatter (a2 #51669 B2), and the package gets full control.

# An `astryx` on PATH that is the old link to init.sh, not the Python CLI.
astryx_is_initsh_link() {
  local p t
  p=$(command -v astryx 2>/dev/null) || return 1
  [ -L "$p" ] || return 1
  t=$(readlink "$p")
  case "$t" in */init.sh|init.sh) return 0 ;; *) return 1 ;; esac
}

USE_CLI=0
install_astryx() {
  local link="$HOME/.local/bin/astryx"
  say "installing astryx from git into $ASTRYX_DIR"
  if [ -d "$ASTRYX_DIR/.git" ] && [ -d "$ASTRYX_DIR/homes/seed" ] && [ "$UPGRADE" = 0 ] \
     && tmux has-session -t "=ax-seed" 2>/dev/null; then
    die "an org is running from $ASTRYX_DIR (ax-seed is up). Re-running here pulls and re-inits a live org; if you mean that, add --upgrade. To start a second org, pick another place with --dir."
  fi
  if [ -d "$ASTRYX_DIR/.git" ]; then
    if [ -n "$(git -C "$ASTRYX_DIR" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
      warn "$ASTRYX_DIR has local changes; leaving it as it is (no pull)"
    else
      run git -C "$ASTRYX_DIR" pull --ff-only || warn "git pull failed; carrying on with what's there"
    fi
  elif [ -e "$ASTRYX_DIR" ]; then
    die "$ASTRYX_DIR exists and isn't a git clone. Move it aside, or pick another place with --dir."
  else
    run git clone "$ASTRYX_REPO" "$ASTRYX_DIR"
  fi
  if [ -f "$ASTRYX_DIR/pyproject.toml" ]; then
    if command -v pipx >/dev/null 2>&1; then
      if [ -L "$link" ] && case "$(readlink "$link")" in */init.sh) true ;; *) false ;; esac; then
        warn "$link is the old link to init.sh; the astryx CLI replaces it (init.sh stays)"
        run rm -f "$link"
      fi
      run pipx install --force --editable "$ASTRYX_DIR" && USE_CLI=1
    else
      warn "pipx missing, so the astryx CLI isn't installed; ./init.sh does the same job"
    fi
  fi
}

run_init() {
  if [ "$DO_INIT" = 0 ]; then say "--no-init: done. When you're ready: cd $ASTRYX_DIR && ./init.sh"; return 0; fi
  if [ "$RELOGIN" = 1 ]; then
    say "one pause: you were just added to the docker group, which takes effect at your next login."
    if [ "$WSL" != no ]; then say "  close this terminal, run 'wsl --shutdown' in Windows PowerShell, reopen the distro,"
    else say "  log out and back in (or reboot),"; fi
    say "  then run the same install line again. It skips what's done and carries on from here."
    [ "$DRY" = 1 ] || exit 0
  fi
  if [ "$USE_CLI" = 1 ] || { command -v astryx >/dev/null 2>&1 && ! astryx_is_initsh_link; }; then
    say "handing over to: astryx init"
    _tty_run astryx init
  else
    say "handing over to: ./init.sh (in $ASTRYX_DIR)"
    if [ "$DRY" = 1 ]; then run ./init.sh; return 0; fi
    ( cd "$ASTRYX_DIR" && _tty_run ./init.sh )
  fi
}

usage() {   # inline, not read from $0: under `curl | bash`, $0 is "bash" (a2 N2)
  cat <<'EOF'
astryx install: the one-line bootstrap for Linux, macOS and WSL2.
  curl -fsSL https://raw.githubusercontent.com/Umair444/astryx/main/install.sh | bash
  ... | bash -s -- [flags]
Flags:  --dry-run   print every command it would run, run none of them
        --yes       say yes to every install prompt (for unattended VMs)
        --dir DIR   where the clone lives (default ~/astryx; env ASTRYX_DIR)
        --no-init   stop after installing; don't run astryx init
        --upgrade   allow pulling into a directory where an org is already running
EOF
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) DRY=1 ;;
      --yes|-y)  YES=1 ;;
      --dir)     ASTRYX_DIR=${2:?--dir needs a path}; shift ;;
      --dir=*)   ASTRYX_DIR=${1#--dir=} ;;
      --no-init) DO_INIT=0 ;;
      --upgrade) UPGRADE=1 ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown flag '$1' (try --help)" ;;
    esac
    shift
  done

  [ "$(id -u)" = 0 ] && die "don't run this as root. Run it as the user the org will live under; it asks for sudo only for package installs, and shows each line first."

  if [ "$DRY" = 1 ]; then say "astryx installer — DRY RUN: printing every command, running none"
  else say "astryx installer"; fi
  # pipx and Claude Code's native installer both put commands in ~/.local/bin; see them in this run too.
  case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac
  cat <<'EOF'

  Before you start: astryx agents get full control of this machine. They run commands, install
  software and edit files as your user, around the clock. That is the design, so give them a
  machine of their own: a dedicated VM, a spare computer, or a cloud box. Not your daily laptop.

EOF

  detect_platform
  case "$OS:$WSL" in
    macos:*)  say "platform: macOS (services run under launchd; see ./init.sh doctor)" ;;
    linux:wsl2) say "platform: WSL2 ($DISTRO). The org lives inside WSL: when Windows sleeps, the org sleeps." ;;
    linux:wsl1) die "this is WSL1. astryx needs WSL2: from Windows PowerShell run  wsl --set-version ${WSL_DISTRO_NAME:-Ubuntu} 2  then re-run." ;;
    *)        say "platform: Linux ($DISTRO, packages via $PKG)" ;;
  esac
  [ "$PKG" = brew ] && ! command -v brew >/dev/null 2>&1 && \
    MISSING+=("Homebrew: https://brew.sh — then re-run this") && warn "Homebrew missing (https://brew.sh); install it first for the package steps"

  say "checking what astryx needs"
  need_simple git
  check_python
  check_pipx
  check_node
  need_simple tmux
  check_docker
  check_claude

  if ! command -v git >/dev/null 2>&1 && [ "$DRY" = 0 ]; then
    die "git is still missing, so astryx can't be fetched. Install it (${MISSING[0]:-}) and re-run."
  fi

  install_astryx

  if [ "${#MISSING[@]}" -gt 0 ]; then
    say "still to do:"
    local m blocking=0; for m in "${MISSING[@]}"; do warn "$m"
      case "$m" in python*|docker:*|"docker daemon"*|claude:*|node*) blocking=1 ;; esac; done
    # setup can't succeed without these, and fails later with a less clear error (a2 N1): stop here instead
    if [ "$blocking" = 1 ] && [ "$DO_INIT" = 1 ] && [ "$DRY" = 0 ]; then
      say "fix the lines above, then run the same install line again. It skips what's done and carries on."
      exit 1
    fi
  fi
  command -v claude >/dev/null 2>&1 && say "Claude Code needs one login, by a human: if you haven't yet, run 'claude' and follow /login."

  run_init
  say "done. 'astryx doctor' (or ./init.sh doctor) checks everything any time."
}

main "$@"
