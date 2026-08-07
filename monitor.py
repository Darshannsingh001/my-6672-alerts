"""
Keyword Monitor (Security & Administrative Filtered)
---------------------------------------------------
Checks Google News RSS for a set of target keywords specifically scoped to
security and administrative topics. Sends a push notification (via ntfy.sh)
for new matching articles. If nothing new is found, sends a low-priority
heartbeat notification.

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

# Target location and organization keywords
KEYWORDS = [
    "CISF",
    "SILIGURI CORRIDOR",
    "SILIGURI",
    "DARJEELING",
    "KALIMPONG",
    "TEESTA",
    "NHPC",
]

# Query filter enforcing security & administrative relevance
SECURITY_ADMIN_FILTER = (
    "security OR administration OR police OR deployment OR "
    '"law and order" OR border OR intelligence OR government OR "district magistrate"'
)

STATE_FILE = "state.json"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}" if NTFY_TOPIC else None

MAX_ITEMS_PER_KEYWORD_NOTIFICATION = 5  # Cap items per notification digest
SECONDS_BETWEEN_NOTIFICATIONS = 3       # Rate limit buffer for ntfy.sh


def load_state():
    """Loads state.json, returning stored list of seen identifiers."""
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
    """
    Fetches Google News RSS items for a keyword filtered strictly by security
    and administrative terms.
    """
    full_query = f'"{keyword}" ({SECURITY_ADMIN_FILTER})'
    query_encoded = urllib.parse.quote(full_query)
    url = f"https://news.google.com/rss/search?q={query_encoded}&hl=en-IN&gl=IN&ceid=IN:en"
    
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
    """Sends push notification via ntfy.sh with retry logic for rate limits."""
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


def main():
    state = load_state()
    
    # Maintain list for chronological ordering and set for O(1) deduplication
    seen_links_list = state.get("seen_links", [])
    seen_set = set(seen_links_list)
    
    new_by_keyword = {}

    try:
        for kw in KEYWORDS:
            try:
                articles = fetch_news(kw)
            except Exception as e:
                print(f"Error fetching RSS for '{kw}': {e}")
                continue

            for title, link, guid in articles:
                item_id = guid if guid else link
                if item_id not in seen_set:
                    new_by_keyword.setdefault(kw, []).append((title, link))
                    seen_set.add(item_id)
                    seen_links_list.append(item_id)

        if new_by_keyword:
            for kw, items in new_by_keyword.items():
                shown = items[:MAX_ITEMS_PER_KEYWORD_NOTIFICATION]
                lines = [f"- {title}\n  {link}" for title, link in shown]
                extra = len(items) - len(shown)
                if extra > 0:
                    lines.append(f"...and {extra} more")
                
                message = "\n".join(lines)
                send_notification(
                    f"{kw} [Security/Admin] ({len(items)} new)",
                    message,
                    priority="high",
                    tags="shield,bell",
                )
                print(f"Sent digest for '{kw}': {len(items)} new item(s)")
                time.sleep(SECONDS_BETWEEN_NOTIFICATIONS)
        else:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            send_notification(
                "Keyword Monitor: No new security/admin alerts",
                f"Checked at {now}. No new matches.",
                priority="min",
                tags="white_check_mark",
            )
            print("No new items found. Sent heartbeat notification.")
    finally:
        # Preserve actual state progression on disk
        save_state(seen_links_list)


if __name__ == "__main__":
    main()
