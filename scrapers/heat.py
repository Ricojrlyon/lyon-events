"""Scraper for HEAT (h-eat.eu/events/).

Page structure (verified):
- Each event is wrapped in an <a href="/events/<slug>/">.
- Inside: image, date pill ("mer. 29 avr.") and <h2> title.
- Date format: short day name + DD + short month name (3 letters, sometimes
  with trailing dot, sometimes "juill" for July).

The page lists events in two sections "Cette semaine" and "Soon", but we
just enumerate all /events/ links on the page.
"""
from typing import List, Optional
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso

VENUE = "HEAT"
SLUG = "heat"
URL = "https://h-eat.eu/events/"
HOST = "https://h-eat.eu"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Short month name -> month number, including "juill" for juillet.
SHORT_MONTHS = {
    "janv": 1, "fevr": 2, "févr": 2, "mars": 3, "avr": 4, "mai": 5,
    "juin": 6, "juil": 7, "juill": 7, "aout": 8, "août": 8, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12, "déc": 12,
}

# "mer. 29 avr." or "jeu. 02 juill."
DATE_RE = re.compile(
    r"\b\w+\.?\s+(\d{1,2})\s+(janv|f[eé]vr|mars|avr|mai|juin|juill?|"
    r"ao[uû]t|sept|oct|nov|d[eé]c)\.?",
    re.IGNORECASE,
)

CATEGORIES = (
    "afterwork", "atelier", "blindtest", "blind test", "club labo",
    "comedy lab", "danse", "dj set", "festival", "jeux", "market",
    "open air", "sport",
)


def _smart_year(month: int, day: int) -> int:
    today = Date.today()
    try:
        candidate = Date(today.year, month, day)
    except ValueError:
        return today.year
    return today.year + 1 if candidate < today else today.year


def _normalize_month(s: str) -> Optional[int]:
    """Map short month name to int. Strips accents and trailing 'l'."""
    s = s.lower().rstrip(".")
    s = s.replace("é", "e").replace("è", "e").replace("ê", "e").replace("ô", "o").replace("û", "u")
    return SHORT_MONTHS.get(s)


def fetch() -> List[Event]:
    resp = requests.get(URL, timeout=20, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    events: List[Event] = []
    seen_urls: set = set()

    for a in soup.select('a[href*="/events/"]'):
        href = a.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        if not href.startswith("http"):
            continue
        # Skip the events listing root
        if href.rstrip("/") in (HOST + "/events", HOST + "/events-archives"):
            continue
        if href in seen_urls:
            continue

        text = a.get_text(" ", strip=True)
        m = DATE_RE.search(text)
        if not m:
            continue
        day = int(m.group(1))
        month = _normalize_month(m.group(2))
        if not month:
            continue
        try:
            year = _smart_year(month, day)
            d = Date(year, month, day)
        except ValueError:
            continue

        # Title from <h2>
        title_el = a.find("h2")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 250:
            continue

        # Category: try to detect from page text near the link (HEAT lists
        # category tags in the navbar but not per card)
        category: Optional[str] = None
        text_lower = text.lower()
        for kw in CATEGORIES:
            if kw in text_lower:
                category = kw.replace(" ", "-")
                break

        # Image
        image: Optional[str] = None
        img = a.find("img")
        if img:
            src = img.get("src", "") or ""
            if src.startswith("http"):
                image = src

        seen_urls.add(href)
        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=None,
            category=category,
            date_start=iso(d),
            date_end=None,
            time=None,
            url=href,
            image=image,
        ))

    if not events:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: HEAT — 0 events", file=sys.stderr)
        links = soup.select('a[href*="/events/"]')
        print(f"  /events/ links: {len(links)}", file=sys.stderr)
        for a in links[:5]:
            t = a.get_text(' ', strip=True)[:100]
            print(f"    - {a.get('href', '')!r} | text: {t!r}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    events.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "·", e.title, "·", e.url)
