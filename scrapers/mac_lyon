"""Scraper for Musée d'Art Contemporain de Lyon (mac-lyon.com).

Two pages to scrape:
- /fr/expositions: current exhibitions, format "Vendredi 6 mars 2026 - Dimanche 12 juillet 2026"
- /fr/agenda: events (nocturnes, conferences, performances)

Each event has:
- <h2> (or h3) with title inside or near a <a href="/fr/programmation/<slug>">
- Date with "Date" label and the value below
- Category line "Exposition", "Rencontres", "Performances et ateliers..."
"""
from typing import List, Optional, Tuple
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso, FR_MONTHS

VENUE = "Musée d'Art Contemporain"
SLUG = "mac-lyon"
HOST = "https://www.mac-lyon.com"
URLS = [
    HOST + "/fr/expositions",
    HOST + "/fr/agenda",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# "Vendredi 6 mars 2026 - Dimanche 12 juillet 2026" — range with day names
DATE_RANGE = re.compile(
    r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+"
    r"(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\s*[-–]\s*"
    r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+"
    r"(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
# "Vendredi 6 mars 2026 - 18:30" — single date with time
DATE_SINGLE_TIME = re.compile(
    r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+"
    r"(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\s*[-–]\s*(\d{1,2}):(\d{2})\b",
    re.IGNORECASE,
)
# "Vendredi 6 mars 2026" — bare single
DATE_SINGLE = re.compile(
    r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+"
    r"(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)


def _normalize_month(s: str) -> Optional[int]:
    s = s.lower().rstrip(".")
    s = (s.replace("é", "e").replace("è", "e").replace("ê", "e")
           .replace("ô", "o").replace("û", "u"))
    return FR_MONTHS.get(s)


def _slug_from_href(href: str) -> str:
    if not href:
        return ""
    return href.split("?")[0].split("#")[0].rstrip("/").lower()


def _extract_dates_and_time(text: str) -> Tuple[Optional[Date], Optional[Date], Optional[str]]:
    """Returns (date_start, date_end, time)."""
    # 1. Range
    m = DATE_RANGE.search(text)
    if m:
        d1, mo1, y1, d2, mo2, y2 = m.groups()
        month1 = _normalize_month(mo1)
        month2 = _normalize_month(mo2)
        if month1 and month2:
            try:
                start = Date(int(y1), month1, int(d1))
                end = Date(int(y2), month2, int(d2))
                if end >= start:
                    return start, end, None
            except ValueError:
                pass

    # 2. Single with time
    m = DATE_SINGLE_TIME.search(text)
    if m:
        d, mo, yr, hh, mm = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                date = Date(int(yr), month, int(d))
                return date, None, f"{int(hh):02d}:{mm}"
            except ValueError:
                pass

    # 3. Single bare
    m = DATE_SINGLE.search(text)
    if m:
        d, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                return Date(int(yr), month, int(d)), None, None
            except ValueError:
                pass

    return None, None, None


def _find_card(link: Tag, max_levels: int = 8) -> Optional[Tag]:
    """Walk up to a card containing the link and at most one programmation slug."""
    el: Optional[Tag] = link
    target = _slug_from_href(link.get("href", ""))
    for _ in range(max_levels):
        parent = el.parent if el else None
        if parent is None or parent.name in ("html", "body"):
            return None
        el = parent
        text = el.get_text(" ", strip=True)
        if not DATE_SINGLE.search(text):
            continue
        # Distinct programmation slugs
        distinct = set()
        for a in el.select('a[href*="/fr/programmation/"]'):
            slug = _slug_from_href(a.get("href", ""))
            if slug and not slug.endswith("/fr/programmation"):
                distinct.add(slug)
        if len(distinct) <= 1:
            return el
        return None
    return None


def _scrape_page(url: str) -> List[Event]:
    try:
        resp = requests.get(url, timeout=20, headers=HEADERS)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    events: List[Event] = []
    seen_slugs: set = set()
    today = Date.today()

    for link in soup.select('a[href*="/fr/programmation/"]'):
        href = link.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        slug = _slug_from_href(href)
        if not slug or slug in seen_slugs:
            continue
        if slug.endswith("/fr/programmation"):
            continue

        card = _find_card(link)
        if card is None:
            continue

        text = card.get_text(" ", strip=True)
        d_start, d_end, time_str = _extract_dates_and_time(text)
        if not d_start:
            continue
        if d_start < today and (d_end is None or d_end < today):
            continue

        # Title: h2 or h3 in card
        title_el = card.find(["h2", "h3"])
        if title_el:
            title = title_el.get_text(" ", strip=True)
        else:
            title = link.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 250:
            continue
        if title.lower() in ("en savoir +", "en savoir plus", "actuellement -"):
            continue

        # Image
        image: Optional[str] = None
        img = card.find("img")
        if img:
            src = img.get("src", "") or ""
            if src.startswith("http"):
                image = src
            elif src.startswith("/"):
                image = HOST + src

        # Category: try to detect
        category: Optional[str] = None
        text_lower = text.lower()
        for kw in ("exposition", "rencontres", "performances",
                   "atelier", "nocturne", "conférence", "visite"):
            if kw in text_lower:
                category = kw
                break

        seen_slugs.add(slug)
        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=None,
            category=category or "exposition",
            date_start=iso(d_start),
            date_end=iso(d_end) if d_end else None,
            time=time_str,
            url=href.split("?")[0],
            image=image,
        ))

    return events


def fetch() -> List[Event]:
    all_events: List[Event] = []
    for url in URLS:
        all_events.extend(_scrape_page(url))

    seen, unique = set(), []
    for e in all_events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)

    if not unique:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: MAC Lyon — 0 events", file=sys.stderr)
        for url in URLS:
            try:
                resp = requests.get(url, timeout=15, headers=HEADERS)
                print(f"  {url} -> {resp.status_code} ({len(resp.text)} bytes)",
                      file=sys.stderr)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    links = soup.select('a[href*="/fr/programmation/"]')
                    distinct = set()
                    for a in links:
                        s = _slug_from_href(a.get("href", ""))
                        if s and not s.endswith("/fr/programmation"):
                            distinct.add(s)
                    print(f"  Distinct /fr/programmation/ slugs: {len(distinct)}",
                          file=sys.stderr)
                    page_text = soup.get_text(" ", strip=True)[:500]
                    print(f"  page text excerpt: {page_text!r}", file=sys.stderr)
            except requests.RequestException as e:
                print(f"  {url} -> failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    unique.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "→", e.date_end or "  -  ", e.time or "", "·", e.title)
