"""Async SQLite database layer for Clear Feed News."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from config import DB_PATH, TRENDING_WEIGHT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id   INTEGER PRIMARY KEY,
    username  TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    timezone_offset INTEGER DEFAULT NULL,
    digest_times TEXT NOT NULL DEFAULT '09:00,18:00',
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS user_categories (
    user_id       INTEGER NOT NULL,
    category_name TEXT    NOT NULL,
    PRIMARY KEY (user_id, category_name),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_blocks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    block_type  TEXT    NOT NULL CHECK (block_type IN ('keyword', 'source')),
    block_value TEXT    NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (user_id, block_type, block_value)
);

CREATE TABLE IF NOT EXISTS articles (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT    NOT NULL,
    url            TEXT    NOT NULL UNIQUE,
    source_name    TEXT,
    category       TEXT    NOT NULL,
    summary        TEXT,
    sentiment_label TEXT,
    published_at   TEXT,
    fetched_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    trending_score REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS sent_articles (
    user_id    INTEGER NOT NULL,
    article_id INTEGER NOT NULL,
    sent_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (user_id, article_id),
    FOREIGN KEY (user_id)    REFERENCES users(user_id)    ON DELETE CASCADE,
    FOREIGN KEY (article_id) REFERENCES articles(id)      ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_articles_category   ON articles(category);
CREATE INDEX IF NOT EXISTS idx_articles_fetched_at  ON articles(fetched_at);
CREATE INDEX IF NOT EXISTS idx_sent_articles_user   ON sent_articles(user_id);
"""


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------
async def get_db() -> aiosqlite.Connection:
    """Return a connection with WAL mode and foreign keys enabled."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db() -> None:
    """Create tables if they don't exist."""
    db = await get_db()
    try:
        # Migrate existing DBs: add trending_score before schema runs
        try:
            await db.execute(
                "ALTER TABLE articles ADD COLUMN trending_score REAL NOT NULL DEFAULT 0.0"
            )
            await db.commit()
        except Exception:
            pass  # column already exists or table doesn't exist yet
        # Migrate timezone_offset: convert NOT NULL DEFAULT 0 -> DEFAULT NULL
        try:
            cur = await db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")
            row = await cur.fetchone()
            if row and "NOT NULL DEFAULT 0" in (row[0] or ""):
                await db.execute("UPDATE users SET timezone_offset = NULL WHERE timezone_offset = 0")
                await db.commit()
        except Exception:
            pass
        await db.executescript(_SCHEMA)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_trending ON articles(trending_score)"
        )
        await db.commit()
        logger.info("Database initialised at %s", DB_PATH)
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------
async def upsert_user(user_id: int, username: str | None = None) -> None:
    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO users (user_id, username)
               VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET username = excluded.username""",
            (user_id, username),
        )
        await db.commit()
    finally:
        await db.close()


async def get_user(user_id: int) -> dict[str, Any] | None:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def set_user_active(user_id: int, active: bool) -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET is_active = ? WHERE user_id = ?",
            (1 if active else 0, user_id),
        )
        await db.commit()
    finally:
        await db.close()


async def set_user_timezone(user_id: int, offset: int) -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET timezone_offset = ? WHERE user_id = ?",
            (offset, user_id),
        )
        await db.commit()
    finally:
        await db.close()


async def set_user_digest_times(user_id: int, digest_times: str) -> None:
    """Update the user's digest delivery times (comma-separated HH:MM)."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET digest_times = ? WHERE user_id = ?",
            (digest_times, user_id),
        )
        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Category helpers
# ---------------------------------------------------------------------------
async def get_user_categories(user_id: int) -> list[str]:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT category_name FROM user_categories WHERE user_id = ?", (user_id,)
        )
        rows = await cur.fetchall()
        return [r["category_name"] for r in rows]
    finally:
        await db.close()


async def toggle_user_category(user_id: int, category: str) -> bool:
    """Toggle a category for a user. Returns True if now subscribed, False if removed."""
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT 1 FROM user_categories WHERE user_id = ? AND category_name = ?",
            (user_id, category),
        )
        exists = await cur.fetchone()
        if exists:
            await db.execute(
                "DELETE FROM user_categories WHERE user_id = ? AND category_name = ?",
                (user_id, category),
            )
            await db.commit()
            return False
        else:
            await db.execute(
                "INSERT INTO user_categories (user_id, category_name) VALUES (?, ?)",
                (user_id, category),
            )
            await db.commit()
            return True
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Block helpers
# ---------------------------------------------------------------------------
async def add_block(user_id: int, block_type: str, value: str) -> bool:
    """Add a block entry. Returns True if added, False if already exists."""
    db = await get_db()
    try:
        try:
            await db.execute(
                "INSERT INTO user_blocks (user_id, block_type, block_value) VALUES (?, ?, ?)",
                (user_id, block_type, value.lower()),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False
    finally:
        await db.close()


async def remove_block(user_id: int, value: str) -> bool:
    """Remove a block by value (any type). Returns True if removed."""
    db = await get_db()
    try:
        cur = await db.execute(
            "DELETE FROM user_blocks WHERE user_id = ? AND block_value = ?",
            (user_id, value.lower()),
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def get_user_blocks(user_id: int) -> list[dict[str, str]]:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT block_type, block_value FROM user_blocks WHERE user_id = ?",
            (user_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Article helpers
# ---------------------------------------------------------------------------
async def insert_articles(articles: list[dict[str, Any]]) -> int:
    """Bulk-insert articles, ignoring duplicates. Returns count of new rows."""
    if not articles:
        return 0
    db = await get_db()
    inserted = 0
    try:
        for a in articles:
            try:
                await db.execute(
                    """INSERT INTO articles (title, url, source_name, category, summary,
                       sentiment_label, published_at, trending_score)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        a["title"],
                        a["url"],
                        a.get("source_name"),
                        a["category"],
                        a.get("summary"),
                        a.get("sentiment_label"),
                        a.get("published_at"),
                        a.get("trending_score", 0.0),
                    ),
                )
                inserted += 1
            except aiosqlite.IntegrityError:
                pass  # duplicate URL
        await db.commit()
        return inserted
    finally:
        await db.close()


async def get_unseen_articles(
    user_id: int, categories: list[str], limit_per_cat: int = 5
) -> dict[str, list[dict[str, Any]]]:
    """Return unseen articles grouped by category for the given user."""
    if not categories:
        return {}
    db = await get_db()
    try:
        result: dict[str, list[dict[str, Any]]] = {}
        # Fetch user blocks to apply
        blocks = await get_user_blocks(user_id)
        blocked_keywords = [b["block_value"] for b in blocks if b["block_type"] == "keyword"]
        blocked_sources = [b["block_value"] for b in blocks if b["block_type"] == "source"]

        recency_weight = round(1.0 - TRENDING_WEIGHT, 2)
        # Fetch extra rows so we have enough after block filtering + diversity cap
        fetch_limit = limit_per_cat * 6

        for cat in categories:
            cur = await db.execute(
                f"""SELECT a.*,
                       (a.trending_score / 100.0 * {TRENDING_WEIGHT}
                        + (1.0 - MIN(
                            (julianday('now') - julianday(a.fetched_at)) / 1.0,
                            1.0
                          )) * {recency_weight}
                       ) AS composite_score
                   FROM articles a
                   WHERE a.category = ?
                     AND a.id NOT IN (
                         SELECT article_id FROM sent_articles WHERE user_id = ?
                     )
                   ORDER BY composite_score DESC
                   LIMIT ?""",
                (cat, user_id, fetch_limit),
            )
            rows = await cur.fetchall()
            filtered: list[dict[str, Any]] = []
            source_counts: dict[str, int] = {}
            for row in rows:
                if len(filtered) >= limit_per_cat:
                    break
                article = dict(row)
                title_lower = (article.get("title") or "").lower()
                summary_lower = (article.get("summary") or "").lower()
                source_lower = (article.get("source_name") or "").lower()
                # Apply user blocks
                if any(kw in title_lower or kw in summary_lower for kw in blocked_keywords):
                    continue
                if any(src in source_lower for src in blocked_sources):
                    continue
                # Source diversity: max 2 articles per source
                src_key = source_lower
                source_counts[src_key] = source_counts.get(src_key, 0) + 1
                if source_counts[src_key] > 2:
                    continue
                filtered.append(article)
            if filtered:
                result[cat] = filtered
        return result
    finally:
        await db.close()


async def count_unseen_articles(user_id: int, category: str) -> int:
    """Return the count of unseen articles in a category for the user."""
    db = await get_db()
    try:
        cur = await db.execute(
            """SELECT COUNT(*) FROM articles a
               WHERE a.category = ?
                 AND a.id NOT IN (
                     SELECT article_id FROM sent_articles WHERE user_id = ?
                 )""",
            (category, user_id),
        )
        row = await cur.fetchone()
        return row[0] if row else 0
    finally:
        await db.close()


async def mark_articles_sent(user_id: int, article_ids: list[int]) -> None:
    if not article_ids:
        return
    db = await get_db()
    try:
        await db.executemany(
            "INSERT OR IGNORE INTO sent_articles (user_id, article_id) VALUES (?, ?)",
            [(user_id, aid) for aid in article_ids],
        )
        await db.commit()
    finally:
        await db.close()


async def get_active_users() -> list[dict[str, Any]]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM users WHERE is_active = 1")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def remove_all_blocks(user_id: int) -> int:
    """Remove all blocks for a user. Returns count removed."""
    db = await get_db()
    try:
        cur = await db.execute(
            "DELETE FROM user_blocks WHERE user_id = ?", (user_id,)
        )
        await db.commit()
        return cur.rowcount
    finally:
        await db.close()


async def reset_user(user_id: int) -> None:
    """Delete all user preferences (categories, blocks, sent history)."""
    db = await get_db()
    try:
        await db.execute("DELETE FROM user_categories WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM user_blocks WHERE user_id = ?", (user_id,))
        await db.execute("DELETE FROM sent_articles WHERE user_id = ?", (user_id,))
        await db.execute(
            "UPDATE users SET timezone_offset = NULL, digest_times = '09:00,18:00', is_active = 1 WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()
    finally:
        await db.close()


async def cleanup_old_articles(days: int = 30) -> int:
    """Delete articles older than *days*. Returns count removed."""
    db = await get_db()
    try:
        cur = await db.execute(
            "DELETE FROM articles WHERE fetched_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        await db.commit()
        return cur.rowcount
    finally:
        await db.close()
