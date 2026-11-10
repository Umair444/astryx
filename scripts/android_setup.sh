#!/usr/bin/env bash
# astryx · android_setup — the Android phone capability (plan-8675), OPT-IN, installed user-locally.
#
#   scripts/android_setup.sh check      0 = ready or off · 1 = not installed · 3 = licence not accepted · 77 = no KVM
#   scripts/android_setup.sh install    download the PINNED packages, verify, unpack, make the phone
#
# Settings (.env):
#   ANDROID_ENABLED=1            opt in (anything else: this whole capability is off)
#   ANDROID_SDK_LICENSE=accepted the Android SDK licence is the OPERATOR's to accept, never an agent's:
#                                https://developer.android.com/studio/terms
#   ANDROID_SDK_ROOT=…           where to install (default: ~/Android/Sdk)
#   ANDROID_AVD=…                the phone's name (default: astryx-phone)
#   ANDROID_DL_CACHE=…           (environment) a directory already holding the archives: used instead of downloading,
#                                and verified exactly like a download
#
# NO JAVA. Google's sdkmanager/avdmanager need a JDK; this doesn't use them. Each package is an exact archive from
# dl.google.com, verified against a SHA-256 pinned below (and Google's own published SHA-1), unpacked into the SDK
# layout the emulator reads, and the phone's two ini files are written directly. An upgrade is a reviewed change to
# the pins, never "latest". Measured needs (S0, plan-8675): /dev/kvm, ~3 GB free RAM while the phone runs (its qemu
# held 2.6–2.9 GB), ~4 GB disk for the SDK plus ~3 GB for the phone.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# A setting from the process environment first (so a test run overrides it without WRITING a .env: a copied .env is a
# second holder of the org's secrets), else from .env.
# Through the ONE resolver (plan-11324 S3a): astryx.config's get is exactly this order on one org, and on a host that runs
# several orgs it reads the org's HOME .env only (never an environment another org's process may have left).
envv() { "$ROOT/venv/bin/python" "$ROOT/src/astryx/config.py" get "$1" 2>/dev/null || true; }
ENABLED=$(envv ANDROID_ENABLED)
LICENSE=$(envv ANDROID_SDK_LICENSE)
SDK=$(envv ANDROID_SDK_ROOT); SDK=${SDK:-$HOME/Android/Sdk}; SDK=${SDK/#\~/$HOME}
AVD=$(envv ANDROID_AVD); AVD=${AVD:-astryx-phone}
AVD_HOME=${ANDROID_AVD_HOME:-$HOME/.android/avd}
BASE=https://dl.google.com/android/repository

# name | url path | sha256 | sha1 (Google's, from repository2-3.xml / sys-img2-3.xml) | unpack into | top dir in the zip
PINS=(
  "platform-tools 37.0.1|platform-tools_r37.0.1-linux.zip|d230f13842f60f782a8645f9c813f8f845bf36089ea7289f28c48f17979313f1|477254aa5f903c15cf51001717bdf347fb6b53e0|.|platform-tools"
  "emulator 37.2.12|emulator-linux_x64-16428233.zip|b08fc43d8608d2955f607f1b287beb525041e730086bdca3af152accac3af9c1|cd7362ea55dfb86a418958138dc396e74165dd01|.|emulator"
  "android-35 google_apis_playstore x86_64 r09|sys-img/google_apis_playstore/x86_64-35_r09.zip|1fb5e5fd1c4b1b54bfe5558f6f361d6c10e13786acff630153e0542df356dfe6|2f0054868e6aab3c098acd3decba17a82aed4176|system-images/android-35/google_apis_playstore|x86_64"
)
IMAGE_DIR=system-images/android-35/google_apis_playstore/x86_64

say() { echo "[android] $*"; }
tmp=""
trap 'rm -rf "${tmp:-}"' EXIT

kvm_ok() { [ -r /dev/kvm ] && [ -w /dev/kvm ]; }

pinned() {  # is this package installed at exactly this pin?
  local dest=$1 top=$2 sha=$3
  [ "$(cat "$SDK/$dest/$top/.astryx-pin" 2>/dev/null)" = "$sha" ]
}

installed() {
  local e name path sha sha1 dest top
  for e in "${PINS[@]}"; do
    IFS='|' read -r name path sha sha1 dest top <<< "$e"
    pinned "$dest" "$top" "$sha" || return 1
  done
  [ -f "$AVD_HOME/$AVD.ini" ] && [ -f "$AVD_HOME/$AVD.avd/config.ini" ] \
    && [ -f "$ROOT/mcp/phone/upstream/node_modules/@mobilenext/mobile-mcp/lib/index.js" ]
}

check() {
  [ "$ENABLED" = 1 ] || { echo "off (ANDROID_ENABLED=1 in .env opts in)"; return 0; }   # org-home: a message
  kvm_ok || { echo "SKIP: /dev/kvm is missing or not usable by $(id -un): the emulator needs hardware virtualisation"; return 77; }
  [ "$LICENSE" = accepted ] || { echo "the Android SDK licence isn't accepted: read https://developer.android.com/studio/terms, then put ANDROID_SDK_LICENSE=accepted in .env (the operator's act)"; return 3; }   # org-home: a message
  installed && { echo "ready: $AVD at $SDK"; return 0; }
  echo "not installed (scripts/android_setup.sh install)"; return 1
}

fetch() {  # name path sha256 sha1 dest top
  local name=$1 path=$2 sha=$3 sha1=$4 dest=$5 top=$6
  if pinned "$dest" "$top" "$sha"; then say "$name: already installed"; return 0; fi
  for t in curl unzip sha256sum sha1sum; do command -v "$t" >/dev/null || { say "needs $t"; return 1; }; done
  # Unpacked BESIDE the SDK, never in /tmp: /tmp is often RAM-backed or quota-limited, and a 1.7 GB image filled it
  # (measured). Same filesystem, so the final move is a rename.
  mkdir -p "$SDK"
  tmp=$(mktemp -d "$SDK/.astryx-tmp.XXXXXX")       # global: the EXIT trap removes it if a step below fails
  if [ -n "${ANDROID_DL_CACHE:-}" ] && [ -f "$ANDROID_DL_CACHE/$(basename "$path")" ]; then
    say "$name: from the local cache $ANDROID_DL_CACHE (verified below like a download)"
    cp "$ANDROID_DL_CACHE/$(basename "$path")" "$tmp/pkg.zip"
  else
    say "$name: downloading $BASE/$path"
    curl -fsSL -o "$tmp/pkg.zip" "$BASE/$path"
  fi
  if [ "$(sha256sum "$tmp/pkg.zip" | cut -d' ' -f1)" != "$sha" ] || \
     [ "$(sha1sum "$tmp/pkg.zip" | cut -d' ' -f1)" != "$sha1" ]; then
    rm -rf "$tmp"; say "$name: CHECKSUM MISMATCH, refusing to install it"; return 1
  fi
  unzip -q "$tmp/pkg.zip" -d "$tmp/x"
  [ -d "$tmp/x/$top" ] || { rm -rf "$tmp"; say "$name: the archive has no $top/ directory"; return 1; }
  mkdir -p "$SDK/$dest"
  rm -rf "$SDK/$dest/$top"
  mv "$tmp/x/$top" "$SDK/$dest/$top"
  echo "$sha" > "$SDK/$dest/$top/.astryx-pin"
  rm -rf "$tmp"
  say "$name: installed"
}

make_avd() {
  [ -f "$AVD_HOME/$AVD.avd/config.ini" ] && { say "phone $AVD: exists"; return 0; }
  mkdir -p "$AVD_HOME/$AVD.avd"
  chmod 700 "$HOME/.android" "$AVD_HOME" "$AVD_HOME/$AVD.avd"   # the phone's data holds app sessions (a1 A7)
  cat > "$AVD_HOME/$AVD.ini" <<EOF
avd.ini.encoding=UTF-8
path=$AVD_HOME/$AVD.avd
path.rel=avd/$AVD.avd
target=android-35
EOF
  # The keys avdmanager wrote for a pixel_6 on this image (measured, S0), minus the defaults the emulator fills in.
  cat > "$AVD_HOME/$AVD.avd/config.ini" <<EOF
avd.ini.encoding=UTF-8
AvdId=$AVD
avd.ini.displayname=$AVD
PlayStore.enabled=yes
abi.type=x86_64
hw.cpu.arch=x86_64
hw.cpu.ncore=2
image.sysdir.1=$IMAGE_DIR/
tag.id=google_apis_playstore
tag.display=Google Play
hw.device.manufacturer=Google
hw.device.name=pixel_6
hw.lcd.width=1080
hw.lcd.height=2400
hw.lcd.density=420
hw.ramSize=2048M
vm.heapSize=228M
disk.dataPartition.size=6G
hw.keyboard=yes
hw.gpu.enabled=no
hw.audioInput=no
hw.audioOutput=no
hw.camera.back=none
hw.camera.front=none
fastboot.forceFastBoot=yes
showDeviceFrame=no
EOF
  say "phone $AVD: created"
}

install() {
  [ "$ENABLED" = 1 ] || { echo "off: ANDROID_ENABLED=1 in .env opts in"; return 0; }   # org-home: a message
  kvm_ok || { echo "SKIP: no usable /dev/kvm"; return 77; }
  [ "$LICENSE" = accepted ] || { check || true; return 3; }
  local e name path sha sha1 dest top
  for e in "${PINS[@]}"; do
    IFS='|' read -r name path sha sha1 dest top <<< "$e"
    fetch "$name" "$path" "$sha" "$sha1" "$dest" "$top"
  done
  make_avd
  command -v npm >/dev/null || { say "needs node/npm for the phone's MCP upstream"; return 1; }
  (cd "$ROOT/mcp/phone/upstream" && npm ci --ignore-scripts --no-fund --no-audit >/dev/null)
  say "upstream @mobilenext/mobile-mcp installed from the committed lockfile (no install scripts run)"
  check
}

case "${1:-check}" in
  check) check ;;
  install) install ;;
  *) echo "usage: $0 check|install" >&2; exit 2 ;;
esac
