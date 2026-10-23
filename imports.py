"""
imports.py — CSV import, validation, duplicate detection, and update logic.

Core guarantees:
  - conversation_id is the stable unique key.
  - New IDs create new records.
  - Existing IDs with unchanged data are skipped as unchanged duplicates.
  - Existing IDs with changed source data update the existing record.
  - Re-importing the same file never increases the total record count.
  - Manual routing overrides are preserved when automated fields are
    recalculated, unless the underlying source changed materially.
"""

import csv
import io
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from database import (
    upsert_conversation, add_import_history, get_all_conversations,
    count_conversations, init_db,
)
from routing import route_conversation, route_to_dict
from audit import log_action


# ---------------------------------------------------------------------------
# Required schema
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = [
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
    "status",
]

OPTIONAL_FIELDS = [
    "priority",
    "routing_category",
    "routing_reason",
    "evidence_excerpt",
    "next_action",
    "source_file",
]

VALID_TYPES = {"call", "meeting"}
VALID_SENTIMENTS = {"positive", "neutral", "negative"}
VALID_INTENTS = {"high", "medium", "low", "none"}
VALID_STATUSES = {"open", "closed"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_row(row: dict, row_num: int) -> tuple[bool, str]:
    """
    Validate a single CSV row.  Returns (is_valid, error_message).
    """
    # Check required fields are present and non-empty
    for field in REQUIRED_FIELDS:
        val = str(row.get(field, "")).strip()
        if not val:
            return False, f"Row {row_num}: Missing required field '{field}'"

    # Validate conversation_id format (non-empty, no spaces)
    cid = str(row["conversation_id"]).strip()
    if " " in cid:
        return False, f"Row {row_num}: conversation_id '{cid}' contains spaces"

    # Validate conversation_date format (YYYY-MM-DD)
    date_str = str(row["conversation_date"]).strip()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return False, f"Row {row_num}: conversation_date '{date_str}' is not a valid YYYY-MM-DD date"

    # Validate follow_up_date if present
    fu = str(row.get("follow_up_date", "")).strip()
    if fu and fu.lower() not in ("", "nan", "none"):
        try:
            datetime.strptime(fu, "%Y-%m-%d")
        except ValueError:
            return False, f"Row {row_num}: follow_up_date '{fu}' is not a valid YYYY-MM-DD date"

    # Validate conversation_type
    ct = str(row["conversation_type"]).strip().lower()
    if ct not in VALID_TYPES:
        return False, f"Row {row_num}: conversation_type '{ct}' must be one of {VALID_TYPES}"

    # Validate sentiment
    sent = str(row["sentiment"]).strip().lower()
    if sent not in VALID_SENTIMENTS:
        return False, f"Row {row_num}: sentiment '{sent}' must be one of {VALID_SENTIMENTS}"

    # Validate buying_intent
    bi = str(row["buying_intent"]).strip().lower()
    if bi not in VALID_INTENTS:
        return False, f"Row {row_num}: buying_intent '{bi}' must be one of {VALID_INTENTS}"

    # Validate status
    st = str(row.get("status", "open")).strip().lower()
    if st not in VALID_STATUSES:
        return False, f"Row {row_num}: status '{st}' must be one of {VALID_STATUSES}"

    # Validate duration_minutes is a positive integer
    try:
        dur = int(float(row["duration_minutes"]))
        if dur < 0:
            return False, f"Row {row_num}: duration_minutes must be non-negative"
    except (ValueError, TypeError):
        return False, f"Row {row_num}: duration_minutes '{row['duration_minutes']}' is not a valid number"

    # Validate deal_value is a number
    try:
        float(row["deal_value"])
    except (ValueError, TypeError):
        return False, f"Row {row_num}: deal_value '{row['deal_value']}' is not a valid number"

    return True, ""


# ---------------------------------------------------------------------------
# Import logic
# ---------------------------------------------------------------------------

def import_csv_data(df: pd.DataFrame, source_file: str = "upload") -> dict:
    """
    Import a DataFrame of conversation records.

    Returns a dict with keys: total, inserted, updated, unchanged, rejected,
    rejected_details, final_count.
    """
    init_db()

    # Normalise column names: strip whitespace, lowercase
    df.columns = [c.strip().lower() for c in df.columns]

    # Check that all required columns exist
    missing_cols = [f for f in REQUIRED_FIELDS if f not in df.columns]
    if missing_cols:
        return {
            "total": 0,
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "rejected": len(df),
            "rejected_details": [
                f"Missing required columns: {', '.join(missing_cols)}"
            ],
            "final_count": count_conversations(),
        }

    total = len(df)
    inserted = 0
    updated = 0
    unchanged = 0
    rejected = 0
    rejected_details = []

    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        row_num = idx + 2  # +2 because row 1 is header, idx 0 = row 2

        is_valid, err = validate_row(row_dict, row_num)
        if not is_valid:
            rejected += 1
            rejected_details.append(err)
            continue

        # Normalise the row into a clean dict
        clean = _normalise_row(row_dict, source_file)

        # Run the routing engine
        routing_result = route_conversation(clean)
        routing_fields = route_to_dict(routing_result)
        clean.update(routing_fields)

        # Upsert
        result = upsert_conversation(clean, source_file)

        if result == "inserted":
            inserted += 1
        elif result == "updated":
            updated += 1
        else:
            unchanged += 1

    # Record import history
    add_import_history(
        source_file, total, inserted, updated, unchanged, rejected,
        rejected_details,
    )

    # Audit log
    log_action(
        "import",
        details={
            "source_file": source_file,
            "total": total,
            "inserted": inserted,
            "updated": updated,
            "unchanged": unchanged,
            "rejected": rejected,
        },
    )

    return {
        "total": total,
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "rejected": rejected,
        "rejected_details": rejected_details,
        "final_count": count_conversations(),
    }


def _normalise_row(row: dict, source_file: str) -> dict:
    """Convert a raw CSV row dict into a normalised conversation dict."""
    clean = {}
    for k, v in row.items():
        clean[k] = "" if pd.isna(v) else str(v).strip()
        if clean[k].lower() in ("nan", "none", ""):
            clean[k] = "" if k != "deal_value" else "0"

    clean["conversation_id"] = clean["conversation_id"].strip()
    clean["conversation_type"] = clean["conversation_type"].strip().lower()
    clean["sentiment"] = clean["sentiment"].strip().lower()
    clean["buying_intent"] = clean["buying_intent"].strip().lower()
    clean["status"] = clean.get("status", "open").strip().lower() or "open"

    # Numeric fields
    try:
        clean["duration_minutes"] = int(float(clean["duration_minutes"]))
    except (ValueError, TypeError):
        clean["duration_minutes"] = 0

    try:
        clean["deal_value"] = float(clean.get("deal_value", "0"))
    except (ValueError, TypeError):
        clean["deal_value"] = 0.0

    clean["source_file"] = source_file
    return clean


# ---------------------------------------------------------------------------
# Sample data generation
# ---------------------------------------------------------------------------

def generate_sample_data() -> pd.DataFrame:
    """Generate 30+ realistic synthetic conversation records."""
    records = [
        {
            "conversation_id": "CONV-001",
            "account_name": "Apex Manufacturing",
            "contact_name": "Sarah Chen",
            "owner": "Jordan Lee",
            "conversation_date": "2025-01-08",
            "conversation_type": "call",
            "duration_minutes": 32,
            "transcript": "Sarah: Thanks for the demo last week. We've reviewed it internally and we're ready to move forward. Let's get the contract started. Our CFO has approved the budget for the annual plan. Can you send the agreement over by Friday? Jordan: Absolutely, I'll prepare the contract today. Sarah: Perfect, we want to sign up as soon as possible.",
            "outcome": "moved to contract",
            "deal_value": 85000,
            "sentiment": "positive",
            "buying_intent": "high",
            "follow_up_date": "2025-01-10",
            "status": "open",
        },
        {
            "conversation_id": "CONV-002",
            "account_name": "BlueWave Logistics",
            "contact_name": "Marcus Reed",
            "owner": "Priya Sharma",
            "conversation_date": "2025-01-09",
            "conversation_type": "meeting",
            "duration_minutes": 45,
            "transcript": "Marcus: The team liked the platform. We're in. Let's proceed with the implementation. I'll need the pricing for the enterprise tier. What does the enterprise plan cost per month? Also, can you send the proposal with payment terms? Priya: I'll send over the pricing sheet and proposal today. Marcus: Great, we want to wrap this up before our fiscal year ends.",
            "outcome": "proposal requested",
            "deal_value": 120000,
            "sentiment": "positive",
            "buying_intent": "high",
            "follow_up_date": "2025-01-12",
            "status": "open",
        },
        {
            "conversation_id": "CONV-003",
            "account_name": "GreenTree Foods",
            "contact_name": "Emily Park",
            "owner": "Jordan Lee",
            "conversation_date": "2025-01-10",
            "conversation_type": "call",
            "duration_minutes": 28,
            "transcript": "Emily: We're comparing you against a couple of other vendors right now. We're evaluating SAP Concur and Expensify as alternatives. How do you compare on pricing? We might switch if the price is right. What makes your platform better than the competitors? Jordan: Let me walk you through our key differentiators. Emily: We need to make a decision by end of quarter.",
            "outcome": "competitive evaluation",
            "deal_value": 95000,
            "sentiment": "neutral",
            "buying_intent": "medium",
            "follow_up_date": "2025-01-20",
            "status": "open",
        },
        {
            "conversation_id": "CONV-004",
            "account_name": "Northwind Traders",
            "contact_name": "David Kim",
            "owner": "Alex Morgan",
            "conversation_date": "2025-01-11",
            "conversation_type": "call",
            "duration_minutes": 22,
            "transcript": "David: I'm calling about a problem with the expense module. It's been broken for three days. The system keeps throwing an error when we try to submit reports. This is really frustrating. We can't access the approval workflow and our month-end close is delayed. I need this escalated. Alex: I'm sorry to hear that. Let me escalate this to our support team immediately. David: We've been very unhappy with the response time so far.",
            "outcome": "support escalated",
            "deal_value": 0,
            "sentiment": "negative",
            "buying_intent": "none",
            "follow_up_date": "2025-01-11",
            "status": "open",
        },
        {
            "conversation_id": "CONV-005",
            "account_name": "Summit Health",
            "contact_name": "Lisa Anderson",
            "owner": "Priya Sharma",
            "conversation_date": "2025-01-12",
            "conversation_type": "meeting",
            "duration_minutes": 55,
            "transcript": "Lisa: This is urgent. We need the implementation completed by tomorrow. The board meeting is on Friday and we need everything ready by then. We can't wait any longer. It's critical that the data migration happens this week. Priya: I understand the urgency. Let me check what we can do to expedite. Lisa: We're running out of time and the deadline is non-negotiable.",
            "outcome": "urgent escalation",
            "deal_value": 60000,
            "sentiment": "negative",
            "buying_intent": "medium",
            "follow_up_date": "2025-01-13",
            "status": "open",
        },
        {
            "conversation_id": "CONV-006",
            "account_name": "Cornerstone Retail",
            "contact_name": "Tom Wilson",
            "owner": "Jordan Lee",
            "conversation_date": "2025-01-13",
            "conversation_type": "call",
            "duration_minutes": 18,
            "transcript": "Tom: Just following up on our last conversation. Wanted to check in and see where things stand. Let's circle back next week to discuss next steps. Nothing urgent, just a routine check-in. Jordan: Sounds good, I'll follow up with you next Tuesday. Tom: Great, we can reconnect then and see if there's anything new to discuss.",
            "outcome": "routine follow-up",
            "deal_value": 45000,
            "sentiment": "neutral",
            "buying_intent": "low",
            "follow_up_date": "2025-01-21",
            "status": "open",
        },
        {
            "conversation_id": "CONV-007",
            "account_name": "GlobalTech Systems",
            "contact_name": "Anna Schmidt",
            "owner": "Alex Morgan",
            "conversation_date": "2025-01-14",
            "conversation_type": "meeting",
            "duration_minutes": 40,
            "transcript": "Anna: We want to proceed with the full enterprise package. Let's do this. Our procurement team is ready to issue the purchase order. We commit to moving forward this quarter. Send us the agreement and we'll sign up. Alex: Excellent, I'll have the contract ready within 24 hours. Anna: The team is on board and leadership has approved everything.",
            "outcome": "contract ready",
            "deal_value": 150000,
            "sentiment": "positive",
            "buying_intent": "high",
            "follow_up_date": "2025-01-16",
            "status": "open",
        },
        {
            "conversation_id": "CONV-008",
            "account_name": "Pioneer Bank",
            "contact_name": "Robert Yu",
            "owner": "Priya Sharma",
            "conversation_date": "2025-01-15",
            "conversation_type": "call",
            "duration_minutes": 25,
            "transcript": "Robert: We need a quote for 500 users. What's the pricing for the premium tier? Can you also send a proposal with the payment terms? How much does the annual plan cost? We have a budget of 200k allocated for this. Priya: I'll send the pricing details and a formal proposal today. Robert: We'd like a discount if we commit to a multi-year contract.",
            "outcome": "pricing requested",
            "deal_value": 200000,
            "sentiment": "positive",
            "buying_intent": "medium",
            "follow_up_date": "2025-01-18",
            "status": "open",
        },
        {
            "conversation_id": "CONV-009",
            "account_name": "Sterling Industries",
            "contact_name": "Michelle Brown",
            "owner": "Jordan Lee",
            "conversation_date": "2025-01-16",
            "conversation_type": "call",
            "duration_minutes": 15,
            "transcript": "Michelle: We're considering switching to another vendor. We've been looking at Ramp and Brex as alternatives. The competitor offers a lower rate. We might move to a different solution if things don't improve. How do you compare to Ramp on features? Jordan: I understand your concerns. Let me schedule a deeper comparison. Michelle: We're in the process of vendor evaluation right now.",
            "outcome": "churn risk",
            "deal_value": 75000,
            "sentiment": "negative",
            "buying_intent": "low",
            "follow_up_date": "2025-01-19",
            "status": "open",
        },
        {
            "conversation_id": "CONV-010",
            "account_name": "Quantum Labs",
            "contact_name": "James Foster",
            "owner": "Alex Morgan",
            "conversation_date": "2025-01-17",
            "conversation_type": "meeting",
            "duration_minutes": 50,
            "transcript": "James: The platform has been mostly good but we've had some issues. There's a bug in the receipt scanning feature. It's not working properly and throwing errors. We've submitted a support ticket but haven't heard back. This is becoming a problem for our team. The approval workflow is also broken sometimes. Alex: I'll escalate this to our engineering team right away. James: We're frustrated with the slow response.",
            "outcome": "support issue",
            "deal_value": 55000,
            "sentiment": "negative",
            "buying_intent": "none",
            "follow_up_date": "2025-01-18",
            "status": "open",
        },
        {
            "conversation_id": "CONV-011",
            "account_name": "Riverstone Energy",
            "contact_name": "Patricia Cruz",
            "owner": "Priya Sharma",
            "conversation_date": "2025-01-18",
            "conversation_type": "call",
            "duration_minutes": 20,
            "transcript": "Patricia: This needs to happen ASAP. We have a board presentation next week and we need the data integration done immediately. It's critical that the API connection works by end of day tomorrow. We can't wait any longer. The deadline is tight and this is urgent. Priya: Let me escalate this to our integration team immediately. Patricia: Please, this is time-sensitive and we need it right away.",
            "outcome": "urgent request",
            "deal_value": 110000,
            "sentiment": "neutral",
            "buying_intent": "medium",
            "follow_up_date": "2025-01-19",
            "status": "open",
        },
        {
            "conversation_id": "CONV-012",
            "account_name": "Meridian Software",
            "contact_name": "Chris Taylor",
            "owner": "Jordan Lee",
            "conversation_date": "2025-01-19",
            "conversation_type": "call",
            "duration_minutes": 12,
            "transcript": "Chris: Just wanted to touch base and see how things are going. Let's schedule a follow-up call in two weeks. Nothing pressing, just a routine check-in to see if anything has changed. We can reconnect after the holidays. Jordan: Sounds good, I'll put it on the calendar. Chris: Great, just reach out when you're ready to pick things back up.",
            "outcome": "routine follow-up",
            "deal_value": 30000,
            "sentiment": "neutral",
            "buying_intent": "low",
            "follow_up_date": "2025-02-03",
            "status": "open",
        },
        {
            "conversation_id": "CONV-013",
            "account_name": "Vector Aerospace",
            "contact_name": "Sophia Martinez",
            "owner": "Alex Morgan",
            "conversation_date": "2025-01-20",
            "conversation_type": "meeting",
            "duration_minutes": 38,
            "transcript": "Sophia: We're ready to move forward with the implementation. Leadership has approved the budget. Let's get this done. We want to sign up for the three-year plan. Send us the contract and we'll execute it this week. We're committed to this partnership. Alex: I'll have the contract ready today. Sophia: The team is excited to proceed and get started.",
            "outcome": "moved to contract",
            "deal_value": 180000,
            "sentiment": "positive",
            "buying_intent": "high",
            "follow_up_date": "2025-01-22",
            "status": "open",
        },
        {
            "conversation_id": "CONV-014",
            "account_name": "Coastal Hotels",
            "contact_name": "Brian Murphy",
            "owner": "Priya Sharma",
            "conversation_date": "2025-01-21",
            "conversation_type": "call",
            "duration_minutes": 30,
            "transcript": "Brian: Can you send us a proposal for the group plan? What's the rate for 200 users? We'd like to understand the pricing structure. How much would the premium package cost? Also, what are the payment terms? We have a budget of 90k. Priya: I'll prepare a detailed proposal with pricing for you. Brian: We'd like to compare the different tier options before deciding.",
            "outcome": "proposal requested",
            "deal_value": 90000,
            "sentiment": "neutral",
            "buying_intent": "medium",
            "follow_up_date": "2025-01-25",
            "status": "open",
        },
        {
            "conversation_id": "CONV-015",
            "account_name": "Apex Manufacturing",
            "contact_name": "Sarah Chen",
            "owner": "Jordan Lee",
            "conversation_date": "2025-01-22",
            "conversation_type": "call",
            "duration_minutes": 35,
            "transcript": "Sarah: We're evaluating other solutions. We've been comparing your platform with Coupa and it seems like the competitor has better reporting. We might switch if the reporting gap isn't addressed. How do you compare to Coupa? We need to make a vendor selection decision by next month. Jordan: Let me set up a meeting with our product team. Sarah: We're doing a thorough vendor comparison and need to see a clear differentiation.",
            "outcome": "competitive risk",
            "deal_value": 85000,
            "sentiment": "negative",
            "buying_intent": "medium",
            "follow_up_date": "2025-01-29",
            "status": "open",
        },
        {
            "conversation_id": "CONV-016",
            "account_name": "Zenith Capital",
            "contact_name": "Daniel Wright",
            "owner": "Alex Morgan",
            "conversation_date": "2025-01-23",
            "conversation_type": "call",
            "duration_minutes": 40,
            "transcript": "Daniel: I'm frustrated. The mobile app is broken and keeps crashing. We can't log in and the error messages are unclear. This has been an issue for two weeks. We submitted a support ticket and no one has responded. The whole team is upset about this. We're dissatisfied with the lack of support. Alex: I sincerely apologize. Let me escalate this immediately. Daniel: We need this resolved, it's affecting our operations.",
            "outcome": "support escalation",
            "deal_value": 0,
            "sentiment": "negative",
            "buying_intent": "none",
            "follow_up_date": "2025-01-23",
            "status": "open",
        },
        {
            "conversation_id": "CONV-017",
            "account_name": "Cascade Partners",
            "contact_name": "Nina Patel",
            "owner": "Jordan Lee",
            "conversation_date": "2025-01-24",
            "conversation_type": "meeting",
            "duration_minutes": 28,
            "transcript": "Nina: This is urgent. We need the compliance audit report by tomorrow. The regulators are coming on Monday and we need everything ready. It's critical that we have the documentation prepared. We can't wait any longer. The deadline is this Friday. Jordan: I understand, let me escalate this right now. Nina: Please treat this as time-sensitive and critical.",
            "outcome": "urgent escalation",
            "deal_value": 70000,
            "sentiment": "negative",
            "buying_intent": "medium",
            "follow_up_date": "2025-01-25",
            "status": "open",
        },
        {
            "conversation_id": "CONV-018",
            "account_name": "BlueOcean Media",
            "contact_name": "Kevin Hughes",
            "owner": "Priya Sharma",
            "conversation_date": "2025-01-25",
            "conversation_type": "call",
            "duration_minutes": 14,
            "transcript": "Kevin: Just checking in. Let's follow up in a couple of weeks. We can touch base after the quarterly review. Nothing urgent, just want to stay in the loop. Schedule a call for next month. Priya: I'll send a calendar invite. Kevin: Great, we can circle back then and see where things stand.",
            "outcome": "routine follow-up",
            "deal_value": 25000,
            "sentiment": "neutral",
            "buying_intent": "low",
            "follow_up_date": "2025-02-10",
            "status": "open",
        },
        {
            "conversation_id": "CONV-019",
            "account_name": "Titan Construction",
            "contact_name": "Grace Liu",
            "owner": "Alex Morgan",
            "conversation_date": "2025-01-26",
            "conversation_type": "meeting",
            "duration_minutes": 42,
            "transcript": "Grace: We want to proceed with the full implementation. The board has approved the budget. Let's get the contract started. We're ready to sign up and move forward this quarter. Send us the paperwork and we'll execute immediately. We commit to this deal. Alex: I'll prepare the agreement today. Grace: The procurement team is ready and we want to close this.",
            "outcome": "moved to contract",
            "deal_value": 135000,
            "sentiment": "positive",
            "buying_intent": "high",
            "follow_up_date": "2025-01-28",
            "status": "open",
        },
        {
            "conversation_id": "CONV-020",
            "account_name": "Pacific Foods",
            "contact_name": "Eric Davis",
            "owner": "Jordan Lee",
            "conversation_date": "2025-01-27",
            "conversation_type": "call",
            "duration_minutes": 24,
            "transcript": "Eric: Can you provide pricing for the business plan? What does it cost per user? We'd like a quote for 150 seats. How much is the annual subscription? Also, what are the available discount options? We have about 75k budgeted for this. Jordan: I'll send you a detailed pricing sheet today. Eric: We're evaluating a few options so the price will be a key factor.",
            "outcome": "pricing requested",
            "deal_value": 75000,
            "sentiment": "neutral",
            "buying_intent": "medium",
            "follow_up_date": "2025-01-31",
            "status": "open",
        },
        {
            "conversation_id": "CONV-021",
            "account_name": "Helix Pharma",
            "contact_name": "Rachel Green",
            "owner": "Priya Sharma",
            "conversation_date": "2025-01-28",
            "conversation_type": "call",
            "duration_minutes": 33,
            "transcript": "Rachel: We're interested but also looking at alternatives. We want to move forward but we're also comparing with SAP Concur. The competitor has some features we like. We're ready to sign but might switch to another vendor. We need pricing and also want to evaluate other options. Priya: I understand the mixed signals. Let me address your concerns. Rachel: We're torn between a few solutions and need more time.",
            "outcome": "ambiguous - evaluating",
            "deal_value": 100000,
            "sentiment": "neutral",
            "buying_intent": "medium",
            "follow_up_date": "2025-02-05",
            "status": "open",
        },
        {
            "conversation_id": "CONV-022",
            "account_name": "BrightPath Education",
            "contact_name": "Victor Adams",
            "owner": "Alex Morgan",
            "conversation_date": "2025-01-29",
            "conversation_type": "meeting",
            "duration_minutes": 47,
            "transcript": "Victor: The team likes the platform and wants to move forward, but we've had some issues with the API. It's been broken intermittently. We're ready to proceed but need the integration fixed first. We want to sign up but the support issue is blocking us. Let's do this once the bug is resolved. Alex: Let me escalate the API issue and we'll prioritize the fix. Victor: We're committed but the technical problem needs to be addressed first.",
            "outcome": "ambiguous - blocked by issue",
            "deal_value": 95000,
            "sentiment": "neutral",
            "buying_intent": "high",
            "follow_up_date": "2025-02-03",
            "status": "open",
        },
        {
            "conversation_id": "CONV-023",
            "account_name": "Solaris Tech",
            "contact_name": "Diana Ross",
            "owner": "Jordan Lee",
            "conversation_date": "2025-01-30",
            "conversation_type": "call",
            "duration_minutes": 26,
            "transcript": "Diana: We need pricing for the enterprise tier. But we're also considering switching to Brex. Can you send a proposal? The competitor offers better rates. We'd like to move forward but might choose another vendor. What's the cost and how do you compare? Jordan: Let me prepare a competitive proposal for you. Diana: We're evaluating options and the decision could go either way.",
            "outcome": "ambiguous - evaluating",
            "deal_value": 110000,
            "sentiment": "neutral",
            "buying_intent": "medium",
            "follow_up_date": "2025-02-06",
            "status": "open",
        },
        {
            "conversation_id": "CONV-024",
            "account_name": "Evergreen Insurance",
            "contact_name": "Mark Stevens",
            "owner": "Priya Sharma",
            "conversation_date": "2025-01-31",
            "conversation_type": "call",
            "duration_minutes": 31,
            "transcript": "Mark: We need the annual compliance report urgently. The audit is next week and we need it by Friday. It's critical that the data is ready. We can't wait any longer. This is urgent and the deadline is tight. Priya: I'll prioritize this and get the report ready. Mark: Please, this needs to happen ASAP.",
            "outcome": "urgent request",
            "deal_value": 65000,
            "sentiment": "neutral",
            "buying_intent": "medium",
            "follow_up_date": "2025-02-01",
            "status": "open",
        },
        {
            "conversation_id": "CONV-025",
            "account_name": "Frontier Logistics",
            "contact_name": "Olivia Barnes",
            "owner": "Alex Morgan",
            "conversation_date": "2025-02-01",
            "conversation_type": "meeting",
            "duration_minutes": 36,
            "transcript": "Olivia: The platform is working great. We want to expand our usage. Let's add 200 more users and upgrade to the enterprise plan. We're ready to move forward with the expansion. Send us the updated contract. The team is on board and we want to proceed immediately. Alex: I'll prepare the amendment and send it over today. Olivia: We want to get this done this quarter.",
            "outcome": "expansion deal",
            "deal_value": 140000,
            "sentiment": "positive",
            "buying_intent": "high",
            "follow_up_date": "2025-02-04",
            "status": "open",
        },
        {
            "conversation_id": "CONV-026",
            "account_name": "Vertex Robotics",
            "contact_name": "Henry Clark",
            "owner": "Jordan Lee",
            "conversation_date": "2025-02-02",
            "conversation_type": "call",
            "duration_minutes": 19,
            "transcript": "Henry: There's a problem with the receipt export feature. It's not working and we keep getting an error. The export is broken and we can't generate our monthly report. This is causing issues with our finance close. We need a fix. The bug is affecting the whole team. Jordan: I'll escalate this to our support team right now. Henry: We've been unhappy with how long this has been going on.",
            "outcome": "support issue",
            "deal_value": 50000,
            "sentiment": "negative",
            "buying_intent": "none",
            "follow_up_date": "2025-02-03",
            "status": "open",
        },
        {
            "conversation_id": "CONV-027",
            "account_name": "Maple Leaf Foods",
            "contact_name": "Isabella Ross",
            "owner": "Priya Sharma",
            "conversation_date": "2025-02-03",
            "conversation_type": "call",
            "duration_minutes": 10,
            "transcript": "Isabella: Just wanted to check in. Let's touch base next month. Schedule a follow-up call for March. Nothing pressing, just a routine check-in. We can reconnect after the budget cycle. Priya: I'll send a calendar invite for next month. Isabella: Great, just reach out when it's time to pick things back up.",
            "outcome": "routine follow-up",
            "deal_value": 20000,
            "sentiment": "neutral",
            "buying_intent": "low",
            "follow_up_date": "2025-03-03",
            "status": "open",
        },
        {
            "conversation_id": "CONV-028",
            "account_name": "Infinity Gaming",
            "contact_name": "Lucas Wright",
            "owner": "Alex Morgan",
            "conversation_date": "2025-02-04",
            "conversation_type": "meeting",
            "duration_minutes": 44,
            "transcript": "Lucas: We want to proceed with the full platform. Leadership approved the budget. Let's do this and get the contract started. We're ready to sign up for the annual plan. Send us the agreement and we'll execute this week. We commit to moving forward. Alex: I'll have the contract ready within 24 hours. Lucas: The executive team is on board and we want to close this deal.",
            "outcome": "moved to contract",
            "deal_value": 160000,
            "sentiment": "positive",
            "buying_intent": "high",
            "follow_up_date": "2025-02-06",
            "status": "open",
        },
        {
            "conversation_id": "CONV-029",
            "account_name": "Redwood Partners",
            "contact_name": "Ava Thompson",
            "owner": "Jordan Lee",
            "conversation_date": "2025-02-05",
            "conversation_type": "call",
            "duration_minutes": 21,
            "transcript": "Ava: What's the pricing for 100 users? Can you send a proposal? How much does the premium tier cost? We'd like a quote with payment terms. We have a budget of 80k allocated. Also, are there any discount options? Jordan: I'll send you the pricing and proposal today. Ava: We'd like to review the options before making a decision.",
            "outcome": "pricing requested",
            "deal_value": 80000,
            "sentiment": "neutral",
            "buying_intent": "medium",
            "follow_up_date": "2025-02-09",
            "status": "open",
        },
        {
            "conversation_id": "CONV-030",
            "account_name": "Granite Holdings",
            "contact_name": "William Foster",
            "owner": "Priya Sharma",
            "conversation_date": "2025-02-06",
            "conversation_type": "meeting",
            "duration_minutes": 29,
            "transcript": "William: We've been with you for two years and mostly happy. But we're evaluating other options. We're comparing with another vendor who offers more features. We might switch if the pricing is more competitive. How do you compare on value? We're doing a vendor evaluation. Priya: Let me schedule a review meeting to address your concerns. William: We need to see a clear reason to stay before our renewal date.",
            "outcome": "renewal risk",
            "deal_value": 70000,
            "sentiment": "negative",
            "buying_intent": "low",
            "follow_up_date": "2025-02-13",
            "status": "open",
        },
        {
            "conversation_id": "CONV-031",
            "account_name": "Orion Airlines",
            "contact_name": "Charlotte Lee",
            "owner": "Alex Morgan",
            "conversation_date": "2025-02-07",
            "conversation_type": "call",
            "duration_minutes": 37,
            "transcript": "Charlotte: The platform crashed during our peak processing time. The system was down for two hours. This is a critical outage. We can't have downtime during our billing cycle. This needs to be fixed urgently. The latency is also a problem. We're frustrated with the performance issues. Alex: I'm escalating this to our engineering team immediately. Charlotte: We need a resolution plan and a timeline, this is unacceptable.",
            "outcome": "support escalation",
            "deal_value": 0,
            "sentiment": "negative",
            "buying_intent": "none",
            "follow_up_date": "2025-02-07",
            "status": "open",
        },
        {
            "conversation_id": "CONV-032",
            "account_name": "Cedar Financial",
            "contact_name": "Greg Wilson",
            "owner": "Jordan Lee",
            "conversation_date": "2025-02-08",
            "conversation_type": "meeting",
            "duration_minutes": 41,
            "transcript": "Greg: Great demo. We want to proceed with the implementation. The CFO has approved the budget. Let's get the contract started. We're ready to sign up for the premium plan. Send us the agreement and we'll execute within the week. The team is on board. Jordan: I'll prepare the contract today. Greg: We want to get this done before our fiscal year ends.",
            "outcome": "moved to contract",
            "deal_value": 125000,
            "sentiment": "positive",
            "buying_intent": "high",
            "follow_up_date": "2025-02-10",
            "status": "open",
        },
    ]

    df = pd.DataFrame(records)
    return df


def save_sample_csv(path: str | Path | None = None) -> Path:
    """Save the sample dataset to a CSV file and return its path."""
    df = generate_sample_data()
    if path is None:
        path = Path(__file__).parent / "sample_data.csv"
    else:
        path = Path(path)
    df.to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# Duplicate / update demo
# ---------------------------------------------------------------------------

def run_duplicate_update_demo() -> dict:
    """
    Execute a genuine end-to-end duplicate and update test.

    Steps:
      1. Import a single sample record (expect: inserted=1).
      2. Import the exact same record again (expect: unchanged=1).
      3. Import the same record with a modified transcript (expect: updated=1).
      4. Verify the unique record count remains 1 throughout.

    Returns a dict with all step results.
    """
    init_db()

    # Create a single test record
    test_record = {
        "conversation_id": "DEMO-001",
        "account_name": "Demo Corporation",
        "contact_name": "Test User",
        "owner": "Demo Owner",
        "conversation_date": "2025-02-10",
        "conversation_type": "call",
        "duration_minutes": 20,
        "transcript": "We want to proceed with the purchase. Let's get the contract started. We're ready to move forward.",
        "outcome": "moved to contract",
        "deal_value": 50000,
        "sentiment": "positive",
        "buying_intent": "high",
        "follow_up_date": "2025-02-12",
        "status": "open",
    }

    # Modified version (transcript changed)
    test_record_modified = test_record.copy()
    test_record_modified["transcript"] = (
        "We've decided to move forward. Send us the contract. "
        "Leadership approved the budget and we're ready to sign up immediately."
    )
    test_record_modified["outcome"] = "contract ready"

    df1 = pd.DataFrame([test_record])
    df2 = pd.DataFrame([test_record])
    df3 = pd.DataFrame([test_record_modified])

    results = {}

    # Step 1: First import (should insert)
    results["step1_first_import"] = import_csv_data(df1, "demo_step1.csv")
    count_after_step1 = count_conversations()
    results["step1_first_import"]["count_after"] = count_after_step1

    # Step 2: Identical re-import (should be unchanged)
    results["step2_reimport_unchanged"] = import_csv_data(df2, "demo_step2.csv")
    count_after_step2 = count_conversations()
    results["step2_reimport_unchanged"]["count_after"] = count_after_step2

    # Step 3: Modified re-import (should update)
    results["step3_reimport_modified"] = import_csv_data(df3, "demo_step3.csv")
    count_after_step3 = count_conversations()
    results["step3_reimport_modified"]["count_after"] = count_after_step3

    # Verify: count should not have increased from step1 to step2 or step3
    results["verification"] = {
        "count_after_step1": count_after_step1,
        "count_after_step2": count_after_step2,
        "count_after_step3": count_after_step3,
        "count_stayed_same": (
            count_after_step1 == count_after_step2 == count_after_step3
        ),
        "step1_inserted": results["step1_first_import"]["inserted"] == 1,
        "step2_unchanged": results["step2_reimport_unchanged"]["unchanged"] == 1,
        "step3_updated": results["step3_reimport_modified"]["updated"] == 1,
    }

    # Clean up: remove the demo record so it doesn't pollute the dataset
    from database import get_connection
    conn = get_connection()
    conn.execute("DELETE FROM conversations WHERE conversation_id = 'DEMO-001'")
    conn.execute("DELETE FROM import_history WHERE source_file LIKE 'demo_step%'")
    conn.commit()
    conn.close()

    return results
