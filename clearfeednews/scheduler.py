"""APScheduler setup for periodic fetching and digest delivery."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from config import CATEGORIES, FETCH_INTERVAL_HOURS, MAX_ARTICLES_PER_CATEGORY
from database import count_unseen_articles, get_active_users, get_unseen_articles, get_user_categories, mark_articles_sent
from fetcher import fetch_all_feeds
from formatter import format_category_more

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Reference to the bot instance — set by bot.py at startup.
_bot: Bot | None = None


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
async def job_fetch_feeds() -> None:
    """Periodic RSS fetch job."""
    try:
        count = await fetch_all_feeds()
        logger.info("Scheduled fetch complete — %d new articles", count)
    except Exception:
        logger.exception("Error in scheduled feed fetch")


async def job_send_digests() -> None:
    """Check all active users and send digests to those whose digest time matches now."""
    if _bot is None:
        logger.warning("Bot reference not set — skipping digest delivery")
        return

    try:
        users = await get_active_users()
        now_utc = datetime.now(timezone.utc)

        for user in users:
            try:
                offset_raw = user.get("timezone_offset")
                offset = offset_raw if offset_raw is not None else 0
                user_time = now_utc + timedelta(hours=offset)
                user_hhmm = user_time.strftime("%H:%M")

                digest_times_str = user.get("digest_times", "09:00,18:00")
                digest_times = [t.strip() for t in digest_times_str.split(",")]

                if user_hhmm not in digest_times:
                    continue

                user_id = user["user_id"]
                categories = await get_user_categories(user_id)
                if not categories:
                    continue

                articles_by_cat = await get_unseen_articles(
                    user_id, categories, MAX_ARTICLES_PER_CATEGORY
                )
                if not articles_by_cat:
                    continue

                # Collect article IDs and mark sent before counting remaining
                sent_ids: list[int] = []
                for arts in articles_by_cat.values():
                    sent_ids.extend(a["id"] for a in arts)
                await mark_articles_sent(user_id, sent_ids)

                # Send each category as its own message
                cat_keys = list(articles_by_cat.keys())
                for i, cat in enumerate(cat_keys):
                    arts = articles_by_cat[cat]
                    is_first = i == 0
                    is_last = i == len(cat_keys) - 1

                    remaining = await count_unseen_articles(user_id, cat)
                    has_more = remaining > 0

                    text = format_category_more(
                        cat, arts, has_more,
                        include_header=is_first,
                        include_footer=is_last,
                    )

                    reply_markup = None
                    if has_more:
                        emoji = CATEGORIES.get(cat, "")
                        reply_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                f"{emoji} More {cat} \u2192",
                                callback_data=f"morecat:{cat}",
                            )]
                        ])

                    await _bot.send_message(
                        chat_id=user_id,
                        text=text,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                        reply_markup=reply_markup,
                    )
                    await asyncio.sleep(0.05)

                logger.info("Digest sent to user %d (%d articles)", user_id, len(sent_ids))

                # Stagger between users
                await asyncio.sleep(0.1)

            except Exception:
                logger.exception("Failed to send digest to user %s", user.get("user_id"))

    except Exception:
        logger.exception("Error in digest delivery job")


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------
def start_scheduler() -> None:
    """Register jobs and start the scheduler."""
    # Fetch feeds every N hours
    scheduler.add_job(
        job_fetch_feeds,
        "interval",
        hours=FETCH_INTERVAL_HOURS,
        id="fetch_feeds",
        replace_existing=True,
    )

    # Check for digest delivery every minute
    scheduler.add_job(
        job_send_digests,
        "cron",
        minute="0",
        id="send_digests",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started — fetching every %dh, digest check every hour",
        FETCH_INTERVAL_HOURS,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
