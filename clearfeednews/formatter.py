"""Digest message formatting for Clear Feed News."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from config import CATEGORIES

# Telegram message limit
MAX_MSG_LEN = 4096


def _source_domain(url: str) -> str:
    """Extract a short domain from a URL."""
    parsed = urlparse(url)
    return parsed.netloc.removeprefix("www.")


def _clean_summary(raw: str) -> str:
    """Strip HTML tags and trim to a single short sentence."""
    text = re.sub(r"<[^>]+>", "", raw).strip()
    text = re.sub(r"\s+", " ", text)
    # Take first sentence, cap at 120 chars
    match = re.match(r"(.+?[.!?])\s", text)
    if match and len(match.group(1)) <= 120:
        return match.group(1)
    if len(text) > 120:
        return text[:117].rsplit(" ", 1)[0] + "..."
    return text


def format_digest(
    articles_by_cat: dict[str, list[dict[str, Any]]],
    has_more_by_cat: dict[str, bool] | None = None,
) -> list[str]:
    """Build digest message(s) grouped by category.

    *has_more_by_cat* maps category name -> True when there are additional
    unseen articles beyond the ones shown.  When True, a hint line is
    appended after that category's articles.

    Returns a list of strings, each within Telegram's 4096-char limit.
    """
    if not articles_by_cat:
        return ["No new articles to show right now. Check back later!"]

    if has_more_by_cat is None:
        has_more_by_cat = {}

    header = "\u2600\ufe0f *Your Clear Feed News Digest*\n"
    sections: list[str] = []

    for cat, articles in articles_by_cat.items():
        emoji = CATEGORIES.get(cat, "\U0001f4f0")
        lines = [f"\n*{emoji} {cat}*\n"]
        for a in articles:
            title = a["title"].replace("[", "\\[").replace("]", "\\]")
            domain = _source_domain(a.get("url", ""))

            # Trending fire or bullet prefix
            prefix = "\U0001f525" if a.get("trending_score", 0) > 70 else "\u2022"

            # Build summary line if available
            summary_text = ""
            raw_summary = a.get("summary", "")
            if raw_summary:
                cleaned = _clean_summary(raw_summary)
                if cleaned and cleaned.lower() != title.lower():
                    summary_text = f"{cleaned} - _{domain}_"

            if summary_text:
                lines.append(f"{prefix} [{title}]({a['url']})\n{summary_text}\n")
            else:
                lines.append(f"{prefix} [{title}]({a['url']})\n_{domain}_\n")

        sections.append("\n".join(lines))

    separator = "\n========================\n"
    footer_line = "\n_Clear Feed News \u00b7 Calm, non-outrage curation_\n/more"

    # Assemble, splitting if needed
    messages: list[str] = []
    current = header

    for i, section in enumerate(sections):
        chunk = section
        if i < len(sections) - 1:
            chunk += separator
        if len(current) + len(chunk) + len(footer_line) + 2 > MAX_MSG_LEN:
            messages.append(current)
            current = ""
        current += chunk

    current += "\n" + footer_line
    messages.append(current)
    return messages


def format_category_more(
    category: str,
    articles: list[dict[str, Any]],
    has_more: bool,
    include_header: bool = False,
    include_footer: bool = False,
) -> str:
    """Format a single-category message.

    *include_header* prepends the digest header line.
    *include_footer* appends the footer tagline.
    """
    parts: list[str] = []

    if include_header:
        parts.append("\u2600\ufe0f *Your Clear Feed News Digest*\n")

    emoji = CATEGORIES.get(category, "\U0001f4f0")
    lines = [f"*{emoji} {category}*\n"]

    for a in articles:
        title = a["title"].replace("[", "\\[").replace("]", "\\]")
        domain = _source_domain(a.get("url", ""))
        prefix = "\U0001f525" if a.get("trending_score", 0) > 70 else "\u2022"

        summary_text = ""
        raw_summary = a.get("summary", "")
        if raw_summary:
            cleaned = _clean_summary(raw_summary)
            if cleaned and cleaned.lower() != title.lower():
                summary_text = f"{cleaned} - _{domain}_"

        if summary_text:
            lines.append(f"{prefix} [{title}]({a['url']})\n{summary_text}\n")
        else:
            lines.append(f"{prefix} [{title}]({a['url']})\n_{domain}_\n")

    parts.append("\n".join(lines))

    if include_footer:
        parts.append(
            "\n_Clear Feed News \u00b7 Calm, non-outrage curation_"
        )

    return "\n".join(parts)
