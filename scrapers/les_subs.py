"""Scraper for Les Subsistances (les-subs.com/agenda).

Approach: walk the DOM in document order. Track the "current" event URL
(updated each time we encounter an /evenement/ link). For every text node
containing a date pattern, attribute the date to the current event URL.

This works for flat layouts where event title links and their date pills
are siblings under a common parent — exactly what the diagnostic showed:
63 /evenement/ links, 98 date matches, 0 h2/h3 elements.
"""
from typing import List, Optional
import re
import sys
import requests
from bs4 import BeautifulSoup, NavigableString

from .base import Event, parse_french_date, iso

VENUE = "Les Subsistances"
SLUG = "les-subs"
URL = "https://www.les-subs.com/agenda/"
HOST = "https://www.les-subs.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Bullet date pattern: "mer. 6 Mai | 18:30"
DATE_RE = re.compile(
    r"\b(\w+)\.?\s+(\d{1,2})\s+(\w+)\s*\|\s*(\d{1,2}):(\d{2})",
    re.IGNORECASE,
)


def _clean_title(raw: str) -> str:
    """Many Les Subs links have their text duplicated, e.g.
    'Fun Times Fun Times' -> 'Fun Times'. Detect & collapse such repeats.
    """
    raw = raw.strip()
    if not raw:
        return raw
    words = raw.split()
    n = len(words)
    if n >= 2 and n % 2 == 0:
        half = n // 2
        if words[:half] == words[half:]:
            return " ".join(words[:half])
    return raw


def fetch() -> List[Event]:
    resp = requests.get(URL, timeout=20, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # url -> {"title": ..., "image": ..., "dates": set of (day, month, hh, mm)}
    events_by_url: dict = {}
    current_url: Optional[str] = None

    for el in soup.descendants:
        # When we enter an /evenement/ link, switch the "current event" pointer
        if hasattr(el, "name") and el.name == "a":
            href = el.get("href", "") or ""
            if "/evenement/" in href:
                if href.startswith("/"):
                    href = HOST + href
                current_url = href
                if href not in events_by_url:
                    title = _clean_title(el.get_text(" ", strip=True))
                    image = None
                    img = el.find("img")
                    if img:
                        src = img.get("src", "") or ""
                        if src.startswith("http"):
                            image = src
                    events_by_url[href] = {
                        "title": title,
                        "image": image,
                        "dates": set(),
                    }
            continue

        # Attribute any date in a text node to the current event
        if isinstance(el, NavigableString):
            text = str(el)
            if not text or "|" not in text:
                continue
            for m in DATE_RE.finditer(text):
                if current_url is None:
                    continue
                info = events_by_url.get(current_url)
                if info is None:
                    continue
                # store as (day_num, month_str, hour, minute) — strip day_name
                _, day_num, month_str, hour, minute = m.groups()
                info["dates"].add((day_num, month_str, hour, minute))

    events: List[Event] = []
    for url, info in events_by_url.items():
        title = info["title"]
        if not title or len(title) < 2 or len(title) > 200:
            continue
        for day_num, month_str, hour, minute in info["dates"]:
            d = parse_french_date(f"{day_num} {month_str}")
            if not d:
                continue
            events.append(Event(
                venue=VENUE,
                venue_slug=SLUG,
                title=title,
                subtitle=None,
                category=None,
                date_start=iso(d),
                date_end=None,
                time=f"{int(hour):02d}:{minute}",
                url=url,
                image=info["image"],
            ))

    if not events:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: Les Subs scraper found 0 events.", file=sys.stderr)
        print(f"  URLs collected: {len(events_by_url)}", file=sys.stderr)
        for url, info in list(events_by_url.items())[:5]:
            print(f"    - {url}: title={info['title']!r}, "
                  f"dates={len(info['dates'])}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    # Sort by date for stable output
    events.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, e.time or "  -  ", "·", e.title, "·", e.url)
