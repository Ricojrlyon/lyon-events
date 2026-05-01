"""Scraper for Théâtre National Populaire (tnp-villeurbanne.com).

Page structure (verified):
- Page /programmation/ has two sections: "saison 2025-2026" (upcoming) then
  "Spectacles passés" (past). We MUST stop at the past section.
- Each event is a card containing:
    - <h3> with link to /spectacle/<slug>/ and the title
    - Author/director/company line
    - Date "22 → 29 avril 2026" or "30 mai → 6 juin 2026" or "10 et 11 septembre 2025, 20h"
    - Optional badges (Création, Dès 13 ans, etc.)
    - Image
    - Description
"""
from typing import List, Optional, Tuple
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso, FR_MONTHS

VENUE = "TNP"
SLUG = "tnp"
HOST = "https://www.tnp-villeurbanne.com"
URL = HOST + "/programmation/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# "22 → 29 avril 2026" or "30 mai → 6 juin 2026" — also "-" "–"
DATE_RANGE_TWO_MONTHS = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+)\s*[→–\-]\s*(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
DATE_RANGE_ONE_MONTH = re.compile(
    r"\b(\d{1,2})\s*[→–\-]\s*(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
# "22 et 23 janvier 2026" — two specific dates
DATE_TWO = re.compile(
    r"\b(\d{1,2})\s+et\s+(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
DATE_SINGLE = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)


def _normalize_month(s: str) -> Optional[int]:
    s = s.lower().rstrip(".")
    s = (s.replace("é", "e").replace("è", "e").replace("ê", "e")
           .replace("ô", "o").replace("û", "u"))
    return FR_MONTHS.get(s)


def _extract_dates(text: str) -> Tuple[Optional[Date], Optional[Date]]:
    # Range with two months: "30 mai → 6 juin 2026"
    m = DATE_RANGE_TWO_MONTHS.search(text)
    if m:
        d1, mo1, d2, mo2, yr = m.groups()
        month1 = _normalize_month(mo1)
        month2 = _normalize_month(mo2)
        year = int(yr)
        if month1 and month2:
            try:
                start_year = year - 1 if month1 > month2 else year
                start = Date(start_year, month1, int(d1))
                end = Date(year, month2, int(d2))
                return start, end
            except ValueError:
                pass

    # Range with one month: "22 → 29 avril 2026"
    m = DATE_RANGE_ONE_MONTH.search(text)
    if m:
        d1, d2, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                start = Date(int(yr), month, int(d1))
                end = Date(int(yr), month, int(d2))
                if end >= start:
                    return start, end
            except ValueError:
                pass

    # Two specific dates: "22 et 23 janvier 2026" — treat as range
    m = DATE_TWO.search(text)
    if m:
        d1, d2, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                start = Date(int(yr), month, int(d1))
                end = Date(int(yr), month, int(d2))
                if end >= start:
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


def _find_card(link: Tag, max_levels: int = 8) -> Optional[Tag]:
    """Walk up to find the smallest ancestor that contains a date pattern
    AND does not contain other /spectacle/ links."""
    el: Optional[Tag] = link
    target_href = link.get("href", "").split("?")[0]
    for _ in range(max_levels):
        parent = el.parent if el else None
        if parent is None or parent.name in ("html", "body"):
            return None
        el = parent
        text = el.get_text(" ", strip=True)
        if not DATE_SINGLE.search(text):
            continue
        # Must not contain other /spectacle/ links beyond ours
        other = 0
        for a in el.select('a[href*="/spectacle/"]'):
            href = a.get("href", "").split("?")[0]
            if href and href != target_href:
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

    html = resp.text

    # CRITICAL: cut everything from "Spectacles passés" onwards
    cut = html.lower().find("spectacles passés")
    if cut > 0:
        html = html[:cut]

    soup = BeautifulSoup(html, "html.parser")
    events: List[Event] = []
    seen_urls: set = set()
    today = Date.today()

    # Anchor on h3 elements that have a /spectacle/ link inside
    for h3 in soup.find_all("h3"):
        link = h3.find("a", href=True)
        if not link:
            continue
        href = link.get("href", "")
        if "/spectacle/" not in href:
            continue
        if href.startswith("/"):
            href = HOST + href
        href_clean = href.split("?")[0]
        if href_clean in seen_urls:
            continue

        title = link.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 250:
            continue

        # Find the card
        card = _find_card(link)
        if card is None:
            continue
        text = card.get_text(" ", strip=True)

        d_start, d_end = _extract_dates(text)
        if not d_start:
            continue
        if d_start < today and (d_end is None or d_end < today):
            continue

        # Subtitle: line before the date (typically authors/directors)
        # Strategy: find the first non-title, non-date text node
        subtitle: Optional[str] = None
        for tn in card.stripped_strings:
            if tn == title:
                continue
            tn_lower = tn.lower()
            # Skip date patterns
            if (DATE_RANGE_TWO_MONTHS.fullmatch(tn) or
                DATE_RANGE_ONE_MONTH.fullmatch(tn) or
                DATE_SINGLE.fullmatch(tn) or
                DATE_TWO.fullmatch(tn)):
                continue
            # Skip badges
            if tn_lower.startswith("dès "):
                continue
            if tn_lower in ("réserver", "création", "biennale de la danse",
                            "événement", "temps fort", "première française",
                            "hors les murs", "festival sens interdits",
                            "festival écrans mixtes",
                            "lauréat prix incandescences 2024",
                            "avec l'opéra de lyon", "avec les célestins, théâtre de lyon",
                            "ukraine", "chine", "belgique", "suisse", "liban",
                            "hongrie - norvège"):
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

        seen_urls.add(href_clean)
        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=subtitle,
            category="théâtre",
            date_start=iso(d_start),
            date_end=iso(d_end) if d_end else None,
            time=None,
            url=href_clean,
            image=image,
        ))

    if not events:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: TNP — 0 events", file=sys.stderr)
        try:
            resp2 = requests.get(URL, timeout=15, headers=HEADERS)
            print(f"  {URL} -> {resp2.status_code} ({len(resp2.text)} bytes)",
                  file=sys.stderr)
            soup2 = BeautifulSoup(resp2.text, "html.parser")
            spec_links = soup2.select('a[href*="/spectacle/"]')
            print(f"  /spectacle/ links: {len(spec_links)}", file=sys.stderr)
            h3s = soup2.find_all("h3")
            print(f"  h3 count: {len(h3s)}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    events.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "→", e.date_end or "  -  ", "·", e.title)
