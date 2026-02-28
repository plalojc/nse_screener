
# ============================================================
# analysis/news_fetcher.py – RSS market news fetcher
# ============================================================
import feedparser
import sqlite3
from datetime import datetime
from config import NEWS_RSS_FEEDS, DB_PATH


def fetch_and_store_news():
    """Fetch latest market news from RSS and store in SQLite."""
    conn = sqlite3.connect(DB_PATH)
    inserted = 0

    for feed_url in NEWS_RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                title     = entry.get("title", "")
                url       = entry.get("link", "")
                published = entry.get("published", str(datetime.now()))
                source    = feed.feed.get("title", feed_url)

                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO news_cache (title, url, published, source) VALUES (?,?,?,?)",
                        (title, url, published, source)
                    )
                    inserted += conn.execute("SELECT changes()").fetchone()[0]
                except Exception:
                    pass
        except Exception as e:
            print(f"[News] Error parsing {feed_url}: {e}")

    conn.commit()
    conn.close()
    return inserted


def get_recent_news(limit: int = 20) -> list:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT title, url, source, published FROM news_cache ORDER BY fetched_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [{"title": r[0], "url": r[1], "source": r[2], "published": r[3]} for r in rows]


def get_news_for_symbol(symbol: str) -> list:
    """Return news items where title mentions the symbol."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT title, url, source FROM news_cache WHERE title LIKE ? ORDER BY fetched_at DESC LIMIT 5",
        (f"%{symbol}%",)
    ).fetchall()
    conn.close()
    return [{"title": r[0], "url": r[1], "source": r[2]} for r in rows]
