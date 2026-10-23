"""
tests/test_imports.py — Tests for CSV import, duplicate detection, and updates.

Run with:
    python -m pytest tests/test_imports.py -v
"""

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pandas as pd

from database import init_db, reset_database, count_conversations, get_connection
from imports import import_csv_data, run_duplicate_update_demo
from imports import generate_sample_data


@pytest.fixture(autouse=True)
def clean_db():
    """Reset the database before each test."""
    reset_database()
    yield
    # Teardown: reset again to avoid cross-test contamination
    reset_database()


# ---------------------------------------------------------------------------
# 1. First import inserts a record
# ---------------------------------------------------------------------------

def test_first_import_inserts():
    """Importing a new record should insert it (count = 1)."""
    record = {
        "conversation_id": "TEST-001",
        "account_name": "Test Corp",
        "contact_name": "Test Person",
        "owner": "Test Owner",
        "conversation_date": "2025-02-10",
        "conversation_type": "call",
        "duration_minutes": 20,
        "transcript": "We want to proceed with the purchase. Let's get the contract started.",
        "outcome": "moved to contract",
        "deal_value": 50000,
        "sentiment": "positive",
        "buying_intent": "high",
        "follow_up_date": "2025-02-12",
        "status": "open",
    }
    df = pd.DataFrame([record])
    result = import_csv_data(df, "test_file.csv")

    assert result["inserted"] == 1, f"Expected inserted=1, got {result}"
    assert result["updated"] == 0
    assert result["unchanged"] == 0
    assert count_conversations() == 1


# ---------------------------------------------------------------------------
# 2. Identical second import does not duplicate
# ---------------------------------------------------------------------------

def test_identical_reimport_no_duplicate():
    """Re-importing the exact same record should be unchanged, not a duplicate."""
    record = {
        "conversation_id": "TEST-001",
        "account_name": "Test Corp",
        "contact_name": "Test Person",
        "owner": "Test Owner",
        "conversation_date": "2025-02-10",
        "conversation_type": "call",
        "duration_minutes": 20,
        "transcript": "We want to proceed with the purchase. Let's get the contract started.",
        "outcome": "moved to contract",
        "deal_value": 50000,
        "sentiment": "positive",
        "buying_intent": "high",
        "follow_up_date": "2025-02-12",
        "status": "open",
    }
    df = pd.DataFrame([record])

    # First import
    result1 = import_csv_data(df, "test_file.csv")
    assert result1["inserted"] == 1

    # Second identical import
    result2 = import_csv_data(df, "test_file.csv")
    assert result2["inserted"] == 0, "Should not insert again"
    assert result2["unchanged"] == 1, "Should be unchanged"
    assert result2["updated"] == 0, "Should not be updated"
    assert count_conversations() == 1, "Count must stay 1"


# ---------------------------------------------------------------------------
# 3. Changed source data updates the existing record
# ---------------------------------------------------------------------------

def test_changed_data_updates():
    """Importing a record with changed transcript should update, not insert."""
    record = {
        "conversation_id": "TEST-001",
        "account_name": "Test Corp",
        "contact_name": "Test Person",
        "owner": "Test Owner",
        "conversation_date": "2025-02-10",
        "conversation_type": "call",
        "duration_minutes": 20,
        "transcript": "We want to proceed with the purchase. Let's get the contract started.",
        "outcome": "moved to contract",
        "deal_value": 50000,
        "sentiment": "positive",
        "buying_intent": "high",
        "follow_up_date": "2025-02-12",
        "status": "open",
    }
    df = pd.DataFrame([record])
    import_csv_data(df, "test_file.csv")

    # Modify transcript and outcome
    record_modified = record.copy()
    record_modified["transcript"] = "We've decided to move forward. Send the contract. Leadership approved."
    record_modified["outcome"] = "contract ready"
    df2 = pd.DataFrame([record_modified])

    result = import_csv_data(df2, "test_file_v2.csv")
    assert result["updated"] == 1, f"Expected updated=1, got {result}"
    assert result["inserted"] == 0
    assert count_conversations() == 1, "Count must still be 1"

    # Verify the update took effect
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT transcript, outcome FROM conversations WHERE conversation_id = 'TEST-001'")
    row = cur.fetchone()
    conn.close()
    assert "decided to move forward" in row["transcript"]
    assert row["outcome"] == "contract ready"


# ---------------------------------------------------------------------------
# 4. Invalid rows are rejected and reported
# ---------------------------------------------------------------------------

def test_invalid_rows_rejected():
    """Rows with missing or invalid data should be rejected with details."""
    records = [
        {
            "conversation_id": "VALID-001",
            "account_name": "Valid Corp",
            "contact_name": "Valid Person",
            "owner": "Owner A",
            "conversation_date": "2025-02-10",
            "conversation_type": "call",
            "duration_minutes": 20,
            "transcript": "We want to proceed with the purchase.",
            "outcome": "moved to contract",
            "deal_value": 50000,
            "sentiment": "positive",
            "buying_intent": "high",
            "follow_up_date": "2025-02-12",
            "status": "open",
        },
        {
            "conversation_id": "",  # Missing required ID
            "account_name": "Invalid Corp",
            "contact_name": "Invalid Person",
            "owner": "Owner B",
            "conversation_date": "2025-02-10",
            "conversation_type": "call",
            "duration_minutes": 20,
            "transcript": "Hello world",
            "outcome": "unknown",
            "deal_value": 0,
            "sentiment": "neutral",
            "buying_intent": "low",
            "follow_up_date": "",
            "status": "open",
        },
        {
            "conversation_id": "INVALID-002",
            "account_name": "Bad Date Corp",
            "contact_name": "Bad Date Person",
            "owner": "Owner C",
            "conversation_date": "not-a-date",  # Invalid date
            "conversation_type": "call",
            "duration_minutes": 20,
            "transcript": "Hello world",
            "outcome": "unknown",
            "deal_value": 0,
            "sentiment": "neutral",
            "buying_intent": "low",
            "follow_up_date": "",
            "status": "open",
        },
    ]
    df = pd.DataFrame(records)
    result = import_csv_data(df, "invalid_test.csv")

    assert result["inserted"] == 1, "One valid record should be inserted"
    assert result["rejected"] == 2, f"Expected 2 rejected, got {result['rejected']}"
    assert len(result["rejected_details"]) == 2
    assert any("conversation_id" in d for d in result["rejected_details"])
    assert any("not a valid" in d for d in result["rejected_details"])


# ---------------------------------------------------------------------------
# 5. Manual routing overrides are preserved on re-import
# ---------------------------------------------------------------------------

def test_manual_override_preserved():
    """When a record with a manual override is re-imported unchanged,
    the manual override should be preserved."""
    record = {
        "conversation_id": "TEST-OVR-001",
        "account_name": "Override Corp",
        "contact_name": "Override Person",
        "owner": "Owner X",
        "conversation_date": "2025-02-10",
        "conversation_type": "call",
        "duration_minutes": 20,
        "transcript": "We want to proceed with the purchase. Let's get the contract started.",
        "outcome": "moved to contract",
        "deal_value": 50000,
        "sentiment": "positive",
        "buying_intent": "high",
        "follow_up_date": "2025-02-12",
        "status": "open",
    }
    df = pd.DataFrame([record])
    import_csv_data(df, "test_override.csv")

    # Apply a manual override
    from database import update_routing_override
    update_routing_override(
        "TEST-OVR-001", "Customer support issue", "high",
        "Manager manually reclassified this conversation", "Call customer", "open",
        user="manager",
    )

    # Verify override is applied
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT routing_category, manual_override_applied FROM conversations WHERE conversation_id = 'TEST-OVR-001'")
    row = cur.fetchone()
    assert row["routing_category"] == "Customer support issue"
    assert row["manual_override_applied"] == 1
    conn.close()

    # Re-import the SAME data (unchanged) — override should stay
    import_csv_data(df, "test_override.csv")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT routing_category, manual_override_applied FROM conversations WHERE conversation_id = 'TEST-OVR-001'")
    row = cur.fetchone()
    conn.close()

    assert row["manual_override_applied"] == 1, "Manual override must be preserved"
    assert row["routing_category"] == "Customer support issue", "Manual routing must be preserved"


# ---------------------------------------------------------------------------
# 6. Full duplicate/update demo test
# ---------------------------------------------------------------------------

def test_duplicate_update_demo():
    """The demo function should show insert, unchanged, update with stable count."""
    results = run_duplicate_update_demo()

    assert results["step1_first_import"]["inserted"] == 1
    assert results["step2_reimport_unchanged"]["unchanged"] == 1
    assert results["step3_reimport_modified"]["updated"] == 1
    assert results["verification"]["count_stayed_same"] is True


# ---------------------------------------------------------------------------
# 7. Re-importing sample data doesn't increase count
# ---------------------------------------------------------------------------

def test_reimport_sample_data_no_increase():
    """Importing sample data twice should not increase the record count."""
    df = generate_sample_data()
    result1 = import_csv_data(df, "sample_data.csv")
    count1 = count_conversations()

    result2 = import_csv_data(df, "sample_data.csv")
    count2 = count_conversations()

    assert count1 == count2, f"Count changed: {count1} -> {count2}"
    assert result2["unchanged"] == result1["inserted"], "All should be unchanged on reimport"
