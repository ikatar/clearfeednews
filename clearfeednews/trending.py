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
# Stopwords — lightweight set, no NLTK download required
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
    """Blocking call to trendspy — run in executor."""
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
# Scoring
# ---------------------------------------------------------------------------
def compute_trending_score(
    keywords: list[str], trending: list[str]
) -> float:
    """Score keyword overlap against trending topics.

    Returns a value 0–100.  Higher-ranked trends (earlier in list) carry
    more weight.
    """
    if not keywords or not trending:
        return 0.0

    total_topics = len(trending)
    raw_score = 0.0

    for kw in keywords:
        for rank, topic in enumerate(trending):
            # Position weight: top-ranked trends score higher
            position_weight = 1.0 - (rank / total_topics)

            # Check if keyword appears as substring in topic
            if kw in topic:
                raw_score += position_weight * 1.0
                break  # one match per keyword is enough

            # Fuzzy match for close-but-not-exact matches
            # Check against individual words in the topic
            for topic_word in topic.split():
                similarity = SequenceMatcher(None, kw, topic_word).ratio()
                if similarity > 0.6:
                    raw_score += position_weight * similarity
                    break
            else:
                continue
            break  # matched via fuzzy — move to next keyword

    # Normalise to 0–100
    max_possible = len(keywords)  # perfect score = 1 match per keyword
    if max_possible == 0:
        return 0.0
    score = min((raw_score / max_possible) * 100, 100.0)
    return round(score, 1)


def score_articles(
    articles: list[dict[str, Any]], trending: list[str]
) -> None:
    """Compute and attach trending_score to each article dict in-place."""
    for article in articles:
        keywords = extract_keywords(article.get("title", ""))
        article["trending_score"] = compute_trending_score(keywords, trending)
