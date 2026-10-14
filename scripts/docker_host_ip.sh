# astryx · docker_host_ip — the ONE answer to "what address do containers use to reach this host?" (goal 10224 S3).
# The whatsapp bridge binds it and wacli's webhook targets it. It used to be a hardcoded 172.17.0.1, which is only
# right on a Linux host running docker-ce with the default bridge. Resolution order, first answer wins:
#   1. $ASTRYX_DOCKER_HOST_IP in the environment     (an explicit choice always wins)
#   2. ASTRYX_DOCKER_HOST_IP= in the env file ($1, default .env)
#   3. the IPv4 address of docker0                   (`ip -4 addr show docker0`: docker-ce on Linux or inside WSL)
#   4. what host.docker.internal resolves to         (`getent hosts`: Docker Desktop)
#   5. 172.17.0.1                                    (the old literal, so a host that answers nothing behaves as before)
# On a docker-ce Linux host (the live org) step 3 answers 172.17.0.1, so generated units are byte-identical.
# `ip` and `getent` are called bare so tests can stub them as shell functions. Sourced by init.sh and
# scripts/deploy.sh; run directly, it prints the answer.
_docker_host_ip() {
  local envf=${1:-.env} v=""
  [ -n "${ASTRYX_DOCKER_HOST_IP:-}" ] && { printf '%s\n' "$ASTRYX_DOCKER_HOST_IP"; return 0; }
  v=$(grep -m1 '^ASTRYX_DOCKER_HOST_IP=' "$envf" 2>/dev/null | cut -d= -f2- || true)
  [ -n "$v" ] && { printf '%s\n' "$v"; return 0; }
  v=$(ip -4 addr show docker0 2>/dev/null | awk '$1 == "inet" { sub(/\/.*/, "", $2); print $2; exit }' || true)
  [ -n "$v" ] && { printf '%s\n' "$v"; return 0; }
  v=$(getent hosts host.docker.internal 2>/dev/null | awk '$1 ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ { print $1; exit }' || true)
  [ -n "$v" ] && { printf '%s\n' "$v"; return 0; }
  printf '%s\n' 172.17.0.1
}
if [ "${BASH_SOURCE[0]}" = "$0" ]; then _docker_host_ip "$@"; fi
