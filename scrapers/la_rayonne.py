"""Scraper for La Rayonne / CCO (larayonne.org/agenda).

Uses the FILTERED agenda URL with type=24 (Programmation only) to exclude
training / workshops / administrative meetings, keeping only concerts and
artistic shows.
"""
from typing import List, Optional
import re
import requests
from bs4 import BeautifulSoup

from .base import Event, parse_french_date, iso

VENUE = "La Rayonne"
SLUG = "la-rayonne"
# type=24 = "Programmation" — concerts and shows only.
URL = "https://larayonne.org/agenda/?univers=&type=24&saison=&st="
HOST = "https://larayonne.org"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

DATE_RE = re.compile(r"\b(\w+)\.\s+(\d{1,2})\s+(\w+)", re.IGNORECASE)
RANGE_END_RE = re.compile(r"au\s+(\w+)\.\s+(\d{1,2})\s+(\w+)", re.IGNORECASE)
TIME_RE = re.compile(r"(\d{1,2})h(\d{2})?")

CATEGORIES = (
    "Musique", "Théâtre", "Danse", "Humour", "Spectacle", "Rencontre",
    "Cinéma", "Exposition", "Performance",
)

# Skip non-music programming types and admin event categories.
SKIP_TYPES = (
    "rencontres et formations",
    "activités et ateliers",
    "mémoires vives",
)

SKIP_TITLES = (
    "filtre", "la prog", "rencontres et formations",
    "activités et ateliers", "voir tous", "agenda",
)


def _find_card(link, max_levels: int = 6):
    el = link
    for _ in range(max_levels):
        parent = el.parent
        if parent is None or parent.name in ("html", "body"):
            return el
        el = parent
        if DATE_RE.search(el.get_text(" ", strip=True)):
            return el
    return el


def fetch() -> List[Event]:
    resp = requests.get(URL, timeout=20, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    events: List[Event] = []
    seen_urls: set = set()

    for a in soup.select('a[href*="/evenement/"]'):
        href = a.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        if not href.startswith("http"):
            continue
        if href in seen_urls:
            continue

        title = a.get_text(" ", strip=True)
        if not title or len(title) < 3:
            continue
        if any(skip in title.lower() for skip in SKIP_TITLES):
            continue

        card = _find_card(a)
        text = card.get_text(" ", strip=True)
        text_lower = text.lower()

        # Belt-and-suspenders: even with type=24 in URL, still filter out
        # any cards that explicitly mention non-music types.
        if any(t in text_lower for t in SKIP_TYPES):
            continue

        m = DATE_RE.search(text)
        if not m:
            continue
        d = parse_french_date(f"{m.group(2)} {m.group(3)}")
        if not d:
            continue

        date_end_iso = None
        m_end = RANGE_END_RE.search(text)
        if m_end:
            d_end = parse_french_date(f"{m_end.group(2)} {m_end.group(3)}")
            if d_end:
                date_end_iso = iso(d_end)

        time_str: Optional[str] = None
        m_time = TIME_RE.search(text)
        if m_time:
            hh = int(m_time.group(1))
            mm = m_time.group(2) or "00"
            time_str = f"{hh:02d}:{mm}"

        category: Optional[str] = None
        for kw in CATEGORIES:
            if kw in text:
                category = kw.lower()
                break

        image: Optional[str] = None
        for img in card.find_all("img"):
            src = img.get("src") or ""
            if src.startswith("http") and not src.endswith(".svg"):
                image = src
                break

        seen_urls.add(href)
        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=None,
            category=category,
            date_start=iso(d),
            date_end=date_end_iso,
            time=time_str,
            url=href,
            image=image,
        ))

    seen, unique = set(), []
    for e in events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)
    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, e.time or "  -  ", "·", e.title, "·", e.url)
