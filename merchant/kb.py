"""
Knowledge-base retrieval.

Keyword + page scoring over `merchant/knowledge/kb.json`. No embeddings and no
vector store: the corpus is ~30 curated cards, so lexical scoring is both
sufficient and — more importantly — reproducible, which the evaluation harness
depends on.

Every entry carries an official source URL and a last-reviewed date. If nothing
scores above the floor, retrieval returns nothing and the caller must say "I
don't know" rather than improvise.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from merchant.models import DashboardPage, Intent, KnowledgeEntry, Language

KB_PATH = Path(__file__).resolve().parent / "knowledge" / "kb.json"

# Minimum score for an entry to be considered relevant at all.
RELEVANCE_FLOOR = 1.0

_TOKEN = re.compile(r"[a-z0-9]+|[ऀ-ॿ]+")

# Which KB topics answer which intent, when the utterance itself is vague.
_INTENT_TOPICS: dict[Intent, tuple[str, ...]] = {
    Intent.EXPLAIN_SETTLEMENT: ("settlements", "settlement_timelines", "fees", "tax"),
    Intent.SHOW_FAILED_PAYMENTS: ("failed_payments", "payment_status"),
    Intent.EXPLAIN_FAILED_PAYMENT: ("failed_payments", "payment_status"),
    Intent.CREATE_PAYMENT_LINK_TUTORIAL: ("payment_links",),
    Intent.REFUND_TUTORIAL: ("refunds",),
    Intent.EXPLAIN_FEES: ("fees", "tax", "settlements"),
    Intent.EXPLAIN_REPORT: ("reports", "settlements"),
    Intent.EXPLAIN_SCREEN: (),
    Intent.EXPLAIN_TERM: (),
}


@lru_cache(maxsize=1)
def _load(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else KB_PATH
    if not p.exists():
        return {"version": "0", "entries": []}
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def all_entries() -> list[KnowledgeEntry]:
    raw = _load()
    out: list[KnowledgeEntry] = []
    for e in raw.get("entries", []):
        try:
            out.append(KnowledgeEntry(
                id=str(e["id"]),
                topic=str(e["topic"]),
                title=str(e["title"]),
                simple_en=str(e["simple_en"]),
                simple_hi=str(e.get("simple_hi", "")),
                simple_hinglish=str(e.get("simple_hinglish", "")),
                source_url=str(e.get("source_url", "")),
                last_reviewed=str(e.get("last_reviewed", "")),
                pages=list(e.get("pages", [])),
                keywords=[str(k).lower() for k in e.get("keywords", [])],
                verified=bool(e.get("verified", True)),
            ))
        except KeyError:
            # A malformed card is skipped rather than crashing retrieval.
            continue
    return out


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def score_entry(
    entry: KnowledgeEntry,
    query_tokens: set[str],
    page: DashboardPage,
    topics: tuple[str, ...],
    topic_hint: str,
) -> float:
    score = 0.0

    for kw in entry.keywords:
        kw_tokens = _tokens(kw)
        if not kw_tokens:
            continue
        if kw_tokens <= query_tokens:
            # Multi-word keywords are stronger evidence than single words.
            score += 2.0 if len(kw_tokens) > 1 else 1.0

    title_overlap = _tokens(entry.title) & query_tokens
    score += 0.5 * len(title_overlap)

    if topic_hint and entry.topic == topic_hint:
        score += 2.0
    if topics and entry.topic in topics:
        score += 1.5
    if page is not DashboardPage.UNKNOWN and page.value in entry.pages:
        score += 1.0
    if not entry.verified:
        # Prefer verified cards when both would otherwise tie.
        score -= 0.25

    return score


def retrieve(
    query: str,
    page: DashboardPage = DashboardPage.UNKNOWN,
    intent: Intent = Intent.UNKNOWN,
    topic_hint: str = "",
    limit: int = 3,
    min_score: float | None = None,
) -> list[KnowledgeEntry]:
    """Return the most relevant knowledge cards, best first. May be empty.

    `min_score` raises the bar above `RELEVANCE_FLOOR` for callers that would
    rather answer "I don't know" than surface a weak match.
    """
    entries = all_entries()
    if not entries:
        return []

    query_tokens = _tokens(query)
    topics = _INTENT_TOPICS.get(intent, ())

    scored = [
        (score_entry(e, query_tokens, page, topics, topic_hint), e)
        for e in entries
    ]
    floor = RELEVANCE_FLOOR if min_score is None else max(RELEVANCE_FLOOR, min_score)
    scored = [(s, e) for s, e in scored if s >= floor]
    scored.sort(key=lambda se: (-se[0], se[1].id))
    return [e for _, e in scored[:limit]]


def get(entry_id: str) -> Optional[KnowledgeEntry]:
    for e in all_entries():
        if e.id == entry_id:
            return e
    return None


def by_topic(topic: str) -> list[KnowledgeEntry]:
    return [e for e in all_entries() if e.topic == topic]


def source_urls(entries: list[KnowledgeEntry]) -> list[str]:
    """De-duplicated source URLs, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for e in entries:
        if e.source_url and e.source_url not in seen:
            seen.add(e.source_url)
            out.append(e.source_url)
    return out


def render(entries: list[KnowledgeEntry], language: Language, limit: int = 2) -> str:
    """Join the top entries into a short explanation in the merchant's language."""
    return " ".join(e.text_for(language) for e in entries[:limit]).strip()


def unverified_notice(entries: list[KnowledgeEntry], language: Language) -> str:
    """Caveat text when any cited card is not backed by a verified source."""
    if not any(not e.verified for e in entries):
        return ""
    if language is Language.HINDI:
        return "यह जानकारी आधिकारिक रूप से सत्यापित नहीं है — कृपया अपने डैशबोर्ड पर जाँच लें।"
    if language is Language.HINGLISH:
        return "Ye jaankari officially verify nahi hui hai — apne dashboard par check kar lijiye."
    return "This detail is not officially verified — please check it in your own dashboard."
