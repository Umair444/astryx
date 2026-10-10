#!/usr/bin/env bash
# test_doctor_pg_exposure — init.sh doctor's "every org's database is localhost-only" check (owner
# 10-10), through its real helper _pg_exposure with a stubbed `ss`. It must fail BOTH ways: a wide
# listener is "wide", loopback alone is "ok", and an ss that can't answer is "unverified", never ok
# (a2 #42283: the first version read OK when ss was missing).
set -u
cd "$(dirname "$0")/.."
eval "$(sed -n '/^_pg_exposure() {/,/^}/p' init.sh)"
fails=0
arm() { if [ "$2" = "$3" ]; then echo "  PASS  $1"; else echo "  FAIL  $1 — got '$2', want '$3'"; fails=$((fails+1)); fi; }
first() { printf '%s' "$1" | cut -d' ' -f1; }

ss() { printf 'LISTEN 0 4096 127.0.0.1:5432 0.0.0.0:*\nLISTEN 0 4096 192.168.1.9:5432 0.0.0.0:*\n'; }
arm "(1) a LAN listener on the port → wide" "$(first "$(_pg_exposure 5432)")" wide
ss() { printf 'LISTEN 0 4096 0.0.0.0:5432 0.0.0.0:*\n'; }
arm "(2) 0.0.0.0 → wide" "$(first "$(_pg_exposure 5432)")" wide
ss() { printf 'LISTEN 0 4096 [::]:5432 [::]:*\n'; }
arm "(2) [::] → wide" "$(first "$(_pg_exposure 5432)")" wide
ss() { printf 'LISTEN 0 4096 127.0.0.1:5432 0.0.0.0:*\nLISTEN 0 4096 [::1]:5432 [::]:*\nLISTEN 0 4096 0.0.0.0:8090 0.0.0.0:*\n'; }
arm "(3) loopback only (another port wide doesn't count) → ok" "$(_pg_exposure 5432)" ok
ss() { return 127; }
arm "(4) ss missing → unverified, never ok" "$(_pg_exposure 5432)" unverified
ss() { return 0; }
arm "(4) ss prints nothing → unverified, never ok" "$(_pg_exposure 5432)" unverified
[ "$fails" = 0 ] && echo PASS || { echo "FAIL ($fails)"; exit 1; }
