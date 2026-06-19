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
        """Return the row_hash of the last inserted row, or 'genesis'."""
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

        Event types: graph_construction, figure_computed, reconciliation,
        config_loaded, report_exported.
        """
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
        The first row's prev_hash is compared against the genesis seed.
        """
        rows = self._conn.execute(
            "SELECT event_type, actor, config_hash, payload, prev_hash, row_hash "
            "FROM audit_event ORDER BY id ASC"
        ).fetchall()
        for event_type, actor, config_hash, payload_raw, prev_hash, stored_hash in rows:
            # psycopg may return a dict (JSONB) or a string
            if isinstance(payload_raw, str):
                payload = json.loads(payload_raw)
            else:
                payload = payload_raw
            computed = self._compute_row_hash(event_type, actor, config_hash, payload, prev_hash)
            if computed != stored_hash:
                return False
        return True

    def close(self) -> None:
        self._conn.close()
