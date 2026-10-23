"""
tests/test_exports.py — Tests for CSV/JSON exports and manifest checksums.

Run with:
    python -m pytest tests/test_exports.py -v
"""

import sys
import json
import zipfile
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pandas as pd

from database import init_db, reset_database, count_conversations
from imports import import_csv_data, generate_sample_data
from exports import (
    export_conversations_csv, export_conversations_json,
    export_routing_review_csv, export_findings_json,
    create_export_zip, compute_sha256, generate_manifest, EXPORT_DIR,
)
from analytics import generate_findings


@pytest.fixture(autouse=True)
def setup_data():
    """Load sample data before each test."""
    reset_database()
    df = generate_sample_data()
    import_csv_data(df, "sample_data.csv")
    yield
    reset_database()


def _get_conversations():
    from database import get_all_conversations
    return get_all_conversations()


# ---------------------------------------------------------------------------
# 1. CSV export has correct record count
# ---------------------------------------------------------------------------

def test_csv_export_count():
    """The CSV export should contain the same number of records as the database."""
    conversations = _get_conversations()
    csv_path = EXPORT_DIR / "test_conversations.csv"
    export_conversations_csv(conversations, csv_path)

    df = pd.read_csv(csv_path)
    assert len(df) == len(conversations), (
        f"CSV has {len(df)} rows, DB has {len(conversations)}"
    )


# ---------------------------------------------------------------------------
# 2. JSON export has correct record count
# ---------------------------------------------------------------------------

def test_json_export_count():
    """The JSON export should contain the same number of records as the database."""
    conversations = _get_conversations()
    json_path = EXPORT_DIR / "test_conversations.json"
    export_conversations_json(conversations, json_path)

    with open(json_path) as f:
        data = json.load(f)

    assert len(data) == len(conversations), (
        f"JSON has {len(data)} records, DB has {len(conversations)}"
    )


# ---------------------------------------------------------------------------
# 3. Manifest checksums match exported file bytes
# ---------------------------------------------------------------------------

def test_manifest_checksums():
    """The SHA-256 checksums in the manifest must match the actual file bytes."""
    conversations = _get_conversations()

    csv_path = EXPORT_DIR / "test_export.csv"
    json_path = EXPORT_DIR / "test_export.json"
    routing_path = EXPORT_DIR / "test_routing.csv"
    findings_path = EXPORT_DIR / "test_findings.json"

    export_conversations_csv(conversations, csv_path)
    export_conversations_json(conversations, json_path)
    export_routing_review_csv(conversations, routing_path)
    export_findings_json(conversations, findings_path)

    exported_files = [
        ("test_export.csv", csv_path),
        ("test_export.json", json_path),
        ("test_routing.csv", routing_path),
        ("test_findings.json", findings_path),
    ]
    record_counts = {
        "test_export.csv": len(conversations),
        "test_export.json": len(conversations),
        "test_routing.csv": len(conversations),
        "test_findings.json": len(generate_findings(conversations)),
    }

    manifest = generate_manifest(exported_files, record_counts, {}, "synthetic")

    for file_info in manifest["exported_files"]:
        filename = file_info["filename"]
        listed_checksum = file_info["sha256_checksum"]

        # Find the actual file
        actual_path = None
        for fname, fpath in exported_files:
            if fname == filename:
                actual_path = fpath
                break

        assert actual_path is not None, f"File {filename} not found"

        # Compute actual checksum from bytes
        actual_checksum = compute_sha256(actual_path)
        assert actual_checksum == listed_checksum, (
            f"Checksum mismatch for {filename}: "
            f"manifest={listed_checksum}, actual={actual_checksum}"
        )

    # Also verify checksums match raw file bytes independently
    for fname, fpath in exported_files:
        h = hashlib.sha256()
        with open(fpath, "rb") as f:
            h.update(f.read())
        raw_checksum = h.hexdigest()
        manifest_entry = next(
            fi for fi in manifest["exported_files"] if fi["filename"] == fname
        )
        assert raw_checksum == manifest_entry["sha256_checksum"], (
            f"Raw byte checksum mismatch for {fname}"
        )


# ---------------------------------------------------------------------------
# 4. ZIP contains all expected files
# ---------------------------------------------------------------------------

def test_zip_contains_all_files():
    """The generated ZIP should contain all export files and the manifest."""
    conversations = _get_conversations()
    zip_path = create_export_zip(conversations, {}, "synthetic")

    assert zip_path.exists(), "ZIP file was not created"

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert "conversations.csv" in names
        assert "conversations.json" in names
        assert "routing_review.csv" in names
        assert "findings.json" in names
        assert "manifest.json" in names

        # Verify manifest inside ZIP has checksums
        with zf.open("manifest.json") as mf:
            manifest = json.loads(mf.read().decode("utf-8"))
        assert manifest["total_files"] == 4
        assert "export_timestamp_utc" in manifest
        assert "application_version" in manifest
        assert manifest["dataset_type"] == "synthetic"
        assert len(manifest["exported_files"]) == 4


# ---------------------------------------------------------------------------
# 5. Manifest includes required fields
# ---------------------------------------------------------------------------

def test_manifest_fields():
    """Manifest must include timestamp, filenames, record counts, checksums, version, dataset type."""
    conversations = _get_conversations()
    zip_path = create_export_zip(conversations, {"owner": "All"}, "synthetic")

    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open("manifest.json") as mf:
            manifest = json.loads(mf.read().decode("utf-8"))

    required_fields = [
        "export_timestamp_utc",
        "application_version",
        "dataset_type",
        "applied_filters",
        "exported_files",
        "total_files",
        "total_records_exported",
    ]
    for field in required_fields:
        assert field in manifest, f"Manifest missing field: {field}"

    for file_info in manifest["exported_files"]:
        assert "filename" in file_info
        assert "record_count" in file_info
        assert "sha256_checksum" in file_info
        assert "size_bytes" in file_info


# ---------------------------------------------------------------------------
# 6. Routing review CSV has correct columns
# ---------------------------------------------------------------------------

def test_routing_review_csv_columns():
    """The routing review CSV should contain routing-specific columns."""
    conversations = _get_conversations()
    routing_path = EXPORT_DIR / "test_routing_cols.csv"
    export_routing_review_csv(conversations, routing_path)

    df = pd.read_csv(routing_path)
    expected_cols = [
        "conversation_id", "auto_routing_category", "auto_priority",
        "auto_confidence", "routing_category", "priority",
        "manual_override_applied", "needs_review",
    ]
    for col in expected_cols:
        assert col in df.columns, f"Routing review CSV missing column: {col}"
