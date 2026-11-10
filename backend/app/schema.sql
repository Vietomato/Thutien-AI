-- Application schema. Idempotent: safe to run on every start.

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT NOT NULL,
    full_name     TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('accountant', 'chief_accountant', 'customer', 'admin')),
    -- Odoo partner ref (e.g. C001). Only meaningful for role 'customer': limits which invoices they see.
    customer_id   TEXT,
    -- A chief accountant supervises accountants: they see that team's tasks and drafts.
    supervisor_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    failed_logins INT NOT NULL DEFAULT 0,
    locked_until  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS users_username_key ON users (lower(username));

CREATE TABLE IF NOT EXISTS audit_log (
    id     BIGSERIAL PRIMARY KEY,
    ts     TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor  TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_log_ts_idx ON audit_log (ts DESC);

-- Append-only: rows can never be changed or removed (TRUNCATE is only for test cleanup).
CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_log_no_change ON audit_log;
CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

CREATE TABLE IF NOT EXISTS reminder_drafts (
    id            BIGSERIAL PRIMARY KEY,
    invoice_id    TEXT NOT NULL,
    customer_id   TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    contact_email TEXT,
    amount        BIGINT NOT NULL,
    due_date      DATE NOT NULL,
    overdue_days  INT NOT NULL,
    source_version TEXT,
    subject       TEXT NOT NULL,
    body          TEXT NOT NULL,
    generation_source TEXT NOT NULL DEFAULT 'template_fallback',
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    created_by    BIGINT NOT NULL REFERENCES users(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by    BIGINT REFERENCES users(id),
    decided_at    TIMESTAMPTZ,
    decision_note TEXT
);
-- Existing local databases were created before T18; migrate without discarding drafts.
ALTER TABLE reminder_drafts ADD COLUMN IF NOT EXISTS generation_source TEXT NOT NULL DEFAULT 'template_fallback';
ALTER TABLE reminder_drafts ADD COLUMN IF NOT EXISTS source_version TEXT;
-- At most one pending draft per invoice.
CREATE UNIQUE INDEX IF NOT EXISTS reminder_one_pending ON reminder_drafts (invoice_id) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS tasks (
    id            BIGSERIAL PRIMARY KEY,
    invoice_id    TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    title         TEXT NOT NULL,
    note          TEXT,
    assignee_id   BIGINT NOT NULL REFERENCES users(id),
    created_by    BIGINT NOT NULL REFERENCES users(id),
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    done_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS tasks_assignee_idx ON tasks (assignee_id, status);
