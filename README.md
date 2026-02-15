# Clear Feed News

This is an experimental project born out of frustration with modern news in general. I simply got tired of clickbait headlines and sensationalised stories designed to rage bait. I wanted a news feed that respects my attention: no doom-scrolling, no rage bait, no algorithm that would decide what's next for me, for the sake of engagement. Just the information I consider useful, delivered on my schedule.

Clear Feed News is a Telegram bot that curates RSS feeds from handpicked sources, filters out negative and sensational content, ranks articles by what's trending on Google Trends, and delivers a clean digest straight to your chat.

## Features

- **10 curated categories** - Science, Tech, AI, Gaming, Environment, Health, Creative, Good News, Career, Food & Culture
- **Google Trends scoring** - articles ranked by trending relevance, not just recency
- **Aggressive content filtering** - ~50 blocked keywords (violence, sensationalism, political toxicity) and 25+ blocked domains (tabloids, propaganda, clickbait outlets)
- **Source diversity** - max 2 articles per source per category, so no single outlet dominates
- **Per-category messages** - each category sent as its own message with a "More" button
- **Keyword blocking** - filter out topics you don't want
- **Source management** - toggle individual feeds on/off per category
- **Timezone support** - digests arrive at the right local time
- **Configurable delivery times** - pick morning and evening digest times with `/schedule`
- **On-demand digest** - `/more` for instant news
- **Auto-cleanup** - old articles purged daily to keep the database small
- **Async throughout** - built on python-telegram-bot (async), aiosqlite, APScheduler

## Tech Stack

| Component | Library |
|-----------|---------|
| Telegram API | python-telegram-bot 21.x |
| RSS parsing | feedparser 6.x |
| Scheduling | APScheduler 3.10.x |
| Database | aiosqlite (SQLite, WAL mode) |
| Trending | trendspy 0.1.x |
| Config | python-dotenv |

## Quick Start

### 1. Prerequisites

- Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### 2. Setup

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env and set your BOT_TOKEN
```

### 4. Run

```bash
python bot.py
```

The bot will initialise the database, fetch RSS feeds, and start listening for commands.

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message + onboarding |
| `/categories` | Pick news categories (inline keyboard) |
| `/sources` | Toggle individual feeds per category |
| `/timezone` | Set your timezone for digest delivery |
| `/schedule` | Pick morning/evening delivery times |
| `/more` | Get your latest digest now |
| `/block <keyword>` | Block a keyword |
| `/unblock <keyword>` | Remove a block |
| `/unblock all` | Clear entire blocklist |
| `/blocklist` | View your blocks |
| `/settings` | View your current config |
| `/reset` | Reset all preferences |
| `/pause` | Pause scheduled digests |
| `/resume` | Resume scheduled digests |
| `/help` | List all commands |

## Architecture

```
bot.py          - entry point (polling or webhook)
config.py       - settings, RSS feed URLs, blocked keywords
database.py     - async SQLite schema and queries
fetcher.py      - RSS fetching with dedup and filtering
filters.py      - keyword blocklist filtering
trending.py     - Google Trends scoring (pre-indexed for speed)
handlers.py     - Telegram command and callback handlers
scheduler.py    - APScheduler for fetch, digest delivery, and cleanup
formatter.py    - digest message formatting
```

### Data Flow

1. **Scheduler** triggers `fetcher.py` every 2 hours
2. **Trending** fetches ~200-300 Google trending topics (1 API call)
3. **Fetcher** pulls RSS feeds from 41 sources across 10 categories
4. **Filter** removes articles matching blocked keywords or blocked domains
5. **Scoring** matches article keywords against a pre-built trending index (0-100 score)
6. **Database** stores scored articles (deduped by URL)
7. **Scheduler** checks every hour if any user's digest time matches their local time
8. **Formatter** builds Markdown digest sorted by composite score (trending + recency)
9. **Bot** sends per-category messages with "More" buttons for loading additional articles
10. **Cleanup** runs daily at 03:00 UTC, removing articles older than 30 days

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BOT_TOKEN` | Yes | - | Telegram bot token from @BotFather |
| `BOT_MODE` | No | polling | `polling` or `webhook` |
| `WEBHOOK_URL` | webhook only | - | Public URL for webhook mode |
| `PORT` | No | 8443 | Webhook listen port |
| `FETCH_INTERVAL_HOURS` | No | 2 | How often to fetch new articles |
| `MAX_ARTICLES_PER_CATEGORY` | No | 5 | Articles per category per digest |
| `USE_TRENDING` | No | true | Enable Google Trends scoring |
| `TRENDING_WEIGHT` | No | 0.6 | Balance between trending (0.6) and recency (0.4) |
| `DB_PATH` | No | clearfeed.db | SQLite database path |

## Deployment (Oracle Cloud VM)

```bash
# Clone and setup
git clone <your-repo-url> clearfeednews
cd clearfeednews
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env  # set BOT_TOKEN, BOT_MODE=polling
```

### systemd service

```bash
sudo nano /etc/systemd/system/clearfeed.service
```

```ini
[Unit]
Description=Clear Feed News Telegram Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/clearfeednews
ExecStart=/home/ubuntu/clearfeednews/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable clearfeed
sudo systemctl start clearfeed
```

### Updating

```bash
cd clearfeednews
git pull
sudo systemctl restart clearfeed
```

## License

MIT
