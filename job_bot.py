"""
Job Alert Telegram Bot
----------------------
Checks a handful of free job sources for new postings matching your
keywords, and sends you a Telegram message for each new match.

You should NOT need to edit this file. Everything you'd want to change
lives in keywords.txt (your keyword list) and the two secrets
(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) set up in GitHub Actions.
"""

import os
import json
import time
import requests
import feedparser
from bs4 import BeautifulSoup

# ---------- CONFIG ----------
SEEN_FILE = "seen_jobs.json"
KEYWORDS_FILE = "keywords.txt"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


# ---------- HELPERS ----------
def load_keywords():
    if not os.path.exists(KEYWORDS_FILE):
        return []
    with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
        return [line.strip().lower() for line in f if line.strip() and not line.strip().startswith("#")]


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_seen(seen_ids):
    trimmed = list(seen_ids)[-3000:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f)


def matches_keywords(text, keywords):
    text = text.lower()
    return any(kw in text for kw in keywords)


def send_telegram(title, company, link, source):
    if not BOT_TOKEN or not CHAT_ID:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID - skipping send.")
        return
    message = f"🆕 *{title}*\n🏢 {company}\n📍 Source: {source}\n🔗 {link}"
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
                "company": item.get("company", "Unknown company"),
                "link": item.get("url", "https://remoteok.com"),
                "text": f"{item.get('position','')} {item.get('company','')} {' '.join(item.get('tags', []))}",
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
                "company": item.get("company_name", "Unknown company"),
                "link": item.get("url", "https://remotive.com"),
                "text": f"{item.get('title','')} {item.get('category','')} {item.get('description','')[:300]}",
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
                "text": entry.get("title", "") + " " + entry.get("summary", ""),
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
                "text": title,
                "source": "Jobberman",
            })
    except Exception as e:
        print("Jobberman fetch error:", e)
    return jobs


# ---------- MAIN ----------
def main():
    keywords = load_keywords()
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

    print(f"Fetched {len(all_jobs)} total postings across all sources.")

    new_matches = 0
    for job in all_jobs:
        if job["id"] in seen:
            continue
        if matches_keywords(job["text"], keywords):
            send_telegram(job["title"], job["company"], job["link"], job["source"])
            new_matches += 1
            time.sleep(1)
        new_seen.add(job["id"])

    save_seen(new_seen)
    print(f"Done. Sent {new_matches} new matching alerts.")


if __name__ == "__main__":
    main()
