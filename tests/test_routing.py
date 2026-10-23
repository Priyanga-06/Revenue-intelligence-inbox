"""
tests/test_routing.py — Tests for the explainable routing engine.

Run with:
    python -m pytest tests/test_routing.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from routing import route_conversation, CATEGORIES


# ---------------------------------------------------------------------------
# 1. High-intent sales signals
# ---------------------------------------------------------------------------

def test_high_intent_routing():
    """A transcript with strong buying intent should route to high-intent sales."""
    conv = {
        "conversation_id": "TEST-R-001",
        "transcript": "We're ready to move forward. Let's get the contract started. "
                       "Our CFO has approved the budget. Send us the agreement.",
        "buying_intent": "high",
        "sentiment": "positive",
    }
    result = route_conversation(conv)
    assert result.category == CATEGORIES["high_intent_sales"]
    assert result.priority == "high"
    assert "buying-intent" in result.reason.lower() or "signal" in result.reason.lower()
    assert len(result.evidence_excerpt) > 0, "Must have evidence excerpt"


# ---------------------------------------------------------------------------
# 2. Pricing/proposal request
# ---------------------------------------------------------------------------

def test_pricing_routing():
    """A transcript asking about pricing should route to pricing/proposal."""
    conv = {
        "conversation_id": "TEST-R-002",
        "transcript": "Can you send us a proposal for the group plan? What's the rate "
                       "for 200 users? We'd like to understand the pricing structure.",
        "buying_intent": "medium",
        "sentiment": "neutral",
    }
    result = route_conversation(conv)
    assert result.category == CATEGORIES["pricing_proposal"]
    assert len(result.evidence_excerpt) > 0


# ---------------------------------------------------------------------------
# 3. Competitor risk
# ---------------------------------------------------------------------------

def test_competitor_routing():
    """A transcript mentioning competitors should route to competitor risk."""
    conv = {
        "conversation_id": "TEST-R-003",
        "transcript": "We're comparing you against a couple of other vendors right now. "
                       "We're evaluating SAP Concur as an alternative. We might switch "
                       "if the price is right.",
        "buying_intent": "medium",
        "sentiment": "neutral",
    }
    result = route_conversation(conv)
    assert result.category == CATEGORIES["competitor_risk"]
    assert len(result.evidence_excerpt) > 0


# ---------------------------------------------------------------------------
# 4. Customer support issue
# ---------------------------------------------------------------------------

def test_support_routing():
    """A transcript reporting problems should route to customer support issue."""
    conv = {
        "conversation_id": "TEST-R-004",
        "transcript": "The mobile app is broken and keeps crashing. We can't log in "
                       "and the error messages are unclear. This has been an issue for "
                       "two weeks. We're frustrated with the lack of support.",
        "buying_intent": "none",
        "sentiment": "negative",
    }
    result = route_conversation(conv)
    assert result.category == CATEGORIES["support_issue"]
    assert len(result.evidence_excerpt) > 0


# ---------------------------------------------------------------------------
# 5. Urgent follow-up
# ---------------------------------------------------------------------------

def test_urgent_routing():
    """A transcript with urgency signals should route to urgent follow-up."""
    conv = {
        "conversation_id": "TEST-R-005",
        "transcript": "This is urgent. We need the implementation completed by tomorrow. "
                       "The board meeting is on Friday and we need everything ready. "
                       "We can't wait any longer.",
        "buying_intent": "medium",
        "sentiment": "neutral",
    }
    result = route_conversation(conv)
    assert result.category == CATEGORIES["urgent_follow_up"]
    assert result.priority == "high"
    assert len(result.evidence_excerpt) > 0


# ---------------------------------------------------------------------------
# 6. Routine follow-up
# ---------------------------------------------------------------------------

def test_routine_routing():
    """A transcript with no strong signals should route to routine follow-up."""
    conv = {
        "conversation_id": "TEST-R-006",
        "transcript": "Just wanted to check in. Let's follow up in a couple of weeks. "
                       "We can touch base after the quarterly review. Nothing urgent, "
                       "just want to stay in the loop. Schedule a call for next month.",
        "buying_intent": "low",
        "sentiment": "neutral",
    }
    result = route_conversation(conv)
    assert result.category == CATEGORIES["routine_follow_up"]
    assert len(result.evidence_excerpt) > 0


# ---------------------------------------------------------------------------
# 7. Ambiguous conversation flagged for review
# ---------------------------------------------------------------------------

def test_ambiguous_flagged_for_review():
    """A transcript with conflicting signals (intent + competitor) should flag for review."""
    conv = {
        "conversation_id": "TEST-R-007",
        "transcript": "We want to proceed with the full platform. Leadership approved the "
                       "budget. Let's do this. But we're also comparing with SAP Concur. "
                       "We're ready to sign up but might switch to another vendor. "
                       "We need pricing and also want to evaluate other options.",
        "buying_intent": "medium",
        "sentiment": "neutral",
    }
    result = route_conversation(conv)
    assert result.category == CATEGORIES["needs_human_review"], (
        f"Expected needs_human_review, got {result.category}"
    )
    assert result.needs_review is True
    assert result.confidence == "Low"
    assert "conflict" in result.reason.lower() or "ambiguous" in result.reason.lower()


# ---------------------------------------------------------------------------
# 8. Evidence is genuine transcript excerpt
# ---------------------------------------------------------------------------

def test_evidence_from_transcript():
    """The evidence excerpt must come from the actual transcript text."""
    transcript = "We want to proceed with the purchase. Let's get the contract started. We're ready to move forward."
    conv = {
        "conversation_id": "TEST-R-008",
        "transcript": transcript,
        "buying_intent": "high",
        "sentiment": "positive",
    }
    result = route_conversation(conv)
    assert len(result.evidence_excerpt) > 10, "Evidence should be non-trivial"
    # The evidence should contain words from the transcript
    transcript_lower = transcript.lower()
    evidence_lower = result.evidence_excerpt.lower()
    # At least some words should match
    words_in_common = set(transcript_lower.split()) & set(evidence_lower.split())
    assert len(words_in_common) > 2, (
        f"Evidence should share words with transcript. "
        f"Common words: {words_in_common}"
    )


# ---------------------------------------------------------------------------
# 9. Negated keywords not counted as positive signals
# ---------------------------------------------------------------------------

def test_negation_handling():
    """A negated pricing keyword should not trigger pricing routing."""
    conv = {
        "conversation_id": "TEST-R-009",
        "transcript": "We're not interested in pricing right now. We just want to "
                       "check in and see how things are going. Let's follow up next week.",
        "buying_intent": "low",
        "sentiment": "neutral",
    }
    result = route_conversation(conv)
    # Should NOT be pricing proposal (negated)
    assert result.category != CATEGORIES["pricing_proposal"], (
        "Negated pricing keyword should not trigger pricing routing"
    )


# ---------------------------------------------------------------------------
# 10. Confidence labels are High/Medium/Low
# ---------------------------------------------------------------------------

def test_confidence_labels():
    """Confidence should always be High, Medium, or Low."""
    transcripts = [
        ("We're ready to move forward. Let's get the contract started. Send us the agreement. We want to sign up.", "high", "positive"),
        ("Can you send us a quote? What's the pricing?", "medium", "neutral"),
        ("Just checking in. Let's touch base next week.", "low", "neutral"),
    ]
    for transcript, intent, sentiment in transcripts:
        conv = {
            "conversation_id": "TEST-R-010",
            "transcript": transcript,
            "buying_intent": intent,
            "sentiment": sentiment,
        }
        result = route_conversation(conv)
        assert result.confidence in ("High", "Medium", "Low"), (
            f"Confidence must be High/Medium/Low, got {result.confidence}"
        )
