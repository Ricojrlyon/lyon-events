"""Scraper for Radiant-Bellevue (radiant-bellevue.fr).

The home page lists the upcoming events. Each card contains:
- an <a href="/spectacles/<slug>/"> wrapping an image
- a category line ("Humour", "Musique", "Théâtre", "Musique - Chanson", …)
- a <h2> with the title
- a date string in long French form: "jeudi 30 avril 2026", "06 & 07 mai 2026",
  "12 & 13 décembre 2026", "30 & 31 octobre 2026"…

There is no time on the listing page (only on the detail page), so `time`
is left None.
"""
from typing import List, Optional
from datetime import date as Date
import re
import requests
from bs4 import BeautifulSoup

from .base import Event, parse_french_date, iso, FR_MONTHS

VENUE = "Radiant-Bellevue"
SLUG = "radiant-bellevue"
URL = "https://radiant-bellevue.fr/"
HOST = "https://radiant-bellevue.fr"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Single date: "jeudi 30 avril 2026" or "30 avril 2026"
DATE_SINGLE = re.compile(
    r"(?:\w+\s+)?(\d{1,2})\s+(\w+)\s+(\d{4})",
    re.IGNORECASE,
)
# Range "& consecutive": "06 & 07 mai 2026" or "30 & 31 octobre 2026"
DATE_AMP = re.compile(
    r"(\d{1,2})\s*&\s*(\d{1,2})\s+(\w+)\s+(\d{4})",
    re.IGNORECASE,
)
# Three days "&": "26, 27 & 28 juin 2026"
DATE_TRIPLE = re.compile(
    r"(\d{1,2}),\s*(\d{1,2})\s*&\s*(\d{1,2})\s+(\w+)\s+(\d{4})",
    re.IGNORECASE,
)

CATEGORIES = (
    "Musique", "Chanson", "Humour", "Magie", "Théâtre", "Danse",
    "Famille", "Scolaires", "Club Bellevue", "Nouveauté",
)


def _find_card(link, max_levels: int = 6):
    """Walk up to a parent that contains a date line in 4-digit-year form."""
    el = link
    year_re = re.compile(r"\b20\d{2}\b")
    for _ in range(max_levels):
        parent = el.parent
        if parent is None or parent.name in ("html", "body"):
            return el
        el = parent
        if year_re.search(el.get_text(" ", strip=True)):
            return el
    return el


def _french_month_num(s: str) -> Optional[int]:
    return FR_MONTHS.get(s.lower())


def fetch() -> List[Event]:
    resp = requests.get(URL, timeout=20, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    events: List[Event] = []
    seen_urls: set = set()

    for a in soup.select('a[href*="/spectacles/"]'):
        href = a.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        if not href.startswith("http"):
            continue
        # Skip placeholder / billetterie / etc.
        if "/spectacles/" not in href or href.endswith("/spectacles/"):
            continue
        if href in seen_urls:
            continue

        card = _find_card(a)
        text = card.get_text(" ", strip=True)

        # Date extraction with multi-day support
        date_starts: List[str] = []
        date_end_iso: Optional[str] = None

        m_triple = DATE_TRIPLE.search(text)
        m_amp = DATE_AMP.search(text)
        m_single = DATE_SINGLE.search(text)

        if m_triple:
            d1, d2, d3, mo, yr = m_triple.groups()
            month = _french_month_num(mo)
            year = int(yr)
            if month:
                for d_str in (d1, d2, d3):
                    try:
                        date_starts.append(Date(year, month, int(d_str)).isoformat())
                    except ValueError:
                        pass
        elif m_amp:
            d1, d2, mo, yr = m_amp.groups()
            month = _french_month_num(mo)
            year = int(yr)
            if month:
                for d_str in (d1, d2):
                    try:
                        date_starts.append(Date(year, month, int(d_str)).isoformat())
                    except ValueError:
                        pass
        elif m_single:
            d_str, mo, yr = m_single.groups()
            month = _french_month_num(mo)
            year = int(yr)
            if month:
                try:
                    date_starts.append(Date(year, month, int(d_str)).isoformat())
                except ValueError:
                    pass

        if not date_starts:
            continue

        # Title: first <h2> in card
        title_el = card.find(["h2", "h3"])
        if title_el:
            title = title_el.get_text(strip=True)
        else:
            title = a.get_text(" ", strip=True)
        if not title or len(title) < 2:
            continue

        # Category: extract from text — Radiant uses "Humour", "Musique - Chanson", etc.
        category: Optional[str] = None
        for kw in CATEGORIES:
            if kw in text:
                category = kw.lower()
                break

        # Image
        image: Optional[str] = None
        for img in card.find_all("img"):
            src = img.get("src") or ""
            if src.startswith("http") and not src.endswith(".svg"):
                image = src
                break

        seen_urls.add(href)
        for ds in date_starts:
            events.append(Event(
                venue=VENUE,
                venue_slug=SLUG,
                title=title,
                subtitle=None,
                category=category,
                date_start=ds,
                date_end=None,
                time=None,
                url=href,
                image=image,
            ))

    # Dedupe
    seen, unique = set(), []
    for e in events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)
    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "·", e.title, "·", e.url)
