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

        # Teardown: remove test rows (including any intentionally corrupted rows from
        # tamper-detection tests) so they don't pollute the CLI's audit chain.
        with psycopg.connect(PG_DSN) as conn:
            conn.execute("TRUNCATE TABLE audit_event RESTART IDENTITY")
            conn.commit()
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
    import hashlib
    import json

    run_id = str(uuid.uuid4())
    events = [
        ("graph_construction", "system", None, {"event": "graph_construction", "nodes": 5}),
        ("reconciliation", "system", None, {"event": "reconciliation", "status": "ok"}),
        ("report_exported", "system", "abc123", {"event": "report_exported", "format": "pdf"}),
    ]
    for event_type, actor, config_hash, payload in events:
        logger.log_event(
            run_id=run_id,
            event_type=event_type,
            actor=actor,
            payload=payload,
            config_hash=config_hash,
            retention_class="compliance",
        )

    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT event_type, actor, config_hash, payload, prev_hash, row_hash "
            "FROM audit_event ORDER BY id ASC"
        ).fetchall()

    # Recompute from genesis using the same canonical form as _compute_row_hash
    prev = "genesis"
    for event_type, actor, config_hash, payload_raw, stored_prev, stored_hash in rows:
        assert stored_prev == prev, "prev_hash chain is broken"
        canonical = json.dumps(
            {
                "event_type": event_type,
                "actor": actor,
                "config_hash": config_hash,
                "payload": payload_raw,
            },
            sort_keys=True,
            default=str,
        )
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


# ---------------------------------------------------------------------------
# Hash chain covers metadata: actor tamper detection
# ---------------------------------------------------------------------------


def test_verify_chain_detects_actor_tamper(logger):
    """verify_chain() returns False when only the actor column is changed out-of-band.

    Because the hash now covers event_type + actor + config_hash + payload,
    changing actor without recomputing row_hash is detected even though payload
    is untouched. This test proves that metadata fields are protected.
    """
    import psycopg

    run_id = str(uuid.uuid4())
    logger.log_event(
        run_id=run_id,
        event_type="figure_computed",
        actor="legitimate_user",
        payload={"figure": "allocation_sgs", "value": "35.0%"},
        retention_class="compliance",
    )

    # Disable trigger, silently change actor only, re-enable trigger.
    # This is the same DDL technique used in the payload-corruption test.
    # In production, app_role cannot issue DDL — this is superuser-only.
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            "ALTER TABLE audit_event DISABLE TRIGGER audit_event_no_update_delete"
        )
        conn.execute(
            "UPDATE audit_event SET actor = 'attacker' WHERE run_id = %s",
            (run_id,),
        )
        conn.execute(
            "ALTER TABLE audit_event ENABLE TRIGGER audit_event_no_update_delete"
        )
        conn.commit()

    assert logger.verify_chain() is False, (
        "verify_chain() must detect actor tampering — actor is now part of the hash input"
    )


# ---------------------------------------------------------------------------
# BUG 1 — _verify_rows: chain-link enforcement (pure unit tests, no DB)
# ---------------------------------------------------------------------------


def _build_valid_chain(n: int = 3) -> list[tuple]:
    """Build a correctly-linked chain of n rows for testing _verify_rows."""
    import hashlib
    import json

    GENESIS = "genesis"
    rows: list[tuple] = []
    prev = GENESIS
    for i in range(n):
        event_type = "figure_computed"
        actor = "system"
        config_hash = None
        payload = {"index": i}
        canonical = json.dumps(
            {
                "event_type": event_type,
                "actor": actor,
                "config_hash": config_hash,
                "payload": payload,
            },
            sort_keys=True,
            default=str,
        )
        row_hash = hashlib.sha256((canonical + prev).encode()).hexdigest()
        rows.append((event_type, actor, config_hash, payload, prev, row_hash))
        prev = row_hash
    return rows


def test_verify_rows_returns_true_for_valid_chain():
    """_verify_rows returns True for a correctly-linked chain."""
    from src.audit.log import AuditLogger

    rows = _build_valid_chain(3)
    assert AuditLogger._verify_rows(rows) is True


def test_verify_rows_returns_false_for_broken_chain_link():
    """_verify_rows returns False when row N's prev_hash does not equal row N-1's row_hash.

    This is the CRITICAL bug: the old verify_chain() only checked each row's own
    hash was self-consistent, but never verified the chain link between rows.
    A forged sequence where row 2's prev_hash is swapped to something other than
    row 1's row_hash — but row 2 is otherwise internally self-consistent — MUST
    be rejected by the fixed code.
    """
    import hashlib
    import json

    from src.audit.log import AuditLogger

    # Build a valid 3-row chain first.
    rows = list(_build_valid_chain(3))

    # Forge row 2 (index 1): swap its prev_hash to an arbitrary value but
    # recompute its row_hash so the row is internally self-consistent.
    # Row 1 (index 0) still has its original row_hash, so the link is broken.
    event_type, actor, config_hash, payload, _orig_prev, _orig_row_hash = rows[1]
    forged_prev = "a" * 64  # arbitrary valid-looking hash, NOT row 0's row_hash
    canonical = json.dumps(
        {
            "event_type": event_type,
            "actor": actor,
            "config_hash": config_hash,
            "payload": payload,
        },
        sort_keys=True,
        default=str,
    )
    forged_row_hash = hashlib.sha256((canonical + forged_prev).encode()).hexdigest()
    rows[1] = (event_type, actor, config_hash, payload, forged_prev, forged_row_hash)

    # The old code would PASS this because each row's computed hash matches its
    # stored_hash. The fixed _verify_rows must return False because the link is broken.
    assert AuditLogger._verify_rows(rows) is False, (
        "_verify_rows must detect that row 2's prev_hash does not match row 1's row_hash"
    )


def test_verify_rows_empty_chain_returns_true():
    """_verify_rows returns True for an empty chain (nothing to verify)."""
    from src.audit.log import AuditLogger

    assert AuditLogger._verify_rows([]) is True


def test_verify_rows_detects_tampered_row_hash():
    """_verify_rows returns False when a row's stored_hash is corrupted."""
    from src.audit.log import AuditLogger

    rows = list(_build_valid_chain(2))
    # Corrupt the stored_hash of the first row without changing anything else.
    et, ac, ch, pl, pv, _ = rows[0]
    rows[0] = (et, ac, ch, pl, pv, "dead" * 16)  # 64-char garbage
    assert AuditLogger._verify_rows(rows) is False


# ---------------------------------------------------------------------------
# BUG 3 — list_events: SQL-level LIMIT (DB required)
# ---------------------------------------------------------------------------


def test_list_events_uses_sql_limit(logger):
    """list_events returns the last `limit` rows in ascending order without
    fetching the full table — verified by inserting more rows than the limit
    and checking the returned ids are the most recent ones."""
    import psycopg

    # Insert 5 rows, then ask for limit=3 — expect the last 3 in asc order.
    run_id = str(__import__("uuid").uuid4())
    for i in range(5):
        logger.log_event(
            run_id=run_id,
            event_type="figure_computed",
            actor="system",
            payload={"index": i},
        )

    events = logger.list_events(limit=3)
    assert len(events) == 3

    # The returned events must be in ascending id order.
    ids = [e["id"] for e in events]
    assert ids == sorted(ids), "list_events must return events in ascending id order"

    # They must be the LAST 3 rows (highest ids).
    with psycopg.connect(PG_DSN) as conn:
        all_ids = [
            r[0]
            for r in conn.execute(
                "SELECT id FROM audit_event ORDER BY id ASC"
            ).fetchall()
        ]
    assert ids == all_ids[-3:], "list_events must return the most-recent rows"
