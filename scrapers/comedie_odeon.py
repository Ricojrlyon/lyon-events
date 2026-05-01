"""Scraper for Comédie Odéon (comedieodeon.com).

v2: fix _find_card to allow multiple links to the same slug.
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

DATE_RANGE_SAME_MONTH = re.compile(
    r"\b[Dd]u\s+(\d{1,2})\s+au\s+(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
DATE_RANGE_DIFF_MONTH = re.compile(
    r"\b[Dd]u\s+(\d{1,2})\s+([\wéèêôû]+)\s+au\s+(\d{1,2})\s+([\wéèêôû]+)(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)
DATE_RANGE_NO_YEAR = re.compile(
    r"\b[Dd]u\s+(\d{1,2})\s+au\s+(\d{1,2})\s+([\wéèêôû]+)(?!\s+\d{4})\b",
    re.IGNORECASE,
)
DAY_NAME_DATE_NO_YEAR = re.compile(
    r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+"
    r"(\d{1,2})\s+([\wéèêôû]+)(?!\s+\d{4})\b",
    re.IGNORECASE,
)
DAY_NAME_DATE_YEAR = re.compile(
    r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+"
    r"(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
DATE_TWO = re.compile(
    r"\b(\d{1,2})\s+et\s+(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
DATE_BARE = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"à\s+(\d{1,2})h(\d{2})?", re.IGNORECASE)


def _normalize_month(s: str) -> Optional[int]:
    s = s.lower().rstrip(".")
    s = (s.replace("é", "e").replace("è", "e").replace("ê", "e")
           .replace("ô", "o").replace("û", "u"))
    return FR_MONTHS.get(s)


def _smart_year(month: int, day: int) -> int:
    today = Date.today()
    try:
        candidate = Date(today.year, month, day)
    except ValueError:
        return today.year
    return today.year + 1 if candidate < today else today.year


def _slug_from_href(href: str) -> str:
    if not href:
        return ""
    href = href.split("?")[0].split("#")[0]
    return href.rstrip("/").lower()


def _has_any_date(text: str) -> bool:
    """Check whether text contains any plausible date pattern."""
    return bool(
        DATE_BARE.search(text) or
        DAY_NAME_DATE_NO_YEAR.search(text) or
        DATE_RANGE_NO_YEAR.search(text)
    )


def _extract_dates(text: str) -> Tuple[Optional[Date], Optional[Date]]:
    # 1. "du X mois1 au Y mois2 [year]"
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
                    start_year = _smart_year(month1, int(d1))
                    end_year = start_year + 1 if month1 > month2 else start_year
                    return (Date(start_year, month1, int(d1)),
                            Date(end_year, month2, int(d2)))
            except ValueError:
                pass

    # 2. "Du X au Y mois year"
    m = DATE_RANGE_SAME_MONTH.search(text)
    if m:
        d1, d2, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                year = int(yr)
                return (Date(year, month, int(d1)), Date(year, month, int(d2)))
            except ValueError:
                pass

    # 3. "Du X au Y mois" (no year)
    m = DATE_RANGE_NO_YEAR.search(text)
    if m:
        d1, d2, mo = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                year = _smart_year(month, int(d1))
                return (Date(year, month, int(d1)), Date(year, month, int(d2)))
            except ValueError:
                pass

    # 4. "Samedi X mois year"
    m = DAY_NAME_DATE_YEAR.search(text)
    if m:
        d, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                return Date(int(yr), month, int(d)), None
            except ValueError:
                pass

    # 5. "Samedi X mois" (no year)
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

    # 6. "X et Y mois year"
    m = DATE_TWO.search(text)
    if m:
        d1, d2, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                year = int(yr)
                return (Date(year, month, int(d1)), Date(year, month, int(d2)))
            except ValueError:
                pass

    # 7. Bare "X mois year"
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
    """Walk up from link to find the smallest ancestor that:
    - Contains a date pattern.
    - Does NOT contain links to OTHER /spectacle/<slug>/ slugs.
    """
    el: Optional[Tag] = link
    for _ in range(max_levels):
        parent = el.parent if el else None
        if parent is None or parent.name in ("html", "body"):
            return None
        el = parent
        text = el.get_text(" ", strip=True)
        if not _has_any_date(text):
            continue
        # Distinct spectacle slug count (exclude root /spectacle path)
        distinct_slugs = set()
        for a in el.select('a[href*="/spectacle/"]'):
            slug = _slug_from_href(a.get("href", ""))
            if slug and not slug.endswith("/spectacle"):
                distinct_slugs.add(slug)
        if len(distinct_slugs) <= 1:
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
    seen_slugs: set = set()
    today = Date.today()

    # Anchor on /spectacle/<slug>/ links — dedupe by slug
    for link in soup.select('a[href*="/spectacle/"]'):
        href = link.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        slug = _slug_from_href(href)
        if not slug or slug in seen_slugs:
            continue
        if slug.endswith("/spectacle"):
            continue
        # Filter to subpages only (exclude /spectacle root)
        if not slug.replace(HOST.lower(), "").startswith("/spectacle/"):
            continue

        card = _find_card(link)
        if card is None:
            continue
        text = card.get_text(" ", strip=True)

        d_start, d_end = _extract_dates(text)
        if not d_start:
            continue
        if d_start < today and (d_end is None or d_end < today):
            continue

        # Title: h2 or h3 inside card
        title_el = card.find(["h2", "h3"])
        if title_el:
            title = title_el.get_text(" ", strip=True)
        else:
            title = link.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 250:
            continue
        if title.lower() in ("réserver", "voir plus"):
            continue

        time_str = _extract_time(text)

        # Image
        image: Optional[str] = None
        img = card.find("img")
        if img:
            src = img.get("src", "") or ""
            if src.startswith("http"):
                image = src

        seen_slugs.add(slug)
        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=None,
            category="théâtre",
            date_start=iso(d_start),
            date_end=iso(d_end) if d_end else None,
            time=time_str,
            url=href.split("?")[0],
            image=image,
        ))

    if not events:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: Comédie Odéon — 0 events", file=sys.stderr)
        try:
            resp2 = requests.get(URL, timeout=15, headers=HEADERS)
            soup2 = BeautifulSoup(resp2.text, "html.parser")
            spec_links = soup2.select('a[href*="/spectacle/"]')
            distinct_slugs = set()
            for a in spec_links:
                s = _slug_from_href(a.get("href", ""))
                if s and not s.endswith("/spectacle"):
                    distinct_slugs.add(s)
            print(f"  Distinct /spectacle/ slugs: {len(distinct_slugs)}",
                  file=sys.stderr)
            for slug_url in list(distinct_slugs)[:3]:
                first_link = None
                for a in spec_links:
                    if _slug_from_href(a.get("href", "")) == slug_url:
                        first_link = a
                        break
                if first_link:
                    card = _find_card(first_link)
                    if card:
                        text = card.get_text(" ", strip=True)[:200]
                        d_start, d_end = _extract_dates(text)
                        print(f"  slug={slug_url[-60:]!r}", file=sys.stderr)
                        print(f"    card text[:200]={text!r}", file=sys.stderr)
                        print(f"    extracted: {d_start} → {d_end}",
                              file=sys.stderr)
                    else:
                        print(f"  slug={slug_url[-60:]!r}: no card",
                              file=sys.stderr)
        except requests.RequestException as e:
            print(f"  failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    events.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "→", e.date_end or "  -  ", e.time or "", "·", e.title)
