-- Expected outgoings typed in by the accountant (rent, payroll, tax, suppliers). Manual input, not read from Odoo.
CREATE TABLE obligations (
    id          BIGSERIAL PRIMARY KEY,
    description TEXT NOT NULL CHECK (length(btrim(description)) > 0),
    amount      BIGINT NOT NULL CHECK (amount > 0),
    currency    TEXT NOT NULL DEFAULT 'VND' CHECK (currency = 'VND'),
    due_date    DATE NOT NULL,
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX obligations_due_idx ON obligations (due_date);
