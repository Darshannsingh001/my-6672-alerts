"""
Keyword Monitor
---------------
Checks Google News RSS for a set of keywords individually. 

For each keyword:
- If new articles are found, it sends a high-priority notification with ALL links.
- If no new articles are found, it sends a low-priority notification specifically 
  for that keyword stating "No new updates since last run".

Requires only the Python standard library (no pip install step needed).
Expects the NTFY_TOPIC environment variable.
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

SECONDS_BETWEEN_NOTIFICATIONS = 3       # Rate limit buffer for ntfy.sh
MAX_PAYLOAD_BYTES = 3500                 # Safe limit per ntfy message (~4096 max)


def load_state():
    """Loads state.json, preserving stored list order."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load {STATE_FILE} ({e}). Starting fresh.")
    return {"seen_links": []}


def save_state(seen_links_list):
    """Saves up to 3,000 recent items while preserving strict insertion order."""
    trimmed = seen_links_list[-3000:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"seen_links": trimmed}, f, indent=2)


def fetch_news(keyword):
    """Fetches RSS results for a keyword using Google News RSS search."""
    query = urllib.parse.quote(keyword)
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read()
        
    root = ET.fromstring(data)
    items = []
    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        guid = item.findtext("guid", link).strip()
        if title and link:
            items.append((title, link, guid))
    return items


def send_notification(title, message, priority="default", tags="", retries=3):
    """Sends a push notification via ntfy.sh with retry logic for 429 rate limits."""
    if not NTFY_URL:
        print(f"NTFY_TOPIC not set. Skipping notification:\n[{title}]\n{message}")
        return

    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = tags

    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                NTFY_URL,
                data=message.encode("utf-8"),
                headers=headers,
                method="POST",
            )
            urllib.request.urlopen(req, timeout=20)
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = 10 * attempt
                print(f"Rate limited (429), waiting {wait}s before retry {attempt + 1}/{retries}...")
                time.sleep(wait)
                continue
            print(f"Failed to send notification '{title}': {e}")
            return
        except Exception as e:
            print(f"Failed to send notification '{title}': {e}")
            return


def send_keyword_digest(kw, items):
    """
    Formats and sends ALL items for a keyword. If total text size exceeds 
    MAX_PAYLOAD_BYTES, automatically splits into numbered messages (Part 1/2, etc.).
    """
    formatted_items = [f"{i+1}. {title}\n{link}" for i, (title, link) in enumerate(items)]
    
    chunks = []
    current_chunk = []
    current_length = 0

    for item_str in formatted_items:
        item_bytes = len(item_str.encode("utf-8")) + 2  # +2 for double newline
        if current_chunk and (current_length + item_bytes > MAX_PAYLOAD_BYTES):
            chunks.append(current_chunk)
            current_chunk = [item_str]
            current_length = item_bytes
        else:
            current_chunk.append(item_str)
            current_length += item_bytes

    if current_chunk:
        chunks.append(current_chunk)

    total_chunks = len(chunks)
    for idx, chunk in enumerate(chunks, 1):
        part_suffix = f" (Part {idx}/{total_chunks})" if total_chunks > 1 else ""
        title = f"{kw} ({len(items)} new){part_suffix}"
        message = "\n\n".join(chunk)
        
        send_notification(
            title,
            message,
            priority="high",
            tags="bell",
        )
        print(f"Sent digest for '{kw}'{part_suffix}: {len(chunk)} item(s)")
        time.sleep(SECONDS_BETWEEN_NOTIFICATIONS)


def main():
    state = load_state()
    
    seen_links_list = state.get("seen_links", [])
    seen_set = set(seen_links_list)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    try:
        for kw in KEYWORDS:
            try:
                articles = fetch_news(kw)
            except Exception as e:
                print(f"Error fetching RSS for '{kw}': {e}")
                articles = []

            new_items = []
            for title, link, guid in articles:
                item_id = guid if guid else link
                if item_id not in seen_set:
                    new_items.append((title, link))
                    seen_set.add(item_id)
                    seen_links_list.append(item_id)

            if new_items:
                send_keyword_digest(kw, new_items)
            else:
                # Send separate "No updates" notification for this specific keyword
                send_notification(
                    f"{kw}: No new updates",
                    f"Checked at {now}. No new articles found since last run.",
                    priority="min",
                    tags="white_check_mark",
                )
                print(f"No new items for '{kw}'. Sent separate heartbeat.")
                time.sleep(SECONDS_BETWEEN_NOTIFICATIONS)

    finally:
        save_state(seen_links_list)


if __name__ == "__main__":
    main()
