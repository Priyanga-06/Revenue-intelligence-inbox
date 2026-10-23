"""
analytics.py — Dashboard metrics, activity trends, and evidence-linked findings.

All metrics are calculated dynamically from stored conversation records.
Findings are generated from the actual loaded data, not hardcoded.
"""

from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd


# ---------------------------------------------------------------------------
# Dashboard metrics
# ---------------------------------------------------------------------------

def calculate_metrics(conversations: list[dict]) -> dict:
    """Calculate all dashboard metrics from a list of conversation dicts."""
    if not conversations:
        return _empty_metrics()

    df = pd.DataFrame(conversations)

    total = len(df)
    calls = int((df["conversation_type"].fillna("").str.lower() == "call").sum())
    meetings = int((df["conversation_type"].fillna("").str.lower() == "meeting").sum())

    # Priority
    high_priority = int(
        df["priority"].fillna("").str.lower().eq("high").sum()
    )

    # Open follow-ups
    open_followups = int(df["status"].fillna("open").str.lower().eq("open").sum())

    # Pipeline value (sum of deal_value for all conversations)
    pipeline_value = float(pd.to_numeric(df["deal_value"], errors="coerce").fillna(0).sum())

    # Conversations requiring manager attention
    needs_attention_mask = (
        df["needs_review"].fillna(0).eq(1)
        | (df["priority"].fillna("").str.lower().eq("high") & df["status"].fillna("").str.lower().eq("open"))
    )
    needs_attention = int(needs_attention_mask.sum())

    # Sentiment distribution
    sentiment_counts = df["sentiment"].fillna("unknown").str.lower().value_counts().to_dict()

    # Routing category distribution
    routing_counts = df["routing_category"].fillna("Unassigned").value_counts().to_dict()

    # Volume by owner
    owner_counts = df["owner"].fillna("Unknown").value_counts().to_dict()

    # Activity trend by day
    df["conv_date"] = pd.to_datetime(df["conversation_date"], errors="coerce")
    daily_counts = (
        df.groupby(df["conv_date"].dt.date)
        .size()
        .reset_index(name="count")
        .sort_values("conv_date")
    )
    activity_trend = [
        {"date": str(row["conv_date"]), "count": int(row["count"])}
        for _, row in daily_counts.iterrows()
    ]

    return {
        "total_conversations": total,
        "calls": calls,
        "meetings": meetings,
        "high_priority": high_priority,
        "open_followups": open_followups,
        "pipeline_value": pipeline_value,
        "needs_attention": needs_attention,
        "sentiment_distribution": sentiment_counts,
        "routing_category_distribution": routing_counts,
        "owner_distribution": owner_counts,
        "activity_trend": activity_trend,
    }


def _empty_metrics() -> dict:
    return {
        "total_conversations": 0,
        "calls": 0,
        "meetings": 0,
        "high_priority": 0,
        "open_followups": 0,
        "pipeline_value": 0.0,
        "needs_attention": 0,
        "sentiment_distribution": {},
        "routing_category_distribution": {},
        "owner_distribution": {},
        "activity_trend": [],
    }


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_conversations(conversations: list[dict], filters: dict) -> list[dict]:
    """Apply date/owner/priority/sentiment/routing filters to conversations."""
    result = conversations

    if filters.get("date_from"):
        result = [
            c for c in result
            if c.get("conversation_date", "") >= filters["date_from"]
        ]

    if filters.get("date_to"):
        result = [
            c for c in result
            if c.get("conversation_date", "") <= filters["date_to"]
        ]

    if filters.get("owner") and filters["owner"] != "All":
        result = [c for c in result if (c.get("owner") or "") == filters["owner"]]

    if filters.get("priority") and filters["priority"] != "All":
        result = [
            c for c in result
            if (c.get("priority") or "").lower() == filters["priority"].lower()
        ]

    if filters.get("sentiment") and filters["sentiment"] != "All":
        result = [
            c for c in result
            if (c.get("sentiment") or "").lower() == filters["sentiment"].lower()
        ]

    if filters.get("routing_category") and filters["routing_category"] != "All":
        result = [
            c for c in result
            if c.get("routing_category") == filters["routing_category"]
        ]

    return result


# ---------------------------------------------------------------------------
# Evidence-linked findings
# ---------------------------------------------------------------------------

def generate_findings(conversations: list[dict]) -> list[dict]:
    """
    Analyze loaded records and produce three evidence-linked findings.

    Each finding includes:
      - finding_statement
      - supporting_metric and calculation
      - conversation_ids
      - evidence_excerpts (from transcripts)
      - business_impact
      - recommended_action
      - data_source: "synthetic" or "user-provided"
    """
    if not conversations or len(conversations) < 3:
        return [{
            "finding_statement": "Insufficient data to generate findings.",
            "supporting_metric": "Record count below minimum threshold (3).",
            "conversation_ids": [],
            "evidence_excerpts": [],
            "business_impact": "Import more records to enable findings analysis.",
            "recommended_action": "Import at least 3 conversation records.",
            "data_source": "N/A",
        }]

    findings = []

    # Determine if data is synthetic or user-provided
    # Heuristic: if all source_file values are "sample_data.csv" or empty,
    # treat as synthetic. Otherwise user-provided.
    source_files = set(c.get("source_file", "") for c in conversations)
    is_synthetic = source_files.issubset({"", "sample_data.csv", "generate_sample_data"})
    data_source = "synthetic" if is_synthetic else "user-provided"

    # ---- Finding 1: Competitor risk concentration ----------------------------
    competitor_convs = [
        c for c in conversations
        if "competitor" in (c.get("routing_category") or "").lower()
    ]
    if competitor_convs:
        total_pipeline = sum(float(c.get("deal_value", 0)) for c in conversations)
        competitor_pipeline = sum(float(c.get("deal_value", 0)) for c in competitor_convs)
        pct = (competitor_pipeline / total_pipeline * 100) if total_pipeline else 0
        findings.append({
            "finding_statement": (
                f"{len(competitor_convs)} conversation(s) show competitor risk signals, "
                f"representing ${competitor_pipeline:,.0f} ({pct:.1f}%) of total pipeline value."
            ),
            "supporting_metric": (
                f"Competitor-risk conversations: {len(competitor_convs)} / {len(conversations)} total "
                f"= {len(competitor_convs)/len(conversations)*100:.1f}%. "
                f"Pipeline at risk: ${competitor_pipeline:,.0f} of ${total_pipeline:,.0f}."
            ),
            "conversation_ids": [c["conversation_id"] for c in competitor_convs],
            "evidence_excerpts": [
                c.get("evidence_excerpt", c.get("transcript", "")[:200])
                for c in competitor_convs
            ],
            "business_impact": (
                f"At-risk pipeline of ${competitor_pipeline:,.0f} could churn to competitors "
                f"if not addressed with competitive differentiation and proactive engagement."
            ),
            "recommended_action": (
                "Escalate competitor-risk conversations to senior reps. Prepare competitive "
                "battle cards and schedule executive alignment calls within 48 hours."
            ),
            "data_source": data_source,
        })
    else:
        findings.append({
            "finding_statement": "No competitor risk signals detected in the current dataset.",
            "supporting_metric": f"0 of {len(conversations)} conversations flagged as competitor risk.",
            "conversation_ids": [],
            "evidence_excerpts": [],
            "business_impact": "No immediate competitor-driven churn risk identified.",
            "recommended_action": "Continue monitoring for competitor mentions in future conversations.",
            "data_source": data_source,
        })

    # ---- Finding 2: High-intent opportunities ready to close ------------------
    high_intent_convs = [
        c for c in conversations
        if "high-intent" in (c.get("routing_category") or "").lower()
    ]
    if high_intent_convs:
        total_intent_value = sum(float(c.get("deal_value", 0)) for c in high_intent_convs)
        avg_deal = total_intent_value / len(high_intent_convs) if high_intent_convs else 0
        open_count = sum(
            1 for c in high_intent_convs
            if c.get("status", "").lower() == "open"
        )
        findings.append({
            "finding_statement": (
                f"{len(high_intent_convs)} high-intent sales conversations are in the pipeline "
                f"with a combined value of ${total_intent_value:,.0f} "
                f"(average deal size: ${avg_deal:,.0f}). "
                f"{open_count} are still open and require action."
            ),
            "supporting_metric": (
                f"High-intent conversations: {len(high_intent_convs)} / {len(conversations)} total "
                f"= {len(high_intent_convs)/len(conversations)*100:.1f}%. "
                f"Combined pipeline value: ${total_intent_value:,.0f}. "
                f"Open and requiring action: {open_count}."
            ),
            "conversation_ids": [c["conversation_id"] for c in high_intent_convs],
            "evidence_excerpts": [
                c.get("evidence_excerpt", c.get("transcript", "")[:200])
                for c in high_intent_convs
            ],
            "business_impact": (
                f"${total_intent_value:,.0f} in high-intent pipeline represents the highest-value "
                f"near-term revenue opportunity. Delays in contract delivery risk losing these deals."
            ),
            "recommended_action": (
                "Prioritize contract preparation for all high-intent conversations. "
                "Set a 24-hour SLA for contract delivery and schedule closing calls."
            ),
            "data_source": data_source,
        })
    else:
        findings.append({
            "finding_statement": "No high-intent sales opportunities detected in the current dataset.",
            "supporting_metric": f"0 of {len(conversations)} conversations classified as high-intent.",
            "conversation_ids": [],
            "evidence_excerpts": [],
            "business_impact": "No immediate closing opportunities identified.",
            "recommended_action": "Focus on moving medium-intent conversations through the sales funnel.",
            "data_source": data_source,
        })

    # ---- Finding 3: Support issues and customer dissatisfaction ---------------
    support_convs = [
        c for c in conversations
        if "support" in (c.get("routing_category") or "").lower()
    ]
    negative_convs = [
        c for c in conversations
        if c.get("sentiment", "").lower() == "negative"
    ]
    combined = list({c["conversation_id"]: c for c in support_convs + negative_convs}.values())

    if combined:
        negative_pct = len(negative_convs) / len(conversations) * 100 if conversations else 0
        findings.append({
            "finding_statement": (
                f"{len(support_convs)} conversation(s) flagged as customer support issues, "
                f"with {len(negative_convs)} total negative-sentiment interactions "
                f"({negative_pct:.1f}% of all conversations). These may signal product "
                f"reliability or service quality concerns."
            ),
            "supporting_metric": (
                f"Support-issue conversations: {len(support_convs)}. "
                f"Negative-sentiment conversations: {len(negative_convs)} / {len(conversations)} "
                f"= {negative_pct:.1f}%. "
                f"Combined at-risk accounts: {len(combined)}."
            ),
            "conversation_ids": [c["conversation_id"] for c in combined],
            "evidence_excerpts": [
                c.get("evidence_excerpt", c.get("transcript", "")[:200])
                for c in combined[:5]
            ],
            "business_impact": (
                f"{len(combined)} account(s) with support or dissatisfaction signals are at risk "
                f"of churn. Negative sentiment trends can signal broader product issues that "
                f"impact retention and expansion revenue."
            ),
            "recommended_action": (
                "Route all support issues to the customer success team with a 4-hour acknowledgment SLA. "
                "Conduct a root-cause analysis on recurring issues and share resolution timelines with "
                "affected accounts."
            ),
            "data_source": data_source,
        })
    else:
        findings.append({
            "finding_statement": "No customer support issues or negative sentiment detected.",
            "supporting_metric": f"0 of {len(conversations)} conversations show support or negative signals.",
            "conversation_ids": [],
            "evidence_excerpts": [],
            "business_impact": "No immediate customer satisfaction risk identified.",
            "recommended_action": "Continue monitoring sentiment trends for early warning signs.",
            "data_source": data_source,
        })

    return findings


# ---------------------------------------------------------------------------
# Rejected decision log
# ---------------------------------------------------------------------------

def get_rejected_decision() -> dict:
    """Return the documented rejected decision for the decision log."""
    return {
        "decision": "Rejected keyword-only routing",
        "considered_approach": (
            "Keyword-only routing: classify conversations based solely on the presence "
            "of specific keywords (e.g., 'competitor', 'pricing', 'urgent') in the transcript."
        ),
        "reason_for_rejection": (
            "A word such as 'competitor' can appear in a positive or negative context. "
            "For example, 'we chose you over the competitor' is positive, while 'we're "
            "switching to a competitor' is negative. Keyword-only routing cannot distinguish "
            "these meanings and would misclassify conversations. Similarly, 'not interested "
            "in pricing right now' would be wrongly routed as a pricing request."
        ),
        "chosen_alternative": (
            "Context-aware deterministic routing that analyzes sentence-level context, "
            "checks for negation patterns, scores multiple signals, detects conflicts, "
            "and flags ambiguous cases for human review."
        ),
        "trade_off": (
            "The context-aware approach is more complex to implement and slightly slower "
            "than keyword matching. However, it produces significantly more accurate and "
            "explainable routing decisions, reduces false positives, and handles edge cases "
            "gracefully."
        ),
        "expected_benefit": (
            "Higher routing accuracy, fewer misclassified conversations, transparent "
            "evidence excerpts for each decision, and automatic flagging of ambiguous "
            "cases that need human judgment rather than silent misclassification."
        ),
    }
