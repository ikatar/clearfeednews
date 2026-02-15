"""Sentiment filtering for Clear Feed News articles.

Layer 1: keyword blocklist (always active)
Layer 2: Claude Haiku classification (optional, toggled via config)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from config import GLOBAL_BLOCK_KEYWORDS, BLOCKED_SOURCES, USE_CLAUDE_FILTERING

logger = logging.getLogger(__name__)

# Pre-compile a single regex from the global blocklist for speed.
_block_pattern: re.Pattern[str] | None = None


def _get_block_pattern() -> re.Pattern[str]:
    global _block_pattern
    if _block_pattern is None:
        escaped = [re.escape(kw) for kw in GLOBAL_BLOCK_KEYWORDS]
        _block_pattern = re.compile("|".join(escaped), re.IGNORECASE)
    return _block_pattern


def is_source_blocked(url: str) -> bool:
    """Return True if the feed URL belongs to a globally blocked source."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in BLOCKED_SOURCES)


def passes_keyword_filter(title: str, summary: str | None = None) -> bool:
    """Return True if the text does NOT contain any blocked keywords."""
    text = title
    if summary:
        text = f"{title} {summary}"
    return _get_block_pattern().search(text) is None


def filter_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run all active filter layers and return only passing articles."""
    passed: list[dict[str, Any]] = []
    for article in articles:
        title = article.get("title", "")
        summary = article.get("summary", "")

        # Layer 1 - keyword blocklist
        if not passes_keyword_filter(title, summary):
            logger.debug("Blocked by keyword filter: %s", title[:80])
            continue

        article["sentiment_label"] = "neutral"
        passed.append(article)

    logger.info(
        "Filter: %d/%d articles passed keyword filter",
        len(passed),
        len(articles),
    )
    return passed
