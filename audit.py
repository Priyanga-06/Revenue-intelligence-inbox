"""
audit.py — Audit logging for all user and system actions.

Every meaningful action (imports, routing overrides, exports) is recorded
with a timestamp, action type, entity reference, and JSON details.
"""

import json
from datetime import datetime, timezone

from database import get_connection


def log_action(action: str, entity_id: str = "", details: dict | None = None,
               user: str = "system"):
    """Write a single audit entry."""
    conn = get_connection()
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    details_json = json.dumps(details or {})
    cur.execute(
        """
        INSERT INTO audit_log (timestamp, action, entity_id, details, user)
        VALUES (?, ?, ?, ?, ?)
        """,
        (now_iso, action, entity_id, details_json, user),
    )
    conn.commit()
    conn.close()


def get_audit_log(limit: int = 200) -> list[dict]:
    """Return recent audit entries, newest first."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_audit_log_for_entity(entity_id: str) -> list[dict]:
    """Return all audit entries for a specific entity (e.g. conversation_id)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM audit_log WHERE entity_id = ? ORDER BY id DESC",
        (entity_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
