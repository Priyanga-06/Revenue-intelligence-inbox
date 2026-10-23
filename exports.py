"""
exports.py — CSV / JSON exports, ZIP packaging, and manifest generation.

Exports are generated from the currently-filtered conversation set.  The
manifest includes SHA-256 checksums computed from the actual exported
file bytes, applied filters, record counts, and metadata.
"""

import csv
import io
import json
import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from database import APP_VERSION
from analytics import generate_findings


# ---------------------------------------------------------------------------
# Export directory
# ---------------------------------------------------------------------------

EXPORT_DIR = Path(__file__).parent / "exports"


def _ensure_export_dir():
    EXPORT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Individual file generators
# ---------------------------------------------------------------------------

EXPORT_COLUMNS = [
    "conversation_id",
    "account_name",
    "contact_name",
    "owner",
    "conversation_date",
    "conversation_type",
    "duration_minutes",
    "transcript",
    "outcome",
    "deal_value",
    "sentiment",
    "buying_intent",
    "priority",
    "routing_category",
    "routing_reason",
    "evidence_excerpt",
    "next_action",
    "follow_up_date",
    "status",
    "updated_at",
    "source_file",
    "auto_routing_category",
    "auto_routing_reason",
    "auto_priority",
    "auto_evidence_excerpt",
    "auto_next_action",
    "auto_confidence",
    "needs_review",
    "manual_override_applied",
]


def export_conversations_csv(conversations: list[dict], filepath: Path):
    """Write conversations to a CSV file."""
    _ensure_export_dir()
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for conv in conversations:
            row = {k: conv.get(k, "") for k in EXPORT_COLUMNS}
            writer.writerow(row)
    return filepath


def export_conversations_json(conversations: list[dict], filepath: Path):
    """Write conversations to a JSON file."""
    _ensure_export_dir()
    clean = []
    for conv in conversations:
        row = {k: conv.get(k, "") for k in EXPORT_COLUMNS}
        # Convert booleans/integers properly
        row["needs_review"] = int(conv.get("needs_review", 0) or 0)
        row["manual_override_applied"] = int(conv.get("manual_override_applied", 0) or 0)
        row["deal_value"] = float(conv.get("deal_value", 0) or 0)
        row["duration_minutes"] = int(conv.get("duration_minutes", 0) or 0)
        clean.append(row)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2, default=str)
    return filepath


def export_routing_review_csv(conversations: list[dict], filepath: Path):
    """Write routing review data to a CSV file."""
    _ensure_export_dir()
    routing_cols = [
        "conversation_id",
        "account_name",
        "owner",
        "auto_routing_category",
        "auto_priority",
        "auto_confidence",
        "auto_routing_reason",
        "auto_evidence_excerpt",
        "auto_next_action",
        "needs_review",
        "routing_category",
        "priority",
        "routing_reason",
        "evidence_excerpt",
        "next_action",
        "manual_override_applied",
        "status",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=routing_cols, extrasaction="ignore")
        writer.writeheader()
        for conv in conversations:
            row = {k: conv.get(k, "") for k in routing_cols}
            row["needs_review"] = int(conv.get("needs_review", 0) or 0)
            row["manual_override_applied"] = int(conv.get("manual_override_applied", 0) or 0)
            writer.writerow(row)
    return filepath


def export_findings_json(conversations: list[dict], filepath: Path,
                         filters: dict | None = None):
    """Write findings to a JSON file."""
    _ensure_export_dir()
    findings = generate_findings(conversations)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "finding_count": len(findings),
        "filters_applied": filters or {},
        "record_count": len(conversations),
        "findings": findings,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    return filepath


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def compute_sha256(filepath: Path) -> str:
    """Compute the SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_manifest(exported_files: list[tuple[str, Path]],
                      record_counts: dict, filters: dict,
                      dataset_type: str = "synthetic") -> dict:
    """
    Generate a manifest dict for the exported files.

    Parameters
    ----------
    exported_files : list of (filename, filepath) tuples
    record_counts : dict mapping filename to record count
    filters : dict of applied filters
    dataset_type : "synthetic" or "user-provided"
    """
    files_info = []
    for filename, filepath in exported_files:
        checksum = compute_sha256(filepath)
        size_bytes = filepath.stat().st_size
        files_info.append({
            "filename": filename,
            "record_count": record_counts.get(filename, 0),
            "size_bytes": size_bytes,
            "sha256_checksum": checksum,
        })

    manifest = {
        "export_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "application_version": APP_VERSION,
        "dataset_type": dataset_type,
        "applied_filters": filters,
        "exported_files": files_info,
        "total_files": len(files_info),
        "total_records_exported": sum(
            r for r in record_counts.values()
        ),
    }
    return manifest


# ---------------------------------------------------------------------------
# ZIP packaging
# ---------------------------------------------------------------------------

def create_export_zip(conversations: list[dict], filters: dict,
                      dataset_type: str = "synthetic") -> Path:
    """
    Generate all export files and bundle them into a ZIP.

    Returns the path to the ZIP file.
    """
    _ensure_export_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Generate individual files
    csv_path = EXPORT_DIR / f"conversations.csv"
    json_path = EXPORT_DIR / f"conversations.json"
    routing_path = EXPORT_DIR / f"routing_review.csv"
    findings_path = EXPORT_DIR / f"findings.json"

    export_conversations_csv(conversations, csv_path)
    export_conversations_json(conversations, json_path)
    export_routing_review_csv(conversations, routing_path)
    export_findings_json(conversations, findings_path, filters)

    # Record counts
    record_counts = {
        "conversations.csv": len(conversations),
        "conversations.json": len(conversations),
        "routing_review.csv": len(conversations),
        "findings.json": len(generate_findings(conversations)),
    }

    # Generate manifest
    exported_files = [
        ("conversations.csv", csv_path),
        ("conversations.json", json_path),
        ("routing_review.csv", routing_path),
        ("findings.json", findings_path),
    ]
    manifest = generate_manifest(exported_files, record_counts, filters, dataset_type)

    manifest_path = EXPORT_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Create ZIP
    zip_path = EXPORT_DIR / f"revenue_intelligence_exports_{timestamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, filepath in exported_files:
            zf.write(filepath, filename)
        zf.write(manifest_path, "manifest.json")

    return zip_path
