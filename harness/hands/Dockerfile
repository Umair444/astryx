# plan-7862 "Hands", S1: THE CELL. A browser the driver steers, and nothing else.
# Xvfb + chromium + playwright-core are all INSIDE the image (a4 #38063 §1, F1: none on the
# host). There's no claude runtime, no model-API pinhole, no host path, and no canary tree: this
# cell holds a browser profile and nothing of the org's. The one way out is the per-lease proxy
# (nucleus/hands.py); the profile is tmpfs, so killing the container wipes it.
# node:20-bookworm-slim, the base the hermetic cell already uses (local; the registry is
# IPv6-unreachable from this host).
FROM node:20-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium xvfb xauth fonts-liberation ca-certificates curl dumb-init \
    && rm -rf /var/lib/apt/lists/*

# playwright-core drives the SYSTEM chromium (no browser download at run time; the cell has no
# route to a CDN anyway).
WORKDIR /hands
RUN npm init -y >/dev/null && npm install --omit=dev playwright-core@1 >/dev/null \
    && node -e "require('playwright-core')"

COPY drive.mjs /hands/drive.mjs
COPY entry.sh  /hands/entry.sh
RUN chmod +x /hands/entry.sh && useradd -m -u 10001 hands && mkdir -p /profile \
    && chown hands /profile
USER hands
ENV DISPLAY=:99 HANDS_PROFILE=/profile
ENTRYPOINT ["dumb-init", "--", "/hands/entry.sh"]
