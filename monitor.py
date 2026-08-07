"""
Keyword Monitor
---------------
Checks Google News RSS for a set of keywords, and sends a push notification
(via ntfy.sh) for any new matching articles. If nothing new is found, it
sends a low-priority "heartbeat" notification so you know the job is still
running correctly.

Requires only the Python standard library (no pip install step needed).
Expects the NTFY_TOPIC environment variable (set as a GitHub secret).
"""

import json
import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

KEYWORDS = [
    "CISF",
    "SILIGURI CORRIDOR",
    "SILIGURI",
    "DARJEELING",
    "KALIMPONG",
    "TEESTA",
    "NHPC",
]

STATE_FILE = "state.json"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}" if NTFY_TOPIC else None


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"seen_links": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_news(keyword):
    query = urllib.parse.quote(keyword)
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read()
    root = ET.fromstring(data)
    items = []
    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        items.append((title, link))
    return items


def send_notification(title, message, priority="default"):
    if not NTFY_URL:
        print("NTFY_TOPIC not set, skipping notification. Message:", title, message)
        return
    req = urllib.request.Request(
        NTFY_URL,
        data=message.encode("utf-8"),
        headers={"Title": title, "Priority": priority},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=20)


def main():
    state = load_state()
    seen = set(state.get("seen_links", []))
    new_items = []

    for kw in KEYWORDS:
        try:
            articles = fetch_news(kw)
        except Exception as e:
            print(f"Error fetching for '{kw}': {e}")
            continue
        for title, link in articles:
            if link not in seen:
                new_items.append((kw, title, link))
                seen.add(link)

    if new_items:
        for kw, title, link in new_items:
            send_notification(f"\U0001F514 {kw}", f"{title}\n{link}", priority="high")
            print("Sent alert:", kw, "-", title)
    else:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        send_notification(
            "Keyword Monitor: No new alerts",
            f"Checked at {now}. No new matches.",
            priority="min",
        )
        print("No new items found. Sent heartbeat notification.")

    state["seen_links"] = list(seen)[-2000:]  # keep state file bounded
    save_state(state)


if __name__ == "__main__":
    main()
