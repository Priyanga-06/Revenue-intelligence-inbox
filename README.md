# Revenue Intelligence Inbox

A complete, self-contained sales-operations dashboard for managing, routing, and analyzing sales conversations. Built with Python, Streamlit, SQLite, Pandas, and Plotly. No paid APIs, no external AI dependencies, no authentication services — everything runs locally.

## Product Overview

Revenue Intelligence Inbox ingests sales call and meeting transcripts, automatically routes them into actionable categories using explainable deterministic rules, surfaces evidence-linked findings, and lets managers review or override routing decisions. All data persists in SQLite, and every action is audit-logged.

**The included dataset is synthetic** and clearly labeled as such. Never represent synthetic findings as actual customer findings.

## Features

- **Executive Dashboard** — Live KPIs (total conversations, calls vs meetings, high-priority, open follow-ups, pipeline value, needs-attention count) with Plotly charts for sentiment, routing, activity trends, and owner volume. All metrics respond to filters.
- **Conversation Inbox** — Browse, search, and inspect individual records with full transcripts and routing analysis.
- **Import & Data Quality** — Upload CSV with validation, preview, duplicate detection, and a one-click duplicate/update demo.
- **Routing Review** — Review automated routing decisions with evidence excerpts, confidence labels, and manual override/approve/reject controls.
- **Reports & Exports** — Generate CSV, JSON, routing review, and findings exports bundled in a ZIP with a SHA-256 manifest.
- **Audit Log** — Complete timestamped log of all imports, overrides, and system actions.

## Architecture

```
app.py                 Streamlit frontend (all pages)
database.py            SQLite layer (conversations, import history, audit log, overrides)
routing.py             Deterministic, explainable routing engine
imports.py             CSV import, validation, dedup/update, sample data generation
analytics.py           Metrics calculation, filtering, findings generation
exports.py             CSV/JSON exports, ZIP packaging, manifest with checksums
audit.py               Audit logging
tests/                 Automated tests (imports, routing, exports)
exports/               Generated export files and manifests
sample_data.csv        32 synthetic conversation records
findings_and_decisions.pptx  Five-slide editable presentation
demo_script.md         Three-minute narrated demo script
```

## Local Setup

### Prerequisites

- Python 3.11+
- pip

### Installation

```bash
cd revenue-intelligence-inbox
pip install -r requirements.txt
```

### How to Run

```bash
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`. On first launch, the database is initialized and 32 synthetic records are loaded automatically.

## CSV Schema

Required columns:

| Field | Type | Description |
|---|---|---|
| conversation_id | string (unique) | Stable unique key for dedup |
| account_name | string | Customer account name |
| contact_name | string | Contact person |
| owner | string | Sales rep who owns the conversation |
| conversation_date | YYYY-MM-DD | Date of conversation |
| conversation_type | call \| meeting | Type of conversation |
| duration_minutes | integer | Duration in minutes |
| transcript | string | Full conversation transcript |
| outcome | string | Outcome summary |
| deal_value | number | Deal value in USD |
| sentiment | positive \| neutral \| negative | Sentiment label |
| buying_intent | high \| medium \| low \| none | Buying intent level |
| follow_up_date | YYYY-MM-DD | Next follow-up date (can be empty) |
| status | open \| closed | Current status |

## Routing Rules

The routing engine classifies each conversation into one of seven categories:

1. **High-intent sales opportunity** — Strong buying-intent signals (ready to move forward, contract request, budget approval)
2. **Pricing or proposal request** — Explicit pricing/quote/proposal requests
3. **Competitor risk** — Competitor mentions, vendor comparisons, switching signals
4. **Customer support issue** — Problems, errors, complaints, dissatisfaction
5. **Urgent follow-up** — Deadline urgency, time-sensitive language
6. **Routine follow-up** — Standard check-in, no strong signals
7. **Needs human review** — Conflicting or ambiguous signals

The engine analyzes **sentence-level context**, checks for negation patterns, scores multiple signals, and detects conflicts. It does not rely on isolated keywords alone.

### Rejected Decision

**Rejected keyword-only routing** because a word such as "competitor" can appear in a positive or negative context (e.g., "we chose you over the competitor" vs. "we're switching to a competitor"). Chose context-aware deterministic rules, transcript evidence, and human review for ambiguous cases.

## Duplicate/Update Behavior

- `conversation_id` is the stable unique key.
- New IDs → inserted as new records.
- Existing IDs with unchanged data → skipped as unchanged duplicates.
- Existing IDs with changed source data → updated in-place.
- Re-importing the same file never increases the total record count.
- Manual routing overrides are preserved when automated fields are recalculated. If the source data changes materially (transcript or outcome), the record is flagged for review without erasing the manual override.

## Tests and Actual Results

Run tests:

```bash
python -m pytest tests/ -v
```

Test coverage:

| Test | Description |
|---|---|
| test_first_import_inserts | First import of a new record inserts it |
| test_identical_reimport_no_duplicate | Identical re-import does not duplicate |
| test_changed_data_updates | Changed source data updates the existing record |
| test_invalid_rows_rejected | Invalid rows are rejected and reported |
| test_manual_override_preserved | Manual routing overrides are preserved on re-import |
| test_duplicate_update_demo | Full demo: insert → unchanged → update with stable count |
| test_reimport_sample_data_no_increase | Re-importing sample data doesn't increase count |
| test_high_intent_routing | High-intent signals route correctly |
| test_pricing_routing | Pricing requests route correctly |
| test_competitor_routing | Competitor mentions route correctly |
| test_support_routing | Support issues route correctly |
| test_urgent_routing | Urgent signals route correctly |
| test_routine_routing | Routine follow-ups route correctly |
| test_ambiguous_flagged_for_review | Ambiguous conversations are flagged for review |
| test_evidence_from_transcript | Evidence excerpts come from actual transcripts |
| test_negation_handling | Negated keywords don't trigger false routing |
| test_confidence_labels | Confidence labels are High/Medium/Low |
| test_csv_export_count | CSV export has correct record count |
| test_json_export_count | JSON export has correct record count |
| test_manifest_checksums | Manifest checksums match exported file bytes |
| test_zip_contains_all_files | ZIP contains all expected files |
| test_manifest_fields | Manifest includes all required fields |
| test_routing_review_csv_columns | Routing review CSV has correct columns |

## Exports and Manifest

Exports are generated based on current filters and bundled into a ZIP:

- `conversations.csv` — Full conversation data
- `conversations.json` — Full conversation data (JSON)
- `routing_review.csv` — Routing decisions and override status
- `findings.json` — Three evidence-linked findings
- `manifest.json` — Metadata including:
  - Export timestamp (UTC)
  - Exported filenames
  - Record count per file
  - Applied filters
  - SHA-256 checksum per file (computed from actual file bytes)
  - Application version
  - Dataset type (synthetic or user-provided)

## Deployment (Streamlit Community Cloud)

1. Push the repository to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io).
3. Connect your GitHub account and select the repository.
4. Set the main file path to `app.py`.
5. Click Deploy.

**Known limitation:** Local SQLite storage on hosted instances may not survive restarts or redeployments. The app will reinitialize the database with sample data on each cold start. For persistent storage in production, connect an external database (e.g., PostgreSQL) by updating `database.py`.

Do not claim successful deployment without verifying the public URL opens without errors.

## Known Limitations

- SQLite is not suitable for concurrent multi-user write access in production.
- Cloud-hosted SQLite data may not persist across restarts.
- The routing engine is deterministic and does not use ML/AI — it relies on pattern matching and signal scoring.
- Findings are generated from the loaded dataset. If evidence is insufficient, the app states that instead of fabricating results.
- The included dataset is **synthetic** and labeled as such.

## Findings and Synthetic Data

Three findings are generated dynamically from the loaded data:
1. **Competitor risk concentration** — Conversations showing competitor signals and the pipeline value at risk.
2. **High-intent opportunities ready to close** — High-intent conversations with combined pipeline value.
3. **Support issues and customer dissatisfaction** — Support-issue conversations and negative-sentiment trends.

When using the synthetic dataset, findings are labeled "synthetic-data findings." When users import their own data, findings are recalculated and labeled "user-provided."
