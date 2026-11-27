#!/bin/sh
# astryx · qsand — ONE Qalculate evaluation in a sandbox (chat calc, owner 11-15). Run by calc.py as
#     timeout 5 unshare -rnm --propagation private qsand.sh <rates dir> " <expression>"
# The user namespace maps us to root INSIDE it only; -n leaves no network; -m gives a private mount table. In it, qalc
# runs CHROOTED into an empty tmpfs that holds only what it needs, read-only: its binary, the shared libraries, its
# data (/usr/share/qalculate), a copy of the exchange rates and a two-line /etc/passwd. No shell, no other program,
# no host file: Qalculate's load()/command() (callable WITHOUT parentheses, which beat the name gate: medic 12192) find
# nothing to read and nothing to run, and export()/save() find nowhere to write but the jail's own scratch.
set -e
R="$1"; shift
J=/tmp/jail
mount -t tmpfs -o size=16m,mode=0755 tmpfs /tmp
mkdir -p $J/usr/bin $J/usr/lib/x86_64-linux-gnu $J/usr/lib64 $J/usr/share/qalculate $J/etc $J/h/.local/share/qalculate \
         $J/h/.config $J/tmp
ln -s usr/lib $J/lib; ln -s usr/lib64 $J/lib64
touch $J/usr/bin/qalc
for m in /usr/bin/qalc /usr/lib/x86_64-linux-gnu /usr/lib64 /usr/share/qalculate; do
  mount --bind "$m" "$J$m"
  mount -o remount,bind,ro "$J$m"
done
cp "$R"/* $J/h/.local/share/qalculate/ 2>/dev/null || true
printf 'root:x:0:0::/h:/nonexistent\n' > $J/etc/passwd
printf 'root:x:0:\n' > $J/etc/group
cd $J
exec chroot $J /usr/bin/qalc -t "$@" 2>/dev/null
