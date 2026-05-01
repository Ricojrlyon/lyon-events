"""Scraper for Comédie Odéon (comedieodeon.com).

v3: changed strategy. The HTML structure is:
    <h2>Title</h2>
    <a href="/spectacle/slug/"><img></a>
    <a href="/billetterie/...">Réserver</a>
    Date text
    <a href="/spectacle/slug/">Voir plus</a>

The <h2> is a SIBLING of the date and links, not a parent.
New approach: anchor on <h2>, then walk forward through siblings to find
the date and the spectacle link.
"""
from typing import List, Optional, Tuple
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag, NavigableString

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
# "Jusqu'au 02 mai 2026" — open-ended ongoing event ending on that date
DATE_UNTIL = re.compile(
    r"[Jj]usqu['’]au\s+(\d{1,2})\s+([\wéèêôû]+)(?:\s+(\d{4}))?",
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

    # 4. "Jusqu'au X mois year" — ongoing ends on that date
    m = DATE_UNTIL.search(text)
    if m:
        d, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                year = int(yr) if yr else _smart_year(month, int(d))
                end = Date(year, month, int(d))
                today = Date.today()
                # Start = today (it's ongoing)
                return today, end
            except ValueError:
                pass

    # 5. "Samedi X mois year"
    m = DAY_NAME_DATE_YEAR.search(text)
    if m:
        d, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                return Date(int(yr), month, int(d)), None
            except ValueError:
                pass

    # 6. "Samedi X mois" (no year)
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

    # 7. "X et Y mois year"
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

    # 8. Bare "X mois year"
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


def _gather_event_data(h2: Tag) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """From a <h2>, walk forward through siblings (and their descendants)
    until hitting the next <h2>, gathering: spectacle slug URL, image, raw text.
    Returns (href, image, text, raw_text_for_diag)
    """
    href: Optional[str] = None
    image: Optional[str] = None
    text_parts = []

    sib = h2.next_sibling
    while sib is not None:
        if isinstance(sib, Tag):
            if sib.name == "h2":
                break
            # Look for spectacle link
            if href is None:
                a_links = sib.select('a[href*="/spectacle/"]') if hasattr(sib, "select") else []
                # Plus the sibling itself if it's an <a>
                if sib.name == "a" and "/spectacle/" in sib.get("href", ""):
                    a_links = [sib] + list(a_links)
                for a in a_links:
                    h = a.get("href", "")
                    if h.startswith("/"):
                        h = HOST + h
                    slug = _slug_from_href(h)
                    if slug and not slug.endswith("/spectacle"):
                        href = h
                        break
            # Look for image
            if image is None:
                img = sib.find("img") if hasattr(sib, "find") else None
                if img is None and sib.name == "img":
                    img = sib
                if img:
                    src = img.get("src", "") or ""
                    if src.startswith("http"):
                        image = src
            # Append text
            text_parts.append(sib.get_text(" ", strip=True))
        elif isinstance(sib, NavigableString):
            t = str(sib).strip()
            if t:
                text_parts.append(t)
        sib = sib.next_sibling

    text = " ".join(t for t in text_parts if t)
    return href, image, text, text


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

    # Anchor on <h2> elements (each event has a unique h2 for the title)
    for h2 in soup.find_all("h2"):
        title = h2.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 250:
            continue
        # Skip menu/section h2
        if title.lower() in ("toutes nos productions", "saison 2025 2026",
                              "saison 2025/2026", "spectacles passés"):
            continue

        href, image, text, _ = _gather_event_data(h2)
        if not href:
            continue
        slug = _slug_from_href(href)
        if slug in seen_slugs:
            continue

        d_start, d_end = _extract_dates(text)
        if not d_start:
            continue
        if d_start < today and (d_end is None or d_end < today):
            continue

        time_str = _extract_time(text)

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
            h2s = soup2.find_all("h2")
            print(f"  h2 count: {len(h2s)}", file=sys.stderr)
            for h2 in h2s[:5]:
                title = h2.get_text(' ', strip=True)
                href, image, text, _ = _gather_event_data(h2)
                d_start, d_end = _extract_dates(text or "")
                print(f"  h2={title[:40]!r}", file=sys.stderr)
                print(f"    href={href!r}", file=sys.stderr)
                print(f"    text[:200]={text[:200]!r}", file=sys.stderr)
                print(f"    extracted: {d_start} → {d_end}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    events.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "→", e.date_end or "  -  ", e.time or "", "·", e.title)
