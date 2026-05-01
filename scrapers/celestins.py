"""Scraper for Les Célestins, Théâtre de Lyon (theatredescelestins.com).

Page /programme/saison-25-26 lists all shows. Each card is wrapped in
<a href="/fr/programmation/2025-2026/<salle>/<slug>"> where salle is
"grande-salle", "celestine", or "hors-les-murs".

Inside the card text:
- Title
- Author / company
- Date in format "28 avr. – 2 mai 2026" (range) or "21 – 30 avr. 2026"
- Venue label "Grande salle", "Célestine", "Hors les murs"
- Optional age guidance "dès 12 ans"
"""
from typing import List, Optional, Tuple
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso, FR_MONTHS

VENUE = "Théâtre des Célestins"
SLUG = "celestins"
HOST = "https://www.theatredescelestins.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Try the current season page; fallback to "saison-26-27" when next season is up.
URLS = [
    HOST + "/programme/saison-25-26",
    HOST + "/programme/saison-26-27",
]

SHORT_MONTHS = {
    "janv": 1, "fevr": 2, "févr": 2, "mars": 3, "avr": 4, "mai": 5,
    "juin": 6, "juil": 7, "aout": 8, "août": 8, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12, "déc": 12,
}

# Range "28 avr. – 2 mai 2026" — start day, start month, end day, end month, year
DATE_RANGE = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+\.?)\s*[–-]\s*(\d{1,2})\s+([\wéèêôû]+\.?)\s+(\d{4})\b",
    re.IGNORECASE,
)
# Range with single month "21 – 30 avr. 2026" — start, end, month, year
DATE_RANGE_SHORT = re.compile(
    r"\b(\d{1,2})\s*[–-]\s*(\d{1,2})\s+([\wéèêôû]+\.?)\s+(\d{4})\b",
    re.IGNORECASE,
)
# Single date "lundi 18 mai 2026"
DATE_SINGLE = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+\.?)\s+(\d{4})\b",
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
    # Try "28 avr. – 2 mai 2026"
    m = DATE_RANGE.search(text)
    if m:
        d1, mo1, d2, mo2, yr = m.groups()
        month1 = _normalize_month(mo1)
        month2 = _normalize_month(mo2)
        year = int(yr)
        if month1 and month2:
            try:
                # If start month > end month, range crosses year boundary
                start_year = year - 1 if month1 > month2 else year
                start = Date(start_year, month1, int(d1))
                end = Date(year, month2, int(d2))
                return start, end
            except ValueError:
                pass

    # Try "21 – 30 avr. 2026"
    m = DATE_RANGE_SHORT.search(text)
    if m:
        d1, d2, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                start = Date(int(yr), month, int(d1))
                end = Date(int(yr), month, int(d2))
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


def _venue_from_url(href: str) -> Optional[str]:
    m = re.search(r"/programmation/[^/]+/([^/]+)/", href)
    if m:
        seg = m.group(1).replace("-", " ")
        return seg
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
        if href in seen_urls:
            continue
        # Skip the listing root or generic landing pages
        path_part = href.replace(HOST, "").rstrip("/")
        if path_part.count("/") < 3:
            continue

        text_nodes = [t for t in a.stripped_strings]
        if not text_nodes:
            continue
        text = " ".join(text_nodes)

        d_start, d_end = _extract_dates(text)
        if not d_start:
            continue
        if d_start < today and (d_end is None or d_end < today):
            continue

        # Title is typically the first text node (and longest meaningful one).
        # Filter out date / venue label nodes.
        candidates: List[str] = []
        for tn in text_nodes:
            tn_lower = tn.lower()
            if DATE_RANGE.fullmatch(tn) or DATE_RANGE_SHORT.fullmatch(tn) or DATE_SINGLE.fullmatch(tn):
                continue
            if tn_lower.startswith("dès "):
                continue
            if tn_lower in ("grande salle", "célestine", "celestine",
                            "hors les murs", "réserver", "programme",
                            "voir tout", "spectacles", "événements",
                            "le théâtre"):
                continue
            # Filter out compound venue/age notes like "Grande salle • dès 12 ans"
            if "• dès" in tn_lower or "•" in tn and ("salle" in tn_lower or "celestine" in tn_lower):
                continue
            if len(tn) < 2 or len(tn) > 250:
                continue
            candidates.append(tn)

        if not candidates:
            continue
        title = candidates[0]
        subtitle = candidates[1] if len(candidates) > 1 else None
        if subtitle and len(subtitle) > 250:
            subtitle = None

        # Image
        image: Optional[str] = None
        img = a.find("img")
        if img:
            src = img.get("src", "") or ""
            if src.startswith("http"):
                image = src

        category = _venue_from_url(href) or "théâtre"

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
        print("DIAGNOSTIC: Théâtre des Célestins — 0 events", file=sys.stderr)
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
            except requests.RequestException as e:
                print(f"  {url} -> failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    unique.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "·", e.title, "·", e.url)
