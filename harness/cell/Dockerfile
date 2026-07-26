# The hermetic agent cell (goal 15) — containment milestone 0.
# Reproduces the exact host paths the runtime + hooks resolve, with CANARY content and
# NO host mount, so a same-uid injected agent inside finds only the sandbox. The real
# claude runtime goes in at milestone 2; this image proves the boundary holds first.
FROM node:20-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 postgresql-client iproute2 netcat-openbsd ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The canary tree AT THE EXACT REAL ABSOLUTE PATHS. Because hooks/step.py:21 hardcodes
# /home/umair/astryx/.env and channel/server.mjs:15 resolves its own sibling ../.env, a
# sandbox at any OTHER directory would not redirect them — so the cell must present canary
# content at these very paths.
RUN mkdir -p /home/umair/astryx/channel /home/umair/astryx/hooks \
             /home/umair/astryx/venv/bin /home/umair/astryx/mcp

COPY canary/env.canary        /home/umair/astryx/.env
COPY canary/CANARY.txt        /home/umair/astryx/CANARY.txt
COPY canary/resolve_dsn.mjs   /home/umair/astryx/channel/resolve_dsn.mjs
COPY canary/step.py           /home/umair/astryx/hooks/step.py
COPY canary/venv_marker       /home/umair/astryx/venv/CANARY
COPY canary/venv_marker       /home/umair/astryx/mcp/CANARY

COPY prove_containment.sh     /prove_containment.sh
RUN chmod +x /prove_containment.sh

# Non-root inside the cell as an extra layer (defence in depth); the boundary that
# matters is the filesystem+network isolation, not the uid.
CMD ["/prove_containment.sh"]
