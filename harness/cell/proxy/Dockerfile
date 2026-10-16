# The egress seam (goal 15, milestone 1) — the ONE hole in the cell's containment.
# A default-deny forward proxy: only the model-API host (the cognition channel the
# runtime must reach to think) is allowed; every other CONNECT is denied AND logged —
# that denied-attempt log IS the arbitrary-host-exfil detector. NO TLS interception
# (rank-4 #1046): the SNI/host allow-list works on the plaintext CONNECT target without
# decrypting, and the canary-egress oracle lives in-cell at the plaintext tool boundary,
# not here (the model-API body carries planted canaries by design — scanning it would
# false-positive every turn).
# node:20-bookworm-slim (already local; the registry is IPv6-unreachable from this host,
# and debian bookworm is the same apt base) — we only need tinyproxy off it.
FROM node:20-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends tinyproxy \
    && rm -rf /var/lib/apt/lists/*
COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY filter         /etc/tinyproxy/filter
EXPOSE 8888
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
