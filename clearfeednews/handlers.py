"""Telegram command handlers for Clear Feed News."""

from __future__ import annotations

import logging
import time
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from urllib.parse import urlparse

from config import CATEGORIES, COMMAND_COOLDOWN_SECONDS, FEEDS, MAX_ARTICLES_PER_CATEGORY
from database import (
    add_block,
    count_unseen_articles,
    get_unseen_articles,
    get_user,
    get_user_blocks,
    get_user_categories,
    mark_articles_sent,
    remove_all_blocks,
    remove_block,
    reset_user,
    set_user_active,
    set_user_digest_times,
    set_user_timezone,
    toggle_user_category,
    upsert_user,
)
import asyncio

from formatter import format_category_more, format_digest

logger = logging.getLogger(__name__)

# Simple per-user rate limiting
_last_command: dict[int, float] = {}


def _rate_limited(user_id: int) -> bool:
    now = time.monotonic()
    last = _last_command.get(user_id, 0)
    if now - last < COMMAND_COOLDOWN_SECONDS:
        return True
    _last_command[user_id] = now
    return False


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    await upsert_user(user.id, user.username)

    welcome = (
        f"Hi {user.first_name}! Welcome to *Clear Feed News* \u2600\ufe0f\n\n"
        "I deliver curated *positive & educational* news "
        "straight to your chat - no doom-scrolling required.\n\n"
        "*Here\u2019s how to get started:*\n"
        "1\ufe0f\u20e3 Pick your categories with /categories\n"
        "2\ufe0f\u20e3 Set your timezone and delivery schedule\n"
        "3\ufe0f\u20e3 Get your first digest now with /more\n\n"
        "Type /help to see all commands."
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")

    # Immediately show category picker
    await _send_category_keyboard(update, context)


# ---------------------------------------------------------------------------
# /categories
# ---------------------------------------------------------------------------
async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or _rate_limited(user.id):
        return
    await upsert_user(user.id, user.username)
    await _send_category_keyboard(update, context)


async def _send_category_keyboard(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    if not user:
        return
    subscribed = await get_user_categories(user.id)

    buttons: list[list[InlineKeyboardButton]] = []
    for cat, emoji in CATEGORIES.items():
        check = "\u2705 " if cat in subscribed else ""
        buttons.append(
            [InlineKeyboardButton(f"{check}{emoji} {cat}", callback_data=f"cat:{cat}")]
        )

    buttons.append([InlineKeyboardButton("\u2705 Done", callback_data="cat:done")])
    reply_markup = InlineKeyboardMarkup(buttons)

    text = (
        "*Select your categories*\n"
        "Tap to toggle. Tap *Done* when finished."
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode="Markdown"
        )


async def callback_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    user = update.effective_user
    if not user:
        return

    data = query.data.removeprefix("cat:")

    if data == "done":
        cats = await get_user_categories(user.id)
        if cats:
            cat_list = ", ".join(cats)
            await query.edit_message_text(
                f"You\u2019re subscribed to: *{cat_list}*\n\n"
                "Use /more to get articles now, or wait for your scheduled digest.",
                parse_mode="Markdown",
            )
            # If timezone has never been set, prompt them
            db_user = await get_user(user.id)
            if db_user and db_user.get("timezone_offset") is None:
                context.user_data["onboarding"] = True
                await _send_timezone_keyboard(query.message.chat_id, context)
        else:
            await query.edit_message_text(
                "You haven\u2019t selected any categories yet.\n"
                "Use /categories to pick some."
            )
        return

    await toggle_user_category(user.id, data)
    # Refresh the keyboard
    await _send_category_keyboard(update, context)


# ---------------------------------------------------------------------------
# /timezone
# ---------------------------------------------------------------------------
_TIMEZONE_OPTIONS = [
    (-12, "UTC-12 (Baker Island)"),
    (-10, "UTC-10 (Hawaii)"),
    (-9, "UTC-9 (Alaska)"),
    (-8, "UTC-8 (Los Angeles)"),
    (-7, "UTC-7 (Denver)"),
    (-6, "UTC-6 (Chicago)"),
    (-5, "UTC-5 (New York)"),
    (-4, "UTC-4 (Santiago)"),
    (-3, "UTC-3 (Buenos Aires)"),
    (-2, "UTC-2 (South Georgia)"),
    (-1, "UTC-1 (Azores)"),
    (0, "UTC+0 (London)"),
    (1, "UTC+1 (Paris)"),
    (2, "UTC+2 (Cairo)"),
    (3, "UTC+3 (Istanbul)"),
    (4, "UTC+4 (Dubai)"),
    (5, "UTC+5 (Karachi)"),
    (5, "UTC+5:30 (India)"),
    (6, "UTC+6 (Dhaka)"),
    (7, "UTC+7 (Bangkok)"),
    (8, "UTC+8 (Singapore)"),
    (9, "UTC+9 (Tokyo)"),
    (10, "UTC+10 (Sydney)"),
    (12, "UTC+12 (Auckland)"),
]


async def _send_timezone_keyboard(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send timezone picker as a new message."""
    buttons: list[list[InlineKeyboardButton]] = []
    for offset, label in _TIMEZONE_OPTIONS:
        buttons.append(
            [InlineKeyboardButton(label, callback_data=f"tz:{offset}")]
        )

    await context.bot.send_message(
        chat_id=chat_id,
        text="*Set your timezone*\nThis ensures digests arrive at the right local time.",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def cmd_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or _rate_limited(user.id):
        return

    # If they passed an offset directly: /timezone -5
    if context.args:
        try:
            offset = int(context.args[0])
            if not -12 <= offset <= 14:
                raise ValueError
            await set_user_timezone(user.id, offset)
            sign = "+" if offset >= 0 else ""
            await update.message.reply_text(
                f"Timezone set to *UTC{sign}{offset}*", parse_mode="Markdown"
            )
            return
        except (ValueError, IndexError):
            await update.message.reply_text(
                "Usage: `/timezone -5` or tap a button below.",
                parse_mode="Markdown",
            )

    await _send_timezone_keyboard(update.effective_chat.id, context)


async def callback_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    user = update.effective_user
    if not user:
        return

    offset = int(query.data.removeprefix("tz:"))
    await set_user_timezone(user.id, offset)
    sign = "+" if offset >= 0 else ""
    await query.edit_message_text(
        f"Timezone set to *UTC{sign}{offset}*",
        parse_mode="Markdown",
    )

    # During onboarding, chain into schedule picker
    if context.user_data.pop("onboarding", False):
        await _send_schedule_morning_keyboard(query.message.chat_id, context)


# ---------------------------------------------------------------------------
# /schedule - pick delivery times
# ---------------------------------------------------------------------------
_MORNING_OPTIONS = [
    ("06:00", "6:00 AM"),
    ("07:00", "7:00 AM"),
    ("08:00", "8:00 AM"),
    ("09:00", "9:00 AM"),
]

_EVENING_OPTIONS = [
    ("17:00", "5:00 PM"),
    ("18:00", "6:00 PM"),
    ("19:00", "7:00 PM"),
    ("20:00", "8:00 PM"),
    ("none", "No evening digest"),
]


async def _send_schedule_morning_keyboard(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"sched_am:{value}")]
        for value, label in _MORNING_OPTIONS
    ]
    await context.bot.send_message(
        chat_id=chat_id,
        text="*Pick your morning digest time*",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def _send_schedule_evening_keyboard(
    query, context: ContextTypes.DEFAULT_TYPE
) -> None:
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"sched_pm:{value}")]
        for value, label in _EVENING_OPTIONS
    ]
    await query.edit_message_text(
        "*Pick your evening digest time*",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or _rate_limited(user.id):
        return
    await _send_schedule_morning_keyboard(update.effective_chat.id, context)


async def callback_sched_am(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    morning_time = query.data.removeprefix("sched_am:")
    context.user_data["sched_morning"] = morning_time
    await _send_schedule_evening_keyboard(query, context)


async def callback_sched_pm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    user = update.effective_user
    if not user:
        return

    evening_time = query.data.removeprefix("sched_pm:")
    morning_time = context.user_data.pop("sched_morning", "09:00")

    if evening_time == "none":
        digest_times = morning_time
    else:
        digest_times = f"{morning_time},{evening_time}"

    await set_user_digest_times(user.id, digest_times)

    # Format confirmation
    def _fmt(t: str) -> str:
        h, m = t.split(":")
        hour = int(h)
        suffix = "AM" if hour < 12 else "PM"
        return f"{hour % 12 or 12}:{m} {suffix}"

    parts = [_fmt(t) for t in digest_times.split(",")]
    await query.edit_message_text(
        f"Digest schedule set to *{' and '.join(parts)}*\n\n"
        "You're all set! Use /more to get your first digest now.",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /block, /unblock, /blocklist
# ---------------------------------------------------------------------------
async def cmd_block(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or _rate_limited(user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/block <keyword>`\n"
            "Examples:\n"
            "  `/block politics`\n"
            "  `/block crypto`\n\n"
            "To manage sources, use /sources instead.",
            parse_mode="Markdown",
        )
        return

    value = " ".join(context.args).strip()
    added = await add_block(user.id, "keyword", value)

    if added:
        await update.message.reply_text(
            f"Blocked keyword: *{value}*", parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"Already blocked: *{value}*", parse_mode="Markdown")


async def cmd_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or _rate_limited(user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/unblock <keyword>` or `/unblock all`", parse_mode="Markdown"
        )
        return

    value = " ".join(context.args).strip()

    if value.lower() == "all":
        count = await remove_all_blocks(user.id)
        if count:
            await update.message.reply_text(
                f"Removed *{count}* block(s). Your blocklist is now empty.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Your blocklist is already empty.")
        return

    removed = await remove_block(user.id, value)
    if removed:
        await update.message.reply_text(
            f"Unblocked: *{value}*", parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"Not found in your blocklist: *{value}*")


async def cmd_blocklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or _rate_limited(user.id):
        return

    blocks = await get_user_blocks(user.id)
    if not blocks:
        await update.message.reply_text("Your blocklist is empty.")
        return

    lines = ["*Your blocklist:*\n"]
    for b in blocks:
        lines.append(f"\u2022 [{b['block_type']}] {b['block_value']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /more (formerly /digest)
# ---------------------------------------------------------------------------
async def cmd_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or _rate_limited(user.id):
        return
    await upsert_user(user.id, user.username)

    categories = await get_user_categories(user.id)
    if not categories:
        await update.message.reply_text(
            "You haven\u2019t picked any categories yet! Use /categories first."
        )
        return

    articles_by_cat = await get_unseen_articles(
        user.id, categories, MAX_ARTICLES_PER_CATEGORY
    )

    if not articles_by_cat:
        await update.message.reply_text(
            "No new articles to show right now. Check back later!\n\n"
            "Type /more when you\u2019re ready."
        )
        return

    # Mark articles sent first so count_unseen is accurate
    sent_ids: list[int] = []
    for arts in articles_by_cat.values():
        sent_ids.extend(a["id"] for a in arts)
    await mark_articles_sent(user.id, sent_ids)

    # Send each category as its own message
    cat_keys = list(articles_by_cat.keys())
    for i, cat in enumerate(cat_keys):
        articles = articles_by_cat[cat]
        is_first = i == 0
        is_last = i == len(cat_keys) - 1

        remaining = await count_unseen_articles(user.id, cat)
        has_more = remaining > 0

        text = format_category_more(
            cat, articles, has_more,
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

        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )

        if not is_last:
            await asyncio.sleep(0.05)


async def callback_morecat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Load 5 more articles for a specific category."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    user = update.effective_user
    if not user:
        return

    category = query.data.removeprefix("morecat:")

    # Fetch next batch of unseen articles for this category
    articles_by_cat = await get_unseen_articles(
        user.id, [category], MAX_ARTICLES_PER_CATEGORY
    )

    articles = articles_by_cat.get(category, [])
    if not articles:
        await query.message.reply_text(
            f"No more unseen articles in *{category}*.",
            parse_mode="Markdown",
        )
        return

    # Check if there are still more after this batch
    sent_ids = [a["id"] for a in articles]
    await mark_articles_sent(user.id, sent_ids)

    remaining = await count_unseen_articles(user.id, category)
    has_more = remaining > 0

    text = format_category_more(category, articles, has_more)

    reply_markup = None
    if has_more:
        emoji = CATEGORIES.get(category, "")
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"{emoji} More {category} \u2192",
                callback_data=f"morecat:{category}",
            )]
        ])

    await query.message.reply_text(
        text,
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )


# ---------------------------------------------------------------------------
# /reset
# ---------------------------------------------------------------------------
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or _rate_limited(user.id):
        return

    await reset_user(user.id)
    await update.message.reply_text(
        "All your preferences have been reset.\n"
        "Use /categories to start fresh!"
    )


# ---------------------------------------------------------------------------
# /settings
# ---------------------------------------------------------------------------
async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or _rate_limited(user.id):
        return

    db_user = await get_user(user.id)
    categories = await get_user_categories(user.id)
    blocks = await get_user_blocks(user.id)

    tz = db_user["timezone_offset"] if db_user else None
    active = db_user["is_active"] if db_user else True
    digest_times = db_user.get("digest_times", "09:00,18:00") if db_user else "09:00,18:00"

    cat_str = ", ".join(categories) if categories else "None"
    block_str = (
        "\n".join(f"  \u2022 [{b['block_type']}] {b['block_value']}" for b in blocks)
        if blocks
        else "  None"
    )
    status = "Active" if active else "Paused"
    tz_str = f"UTC{tz:+d}" if tz is not None else "Not set"

    # Format digest times readably
    def _fmt_time(t: str) -> str:
        h, m = t.split(":")
        hour = int(h)
        suffix = "AM" if hour < 12 else "PM"
        display_h = hour % 12 or 12
        return f"{display_h}:{m} {suffix}"

    times_display = ", ".join(_fmt_time(t.strip()) for t in digest_times.split(",") if t.strip())

    text = (
        "*Your Clear Feed News Settings*\n\n"
        f"*Status:* {status}\n"
        f"*Timezone:* {tz_str}\n"
        f"*Digest times:* {times_display}\n"
        f"*Categories:* {cat_str}\n"
        f"*Blocklist:*\n{block_str}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or _rate_limited(user.id):
        return

    text = (
        "*Clear Feed News Commands*\n\n"
        "/start - Welcome & onboarding\n"
        "/categories - Pick news categories\n"
        "/sources - Toggle individual feeds per category\n"
        "/timezone - Set your timezone\n"
        "/schedule - Pick delivery times\n"
        "/more - Get your latest digest now\n"
        "/block `<keyword>` - Block a keyword\n"
        "/unblock `<keyword>` - Remove a block\n"
        "/unblock `all` - Clear entire blocklist\n"
        "/blocklist - View your blocks\n"
        "/settings - View your current config\n"
        "/reset - Reset all preferences\n"
        "/pause - Pause scheduled digests\n"
        "/resume - Resume scheduled digests\n"
        "/help - This message"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /pause, /resume
# ---------------------------------------------------------------------------
async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or _rate_limited(user.id):
        return
    await set_user_active(user.id, False)
    await update.message.reply_text(
        "Digest delivery *paused*. Use /resume to restart.", parse_mode="Markdown"
    )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or _rate_limited(user.id):
        return
    await set_user_active(user.id, True)
    await update.message.reply_text(
        "Digest delivery *resumed*! \u2600\ufe0f", parse_mode="Markdown"
    )


# ---------------------------------------------------------------------------
# /sources - view and toggle individual feeds within categories
# ---------------------------------------------------------------------------
def _domain(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.")


async def cmd_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or _rate_limited(user.id):
        return

    categories = await get_user_categories(user.id)
    if not categories:
        await update.message.reply_text(
            "Subscribe to categories first with /categories"
        )
        return

    # Show category picker - user picks which category to manage sources for
    buttons: list[list[InlineKeyboardButton]] = []
    for cat in categories:
        emoji = CATEGORIES.get(cat, "")
        buttons.append(
            [InlineKeyboardButton(
                f"{emoji} {cat}", callback_data=f"srccat:{cat}"
            )]
        )
    await update.message.reply_text(
        "*Manage sources*\nPick a category to toggle individual feeds:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def _send_sources_keyboard(
    query, user_id: int, category: str
) -> None:
    """Show toggleable feed list for a category."""
    blocks = await get_user_blocks(user_id)
    blocked_sources = {b["block_value"] for b in blocks if b["block_type"] == "source"}

    feeds = FEEDS.get(category, [])
    buttons: list[list[InlineKeyboardButton]] = []
    for url in feeds:
        domain = _domain(url)
        is_blocked = domain.lower() in blocked_sources
        label = f"{'🚫' if is_blocked else '✅'} {domain}"
        buttons.append(
            [InlineKeyboardButton(label, callback_data=f"src:{category}|{domain}")]
        )
    buttons.append(
        [InlineKeyboardButton("\u2705 Done", callback_data=f"srcdone:{category}")]
    )
    buttons.append(
        [InlineKeyboardButton("\u00ab Back to categories", callback_data="srcback")]
    )

    emoji = CATEGORIES.get(category, "")
    await query.edit_message_text(
        f"*{emoji} {category} - Sources*\n"
        "Tap to block/unblock a source:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def callback_srccat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User picked a category to manage sources for."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    user = update.effective_user
    if not user:
        return
    category = query.data.removeprefix("srccat:")
    await _send_sources_keyboard(query, user.id, category)


async def callback_src_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle a specific feed source on/off."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    user = update.effective_user
    if not user:
        return

    payload = query.data.removeprefix("src:")
    category, domain = payload.split("|", 1)

    # Check if already blocked
    blocks = await get_user_blocks(user.id)
    blocked_sources = {b["block_value"] for b in blocks if b["block_type"] == "source"}

    if domain.lower() in blocked_sources:
        await remove_block(user.id, domain)
    else:
        await add_block(user.id, "source", domain)

    # Refresh the keyboard
    await _send_sources_keyboard(query, user.id, category)


async def callback_srcdone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save and confirm source selections."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    user = update.effective_user
    if not user:
        return

    category = query.data.removeprefix("srcdone:")
    emoji = CATEGORIES.get(category, "")

    blocks = await get_user_blocks(user.id)
    blocked_sources = [b["block_value"] for b in blocks if b["block_type"] == "source"]

    feeds = FEEDS.get(category, [])
    active = [_domain(u) for u in feeds if _domain(u).lower() not in blocked_sources]

    if active:
        sources_str = ", ".join(active)
        await query.edit_message_text(
            f"*{emoji} {category}* - sources saved!\n\n"
            f"Active: {sources_str}",
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text(
            f"*{emoji} {category}* - all sources blocked.\n"
            "You won\u2019t receive articles for this category until you re-enable some.",
            parse_mode="Markdown",
        )


async def callback_srcback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Go back to category list in source management."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    user = update.effective_user
    if not user:
        return

    categories = await get_user_categories(user.id)
    buttons: list[list[InlineKeyboardButton]] = []
    for cat in categories:
        emoji = CATEGORIES.get(cat, "")
        buttons.append(
            [InlineKeyboardButton(f"{emoji} {cat}", callback_data=f"srccat:{cat}")]
        )
    await query.edit_message_text(
        "*Manage sources*\nPick a category to toggle individual feeds:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Register all handlers on an Application
# ---------------------------------------------------------------------------
def register_handlers(app) -> None:
    """Add all command and callback handlers to the Telegram Application."""
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("block", cmd_block))
    app.add_handler(CommandHandler("unblock", cmd_unblock))
    app.add_handler(CommandHandler("blocklist", cmd_blocklist))
    app.add_handler(CommandHandler("more", cmd_more))
    app.add_handler(CommandHandler("digest", cmd_more))  # backward compat
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("sources", cmd_sources))
    app.add_handler(CommandHandler("timezone", cmd_timezone))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CallbackQueryHandler(callback_timezone, pattern=r"^tz:"))
    app.add_handler(CallbackQueryHandler(callback_sched_am, pattern=r"^sched_am:"))
    app.add_handler(CallbackQueryHandler(callback_sched_pm, pattern=r"^sched_pm:"))
    app.add_handler(CallbackQueryHandler(callback_category, pattern=r"^cat:"))
    app.add_handler(CallbackQueryHandler(callback_morecat, pattern=r"^morecat:"))
    app.add_handler(CallbackQueryHandler(callback_srccat, pattern=r"^srccat:"))
    app.add_handler(CallbackQueryHandler(callback_src_toggle, pattern=r"^src:"))
    app.add_handler(CallbackQueryHandler(callback_srcdone, pattern=r"^srcdone:"))
    app.add_handler(CallbackQueryHandler(callback_srcback, pattern=r"^srcback$"))
