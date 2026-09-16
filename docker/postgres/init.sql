-- ─────────────────────────────────────────────────────────────────────────
-- NetSuite-ISP  —  Postgres initialisation
-- Runs once when the container is first created.
-- ─────────────────────────────────────────────────────────────────────────

-- TimescaleDB extension (installed on the main DB)
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Separate database + user for FreeRADIUS
-- (avoids giving RADIUS the full netsuite password)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'radius') THEN
    CREATE ROLE radius WITH LOGIN PASSWORD 'devpassword';
  END IF;
END
$$;

CREATE DATABASE radius OWNER radius;
