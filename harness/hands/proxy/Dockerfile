# plan-7862 S1: the PER-LEASE proxy. A default-deny tinyproxy whose filter is NOT baked in. The
# executor (nucleus/hands.py) generates it from the lease row and mounts it read-only. Without
# that mount there's no filter file, and the proxy denies everything or refuses to start; both
# are the safe side. Reusing harness/cell/proxy (whose baked filter allows api.anthropic.com)
# would turn a failed mount into a model-API pinhole, which the design forbids (a4 #38063 §1).
FROM node:20-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends tinyproxy \
    && rm -rf /var/lib/apt/lists/* && rm -f /etc/tinyproxy/filter
COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
EXPOSE 8888
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
