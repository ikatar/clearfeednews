"""Google Trends scoring for Clear Feed News articles.

Fetches trending topics once per cycle, then scores each article headline
by fuzzy-matching its keywords against the trending list.
"""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2)

# ---------------------------------------------------------------------------
# Stopwords - lightweight set, no NLTK download required
# ---------------------------------------------------------------------------
_STOPWORDS: set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "need", "must",
    "it", "its", "this", "that", "these", "those", "i", "we", "you",
    "he", "she", "they", "me", "him", "her", "us", "them", "my", "your",
    "his", "our", "their", "what", "which", "who", "whom", "how", "when",
    "where", "why", "not", "no", "nor", "so", "if", "then", "than",
    "too", "very", "just", "about", "above", "after", "again", "all",
    "also", "any", "because", "before", "between", "both", "each",
    "few", "more", "most", "other", "over", "same", "some", "such",
    "into", "through", "during", "out", "up", "down", "off", "only",
    "own", "here", "there", "while", "new", "first", "last", "says",
    "said", "according", "now", "get", "gets", "got", "make", "makes",
    "made", "going", "goes", "see", "look", "like", "come", "take",
    "still", "well", "back", "even", "want", "give", "day", "way",
}

_WORD_RE = re.compile(r"[a-zA-Z]{2,}")


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------
def extract_keywords(title: str) -> list[str]:
    """Tokenise a headline and return significant words."""
    words = _WORD_RE.findall(title.lower())
    return [w for w in words if w not in _STOPWORDS]


# ---------------------------------------------------------------------------
# Trending topic fetching
# ---------------------------------------------------------------------------
def _fetch_trending_sync() -> list[str]:
    """Blocking call to trendspy - run in executor."""
    try:
        from trendspy import Trends

        tr = Trends()
        data = tr.trending_now(geo="US")
        # data is a list of TrendingTopic objects or strings
        topics: list[str] = []
        for item in data:
            topics.append(str(item).lower())
        logger.info("Trending: fetched %d topics", len(topics))
        return topics
    except Exception:
        logger.warning("Failed to fetch trending topics", exc_info=True)
        return []


async def fetch_trending_topics() -> list[str]:
    """Fetch currently trending Google topics (async wrapper)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _fetch_trending_sync)


# ---------------------------------------------------------------------------
# Pre-processed trending index (built once per fetch cycle)
# ---------------------------------------------------------------------------
class _TrendingIndex:
    """Pre-processed lookup structure for fast keyword → trending score."""

    __slots__ = ("exact_words", "topic_entries")

    def __init__(self, trending: list[str]) -> None:
        total = len(trending)
        # Map each unique word → best position weight
        self.exact_words: dict[str, float] = {}
        # Flat list of (word, position_weight) for fuzzy fallback
        self.topic_entries: list[tuple[str, float]] = []

        seen_words: set[str] = set()
        for rank, topic in enumerate(trending):
            weight = 1.0 - (rank / total)
            for word in topic.split():
                # Exact lookup: keep the best (highest) weight per word
                if word not in self.exact_words or self.exact_words[word] < weight:
                    self.exact_words[word] = weight
                # Flat list for fuzzy (deduplicated)
                if word not in seen_words:
                    seen_words.add(word)
                    self.topic_entries.append((word, weight))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def compute_trending_score(
    keywords: list[str], index: _TrendingIndex
) -> float:
    """Score keyword overlap against trending topics.

    Returns a value 0–100.  Higher-ranked trends (earlier in list) carry
    more weight.
    """
    if not keywords or not index.exact_words:
        return 0.0

    raw_score = 0.0

    for kw in keywords:
        # Fast path: exact word match (O(1) dict lookup)
        if kw in index.exact_words:
            raw_score += index.exact_words[kw]
            continue

        # Slow path: fuzzy match against unique topic words
        best = 0.0
        for topic_word, weight in index.topic_entries:
            # Quick length check - SequenceMatcher can't exceed 0.6
            # if lengths differ by more than 2.5x
            if len(kw) > 2 * len(topic_word) or len(topic_word) > 2 * len(kw):
                continue
            similarity = SequenceMatcher(None, kw, topic_word).ratio()
            if similarity > 0.6 and weight * similarity > best:
                best = weight * similarity
        raw_score += best

    # Normalise to 0–100
    max_possible = len(keywords)
    score = min((raw_score / max_possible) * 100, 100.0)
    return round(score, 1)


def score_articles(
    articles: list[dict[str, Any]], trending: list[str]
) -> None:
    """Compute and attach trending_score to each article dict in-place."""
    index = _TrendingIndex(trending)
    for article in articles:
        keywords = extract_keywords(article.get("title", ""))
        article["trending_score"] = compute_trending_score(keywords, index)
