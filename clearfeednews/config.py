"""Clear Feed News configuration — feeds, settings, and blocked keywords."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# ---------------------------------------------------------------------------
# Core bot settings
# ---------------------------------------------------------------------------
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
CLAUDE_API_KEY: str = os.getenv("CLAUDE_API_KEY", "")
USE_CLAUDE_FILTERING: bool = os.getenv("USE_CLAUDE_FILTERING", "false").lower() == "true"
BOT_MODE: str = os.getenv("BOT_MODE", "polling")  # "polling" or "webhook"
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")  # e.g. https://your-app.onrender.com
PORT: int = int(os.getenv("PORT", "8443"))

# ---------------------------------------------------------------------------
# Fetch / digest defaults
# ---------------------------------------------------------------------------
FETCH_INTERVAL_HOURS: int = int(os.getenv("FETCH_INTERVAL_HOURS", "2"))
DEFAULT_DIGEST_TIMES: list[str] = ["09:00", "18:00"]
MAX_ARTICLES_PER_CATEGORY: int = int(os.getenv("MAX_ARTICLES_PER_CATEGORY", "5"))
USE_TRENDING: bool = os.getenv("USE_TRENDING", "true").lower() == "true"
TRENDING_WEIGHT: float = float(os.getenv("TRENDING_WEIGHT", "0.6"))

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "clearfeed.db"))

# ---------------------------------------------------------------------------
# Rate limiting (per-user command cooldown in seconds)
# ---------------------------------------------------------------------------
COMMAND_COOLDOWN_SECONDS: int = 2

# ---------------------------------------------------------------------------
# Global keyword blocklist — articles whose title or summary contain any of
# these words (case-insensitive) are filtered out before reaching users.
# ---------------------------------------------------------------------------
GLOBAL_BLOCK_KEYWORDS: list[str] = [
    # violence / death
    "killed", "murder", "murdered", "massacre", "slaughter", "assassination",
    "dead", "death toll", "fatalities", "casualty", "casualties",
    # conflict
    "war", "airstrike", "bombing", "terrorist", "terrorism", "extremist",
    "insurgent", "militia", "genocide", "ethnic cleansing",
    # crime
    "rape", "sexual assault", "kidnapped", "abducted", "stabbing",
    "shooting", "gunman", "shooter", "hostage",
    # disaster framing (negative-leaning)
    "tragedy", "catastrophe", "devastation", "horrific", "gruesome",
    # political toxicity
    "scandal", "corruption", "impeach", "indicted", "fraud",
    "conspiracy theory", "disinformation", "propaganda",
    # social negativity
    "hate crime", "racist", "racism", "bigotry", "xenophobia",
    # sensationalism
    "shocking", "horrifying", "nightmare", "bloodbath", "carnage",
]

# ---------------------------------------------------------------------------
# Blocked sources — entire domains we never pull from.
# ---------------------------------------------------------------------------
BLOCKED_SOURCES: list[str] = [
    # Misinformation / conspiracy
    "infowars.com",
    "naturalnews.com",
    "beforeitsnews.com",
    "thegatewaypundit.com",
    "wnd.com",
    # State propaganda
    "rt.com",
    "sputniknews.com",
    # Tabloid / sensationalist
    "dailymail.co.uk",
    "thesun.co.uk",
    "mirror.co.uk",
    "express.co.uk",
    "nypost.com",
    # Politically polarised
    "breitbart.com",
    "theblaze.com",
    "dailykos.com",
    "huffpost.com",
    # Cable news (opinion-heavy)
    "cnn.com",
    "msnbc.com",
    "foxnews.com",
    "news.sky.com",
    # Clickbait / low-signal
    "buzzfeednews.com",
    "buzzfeed.com",
    "upworthy.com",
    "boredpanda.com",
]

# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------
CATEGORIES: dict[str, str] = {
    "Science & Space":              "🔬",
    "Tech & Innovation":            "💻",
    "Cinema & Entertainment":       "🎬",
    "AI & Machine Learning":        "🤖",
    "Gaming & Entertainment":       "🎮",
    "Environment & Climate Solutions": "🌱",
    "Health & Wellness":            "🏥",
    "Creative & Design":            "🎨",
    "Good News":                    "😊",
    "Career & Learning":            "📚",
    "Food & Culture":               "🍜",
}

# ---------------------------------------------------------------------------
# RSS feeds — 3-5 real, working feeds per category.
# Chosen for positive / neutral / educational tone.
# ---------------------------------------------------------------------------
FEEDS: dict[str, list[str]] = {
    "Science & Space": [
        "https://www.nasa.gov/feed/",
        "https://www.space.com/feeds/all",
        "https://www.sciencedaily.com/rss/all.xml",
        "https://phys.org/rss-feed/",
        "https://www.livescience.com/feeds/all",
    ],
    "Tech & Innovation": [
        "https://www.engadget.com/rss.xml",
        "https://techcrunch.com/feed/",
        "https://arstechnica.com/feed/",
        "https://feeds.wired.com/wired/index",
    ],
    "Cinema & Entertainment": [
        "https://variety.com/feed/",
        "https://www.rogerebert.com/reviews/feed",
        "https://www.indiewire.com/feed/",
        "https://lwlies.com/feed.rss",
    ],
    "AI & Machine Learning": [
        "https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml",
        "https://blog.google/technology/ai/rss/",
        "https://openai.com/blog/rss.xml",
        "https://deepmind.google/blog/rss.xml",
        "https://raw.githubusercontent.com/Olshansk/rss-feeds/refs/heads/main/feeds/feed_anthropic.xml",#experimental
    ],
    "Gaming & Entertainment": [
        "https://www.polygon.com/rss/index.xml",
        "https://gameinformer.com/rss.xml",
        "https://www.gamesindustry.biz/feed"        
    ],
    "Environment & Climate Solutions": [
        "https://grist.org/feed/",
        "https://www.positive.news/environment/feed/",
        "https://www.treehugger.com/feeds/all",
        "https://www.climatesolutions.org/climate-solutions-rss-feeds",
    ],
    "Health & Wellness": [
        "https://news.harvard.edu/gazette/section/health-medicine/feed/",
        "https://www.newscientist.com/subject/health/feed/"
        "https://newsnetwork.mayoclinic.org/feed/",
        "https://www.sciencedaily.com/rss/health_medicine.xml",
    ],
    "Creative & Design": [
        "https://www.thisiscolossal.com/feed/",
        "https://www.creativebloq.com/feed",
        "https://www.designboom.com/feed/",
        "https://www.dezeen.com/feed/",
        "https://feeds.feedburner.com/design-milk",
    ],
    "Good News": [
        "https://www.positive.news/feed/",
        "https://www.goodnewsnetwork.org/feed/",
        "https://reasonstobecheerful.world/feed/",
    ],
    "Career & Learning": [
        "https://hbr.org/feed",
        "https://www.higheredjobs.com/search/rss.cfm?JobCat=219",
    ],
    "Food & Culture": [
        "https://www.seriouseats.com/feed",
        #"https://www.bonappetit.com/feed/rss",
        "bbc.com/culture/feed.rss ",
        "https://www.openculture.com/feed",
        "https://www.eater.com/rss/index.xml"
    ],
}
