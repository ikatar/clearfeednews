"""RSS feed fetcher with deduplication and filtering."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import feedparser

from config import FEEDS, USE_TRENDING
from database import insert_articles
from filters import filter_articles, is_source_blocked
from trending import fetch_trending_topics, score_articles

logger = logging.getLogger(__name__)

# feedparser is synchronous — run it in a thread pool.
_executor = ThreadPoolExecutor(max_workers=8)


def _parse_feed(url: str) -> feedparser.FeedParserDict:
    """Parse a single RSS feed URL (blocking)."""
    return feedparser.parse(url)


def _extract_source(url: str, feed_title: str | None = None) -> str:
    """Derive a human-readable source name."""
    if feed_title:
        return feed_title
    parsed = urlparse(url)
    return parsed.netloc.removeprefix("www.")


def _entry_to_article(
    entry: Any, category: str, source_name: str
) -> dict[str, Any] | None:
    """Convert a feedparser entry to our article dict, or None if unusable."""
    title = entry.get("title", "").strip()
    link = entry.get("link", "").strip()
    if not title or not link:
        return None

    summary = ""
    if entry.get("summary"):
        summary = entry["summary"][:500]

    published_at = None
    if entry.get("published_parsed"):
        try:
            published_at = datetime(*entry["published_parsed"][:6], tzinfo=timezone.utc).isoformat()
        except Exception:
            pass

    return {
        "title": title,
        "url": link,
        "source_name": source_name,
        "category": category,
        "summary": summary,
        "published_at": published_at,
    }


async def fetch_all_feeds() -> int:
    """Fetch every configured feed, filter, and store new articles.

    Returns the total number of newly inserted articles.
    """
    loop = asyncio.get_running_loop()
    total_inserted = 0

    # Fetch trending topics once for the entire cycle
    trending: list[str] = []
    if USE_TRENDING:
        trending = await fetch_trending_topics()

    for category, urls in FEEDS.items():
        raw_articles: list[dict[str, Any]] = []

        # Fetch all feeds for this category concurrently.
        tasks = []
        valid_urls: list[str] = []
        for url in urls:
            if is_source_blocked(url):
                logger.debug("Skipping blocked source: %s", url)
                continue
            valid_urls.append(url)
            tasks.append(loop.run_in_executor(_executor, _parse_feed, url))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for url, result in zip(valid_urls, results):
            if isinstance(result, Exception):
                logger.warning("Failed to fetch %s: %s", url, result)
                continue

            feed: feedparser.FeedParserDict = result
            if feed.bozo and not feed.entries:
                logger.warning("Empty/malformed feed %s: %s", url, feed.bozo_exception)
                continue
            if feed.bozo:
                logger.debug("Feed %s has bozo flag but %d entries — using them", url, len(feed.entries))

            source_name = _extract_source(url, feed.feed.get("title"))
            for entry in feed.entries:
                article = _entry_to_article(entry, category, source_name)
                if article:
                    raw_articles.append(article)

        # Run sentiment / keyword filter
        filtered = filter_articles(raw_articles)

        # Score articles against trending topics
        if trending:
            score_articles(filtered, trending)

        # Store in database (deduplication handled by UNIQUE url constraint)
        inserted = await insert_articles(filtered)
        total_inserted += inserted
        logger.info(
            "Category [%s]: fetched %d, filtered %d, inserted %d new",
            category,
            len(raw_articles),
            len(filtered),
            inserted,
        )

    logger.info("Fetch complete — %d new articles total", total_inserted)
    return total_inserted
