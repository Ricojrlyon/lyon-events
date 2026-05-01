"""Scraper for Comédie Odéon (comedieodeon.com).

Page /spectacle/ lists all upcoming shows. Each card has:
- <h2> (or <h3>) title with a link to /spectacle/<slug>/
- Image
- Date in various formats:
    - "Du 15 au 25 avril 2026" (range, year explicit)
    - "du 22 avril au 02 mai 2026" (range crossing months, year explicit)
    - "Du 27 mai au 06 juin" (range, year missing → infer)
    - "Du 06 au 23 mai 2026 à 20h" (range with time)
    - "Samedi 06 juin à 19h" (single, year missing → infer)
    - "Lundi 15 juin à 20h"
    - "SAISON 2026-2027 / 12 et 13 mars 2027" (two dates, separator)
- "Réserver" / "Voir plus" links to drop
"""
from typing import List, Optional, Tuple
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso, FR_MONTHS

VENUE = "Comédie Odéon"
SLUG = "comedie-odeon"
HOST = "https://www.comedieodeon.com"
URL = HOST + "/spectacle/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# "Du 15 au 25 avril 2026" — same month range, with year
DATE_RANGE_SAME_MONTH = re.compile(
    r"\b[Dd]u\s+(\d{1,2})\s+au\s+(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
# "du 22 avril au 02 mai 2026" — different months
DATE_RANGE_DIFF_MONTH = re.compile(
    r"\b[Dd]u\s+(\d{1,2})\s+([\wéèêôû]+)\s+au\s+(\d{1,2})\s+([\wéèêôû]+)(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)
# "Du 27 mai au 06 juin" or "Du 27 au 06 mai" without year (infer)
DATE_RANGE_NO_YEAR = re.compile(
    r"\b[Dd]u\s+(\d{1,2})\s+au\s+(\d{1,2})\s+([\wéèêôû]+)(?!\s+\d{4})\b",
    re.IGNORECASE,
)
# "Samedi 06 juin" — single date with day name, no year
DAY_NAME_DATE_NO_YEAR = re.compile(
    r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+"
    r"(\d{1,2})\s+([\wéèêôû]+)(?!\s+\d{4})\b",
    re.IGNORECASE,
)
# "Samedi 20 juin 2026" — single date with day name AND year
DAY_NAME_DATE_YEAR = re.compile(
    r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+"
    r"(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
# "12 et 13 mars 2027" — two specific dates
DATE_TWO = re.compile(
    r"\b(\d{1,2})\s+et\s+(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
# "15 janvier 2027" — bare date
DATE_BARE = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
# Time "à 20h" or "à 21h"
TIME_RE = re.compile(r"à\s+(\d{1,2})h(\d{2})?", re.IGNORECASE)


def _normalize_month(s: str) -> Optional[int]:
    s = s.lower().rstrip(".")
    s = (s.replace("é", "e").replace("è", "e").replace("ê", "e")
           .replace("ô", "o").replace("û", "u"))
    return FR_MONTHS.get(s)


def _smart_year(month: int, day: int) -> int:
    """Infer year: if the date is in the past for current year, use next year."""
    today = Date.today()
    try:
        candidate = Date(today.year, month, day)
    except ValueError:
        return today.year
    return today.year + 1 if candidate < today else today.year


def _extract_dates(text: str) -> Tuple[Optional[Date], Optional[Date]]:
    # 1. "du 22 avril au 02 mai 2026" or "du 22 avril au 02 mai"
    m = DATE_RANGE_DIFF_MONTH.search(text)
    if m:
        d1, mo1, d2, mo2, yr = m.groups()
        month1 = _normalize_month(mo1)
        month2 = _normalize_month(mo2)
        if month1 and month2 and month1 != month2:
            try:
                if yr:
                    year = int(yr)
                    start_year = year - 1 if month1 > month2 else year
                    return (Date(start_year, month1, int(d1)),
                            Date(year, month2, int(d2)))
                else:
                    # Infer year from start
                    start_year = _smart_year(month1, int(d1))
                    end_year = start_year + 1 if month1 > month2 else start_year
                    return (Date(start_year, month1, int(d1)),
                            Date(end_year, month2, int(d2)))
            except ValueError:
                pass

    # 2. "Du 15 au 25 avril 2026" (same month, year explicit)
    m = DATE_RANGE_SAME_MONTH.search(text)
    if m:
        d1, d2, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                year = int(yr)
                return (Date(year, month, int(d1)),
                        Date(year, month, int(d2)))
            except ValueError:
                pass

    # 3. "Du 27 au 06 mai" (same month, no year — infer)
    m = DATE_RANGE_NO_YEAR.search(text)
    if m:
        d1, d2, mo = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                year = _smart_year(month, int(d1))
                return (Date(year, month, int(d1)),
                        Date(year, month, int(d2)))
            except ValueError:
                pass

    # 4. "Samedi 20 juin 2026" — day name + year
    m = DAY_NAME_DATE_YEAR.search(text)
    if m:
        d, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                return Date(int(yr), month, int(d)), None
            except ValueError:
                pass

    # 5. "Samedi 06 juin" — day name, no year (infer)
    m = DAY_NAME_DATE_NO_YEAR.search(text)
    if m:
        d, mo = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                year = _smart_year(month, int(d))
                return Date(year, month, int(d)), None
            except ValueError:
                pass

    # 6. "12 et 13 mars 2027" — two dates → range
    m = DATE_TWO.search(text)
    if m:
        d1, d2, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                year = int(yr)
                return (Date(year, month, int(d1)),
                        Date(year, month, int(d2)))
            except ValueError:
                pass

    # 7. Bare date "15 janvier 2027"
    m = DATE_BARE.search(text)
    if m:
        d, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                return Date(int(yr), month, int(d)), None
            except ValueError:
                pass

    return None, None


def _extract_time(text: str) -> Optional[str]:
    m = TIME_RE.search(text)
    if m:
        hh = int(m.group(1))
        mm = m.group(2) or "00"
        if 0 <= hh <= 23:
            return f"{hh:02d}:{mm}"
    return None


def _find_card(link: Tag, max_levels: int = 8) -> Optional[Tag]:
    """Walk up from link to find a parent containing a date and no other
    /spectacle/<slug>/ links."""
    el: Optional[Tag] = link
    target_href = link.get("href", "").split("?")[0]
    for _ in range(max_levels):
        parent = el.parent if el else None
        if parent is None or parent.name in ("html", "body"):
            return None
        el = parent
        text = el.get_text(" ", strip=True)
        if not DATE_BARE.search(text) and not DAY_NAME_DATE_NO_YEAR.search(text) and not DATE_RANGE_NO_YEAR.search(text):
            continue
        # Check no other /spectacle/<slug>/ link
        other = 0
        for a in el.select('a[href*="/spectacle/"]'):
            href = a.get("href", "").split("?")[0]
            if not href:
                continue
            # Skip the section root /spectacle/
            if href.rstrip("/") == HOST + "/spectacle":
                continue
            if href != target_href:
                other += 1
        if other == 0:
            return el
        return None
    return None


def fetch() -> List[Event]:
    try:
        resp = requests.get(URL, timeout=20, headers=HEADERS)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    events: List[Event] = []
    seen_urls: set = set()
    today = Date.today()

    # Anchor on h2 (titles) inside cards
    for h2 in soup.find_all(["h2", "h3"]):
        title = h2.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 250:
            continue
        # Find a /spectacle/<slug>/ link near this title
        # First try inside the h2, then in the card
        link = None
        # Look forward for the card link
        # Try the card from this h2
        card = _find_card(h2)
        if card is None:
            continue
        for a in card.select('a[href*="/spectacle/"]'):
            href = a.get("href", "").split("?")[0]
            if href.rstrip("/") == HOST + "/spectacle":
                continue
            link = a
            break
        if link is None:
            continue

        href = link.get("href", "").split("?")[0]
        if href.startswith("/"):
            href = HOST + href
        if href in seen_urls:
            continue

        text = card.get_text(" ", strip=True)
        d_start, d_end = _extract_dates(text)
        if not d_start:
            continue
        if d_start < today and (d_end is None or d_end < today):
            continue

        time_str = _extract_time(text)

        # Image
        image: Optional[str] = None
        img = card.find("img")
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
            category="théâtre",
            date_start=iso(d_start),
            date_end=iso(d_end) if d_end else None,
            time=time_str,
            url=href,
            image=image,
        ))

    if not events:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: Comédie Odéon — 0 events", file=sys.stderr)
        try:
            resp2 = requests.get(URL, timeout=15, headers=HEADERS)
            print(f"  {URL} -> {resp2.status_code} ({len(resp2.text)} bytes)",
                  file=sys.stderr)
            soup2 = BeautifulSoup(resp2.text, "html.parser")
            spec_links = soup2.select('a[href*="/spectacle/"]')
            print(f"  /spectacle/ links: {len(spec_links)}", file=sys.stderr)
            h2s = soup2.find_all("h2")
            print(f"  h2 count: {len(h2s)}", file=sys.stderr)
            for h in h2s[:5]:
                print(f"    - {h.get_text(strip=True)[:80]!r}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    events.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "→", e.date_end or "  -  ", e.time or "", "·", e.title)
