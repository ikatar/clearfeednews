# Clear Feed News

A Telegram bot that delivers curated positive, neutral and educational news via RSS feeds. No doom-scrolling — just good stuff.

## Features

- **10 curated categories** — Science, Tech, AI, Gaming, Environment, Health, Creative, Good News, Career, Food & Culture
- **Google Trends scoring** — articles ranked by trending relevance, not just recency
- **Source diversity** — max 2 articles per source per category, so no single outlet dominates
- **Per-category messages** — each category sent as its own message with a dedicated "More" button
- **Keyword blocking** — filter out topics you don't want
- **Source management** — toggle individual feeds on/off per category
- **Timezone support** — digests arrive at the right local time
- **User-configurable delivery times** — pick morning and evening digest times with `/schedule`
- **On-demand digest** — `/more` for instant news
- **Async throughout** — built on python-telegram-bot (async), aiosqlite, APScheduler

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

### 4. Run (polling mode)

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

## Deployment

### Oracle Cloud VM (production)

```bash
# Clone and setup
git clone <your-repo-url> clearfeednews
cd clearfeednews
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env  # set BOT_TOKEN, BOT_MODE=polling

# Create systemd service
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

### Docker (optional)

```bash
docker build -t clearfeed .
docker run -e BOT_TOKEN=your-token -e BOT_MODE=polling clearfeed
```

## Architecture

```
bot.py          — entry point (polling or webhook)
config.py       — settings, RSS feed URLs, blocked keywords
database.py     — async SQLite (aiosqlite) schema and queries
fetcher.py      — RSS fetching with dedup and filtering
filters.py      — keyword blocklist sentiment filtering
trending.py     — Google Trends scoring (trendspy)
handlers.py     — Telegram command handlers
scheduler.py    — APScheduler for periodic fetch + digest delivery
formatter.py    — digest message formatting
```

### Data Flow

1. **Scheduler** triggers `fetcher.py` every 2 hours
2. **Trending** fetches ~200 Google trending topics (1 API call)
3. **Fetcher** pulls RSS feeds, extracts all available articles
4. **Filter** removes articles with negative/blocked keywords
5. **Scoring** fuzzy-matches article keywords against trending topics (0-100 score)
6. **Database** stores scored articles (deduped by URL)
7. **Scheduler** checks every hour if any user's digest time matches
8. **Formatter** builds Markdown digest sorted by composite score (trending + recency)
9. **Bot** sends digest messages with per-category "More" buttons

## License

MIT
