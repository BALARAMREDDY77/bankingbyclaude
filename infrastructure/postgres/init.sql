-- ============================================================
-- PostgreSQL Initialization Script
-- Runs once on first container creation
-- ============================================================

-- Enable useful extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";      -- UUID generation
CREATE EXTENSION IF NOT EXISTS "pg_trgm";         -- Fuzzy text search
CREATE EXTENSION IF NOT EXISTS "btree_gin";       -- GIN index support

-- Set default timezone
SET timezone = 'UTC';

-- Performance tuning for the banking workload
-- (These are set at connection level; configure postgresql.conf for persistence)
ALTER SYSTEM SET timezone = 'UTC';
ALTER SYSTEM SET log_timezone = 'UTC';
