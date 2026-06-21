-- Audit event table for append-only compliance log
CREATE TABLE audit_event (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload JSONB NOT NULL,
    config_hash TEXT,
    prev_hash TEXT,
    row_hash TEXT NOT NULL,
    retention_class TEXT NOT NULL
);

-- Application role with only INSERT + SELECT
CREATE ROLE app_role;
GRANT CONNECT ON DATABASE interopera TO app_role;
GRANT USAGE ON SCHEMA public TO app_role;
GRANT INSERT, SELECT ON audit_event TO app_role;
GRANT USAGE, SELECT ON SEQUENCE audit_event_id_seq TO app_role;

-- Explicitly revoke any write or delete privileges
REVOKE UPDATE, DELETE ON audit_event FROM PUBLIC;
REVOKE UPDATE, DELETE ON audit_event FROM app_role;

-- TRUNCATE bypasses row-level BEFORE DELETE triggers, so it must be revoked separately.
REVOKE TRUNCATE ON audit_event FROM PUBLIC;
REVOKE TRUNCATE ON audit_event FROM app_role;

-- Trigger function to enforce append-only at the DB level
CREATE OR REPLACE FUNCTION enforce_audit_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_event is append-only: UPDATE and DELETE are forbidden';
END;
$$ LANGUAGE plpgsql;

-- Attach trigger for both UPDATE and DELETE
CREATE TRIGGER audit_event_no_update_delete
BEFORE UPDATE OR DELETE ON audit_event
FOR EACH ROW EXECUTE FUNCTION enforce_audit_append_only();
