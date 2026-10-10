# ASTRYX · Postgres 18 + pgvector + PostGIS + Apache AGE (the org's one database server; moved from the deprecated
# genesis tree, 2026-10-10, steward F4 of #42345)
# One database engine for the whole org: agents' basic ops, the Memory RAG (pgvector),
# geospatial (PostGIS), and the social/knowledge graph (AGE, openCypher).
#
# AGE is compiled from source — no PGDG package exists for it. Build rules, from the
# org's rollout plan (2026-08-13):
#   * never overwrite the :latest tag — build as genesis/pg18:age, prove on a restored
#     copy, swap the container; :latest IS the rollback.
#   * never add age to shared_preload_libraries — a broken .so would stop postgres
#     itself (wire, steps, messages all down). Per-session `LOAD 'age'` only.
#   * the AGE extension is created in its OWN database, never in `astryx` — extensions
#     dump at database scope, and `CREATE EXTENSION age` inside the main db would weld
#     disaster recovery to a source-compiled C extension.

FROM postgres:18-bookworm AS agebuild
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        git ca-certificates build-essential postgresql-server-dev-18 \
        bison flex zlib1g-dev libreadline-dev; \
    rm -rf /var/lib/apt/lists/*
# PINNED (seed #42759, steward F4): the PG18 line's 1.8.0 tag, PG18/v1.8.0-rc0, resolved to its commit. It is the only
# 1.8.0 tag on that line (no final release tag as of 2026-10-10); the running image reports age extversion 1.8.0.
# An unpinned master meant "the design on github matches local" could not survive a rebuild. infra's parity gate
# compares AGE_VERSION below with the live extversion, so a rebuild that drifts reads RED.
ARG AGE_REF=e43dc1a12b78fba4acef9835b2b10379b8d243b4
RUN set -eux; \
    git clone https://github.com/apache/age /age; \
    cd /age; \
    git checkout --detach "$AGE_REF"; \
    echo "AGE_SHA=$(git rev-parse HEAD)"; \
    make PG_CONFIG=/usr/lib/postgresql/18/bin/pg_config -j"$(nproc)"; \
    make PG_CONFIG=/usr/lib/postgresql/18/bin/pg_config install

FROM postgres:18-bookworm
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        postgresql-18-pgvector \
        postgresql-18-postgis-3 \
        postgresql-18-postgis-3-scripts; \
    rm -rf /var/lib/apt/lists/*
COPY --from=agebuild /usr/lib/postgresql/18/lib/age.so /usr/lib/postgresql/18/lib/
COPY --from=agebuild /usr/share/postgresql/18/extension/age* /usr/share/postgresql/18/extension/

# The extension versions this image is DECLARED to carry (infra's parity gate reads these lines and compares them with
# the live pg_extension.extversion; a rebuild that drifts reads RED).
LABEL org.astryx.pg.age_version="1.8.0" \
      org.astryx.pg.vector_version="0.8.6" \
      org.astryx.pg.postgis_version="3.6.4"
