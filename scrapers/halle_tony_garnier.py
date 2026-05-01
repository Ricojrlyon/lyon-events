"""Scraper for La Halle Tony Garnier (halle-tony-garnier.com).

Page structure (verified):
- Each event is wrapped in an <a href="/fr/programmation/<slug>">.
- Inside: image, date "DD.MM.YY", time "HHhMM", title in uppercase.
- Some events span multiple days: "28.02 au 01.03.26".

We scrape /fr/programmation (the full listing) and fall back to / (homepage)
which shows the next 8-10 events.
"""
from typing import List, Optional
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso

VENUE = "La Halle Tony Garnier"
SLUG = "halle-tony-garnier"
HOST = "https://www.halle-tony-garnier.com"

URLS = [
    HOST + "/fr/programmation",
    HOST + "/",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Single date "14.03.26" or "DD.MM.YY"
DATE_SINGLE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{2})\b")
# Range "28.02 au 01.03.26" — captures start day, start month, end day, end month, year
DATE_RANGE = re.compile(
    r"\b(\d{2})\.(\d{2})(?:\.(\d{2}))?\s+au\s+(\d{2})\.(\d{2})\.(\d{2})\b"
)
# Time "20h00" or "20h"
TIME_RE = re.compile(r"\b(\d{1,2})h(\d{2})?\b")


def _parse_date(yy: str, mm: str, dd: str) -> Optional[Date]:
    try:
        # Year is two digits, e.g. "26" -> 2026
        year = 2000 + int(yy)
        return Date(year, int(mm), int(dd))
    except ValueError:
        return None


def _scrape_url(url: str) -> List[Event]:
    try:
        resp = requests.get(url, timeout=20, headers=HEADERS)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    events: List[Event] = []
    seen_urls: set = set()
    today = Date.today()

    for a in soup.select('a[href*="/fr/programmation/"]'):
        href = a.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        # Skip the listing page itself
        if href.rstrip("/") in (HOST + "/fr/programmation",):
            continue
        if href in seen_urls:
            continue

        text = a.get_text(" ", strip=True)

        # Try date range first, then single date
        d_start: Optional[Date] = None
        d_end: Optional[Date] = None

        m_range = DATE_RANGE.search(text)
        if m_range:
            d1, m1, y1, d2, m2, y2 = m_range.groups()
            year1 = y1 if y1 else y2
            d_start = _parse_date(year1, m1, d1)
            d_end = _parse_date(y2, m2, d2)
        else:
            m_single = DATE_SINGLE.search(text)
            if m_single:
                dd, mm, yy = m_single.groups()
                d_start = _parse_date(yy, mm, dd)

        if not d_start:
            continue
        if d_start < today:
            # Allow ongoing ranges where end_date is in the future
            if not d_end or d_end < today:
                continue

        # Title: usually all caps. Skip text that's just the date/time.
        # Strategy: take the longest plausible title-like substring.
        title = ""
        # The link's structure is image, date, time, title. The title text
        # typically comes last and is in uppercase.
        # Walk over text nodes
        text_nodes = [t.strip() for t in a.stripped_strings if t.strip()]
        # Filter out date and time tokens
        candidates = []
        for tn in text_nodes:
            if DATE_SINGLE.fullmatch(tn):
                continue
            if DATE_RANGE.fullmatch(tn):
                continue
            if TIME_RE.fullmatch(tn):
                continue
            # Skip "complet" sticker
            if tn.lower() in ("complet", "complète"):
                continue
            # Skip very short / short tokens
            if len(tn) < 2:
                continue
            candidates.append(tn)
        # Pick the longest candidate as title (titles are typically the
        # most informative piece of text)
        if candidates:
            title = max(candidates, key=len)

        if not title or len(title) < 2 or len(title) > 200:
            continue

        # Time
        time_str: Optional[str] = None
        m_time = TIME_RE.search(text)
        if m_time:
            hh = int(m_time.group(1))
            mm = m_time.group(2) or "00"
            if 0 <= hh <= 23:
                time_str = f"{hh:02d}:{mm}"

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
            category="concert",
            date_start=iso(d_start),
            date_end=iso(d_end) if d_end else None,
            time=time_str,
            url=href,
            image=image,
        ))

    return events


def fetch() -> List[Event]:
    all_events: List[Event] = []
    for url in URLS:
        events = _scrape_url(url)
        all_events.extend(events)
        if events:
            # First URL with results is the canonical one
            break

    seen, unique = set(), []
    for e in all_events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)

    if not unique:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: Halle Tony Garnier — 0 events", file=sys.stderr)
        for url in URLS:
            try:
                resp = requests.get(url, timeout=15, headers=HEADERS)
                print(f"  {url} -> {resp.status_code} ({len(resp.text)} bytes)",
                      file=sys.stderr)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    links = soup.select('a[href*="/fr/programmation/"]')
                    print(f"    /fr/programmation/ links: {len(links)}",
                          file=sys.stderr)
                    for a in links[:5]:
                        h = a.get('href', '')
                        t = a.get_text(' ', strip=True)[:80]
                        print(f"      - {h!r} | {t!r}", file=sys.stderr)
            except requests.RequestException as e:
                print(f"  {url} -> failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    unique.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, e.time or "  -  ", "·", e.title, "·", e.url)
