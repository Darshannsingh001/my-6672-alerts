"""
Keyword Monitor
---------------
Checks Google News RSS for a set of keywords, and sends a push notification
(via ntfy.sh) for any new matching articles. If nothing new is found, it
sends a low-priority "heartbeat" notification so you know the job is still
running correctly.

New articles are batched into ONE digest notification per keyword per run
(capped, with a "+N more" note) rather than one notification per article —
this avoids ntfy's rate limits and avoids spamming your phone.

Requires only the Python standard library (no pip install step needed).
Expects the NTFY_TOPIC environment variable (set as a GitHub secret).
"""

import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error
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

MAX_ITEMS_PER_KEYWORD_NOTIFICATION = 5  # avoid huge/spammy messages
SECONDS_BETWEEN_NOTIFICATIONS = 3       # stay well under ntfy's rate limit


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


def send_notification(title, message, priority="default", tags="", retries=3):
    if not NTFY_URL:
        print("NTFY_TOPIC not set, skipping notification. Message:", title, message)
        return
    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = tags
    req = urllib.request.Request(
        NTFY_URL,
        data=message.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    for attempt in range(1, retries + 1):
        try:
            urllib.request.urlopen(req, timeout=20)
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = 10 * attempt
                print(f"Rate limited (429), waiting {wait}s before retry...")
                time.sleep(wait)
                continue
            print(f"Failed to send notification '{title}': {e}")
            return
        except Exception as e:
            print(f"Failed to send notification '{title}': {e}")
            return


def main():
    state = load_state()
    seen = set(state.get("seen_links", []))
    new_by_keyword = {}

    try:
        for kw in KEYWORDS:
            try:
                articles = fetch_news(kw)
            except Exception as e:
                print(f"Error fetching for '{kw}': {e}")
                continue
            for title, link in articles:
                if link not in seen:
                    new_by_keyword.setdefault(kw, []).append((title, link))
                    seen.add(link)

        if new_by_keyword:
            for kw, items in new_by_keyword.items():
                shown = items[:MAX_ITEMS_PER_KEYWORD_NOTIFICATION]
                lines = [f"- {title}\n  {link}" for title, link in shown]
                extra = len(items) - len(shown)
                if extra > 0:
                    lines.append(f"...and {extra} more")
                message = "\n".join(lines)
                send_notification(
                    f"{kw} ({len(items)} new)",
                    message,
                    priority="high",
                    tags="bell",
                )
                print(f"Sent digest for '{kw}': {len(items)} new item(s)")
                time.sleep(SECONDS_BETWEEN_NOTIFICATIONS)
        else:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            send_notification(
                "Keyword Monitor: No new alerts",
                f"Checked at {now}. No new matches.",
                priority="min",
                tags="white_check_mark",
            )
            print("No new items found. Sent heartbeat notification.")
    finally:
        # Always save progress, even if a notification failed partway through,
        # so we never re-send the same articles on the next run.
        state["seen_links"] = list(seen)[-3000:]
        save_state(state)


if __name__ == "__main__":
    main()
