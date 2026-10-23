"""
routing.py — Explainable, deterministic conversation routing engine.

Routes conversations into one of seven categories using context-aware
analysis of the transcript.  Each routing decision includes:
  - Category
  - Priority (high / medium / low)
  - Reason (human-readable explanation)
  - Evidence excerpt (direct quote from the transcript)
  - Next action recommendation
  - Confidence label (High / Medium / Low)
  - Human-review flag (True / False)

The engine does NOT rely on isolated keywords alone.  It looks at
sentence-level context, signal strength, and conflicting signals to make
a defensible, explainable decision.  Ambiguous cases are flagged for
human review rather than forced into a category.
"""

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RoutingResult:
    category: str
    priority: str
    reason: str
    evidence_excerpt: str
    next_action: str
    confidence: str          # "High", "Medium", "Low"
    needs_review: bool
    signals: dict = field(default_factory=dict)


CATEGORIES = {
    "high_intent_sales":     "High-intent sales opportunity",
    "pricing_proposal":      "Pricing or proposal request",
    "competitor_risk":       "Competitor risk",
    "support_issue":         "Customer support issue",
    "urgent_follow_up":      "Urgent follow-up",
    "routine_follow_up":     "Routine follow-up",
    "needs_human_review":    "Needs human review",
}


# ---------------------------------------------------------------------------
# Signal patterns
# ---------------------------------------------------------------------------
# Each pattern is a regex.  We search case-insensitively at the sentence level
# so that surrounding context is available.

INTENT_PATTERNS = [
    r"ready to move forward",
    r"let'?s (do this|move ahead|proceed)",
    r"(send|prepare) (the|a)? ?(contract|agreement)",
    r"(we|i|the team|leadership) (want to|'?d like to|will) (sign|move forward|proceed|go ahead)",
    r"(approved|approving|approve) (the|this)? ?(budget|purchase|deal|proposal)",
    r"purchase order",
    r"(we'?re|we are) (in|on board|ready)",
    r"commit to (this|the|moving)",
    r"(let'?s|we should) (get this done|close this|wrap this up)",
    r"(send|get|prepare) (the|a)? ?paperwork",
    r"(sign|signing) (up|the contract|the agreement)",
]

PRICING_PATTERNS = [
    r"(pricing|price|cost|rate|quote|proposal)",
    r"how much (does|will|is|would)",
    r"what(?:'?s| is) (the|your)? ?(pricing|cost|price)",
    r"budget (is|of|for|allocated)",
    r"(discount|negotiate|terms|payment plan)",
    r"(tier|plan|package) (pricing|cost|options)",
]

COMPETITOR_PATTERNS = [
    r"\bcompetitor\b",
    r"another vendor",
    r"other (provider|option|solution|vendor)",
    r"\b(comparing|comparison)\b",
    r"(considering|evaluating|looking at|exploring).*\b(alternative|other|another)\b",
    r"(switching|switch).*\b(to|from|away|vendor)\b",
    r"(better|cheaper|faster).*\b(than|compared)\b",
    r"(what makes you|how do you compare|why should we choose you over)",
    r"\bvendor\b.*\b(evaluation|comparison|selection)\b",
]

SUPPORT_PATTERNS = [
    r"(problem|issue|broken|not working|error|bug|crash|fail)",
    r"(frustrat|upset|disappoint|unhappy|dissatisf)",
    r"(escalat|complaint|can'?t (access|log in|use))",
    r"(wrong|incorrect|missing) (data|invoice|charge|information)",
    r"(slow|latency|timeout|outage|downtime)",
    r"(support ticket|help desk|technical (issue|problem))",
]

URGENT_PATTERNS = [
    r"urgent",
    r"asap",
    r"immediately",
    r"by (tomorrow|end of (day|week)|friday|monday|the 5th|next week)",
    r"(need (it|this) (by|before|no later than))",
    r"deadline",
    r"time.?sensitive",
    r"critical (that|we|this|deadline)",
    r"right away",
    r"(can'?t wait|no time|running out of time)",
]

ROUTINE_PATTERNS = [
    r"(follow.?up|follow up|check.?in|check in)",
    r"next steps",
    r"circle back",
    r"touch base",
    r"(schedule|set up) (a|another)? ?(call|meeting|sync|check.?in)",
    r"(reconnect|revisit|ping me|reach out) (next|in a|after)",
    r"(update me|let me know) (when|how|what)",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """Split transcript into sentence-like segments."""
    # Replace common separators with a split marker, then split.
    cleaned = text.replace("\n", ". ").replace("?", "? ").replace("!", "! ")
    parts = re.split(r'(?<=[.!?])\s+', cleaned)
    return [p.strip() for p in parts if p.strip()]


def _search_patterns(patterns, text_lower: str) -> list[tuple[str, str]]:
    """
    Search for pattern matches in text.  Returns a list of
    (matched_pattern_string, matched_text_snippet).
    """
    hits = []
    for pat in patterns:
        m = re.search(pat, text_lower)
        if m:
            hits.append((pat, m.group(0)))
    return hits


def _search_in_sentences(patterns, sentences: list[str]) -> list[tuple[str, str]]:
    """
    Search for pattern matches at the sentence level.
    Returns list of (pattern, sentence) so we have full context.
    """
    hits = []
    for sentence in sentences:
        s_lower = sentence.lower()
        for pat in patterns:
            if re.search(pat, s_lower):
                hits.append((pat, sentence))
    return hits


def _has_negation(sentence_lower: str, keyword: str) -> bool:
    """Check whether the keyword in the sentence is preceded by a negation."""
    negations = [
        r"not\b", r"no\b", r"never", r"don'?t", r"doesn'?t", r"isn'?t",
        r"aren'?t", r"wasn'?t", r"weren'?t", r"won'?t", r"wouldn'?t",
        r"haven'?t", r"hasn'?t", r"hadn'?t", r"without",
    ]
    # Look in a window before the keyword occurrence
    idx = sentence_lower.find(keyword)
    if idx == -1:
        return False
    window = sentence_lower[max(0, idx - 40):idx]
    for neg in negations:
        if re.search(neg, window):
            return True
    return False


def _extract_evidence(transcript: str, sentence: str, max_len: int = 220) -> str:
    """Return a clean evidence excerpt from the transcript."""
    if not sentence:
        return ""
    # Find the sentence in the transcript and include a bit of context
    t_lower = transcript.lower()
    s_lower = sentence.lower()
    idx = t_lower.find(s_lower[:60])  # match on first 60 chars
    if idx == -1:
        # Fallback: just return the sentence (trimmed)
        return sentence[:max_len].strip()
    start = max(0, idx - 10)
    end = min(len(transcript), idx + len(sentence) + 20)
    excerpt = transcript[start:end].strip()
    if len(excerpt) > max_len:
        excerpt = excerpt[:max_len].rsplit(" ", 1)[0] + "…"
    return excerpt


# ---------------------------------------------------------------------------
# Main routing function
# ---------------------------------------------------------------------------

def route_conversation(conv: dict) -> RoutingResult:
    """
    Analyze a conversation and return a RoutingResult.

    Parameters
    ----------
    conv : dict
        Must contain at least 'transcript'.  Also uses 'buying_intent'
        and 'sentiment' as auxiliary signals.
    """
    transcript = conv.get("transcript", "")
    buying_intent = (conv.get("buying_intent") or "").lower()
    sentiment = (conv.get("sentiment") or "").lower()

    sentences = _split_sentences(transcript)
    text_lower = transcript.lower()

    # ---- Score each category using sentence-level matching ---------------
    intent_hits = _search_in_sentences(INTENT_PATTERNS, sentences)
    pricing_hits = _search_in_sentences(PRICING_PATTERNS, sentences)
    competitor_hits = _search_in_sentences(COMPETITOR_PATTERNS, sentences)
    support_hits = _search_in_sentences(SUPPORT_PATTERNS, sentences)
    urgent_hits = _search_in_sentences(URGENT_PATTERNS, sentences)
    routine_hits = _search_in_sentences(ROUTINE_PATTERNS, sentences)

    # Remove negated hits (e.g., "not interested in pricing right now")
    def _filter_negated(hits, keyword_fragments):
        """Filter out hits where the keyword is negated in that sentence."""
        filtered = []
        for pat, sent in hits:
            s_lower = sent.lower()
            negated = False
            for kw in keyword_fragments:
                if kw in s_lower and _has_negation(s_lower, kw):
                    negated = True
                    break
            if not negated:
                filtered.append((pat, sent))
        return filtered

    pricing_hits = _filter_negated(pricing_hits, ["pricing", "price", "cost", "quote", "proposal"])
    competitor_hits = _filter_negated(competitor_hits, ["competitor", "switch", "comparing"])
    intent_hits = _filter_negated(intent_hits, ["ready", "sign", "proceed", "move forward", "commit"])

    # ---- Compute raw scores (count of distinct signal sentences) ---------
    scores = {
        "high_intent_sales": len(intent_hits),
        "pricing_proposal": len(pricing_hits),
        "competitor_risk": len(competitor_hits),
        "support_issue": len(support_hits),
        "urgent_follow_up": len(urgent_hits),
        "routine_follow_up": len(routine_hits),
    }

    # ---- Boost scores using auxiliary fields ------------------------------
    if buying_intent == "high":
        scores["high_intent_sales"] += 2
    elif buying_intent == "medium":
        scores["high_intent_sales"] += 1

    if sentiment == "negative":
        scores["support_issue"] += 1
        scores["competitor_risk"] += 1
    elif sentiment == "positive":
        scores["high_intent_sales"] += 1

    # ---- Determine the winning category ------------------------------------
    signals = {
        "intent_hits": len(intent_hits),
        "pricing_hits": len(pricing_hits),
        "competitor_hits": len(competitor_hits),
        "support_hits": len(support_hits),
        "urgent_hits": len(urgent_hits),
        "routine_hits": len(routine_hits),
        "buying_intent": buying_intent,
        "sentiment": sentiment,
    }

    max_score = max(scores.values()) if scores else 0

    if max_score == 0:
        # No signals at all
        return RoutingResult(
            category=CATEGORIES["routine_follow_up"],
            priority="low",
            reason="No strong routing signals detected in the transcript. Defaulting to routine follow-up.",
            evidence_excerpt=transcript[:200].strip() if transcript else "",
            next_action="Schedule a routine check-in with the contact.",
            confidence="Low",
            needs_review=True,
            signals=signals,
        )

    # Find all categories that tie for the max score
    top_categories = [k for k, v in scores.items() if v == max_score]

    # ---- Conflict detection ------------------------------------------------
    # If two or more strong categories tie, or if competitor + intent both
    # have strong signals, flag for human review.
    has_competitor_and_intent = (
        scores["competitor_risk"] >= 2 and scores["high_intent_sales"] >= 2
    )
    has_support_and_intent = (
        scores["support_issue"] >= 2 and scores["high_intent_sales"] >= 2
    )
    multiple_top = len(top_categories) > 1 and max_score >= 2

    if has_competitor_and_intent or has_support_and_intent or multiple_top:
        # Ambiguous / conflicting — needs human review
        evidence_sent = _best_evidence_sentence(
            intent_hits or competitor_hits or support_hits or pricing_hits
            or urgent_hits or routine_hits
        )
        evidence = _extract_evidence(transcript, evidence_sent) if evidence_sent else transcript[:200]
        return RoutingResult(
            category=CATEGORIES["needs_human_review"],
            priority="high",
            reason=(
                f"Conflicting signals detected: high-intent signals ({scores['high_intent_sales']}), "
                f"competitor signals ({scores['competitor_risk']}), "
                f"support signals ({scores['support_issue']}), "
                f"pricing signals ({scores['pricing_proposal']}). "
                f"Manual review recommended to resolve ambiguity."
            ),
            evidence_excerpt=evidence,
            next_action="Manager to review transcript and assign final routing category.",
            confidence="Low",
            needs_review=True,
            signals=signals,
        )

    winning_key = top_categories[0]

    # ---- Build the result for the winning category ------------------------
    return _build_result(winning_key, scores, transcript, sentences,
                         locals(), signals)


def _best_evidence_sentence(hits: list[tuple[str, str]]) -> str:
    """Return the first (most relevant) evidence sentence from hits."""
    if hits:
        return hits[0][1]
    return ""


def _build_result(key: str, scores: dict, transcript: str,
                  sentences: list[str], scope: dict, signals: dict) -> RoutingResult:
    """Build a RoutingResult for a single winning category."""

    # Map scope variable names to hit lists
    hit_map = {
        "high_intent_sales": scope["intent_hits"],
        "pricing_proposal": scope["pricing_hits"],
        "competitor_risk": scope["competitor_hits"],
        "support_issue": scope["support_hits"],
        "urgent_follow_up": scope["urgent_hits"],
        "routine_follow_up": scope["routine_hits"],
    }

    hits = hit_map.get(key, [])
    evidence_sent = _best_evidence_sentence(hits)
    evidence = _extract_evidence(transcript, evidence_sent) if evidence_sent else transcript[:200]
    score = scores[key]

    # Confidence based on signal strength
    if score >= 3:
        confidence = "High"
    elif score >= 2:
        confidence = "Medium"
    else:
        confidence = "Low"

    # Low-confidence single-signal results should be reviewed
    needs_review = confidence == "Low"

    builders = {
        "high_intent_sales": lambda: RoutingResult(
            category=CATEGORIES["high_intent_sales"],
            priority="high",
            reason=(
                f"Strong buying-intent signals detected ({score} signal(s)). "
                f"The contact expressed readiness to move forward or requested contract materials."
            ),
            evidence_excerpt=evidence,
            next_action="Prepare and send the contract or proposal. Notify the deal owner to follow up within 24 hours.",
            confidence=confidence,
            needs_review=needs_review,
            signals=signals,
        ),
        "pricing_proposal": lambda: RoutingResult(
            category=CATEGORIES["pricing_proposal"],
            priority="medium" if score >= 2 else "low",
            reason=(
                f"Contact requested pricing, quote, or proposal information ({score} signal(s)). "
                f"This indicates active evaluation but not necessarily commitment."
            ),
            evidence_excerpt=evidence,
            next_action="Send the pricing sheet or proposal within 2 business days. Schedule a follow-up call to discuss.",
            confidence=confidence,
            needs_review=needs_review,
            signals=signals,
        ),
        "competitor_risk": lambda: RoutingResult(
            category=CATEGORIES["competitor_risk"],
            priority="high",
            reason=(
                f"Competitor mentions or switching signals detected ({score} signal(s)). "
                f"The contact is evaluating alternatives or comparing vendors."
            ),
            evidence_excerpt=evidence,
            next_action="Escalate to the deal owner immediately. Prepare a competitive differentiation deck within 48 hours.",
            confidence=confidence,
            needs_review=needs_review,
            signals=signals,
        ),
        "support_issue": lambda: RoutingResult(
            category=CATEGORIES["support_issue"],
            priority="high" if score >= 2 else "medium",
            reason=(
                f"Customer support issue or complaint detected ({score} signal(s)). "
                f"The contact reported problems, errors, or dissatisfaction."
            ),
            evidence_excerpt=evidence,
            next_action="Route to the customer support team. Acknowledge within 4 hours and provide a resolution timeline.",
            confidence=confidence,
            needs_review=needs_review,
            signals=signals,
        ),
        "urgent_follow_up": lambda: RoutingResult(
            category=CATEGORIES["urgent_follow_up"],
            priority="high",
            reason=(
                f"Urgent or time-sensitive signals detected ({score} signal(s)). "
                f"The contact expressed a deadline or urgency."
            ),
            evidence_excerpt=evidence,
            next_action="Contact the customer today. Confirm timeline and set expectations for delivery.",
            confidence=confidence,
            needs_review=needs_review,
            signals=signals,
        ),
        "routine_follow_up": lambda: RoutingResult(
            category=CATEGORIES["routine_follow_up"],
            priority="low",
            reason=(
                f"Standard follow-up signals detected ({score} signal(s)). "
                f"No urgency or strong buying intent signals were found."
            ),
            evidence_excerpt=evidence,
            next_action="Schedule a routine check-in within 1-2 weeks. Add to the standard follow-up cadence.",
            confidence=confidence,
            needs_review=needs_review,
            signals=signals,
        ),
    }

    return builders[key]()


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def route_to_dict(result: RoutingResult) -> dict:
    """Convert a RoutingResult to a plain dict for storage."""
    return {
        "auto_routing_category": result.category,
        "auto_routing_reason": result.reason,
        "auto_priority": result.priority,
        "auto_evidence_excerpt": result.evidence_excerpt,
        "auto_next_action": result.next_action,
        "auto_confidence": result.confidence,
        "needs_review": 1 if result.needs_review else 0,
        "routing_category": result.category,
        "routing_reason": result.reason,
        "priority": result.priority,
        "evidence_excerpt": result.evidence_excerpt,
        "next_action": result.next_action,
    }
