"""Append-only audit log with SHA-256 hash chain stored in Postgres.

The audit_event table is protected by a BEFORE UPDATE OR DELETE trigger that raises
an exception for all connections, including superuser. The app_role is additionally
restricted by REVOKE at the privilege level — defense in depth.

Production note: the application should connect as a NON-superuser role (app_role)
so that both the trigger AND the REVOKE apply. The superuser connection used in tests
is blocked only by the trigger; in production the privilege-level REVOKE provides a
second layer of protection.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

# Advisory lock key used to serialize concurrent writers in log_event.
# Any stable non-zero 64-bit integer works; this value is arbitrary but fixed.
_AUDIT_LOCK_KEY: int = 7_423_819_204_931_057


class AuditLogger:
    """Write compliance audit events to Postgres audit_event table with hash chain.

    Hash chain: row_hash = sha256(canonical(event_type, actor, config_hash, payload) || prev_hash)
    where prev_hash is the previous row's row_hash (genesis seed: "genesis").

    Canonical form: json.dumps of a dict with keys event_type, actor, config_hash,
    and payload — all serialized with sort_keys=True for determinism.

    Timestamp (ts) is intentionally EXCLUDED from the hash. Including ts would require
    exact round-trip equality of the timestamp string between insert time and verify
    time (timezone/precision issues could silently break verify_chain). Excluding ts
    is safe because event_type + actor + config_hash + payload + prev_hash already
    uniquely characterize the event content and its position in the chain.
    """

    GENESIS_SEED = "genesis"

    def __init__(self, conn_string: str) -> None:
        import psycopg
        self._conn_string = conn_string
        self._conn = psycopg.connect(conn_string)
        self._conn.autocommit = False

    def _last_row_hash(self) -> str:
        """Return the row_hash of the last inserted row, or 'genesis'.

        Must be called inside a transaction that already holds the advisory
        lock (_AUDIT_LOCK_KEY) to prevent TOCTOU races.
        """
        row = self._conn.execute(
            "SELECT row_hash FROM audit_event ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else self.GENESIS_SEED

    def _compute_row_hash(
        self,
        event_type: str,
        actor: str,
        config_hash: Optional[str],
        payload: dict,
        prev_hash: str,
    ) -> str:
        """SHA-256 of canonical(event_type, actor, config_hash, payload) || prev_hash.

        All immutable-intent fields are included so that out-of-band changes to any
        of them (e.g. actor, event_type) are detected by verify_chain().
        """
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
        serialized = (canonical + prev_hash).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    @staticmethod
    def _verify_rows(rows: list[tuple]) -> bool:
        """Verify an ordered list of row tuples forms a valid hash chain.

        Each tuple must be:
            (event_type, actor, config_hash, payload, prev_hash, stored_hash)
        where payload may be a dict or a JSON string.

        Checks two conditions per row:
          1. Chain link: row's prev_hash == expected_prev (the previous row's stored_hash,
             or GENESIS_SEED for the first row).
          2. Row integrity: recomputed hash == stored_hash.

        Returns True only if both conditions hold for every row.
        """
        expected_prev = AuditLogger.GENESIS_SEED
        for event_type, actor, config_hash, payload_raw, prev_hash, stored_hash in rows:
            # Normalise payload: psycopg may return a dict (JSONB) or a string.
            if isinstance(payload_raw, str):
                payload = json.loads(payload_raw)
            else:
                payload = payload_raw

            # Condition 1: chain link — prev_hash must equal the previous row's hash.
            if prev_hash != expected_prev:
                return False

            # Condition 2: row integrity — recomputed hash must match stored hash.
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
            computed = hashlib.sha256((canonical + prev_hash).encode("utf-8")).hexdigest()
            if computed != stored_hash:
                return False

            expected_prev = stored_hash
        return True

    def log_event(
        self,
        run_id: str,
        event_type: str,
        actor: str,
        payload: dict,
        config_hash: Optional[str] = None,
        retention_class: str = "compliance",
    ) -> None:
        """Insert an audit event row with hash chain link.

        A transaction-level advisory lock (_AUDIT_LOCK_KEY) is acquired before
        reading the previous hash, serializing concurrent writers and eliminating
        the TOCTOU race that could fork the chain (BUG 2 fix).

        Event types: graph_construction, figure_computed, reconciliation,
        config_loaded, report_exported.
        """
        # BUG 2 fix: acquire advisory lock before reading prev_hash so that no
        # concurrent writer can read the same prev_hash between our SELECT and INSERT.
        # The lock is automatically released at COMMIT (autocommit=False).
        self._conn.execute(
            "SELECT pg_advisory_xact_lock(%s)", (_AUDIT_LOCK_KEY,)
        )
        prev_hash = self._last_row_hash()
        row_hash = self._compute_row_hash(event_type, actor, config_hash, payload, prev_hash)
        self._conn.execute(
            """
            INSERT INTO audit_event
                (run_id, event_type, actor, payload, config_hash, prev_hash, row_hash, retention_class)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                event_type,
                actor,
                json.dumps(payload),
                config_hash,
                prev_hash,
                row_hash,
                retention_class,
            ),
        )
        self._conn.commit()

    def verify_chain(self) -> bool:
        """Re-derive all row hashes in insertion order and verify the chain is intact.

        Returns True if the chain is valid, False if any row has been tampered with.
        Delegates to _verify_rows, which enforces both row integrity AND chain links.
        """
        rows = self._conn.execute(
            "SELECT event_type, actor, config_hash, payload, prev_hash, row_hash "
            "FROM audit_event ORDER BY id ASC"
        ).fetchall()
        return self._verify_rows(list(rows))

    def list_events(self, limit: int = 20) -> list[dict]:
        """Return the last `limit` audit events in insertion order.

        Uses SQL-level LIMIT on a DESC scan then reverses in Python, avoiding a
        full-table fetch (BUG 3 fix).

        Each dict contains: id, run_id, event_type, actor, ts, payload, config_hash, row_hash.
        """
        # BUG 3 fix: push LIMIT into SQL (DESC scan) then reverse to preserve asc order.
        rows = self._conn.execute(
            "SELECT id, run_id, event_type, actor, ts, payload, config_hash, row_hash "
            "FROM audit_event ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()
        events = []
        for id_, run_id, event_type, actor, ts, payload_raw, config_hash, row_hash in reversed(rows):
            if isinstance(payload_raw, str):
                payload = json.loads(payload_raw)
            else:
                payload = payload_raw
            events.append({
                "id": id_,
                "run_id": run_id,
                "event_type": event_type,
                "actor": actor,
                "ts": ts,
                "payload": payload,
                "config_hash": config_hash,
                "row_hash": row_hash,
            })
        return events

    def close(self) -> None:
        self._conn.close()
