"""Scraper for L'Opéra national de Lyon (opera-lyon.com).

The season program lives at /programmation-reservations/saison-{YEAR1}-{YEAR2}.
Each event card is wrapped in <a href="/fr/programmation/saison-{Y}-{Y+1}/<category>/<slug>">
where category is one of: opera, danse, concert, evenement, opera-underground,
visites.

Date format examples:
- "9 mai 2026" (single)
- "6 mai - 7 mai 2026" (range, single month)
- "26 mars - 11 juil. 2026" (range, different months)
- "20 déc. 2025 - 18 janv. 2026" (range crossing years)
"""
from typing import List, Optional, Tuple
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso, FR_MONTHS

VENUE = "Opéra national de Lyon"
SLUG = "opera-lyon"
HOST = "https://www.opera-lyon.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Both seasons (current + next), in case overlap and for forward visibility.
URLS = [
    HOST + "/programmation-reservations/saison-2025-2026",
    HOST + "/programmation-reservations/saison-2026-2027",
]

# Map URL category segment -> human-readable category for our display.
URL_CATEGORY_MAP = {
    "opera": "opéra",
    "danse": "danse",
    "concert": "concert",
    "evenement": "événement",
    "opera-underground": "underground",
    "visites": "visite",
    "festival": "festival",
}

# Short-month abbreviations used by Opera Lyon (e.g. "juil.", "févr.")
SHORT_MONTHS = {
    "janv": 1, "fevr": 2, "févr": 2, "mars": 3, "avr": 4, "mai": 5,
    "juin": 6, "juil": 7, "aout": 8, "août": 8, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12, "déc": 12,
}

# Single date "9 mai 2026"
DATE_SINGLE = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+\.?)\s+(\d{4})\b",
    re.IGNORECASE,
)
# Range "6 mai - 7 mai 2026" — both same month
DATE_RANGE_SAME = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+\.?)\s*[-–]\s*(\d{1,2})\s+([\wéèêôû]+\.?)\s+(\d{4})\b",
    re.IGNORECASE,
)


def _normalize_month(s: str) -> Optional[int]:
    s = s.lower().rstrip(".")
    s = (s.replace("é", "e").replace("è", "e").replace("ê", "e")
           .replace("ô", "o").replace("û", "u"))
    if s in FR_MONTHS:
        return FR_MONTHS[s]
    return SHORT_MONTHS.get(s)


def _extract_dates(text: str) -> Tuple[Optional[Date], Optional[Date]]:
    """Return (date_start, date_end) or (None, None) if no date found.
    date_end is None for single-date events.
    """
    # Range with two months: "6 mai - 7 mai 2026" or "26 mars - 11 juil. 2026"
    m = DATE_RANGE_SAME.search(text)
    if m:
        d1, mo1, d2, mo2, yr = m.groups()
        month1 = _normalize_month(mo1)
        month2 = _normalize_month(mo2)
        year = int(yr)
        if month1 and month2:
            try:
                # If the start month is later in the year than the end month,
                # the start is in the previous year.
                start_year = year - 1 if month1 > month2 else year
                start = Date(start_year, month1, int(d1))
                end = Date(year, month2, int(d2))
                return start, end
            except ValueError:
                pass

    # Single date
    m = DATE_SINGLE.search(text)
    if m:
        d, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                return Date(int(yr), month, int(d)), None
            except ValueError:
                pass

    return None, None


def _category_from_url(href: str) -> Optional[str]:
    """Extract category from URL path."""
    m = re.search(r"/programmation/saison-\d{4}-\d{4}/([^/]+)/", href)
    if m:
        seg = m.group(1).lower()
        return URL_CATEGORY_MAP.get(seg, seg)
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

    for a in soup.select('a[href*="/programmation/saison-"]'):
        href = a.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        # Skip the season root listing
        if "/programmation/saison-" not in href:
            continue
        # Filter out anchors back to the current page
        if href in (url, url + "/"):
            continue
        if href in seen_urls:
            continue

        text = a.get_text(" ", strip=True)
        d_start, d_end = _extract_dates(text)
        if not d_start:
            continue
        # Skip events fully in the past
        if d_start < today and (d_end is None or d_end < today):
            continue

        # Title: look for a heading or strong text. Opera-Lyon uses neither
        # a clear h2 nor strong inside cards — the title is the largest
        # text node not matching the date.
        # Try: skip image + date, the rest of the link text is title +
        # subtitle. We split on the date to extract the bit before/after.
        # Cleaner approach: use stripped strings, filter out date+meta.
        text_nodes = [t for t in a.stripped_strings]
        # Discard nodes that match date patterns or are filter labels
        candidates: List[str] = []
        for tn in text_nodes:
            if DATE_SINGLE.fullmatch(tn) or DATE_RANGE_SAME.fullmatch(tn):
                continue
            if tn.lower() in ("réserver", "programme", "filtrer", "+", "concert",
                              "opéra", "danse", "évènement", "festival", "visites",
                              "visite guidée", "opéra underground", "voir tout",
                              "plus", "en savoir +"):
                continue
            if tn.lower().startswith("dès "):  # "Dès 7 ans"
                continue
            if len(tn) < 2 or len(tn) > 200:
                continue
            candidates.append(tn)
        if not candidates:
            continue
        # Title = first non-meta candidate. Subtitle = next one if any.
        title = candidates[0]
        subtitle = candidates[1] if len(candidates) > 1 else None
        # If subtitle looks like a date or location (single short word), skip
        if subtitle and (len(subtitle) > 200 or subtitle.lower() in ("dès 12 ans", "dès 14 ans")):
            subtitle = None

        category = _category_from_url(href) or "spectacle"

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
            subtitle=subtitle,
            category=category,
            date_start=iso(d_start),
            date_end=iso(d_end) if d_end else None,
            time=None,
            url=href,
            image=image,
        ))

    return events


def fetch() -> List[Event]:
    all_events: List[Event] = []
    for url in URLS:
        all_events.extend(_scrape_url(url))

    seen, unique = set(), []
    for e in all_events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)

    if not unique:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: Opéra de Lyon — 0 events", file=sys.stderr)
        for url in URLS:
            try:
                resp = requests.get(url, timeout=15, headers=HEADERS)
                print(f"  {url} -> {resp.status_code} ({len(resp.text)} bytes)",
                      file=sys.stderr)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    links = soup.select('a[href*="/programmation/saison-"]')
                    print(f"    /programmation/saison-* links: {len(links)}",
                          file=sys.stderr)
                    for a in links[:5]:
                        h = a.get('href', '')[:120]
                        t = a.get_text(' ', strip=True)[:80]
                        print(f"      - {h!r} | {t!r}", file=sys.stderr)
            except requests.RequestException as e:
                print(f"  {url} -> failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    unique.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "·", e.category, "·", e.title, "·", e.url)
