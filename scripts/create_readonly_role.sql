CREATE ROLE thutien_ro LOGIN PASSWORD 'change-me';
GRANT CONNECT ON DATABASE odoo TO thutien_ro;
GRANT USAGE ON SCHEMA public TO thutien_ro;
GRANT SELECT ON account_move, account_move_line, account_partial_reconcile, res_partner TO thutien_ro;
ALTER ROLE thutien_ro SET default_transaction_read_only = on;