"""Scraper for Théâtre Nouvelle Génération (tng-lyon.fr).

v2: fix _find_card to allow multiple links to same slug.
"""
from typing import List, Optional, Tuple
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso, FR_MONTHS

VENUE = "TNG"
SLUG = "tng"
HOST = "https://www.tng-lyon.fr"
URL = HOST + "/programme/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

SHORT_MONTHS = {
    "janv": 1, "fevr": 2, "févr": 2, "mars": 3, "avr": 4, "mai": 5,
    "juin": 6, "juil": 7, "juill": 7, "aout": 8, "août": 8, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12, "déc": 12,
}

DATE_RANGE = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+)\s*[>→–\-]\s*(\d{1,2})\s+([\wéèêôû]+)\b",
    re.IGNORECASE,
)
DATE_SINGLE = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+)\b",
    re.IGNORECASE,
)


def _normalize_month(s: str) -> Optional[int]:
    s = s.lower().rstrip(".")
    s = (s.replace("é", "e").replace("è", "e").replace("ê", "e")
           .replace("ô", "o").replace("û", "u"))
    if s in FR_MONTHS:
        return FR_MONTHS[s]
    return SHORT_MONTHS.get(s)


def _slug_from_href(href: str) -> str:
    if not href:
        return ""
    href = href.split("?")[0].split("#")[0]
    return href.rstrip("/").lower()


def _smart_year(month: int, day: int, ref: Date) -> int:
    grace = 15
    try:
        candidate = Date(ref.year, month, day)
    except ValueError:
        return ref.year
    delta = (ref - candidate).days
    if delta > grace:
        return ref.year + 1
    return ref.year


def _extract_dates(text: str) -> Tuple[Optional[Date], Optional[Date]]:
    today = Date.today()

    m = DATE_RANGE.search(text)
    if m:
        d1, mo1, d2, mo2 = m.groups()
        # Check that mo1 and mo2 are valid month names (avoid matching arbitrary words)
        month1 = _normalize_month(mo1)
        month2 = _normalize_month(mo2)
        if month1 and month2:
            try:
                day1, day2 = int(d1), int(d2)
                if month1 == month2:
                    year = _smart_year(month1, day1, today)
                    return Date(year, month1, day1), Date(year, month2, day2)
                else:
                    start_year = _smart_year(month1, day1, today)
                    end_year = start_year + 1 if month1 > month2 else start_year
                    return (Date(start_year, month1, day1),
                            Date(end_year, month2, day2))
            except ValueError:
                pass

    # Single — must validate the month matches a real month name
    for m in DATE_SINGLE.finditer(text):
        d, mo = m.group(1), m.group(2)
        month = _normalize_month(mo)
        if month:
            try:
                day = int(d)
                if not (1 <= day <= 31):
                    continue
                year = _smart_year(month, day, today)
                return Date(year, month, day), None
            except ValueError:
                continue

    return None, None


def _has_any_date(text: str) -> bool:
    """Quick check: text has a day-number followed by a real month name."""
    for m in DATE_SINGLE.finditer(text):
        if _normalize_month(m.group(2)):
            return True
    return False


def _find_card(link: Tag, max_levels: int = 8) -> Optional[Tag]:
    """Walk up to find a card containing exactly one event slug."""
    el: Optional[Tag] = link
    for _ in range(max_levels):
        parent = el.parent if el else None
        if parent is None or parent.name in ("html", "body"):
            return None
        el = parent
        text = el.get_text(" ", strip=True)
        if not _has_any_date(text):
            continue
        distinct_slugs = set()
        for a in el.select('a[href*="/evenement/"]'):
            slug = _slug_from_href(a.get("href", ""))
            if slug:
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

    for link in soup.select('a[href*="/evenement/"]'):
        href = link.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        slug = _slug_from_href(href)
        if not slug or slug in seen_slugs:
            continue

        card = _find_card(link)
        if card is None:
            continue

        title_el = card.find(["h2", "h3"])
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 250:
            continue

        text = card.get_text(" ", strip=True)
        d_start, d_end = _extract_dates(text)
        if not d_start:
            continue
        if d_start < today and (d_end is None or d_end < today):
            continue

        # Subtitle
        subtitle: Optional[str] = None
        for tn in card.stripped_strings:
            if tn == title:
                continue
            tn_lower = tn.lower()
            if DATE_RANGE.fullmatch(tn) or DATE_SINGLE.fullmatch(tn):
                continue
            if re.fullmatch(r"\d{1,2}", tn):
                continue
            if tn_lower in (">", "→", "tng-vaise", "ateliers - presqu'île",
                            "ateliers-presqu'île", "en famille",
                            "réserver", "plus d'infos", "voir plus"):
                continue
            if tn_lower.startswith("dès "):
                continue
            if (tn_lower.startswith("3-6 ans") or tn_lower.startswith("7-10") or
                "à 12 ans" in tn_lower or "à 18 ans" in tn_lower or
                re.fullmatch(r"\d+\+", tn) or
                re.fullmatch(r"de \d+ à \d+ ans", tn_lower)):
                continue
            if len(tn) < 3 or len(tn) > 250:
                continue
            subtitle = tn
            break

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
            subtitle=subtitle,
            category="théâtre",
            date_start=iso(d_start),
            date_end=iso(d_end) if d_end else None,
            time=None,
            url=href.split("?")[0],
            image=image,
        ))

    if not events:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: TNG — 0 events", file=sys.stderr)
        try:
            resp2 = requests.get(URL, timeout=15, headers=HEADERS)
            soup2 = BeautifulSoup(resp2.text, "html.parser")
            ev_links = soup2.select('a[href*="/evenement/"]')
            distinct_slugs = set()
            for a in ev_links:
                s = _slug_from_href(a.get("href", ""))
                if s:
                    distinct_slugs.add(s)
            print(f"  Distinct /evenement/ slugs: {len(distinct_slugs)}",
                  file=sys.stderr)
            for slug_url in list(distinct_slugs)[:3]:
                first_link = None
                for a in ev_links:
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
        print(e.date_start, "→", e.date_end or "  -  ", "·", e.title)
