"""Audit log tests. Requires Postgres with init.sql applied.

Set POSTGRES_DSN env var (or POSTGRES_TEST_DSN) to override the default connection string.

Append-only enforcement note:
  The audit_event table has a BEFORE UPDATE OR DELETE trigger that fires for ALL
  connections including superuser.  The app also connects via 'interopera' which is
  the DB superuser in the default postgres image, so the REVOKE alone does not restrict
  it — but the trigger does.  In production the app MUST connect as a non-superuser
  role (app_role) so both the trigger AND the REVOKE apply (defense in depth).
"""
import os
import uuid

import pytest

PG_DSN = os.environ.get(
    "POSTGRES_DSN",
    os.environ.get(
        "POSTGRES_TEST_DSN",
        "postgresql://interopera:interopera@localhost:5432/interopera",
    ),
)


@pytest.fixture
def logger():
    """Provide a fresh AuditLogger with a clean audit_event table."""
    try:
        from src.audit.log import AuditLogger
        import psycopg

        # TRUNCATE is not caught by row-level BEFORE DELETE triggers, so it works
        # even though DELETE is blocked by the trigger.
        with psycopg.connect(PG_DSN) as conn:
            conn.execute("TRUNCATE TABLE audit_event RESTART IDENTITY")
            conn.commit()

        log = AuditLogger(PG_DSN)
        yield log
        log.close()
    except Exception as e:
        pytest.skip(f"Postgres not available: {e}")


# ---------------------------------------------------------------------------
# log_event: basic insert
# ---------------------------------------------------------------------------


def test_log_event_inserts_row(logger):
    """log_event inserts a row with correct run_id, event_type, and actor."""
    import psycopg

    run_id = str(uuid.uuid4())
    logger.log_event(
        run_id=run_id,
        event_type="figure_computed",
        actor="system",
        payload={"figure": "allocation_sgs", "value": "35.0%"},
        retention_class="compliance",
    )
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "SELECT run_id, event_type, actor FROM audit_event WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    assert row is not None
    assert str(row[0]) == run_id
    assert row[1] == "figure_computed"
    assert row[2] == "system"


def test_row_hash_is_sha256(logger):
    """row_hash must be a 64-character lowercase hex string (SHA-256)."""
    import psycopg

    run_id = str(uuid.uuid4())
    logger.log_event(
        run_id=run_id,
        event_type="config_loaded",
        actor="system",
        payload={"firm": "firm_a"},
        retention_class="operational",
    )
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "SELECT row_hash FROM audit_event WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    row_hash = row[0]
    assert len(row_hash) == 64, "SHA-256 hex digest must be 64 characters"
    int(row_hash, 16)  # must be valid hex


# ---------------------------------------------------------------------------
# hash chain: determinism and verify_chain
# ---------------------------------------------------------------------------


def test_verify_chain_returns_true_for_clean_log(logger):
    """verify_chain() returns True when no rows have been tampered with."""
    run_id = str(uuid.uuid4())
    for i in range(3):
        logger.log_event(
            run_id=run_id,
            event_type="figure_computed",
            actor="system",
            payload={"figure": f"fig_{i}", "value": f"{i}.0%"},
            retention_class="compliance",
        )
    assert logger.verify_chain() is True


def test_hash_chain_is_deterministic(logger):
    """Same events in the same order produce identical row_hash values."""
    import psycopg
    import hashlib, json

    run_id = str(uuid.uuid4())
    payloads = [
        {"event": "graph_construction", "nodes": 5},
        {"event": "reconciliation", "status": "ok"},
        {"event": "report_exported", "format": "pdf"},
    ]
    for i, p in enumerate(payloads):
        logger.log_event(
            run_id=run_id,
            event_type=list(p.keys())[0],
            actor="system",
            payload=p,
            retention_class="compliance",
        )

    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT payload, prev_hash, row_hash FROM audit_event ORDER BY id ASC"
        ).fetchall()

    # Recompute from genesis
    prev = "genesis"
    for payload_raw, stored_prev, stored_hash in rows:
        assert stored_prev == prev, "prev_hash chain is broken"
        canonical = json.dumps(payload_raw, sort_keys=True)
        expected = hashlib.sha256((canonical + prev).encode()).hexdigest()
        assert stored_hash == expected, "row_hash mismatch — hash chain is not deterministic"
        prev = stored_hash


def test_verify_chain_returns_false_after_corruption(logger):
    """verify_chain() returns False when a row's stored hash no longer matches.

    The trigger blocks UPDATE for all users, so we temporarily disable it using
    DDL (superuser-only) to simulate tampering, then re-enable it.
    """
    import psycopg

    run_id = str(uuid.uuid4())
    for i in range(3):
        logger.log_event(
            run_id=run_id,
            event_type="figure_computed",
            actor="system",
            payload={"figure": f"fig_{i}", "value": f"{i}.0%"},
            retention_class="compliance",
        )

    # Temporarily disable the append-only trigger to simulate tampering.
    # This requires the superuser — in production this DDL is not available
    # to app_role, which is the correct security posture.
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            "ALTER TABLE audit_event DISABLE TRIGGER audit_event_no_update_delete"
        )
        conn.execute(
            "UPDATE audit_event SET payload = '{\"tampered\": true}'::jsonb "
            "WHERE id = (SELECT MIN(id) FROM audit_event)"
        )
        conn.execute(
            "ALTER TABLE audit_event ENABLE TRIGGER audit_event_no_update_delete"
        )
        conn.commit()

    assert logger.verify_chain() is False, (
        "verify_chain() should detect the tampered row and return False"
    )


# ---------------------------------------------------------------------------
# Append-only enforcement: trigger blocks UPDATE and DELETE
# ---------------------------------------------------------------------------


def test_update_raises_exception_via_trigger(logger):
    """The DB trigger MUST prevent UPDATE on audit_event for all connections.

    Production note: in production the app connects as app_role (non-superuser),
    so both the trigger AND the REVOKE apply.  When connecting as interopera
    (DB superuser, as in tests), only the trigger applies — but it still fires.
    """
    import psycopg

    run_id = str(uuid.uuid4())
    logger.log_event(
        run_id=run_id,
        event_type="config_loaded",
        actor="system",
        payload={"firm": "firm_a"},
        retention_class="operational",
    )
    with pytest.raises(Exception, match="append-only"):
        with psycopg.connect(PG_DSN) as conn:
            conn.execute(
                "UPDATE audit_event SET actor = 'hacker' WHERE run_id = %s",
                (run_id,),
            )
            conn.commit()


def test_delete_raises_exception_via_trigger(logger):
    """The DB trigger MUST prevent DELETE on audit_event for all connections."""
    import psycopg

    run_id = str(uuid.uuid4())
    logger.log_event(
        run_id=run_id,
        event_type="reconciliation",
        actor="system",
        payload={"status": "ok"},
        retention_class="compliance",
    )
    with pytest.raises(Exception, match="append-only"):
        with psycopg.connect(PG_DSN) as conn:
            conn.execute(
                "DELETE FROM audit_event WHERE run_id = %s",
                (run_id,),
            )
            conn.commit()


# ---------------------------------------------------------------------------
# Event types coverage
# ---------------------------------------------------------------------------


def test_all_event_types_are_insertable(logger):
    """All five required event types must be accepted by log_event."""
    event_types = [
        "graph_construction",
        "figure_computed",
        "reconciliation",
        "config_loaded",
        "report_exported",
    ]
    run_id = str(uuid.uuid4())
    for et in event_types:
        logger.log_event(
            run_id=run_id,
            event_type=et,
            actor="system",
            payload={"event": et},
            retention_class="compliance",
        )
    assert logger.verify_chain() is True
