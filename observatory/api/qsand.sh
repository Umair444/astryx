#!/bin/sh
# astryx · qsand — ONE Qalculate evaluation in a sandbox (chat calc, owner 11-15). Run by calc.py as
#     timeout 5 unshare -rnm --propagation private qsand.sh <rates dir> " <expression>"
# The user namespace maps us to root INSIDE it only; -n leaves no network; -m gives a private mount table where the
# whole filesystem is re-bound READ-ONLY and /tmp is a small fresh tmpfs. Qalculate has export()/save() (they write
# files) and load()/command(): calc.py refuses those names, and this is the layer that holds if it ever misses one.
# Exchange rates are copied in from <rates dir> (calc.py refreshes them outside, on a schedule): nothing here fetches.
set -e
R="$1"; shift
mount --bind / / 2>/dev/null || true
mount -o remount,bind,ro /
mount -t tmpfs -o size=8m tmpfs /tmp
mkdir -p /tmp/h/.local/share/qalculate /tmp/h/.config
cp "$R"/* /tmp/h/.local/share/qalculate/ 2>/dev/null || true
cd /tmp
exec env -i HOME=/tmp/h XDG_DATA_HOME=/tmp/h/.local/share XDG_CONFIG_HOME=/tmp/h/.config PATH=/usr/bin:/bin qalc -t "$@" 2>/dev/null
