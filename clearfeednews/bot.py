"""Clear Feed News — main entry point.

Supports two modes (set via BOT_MODE env var):
  polling  — local development / Oracle VM
  webhook  — Render or other PaaS
"""

from __future__ import annotations

import asyncio
import logging
import sys

from telegram.ext import Application

from config import BOT_MODE, BOT_TOKEN, PORT, WEBHOOK_URL
from database import init_db
from fetcher import fetch_all_feeds
from handlers import register_handlers
from scheduler import set_bot, start_scheduler, stop_scheduler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Post-init hook (runs after Application.initialize)
# ---------------------------------------------------------------------------
async def post_init(app: Application) -> None:
    """Initialise DB, run first fetch, and start the scheduler."""
    await init_db()
    logger.info("Running initial feed fetch...")
    try:
        count = await fetch_all_feeds()
        logger.info("Initial fetch complete — %d new articles", count)
    except Exception:
        logger.exception("Initial fetch failed — bot will retry on schedule")
    set_bot(app.bot)
    start_scheduler()


async def post_shutdown(app: Application) -> None:
    stop_scheduler()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN is not set. Export it as an environment variable.")
        sys.exit(1)

    # Python 3.12+ no longer auto-creates an event loop — ensure one exists.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    builder = Application.builder().token(BOT_TOKEN)
    builder.post_init(post_init)
    builder.post_shutdown(post_shutdown)
    app = builder.build()

    register_handlers(app)

    mode = BOT_MODE.lower()
    if mode == "webhook":
        if not WEBHOOK_URL:
            logger.critical("WEBHOOK_URL must be set in webhook mode.")
            sys.exit(1)
        logger.info("Starting in WEBHOOK mode on port %d", PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
        )
    else:
        logger.info("Starting in POLLING mode")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
