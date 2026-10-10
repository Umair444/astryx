-- astryx · schema_geo.sql — the DESIGN of the `geo` database (owner 10-10: "the design on github should match local").
--
-- DDL only, never a value: the location ROWS are human-personal tier and stay out of git (local.md); the writer code
-- (bridges/geoloc.py, mcp/geoloc/) stays gitignored. Applied to the `geo` database (not `astryx`) by init.sh's geoschema
-- node; nucleus/schema_parity.py compares the live `track` schema against a fresh apply of this file.
--
-- PROVENANCE (steward, 10-10, F1 of the DB-design audit #42345): written FROM THE LIVE CATALOG, because the only prior
-- declaration (the deprecated genesis tree's initdb, in no repo) defined track.locations alone. track.zones and
-- track.presence existed only on the server, created by hand. Every statement is idempotent.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS track;

-- one row per fix the phone posts (Tasker → bridges/geoloc.py)
CREATE TABLE IF NOT EXISTS track.locations (
    id          bigserial   PRIMARY KEY,
    ts          timestamptz NOT NULL DEFAULT now(),
    source      text        NOT NULL DEFAULT 'tasker',
    lat         double precision,
    lon         double precision,
    accuracy    double precision,
    altitude    double precision,
    speed       double precision,
    bearing     double precision,
    battery     int,
    raw         jsonb       NOT NULL DEFAULT '{}',
    geom        geography(Point, 4326)
);
CREATE INDEX IF NOT EXISTS locations_ts_idx   ON track.locations (ts DESC);
CREATE INDEX IF NOT EXISTS locations_geom_idx ON track.locations USING gist (geom);

-- named places a fix is judged against
CREATE TABLE IF NOT EXISTS track.zones (
    id          serial      PRIMARY KEY,
    name        text        NOT NULL UNIQUE,
    lat         double precision NOT NULL,
    lon         double precision NOT NULL,
    radius_m    double precision NOT NULL DEFAULT 250,
    tier        text        NOT NULL DEFAULT 'trusted',
    created     timestamptz DEFAULT now()
);

-- the ONE current-presence row (id is always true: the CHECK makes it a singleton)
CREATE TABLE IF NOT EXISTS track.presence (
    id          boolean     PRIMARY KEY DEFAULT true CHECK (id),
    zone        text,
    since       timestamptz,
    updated     timestamptz DEFAULT now()
);
