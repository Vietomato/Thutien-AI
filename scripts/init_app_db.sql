-- Creates the application database (users, reminder drafts, tasks, audit log).
-- Odoo's own database stays read-only for this app; nothing is written there.
-- Run once as the Postgres superuser:
--   Get-Content scripts/init_app_db.sql | docker compose exec -T db psql -U odoo -d postgres
-- Dev-only password, same convention as create_readonly_role.sql. Change it in your own setup
-- and put the real value in APP_DB_PASSWORD.
CREATE ROLE thutien_app LOGIN PASSWORD 'change-me';
CREATE DATABASE thutien_app OWNER thutien_app;
-- Separate database for automated tests (tables are truncated between tests).
CREATE DATABASE thutien_test OWNER thutien_app;
