"""
Job Alert Telegram Bot
----------------------
Checks several free job sources for new postings matching your keywords
(matched against the JOB TITLE only, to cut down on noise), skips
anything matching an exclude word, and sends you a Telegram message
for each new match - including the posting time where the source
provides one.

You should NOT need to edit this file. Everything you'd want to change
lives in keywords.txt / excludes.txt and the two secrets
(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) set up in GitHub Actions.
"""

import os
import json
import time
from datetime import datetime, timezone

import requests
import feedparser
from bs4 import BeautifulSoup

# ---------- CONFIG ----------
SEEN_FILE = "seen_jobs.json"
KEYWORDS_FILE = "keywords.txt"
EXCLUDES_FILE = "excludes.txt"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


# ---------- HELPERS ----------
def load_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [
            line.strip().lower()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_seen(seen_ids):
    trimmed = list(seen_ids)[-4000:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f)


def title_matches(title, keywords, excludes):
    title_lower = title.lower()
    if any(ex in title_lower for ex in excludes):
        return False
    return any(kw in title_lower for kw in keywords)


def format_timestamp(value):
    """Best-effort formatting of whatever date/time value a source gives us."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
            return dt.strftime("%d %b %Y, %H:%M UTC")
        value_str = str(value).strip()
        formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%a, %d %b %Y %H:%M:%S %z",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(value_str, fmt)
                return dt.strftime("%d %b %Y, %H:%M")
            except ValueError:
                continue
        return value_str
    except Exception:
        return None


def send_telegram(job):
    if not BOT_TOKEN or not CHAT_ID:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID - skipping send.")
        return
    posted = format_timestamp(job.get("posted"))
    posted_line = f"🕒 Posted: {posted}\n" if posted else ""
    company_line = f"🏢 {job['company']}\n" if job.get("company") else ""
    message = (
        f"🆕 *{job['title']}*\n"
        f"{company_line}"
        f"{posted_line}"
        f"📍 Source: {job['source']}\n"
        f"🔗 {job['link']}"
    )
    try:
        resp = requests.post(
            TELEGRAM_API,
            data={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print("Telegram send failed:", resp.text)
    except Exception as e:
        print("Telegram send error:", e)


# ---------- SOURCES ----------
def fetch_remoteok():
    jobs = []
    try:
        resp = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        data = resp.json()
        for item in data:
            if not isinstance(item, dict) or "id" not in item:
                continue
            jobs.append({
                "id": f"remoteok-{item.get('id')}",
                "title": item.get("position", "Untitled role"),
                "company": item.get("company", ""),
                "link": item.get("url", "https://remoteok.com"),
                "posted": item.get("date"),
                "source": "RemoteOK",
            })
    except Exception as e:
        print("RemoteOK fetch error:", e)
    return jobs


def fetch_remotive():
    jobs = []
    try:
        resp = requests.get("https://remotive.com/api/remote-jobs", timeout=20)
        data = resp.json()
        for item in data.get("jobs", []):
            jobs.append({
                "id": f"remotive-{item.get('id')}",
                "title": item.get("title", "Untitled role"),
                "company": item.get("company_name", ""),
                "link": item.get("url", "https://remotive.com"),
                "posted": item.get("publication_date"),
                "source": "Remotive",
            })
    except Exception as e:
        print("Remotive fetch error:", e)
    return jobs


def fetch_wwr():
    jobs = []
    try:
        feed = feedparser.parse("https://weworkremotely.com/remote-jobs.rss")
        for entry in feed.entries:
            jobs.append({
                "id": f"wwr-{entry.get('id', entry.get('link'))}",
                "title": entry.get("title", "Untitled role"),
                "company": "",
                "link": entry.get("link", "https://weworkremotely.com"),
                "posted": entry.get("published"),
                "source": "WeWorkRemotely",
            })
    except Exception as e:
        print("WWR fetch error:", e)
    return jobs


def fetch_jobberman():
    jobs = []
    try:
        resp = requests.get(
            "https://www.jobberman.com/jobs",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        soup = BeautifulSoup(resp.text, "lxml")
        for card in soup.select("a[href*='/listings/']"):
            title = card.get_text(strip=True)
            href = card.get("href", "")
            if not title or not href:
                continue
            link = href if href.startswith("http") else f"https://www.jobberman.com{href}"
            jobs.append({
                "id": f"jobberman-{href}",
                "title": title,
                "company": "",
                "link": link,
                "posted": None,
                "source": "Jobberman",
            })
    except Exception as e:
        print("Jobberman fetch error:", e)
    return jobs


def fetch_arbeitnow():
    jobs = []
    try:
        resp = requests.get("https://www.arbeitnow.com/api/job-board-api", timeout=20)
        data = resp.json()
        for item in data.get("data", []):
            jobs.append({
                "id": f"arbeitnow-{item.get('slug')}",
                "title": item.get("title", "Untitled role"),
                "company": item.get("company_name", ""),
                "link": item.get("url", "https://www.arbeitnow.com"),
                "posted": item.get("created_at"),
                "source": "Arbeitnow",
            })
    except Exception as e:
        print("Arbeitnow fetch error:", e)
    return jobs


def fetch_jobicy():
    jobs = []
    try:
        resp = requests.get("https://jobicy.com/api/v2/remote-jobs?count=50", timeout=20)
        data = resp.json()
        for item in data.get("jobs", []):
            jobs.append({
                "id": f"jobicy-{item.get('id')}",
                "title": item.get("jobTitle", "Untitled role"),
                "company": item.get("companyName", ""),
                "link": item.get("url", "https://jobicy.com"),
                "posted": item.get("pubDate"),
                "source": "Jobicy",
            })
    except Exception as e:
        print("Jobicy fetch error:", e)
    return jobs


def fetch_himalayas():
    jobs = []
    try:
        resp = requests.get("https://himalayas.app/jobs/api?limit=20&offset=0", timeout=20)
        data = resp.json()
        listings = data.get("jobs", data) if isinstance(data, dict) else data
        for item in listings:
            if not isinstance(item, dict):
                continue
            jobs.append({
                "id": f"himalayas-{item.get('guid')}",
                "title": item.get("title", "Untitled role"),
                "company": item.get("companyName", ""),
                "link": item.get("applicationLink", "https://himalayas.app"),
                "posted": item.get("pubDate"),
                "source": "Himalayas",
            })
    except Exception as e:
        print("Himalayas fetch error:", e)
    return jobs


# ---------- MAIN ----------
def main():
    keywords = load_lines(KEYWORDS_FILE)
    excludes = load_lines(EXCLUDES_FILE)
    if not keywords:
        print("No keywords configured in keywords.txt - exiting.")
        return

    seen = load_seen()
    new_seen = set(seen)

    all_jobs = []
    all_jobs += fetch_remoteok()
    all_jobs += fetch_remotive()
    all_jobs += fetch_wwr()
    all_jobs += fetch_jobberman()
    all_jobs += fetch_arbeitnow()
    all_jobs += fetch_jobicy()
    all_jobs += fetch_himalayas()

    print(f"Fetched {len(all_jobs)} total postings across all sources.")

    new_matches = 0
    for job in all_jobs:
        if job["id"] in seen:
            continue
        if title_matches(job["title"], keywords, excludes):
            send_telegram(job)
            new_matches += 1
            time.sleep(1)
        new_seen.add(job["id"])

    save_seen(new_seen)
    print(f"Done. Sent {new_matches} new matching alerts.")


if __name__ == "__main__":
    main()
