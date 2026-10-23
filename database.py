"""
database.py — SQLite persistence layer for Revenue Intelligence Inbox.

Handles all database operations: table creation, conversation upserts,
import history, audit logging, and manual routing overrides.
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent / "revenue_intelligence.db"
APP_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_connection():
    """Return a SQLite connection with row factory enabled."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all required tables if they do not already exist."""
    conn = get_connection()
    cur = conn.cursor()

    # ---- Conversations (main table) ---------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id       TEXT PRIMARY KEY,
            account_name           TEXT,
            contact_name           TEXT,
            owner                  TEXT,
            conversation_date      TEXT,
            conversation_type      TEXT,
            duration_minutes       INTEGER,
            transcript             TEXT,
            outcome                TEXT,
            deal_value             REAL,
            sentiment              TEXT,
            buying_intent          TEXT,
            priority               TEXT,
            routing_category       TEXT,
            routing_reason         TEXT,
            evidence_excerpt       TEXT,
            next_action            TEXT,
            follow_up_date         TEXT,
            status                  TEXT,
            updated_at             TEXT,
            source_file            TEXT,

            -- Automated routing fields (preserved separately from manual override)
            auto_routing_category   TEXT,
            auto_routing_reason     TEXT,
            auto_priority           TEXT,
            auto_evidence_excerpt   TEXT,
            auto_next_action        TEXT,
            auto_confidence         TEXT,
            needs_review            INTEGER DEFAULT 0,
            manual_override_applied INTEGER DEFAULT 0,

            -- Hash of source data for duplicate detection
            source_hash             TEXT
        )
    """)

    # ---- Import history ---------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS import_history (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            import_timestamp  TEXT,
            source_file       TEXT,
            total_rows        INTEGER,
            inserted           INTEGER,
            updated            INTEGER,
            unchanged          INTEGER,
            rejected           INTEGER,
            rejected_details   TEXT
        )
    """)

    # ---- Audit log --------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT,
            action      TEXT,
            entity_id   TEXT,
            details     TEXT,
            user        TEXT
        )
    """)

    # ---- Manual routing overrides ----------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS routing_overrides (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id       TEXT,
            original_category      TEXT,
            original_priority      TEXT,
            original_reason        TEXT,
            override_category      TEXT,
            override_priority      TEXT,
            override_reason        TEXT,
            override_next_action   TEXT,
            override_status        TEXT,
            override_by            TEXT,
            override_timestamp     TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
        )
    """)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Conversation CRUD
# ---------------------------------------------------------------------------

def upsert_conversation(conv: dict, source_file: str = "unknown") -> str:
    """
    Insert or update a conversation record.

    Uses conversation_id as the unique key.  Returns one of:
      'inserted', 'updated', 'unchanged'

    The source_hash column stores a hash of the *source* fields so we can
    tell whether the incoming data actually changed.
    """
    conn = get_connection()
    cur = conn.cursor()

    conv_id = conv["conversation_id"]

    # Compute a hash of the source data fields (excluding auto-generated
    # routing and metadata fields).
    source_fields = [
        "account_name", "contact_name", "owner", "conversation_date",
        "conversation_type", "duration_minutes", "transcript", "outcome",
        "deal_value", "sentiment", "buying_intent", "follow_up_date",
        "status",
    ]
    source_str = "|".join(str(conv.get(f, "")) for f in source_fields)
    source_hash = hash_string(source_str)

    # Check existing record
    cur.execute(
        "SELECT source_hash, manual_override_applied, auto_routing_category "
        "FROM conversations WHERE conversation_id = ?",
        (conv_id,),
    )
    existing = cur.fetchone()

    now_iso = datetime.now(timezone.utc).isoformat()

    if existing is None:
        # ---- New record ----
        conv["updated_at"] = now_iso
        _insert_conversation(cur, conv, source_file, source_hash, now_iso)
        conn.commit()
        conn.close()
        return "inserted"

    if existing["source_hash"] == source_hash:
        # ---- Unchanged duplicate ----
        conn.commit()
        conn.close()
        return "unchanged"

    # ---- Update existing record ----
    # Preserve manual override fields: if the user manually set a routing
    # category and the automated fields are being recalculated, we keep the
    # manual override but flag for review if the source data changed
    # materially (transcript or outcome).
    manual_override_applied = existing["manual_override_applied"] or 0

    # Determine whether the change is "material" (transcript or outcome changed)
    cur.execute(
        "SELECT transcript, outcome FROM conversations WHERE conversation_id = ?",
        (conv_id,),
    )
    old_row = cur.fetchone()
    material_change = (
        old_row["transcript"] != conv.get("transcript", "")
        or old_row["outcome"] != conv.get("outcome", "")
    )

    _update_conversation(
        cur, conv, source_file, source_hash, now_iso,
        preserve_manual_override=manual_override_applied,
        material_change=material_change,
    )
    conn.commit()
    conn.close()
    return "updated"


def _insert_conversation(cur, conv, source_file, source_hash, now_iso):
    """Insert a brand-new conversation row."""
    cur.execute(
        """
        INSERT INTO conversations (
            conversation_id, account_name, contact_name, owner,
            conversation_date, conversation_type, duration_minutes,
            transcript, outcome, deal_value, sentiment, buying_intent,
            priority, routing_category, routing_reason, evidence_excerpt,
            next_action, follow_up_date, status, updated_at, source_file,
            auto_routing_category, auto_routing_reason, auto_priority,
            auto_evidence_excerpt, auto_next_action, auto_confidence,
            needs_review, manual_override_applied, source_hash
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?
        )
        """,
        (
            conv["conversation_id"],
            conv.get("account_name", ""),
            conv.get("contact_name", ""),
            conv.get("owner", ""),
            conv.get("conversation_date", ""),
            conv.get("conversation_type", ""),
            conv.get("duration_minutes", 0),
            conv.get("transcript", ""),
            conv.get("outcome", ""),
            conv.get("deal_value", 0),
            conv.get("sentiment", ""),
            conv.get("buying_intent", ""),
            conv.get("priority", ""),
            conv.get("routing_category", ""),
            conv.get("routing_reason", ""),
            conv.get("evidence_excerpt", ""),
            conv.get("next_action", ""),
            conv.get("follow_up_date", ""),
            conv.get("status", ""),
            now_iso,
            source_file,
            conv.get("auto_routing_category", ""),
            conv.get("auto_routing_reason", ""),
            conv.get("auto_priority", ""),
            conv.get("auto_evidence_excerpt", ""),
            conv.get("auto_next_action", ""),
            conv.get("auto_confidence", ""),
            conv.get("needs_review", 0),
            0,
            source_hash,
        ),
    )


def _update_conversation(cur, conv, source_file, source_hash, now_iso,
                          preserve_manual_override, material_change):
    """Update an existing conversation row in-place."""
    # If manual override exists and the change is material, flag for review
    # but do NOT erase the manual override.
    needs_review = conv.get("needs_review", 0)
    if preserve_manual_override and material_change:
        needs_review = 1

    # Determine which routing columns to update.
    # If a manual override is preserved, keep the manually-set routing fields
    # and only update the auto_* fields.
    if preserve_manual_override:
        # Keep existing routing_category, routing_reason, etc. (manual values)
        cur.execute(
            """
            UPDATE conversations SET
                account_name = ?, contact_name = ?, owner = ?,
                conversation_date = ?, conversation_type = ?, duration_minutes = ?,
                transcript = ?, outcome = ?, deal_value = ?, sentiment = ?,
                buying_intent = ?, follow_up_date = ?, status = ?,
                updated_at = ?, source_file = ?,
                auto_routing_category = ?, auto_routing_reason = ?,
                auto_priority = ?, auto_evidence_excerpt = ?,
                auto_next_action = ?, auto_confidence = ?,
                needs_review = ?, source_hash = ?
            WHERE conversation_id = ?
            """,
            (
                conv.get("account_name", ""),
                conv.get("contact_name", ""),
                conv.get("owner", ""),
                conv.get("conversation_date", ""),
                conv.get("conversation_type", ""),
                conv.get("duration_minutes", 0),
                conv.get("transcript", ""),
                conv.get("outcome", ""),
                conv.get("deal_value", 0),
                conv.get("sentiment", ""),
                conv.get("buying_intent", ""),
                conv.get("follow_up_date", ""),
                conv.get("status", ""),
                now_iso,
                source_file,
                conv.get("auto_routing_category", ""),
                conv.get("auto_routing_reason", ""),
                conv.get("auto_priority", ""),
                conv.get("auto_evidence_excerpt", ""),
                conv.get("auto_next_action", ""),
                conv.get("auto_confidence", ""),
                needs_review,
                source_hash,
                conv["conversation_id"],
            ),
        )
    else:
        # No manual override — update everything including routing fields
        cur.execute(
            """
            UPDATE conversations SET
                account_name = ?, contact_name = ?, owner = ?,
                conversation_date = ?, conversation_type = ?, duration_minutes = ?,
                transcript = ?, outcome = ?, deal_value = ?, sentiment = ?,
                buying_intent = ?, priority = ?, routing_category = ?,
                routing_reason = ?, evidence_excerpt = ?, next_action = ?,
                follow_up_date = ?, status = ?, updated_at = ?, source_file = ?,
                auto_routing_category = ?, auto_routing_reason = ?,
                auto_priority = ?, auto_evidence_excerpt = ?,
                auto_next_action = ?, auto_confidence = ?,
                needs_review = ?, source_hash = ?
            WHERE conversation_id = ?
            """,
            (
                conv.get("account_name", ""),
                conv.get("contact_name", ""),
                conv.get("owner", ""),
                conv.get("conversation_date", ""),
                conv.get("conversation_type", ""),
                conv.get("duration_minutes", 0),
                conv.get("transcript", ""),
                conv.get("outcome", ""),
                conv.get("deal_value", 0),
                conv.get("sentiment", ""),
                conv.get("buying_intent", ""),
                conv.get("priority", ""),
                conv.get("routing_category", ""),
                conv.get("routing_reason", ""),
                conv.get("evidence_excerpt", ""),
                conv.get("next_action", ""),
                conv.get("follow_up_date", ""),
                conv.get("status", ""),
                now_iso,
                source_file,
                conv.get("auto_routing_category", ""),
                conv.get("auto_routing_reason", ""),
                conv.get("auto_priority", ""),
                conv.get("auto_evidence_excerpt", ""),
                conv.get("auto_next_action", ""),
                conv.get("auto_confidence", ""),
                needs_review,
                source_hash,
                conv["conversation_id"],
            ),
        )


def get_conversation(conv_id: str) -> dict | None:
    """Return a single conversation as a dict, or None."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM conversations WHERE conversation_id = ?", (conv_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_conversations() -> list[dict]:
    """Return all conversations as a list of dicts, ordered by date desc."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM conversations ORDER BY conversation_date DESC"
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_conversations() -> int:
    """Return the total number of conversation records."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM conversations")
    result = cur.fetchone()
    conn.close()
    return result["cnt"]


def update_routing_override(conv_id: str, category: str, priority: str,
                            reason: str, next_action: str, status: str,
                            user: str = "manager"):
    """Apply a manual routing override to a conversation."""
    conn = get_connection()
    cur = conn.cursor()

    # Fetch current routing values as the "original"
    cur.execute(
        "SELECT routing_category, priority, routing_reason FROM conversations "
        "WHERE conversation_id = ?",
        (conv_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Conversation {conv_id} not found")

    now_iso = datetime.now(timezone.utc).isoformat()

    # Save the override record
    cur.execute(
        """
        INSERT INTO routing_overrides (
            conversation_id, original_category, original_priority, original_reason,
            override_category, override_priority, override_reason,
            override_next_action, override_status, override_by, override_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            conv_id, row["routing_category"], row["priority"], row["routing_reason"],
            category, priority, reason, next_action, status, user, now_iso,
        ),
    )

    # Apply override to the conversation row
    cur.execute(
        """
        UPDATE conversations SET
            routing_category = ?, priority = ?, routing_reason = ?,
            next_action = ?, status = ?, updated_at = ?,
            manual_override_applied = 1, needs_review = 0
        WHERE conversation_id = ?
        """,
        (category, priority, reason, next_action, status, now_iso, conv_id),
    )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Import history
# ---------------------------------------------------------------------------

def add_import_history(source_file: str, total: int, inserted: int,
                       updated: int, unchanged: int, rejected: int,
                       rejected_details: list | None = None):
    """Record an import run in the import_history table."""
    conn = get_connection()
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    details_json = json.dumps(rejected_details or [])
    cur.execute(
        """
        INSERT INTO import_history (
            import_timestamp, source_file, total_rows, inserted, updated,
            unchanged, rejected, rejected_details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (now_iso, source_file, total, inserted, updated, unchanged, rejected,
         details_json),
    )
    conn.commit()
    conn.close()


def get_import_history() -> list[dict]:
    """Return all import history entries, newest first."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM import_history ORDER BY id DESC"
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def hash_string(text: str) -> str:
    """Return a SHA-256 hex digest of the given text."""
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reset_database():
    """Drop and recreate all tables (used by tests and demo resets)."""
    conn = get_connection()
    cur = conn.cursor()
    # Disable foreign keys to allow dropping in any order
    cur.execute("PRAGMA foreign_keys=OFF")
    cur.execute("DROP TABLE IF EXISTS routing_overrides")
    cur.execute("DROP TABLE IF EXISTS conversations")
    cur.execute("DROP TABLE IF EXISTS import_history")
    cur.execute("DROP TABLE IF EXISTS audit_log")
    conn.commit()
    conn.close()
    init_db()
