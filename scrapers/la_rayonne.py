"""Scraper for La Rayonne / CCO (larayonne.org/agenda).

The agenda is a flat list. Each event has:
- a <span> with category pills like "[Musique] [Programmation]"
- a heading link <a href="/evenement/<slug>/"> with the event title
- a date line like "jeu. 30 avril" or "du sam. 06 juin au dim. 07 juin"
- a time line like "14h > 16h", "18h30 > 21h" or "à partir de 19h"

We anchor on the title link and walk up the DOM to find the surrounding card
that contains the date pattern.
"""
from typing import List, Optional
import re
import requests
from bs4 import BeautifulSoup

from .base import Event, parse_french_date, iso

VENUE = "La Rayonne"
SLUG = "la-rayonne"
URL = "https://larayonne.org/agenda/"
HOST = "https://larayonne.org"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Date pattern: "jeu. 30 avril" or "ven. 09 octobre"
DATE_RE = re.compile(r"\b(\w+)\.\s+(\d{1,2})\s+(\w+)", re.IGNORECASE)
# Range end: "au dim. 07 juin"
RANGE_END_RE = re.compile(r"au\s+(\w+)\.\s+(\d{1,2})\s+(\w+)", re.IGNORECASE)
# Time: "14h > 16h", "18h30", "19h30", "à partir de 19h"
TIME_RE = re.compile(r"(\d{1,2})h(\d{2})?")

CATEGORIES = (
    "Musique", "Théâtre", "Danse", "Humour", "Spectacle", "Rencontre",
    "Atelier", "Yoga", "Cinéma", "Exposition", "Performance",
)

# Words that disqualify an /evenement/ link (it's the menu, not a real event).
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

        m = DATE_RE.search(text)
        if not m:
            continue
        d = parse_french_date(f"{m.group(2)} {m.group(3)}")
        if not d:
            continue

        # Optional date_end for ranges ("du sam. 06 juin au dim. 07 juin")
        date_end_iso = None
        m_end = RANGE_END_RE.search(text)
        if m_end:
            d_end = parse_french_date(f"{m_end.group(2)} {m_end.group(3)}")
            if d_end:
                date_end_iso = iso(d_end)

        # Time: take the FIRST time mentioned (start time)
        time_str: Optional[str] = None
        m_time = TIME_RE.search(text)
        if m_time:
            hh = int(m_time.group(1))
            mm = m_time.group(2) or "00"
            time_str = f"{hh:02d}:{mm}"

        # Category
        category: Optional[str] = None
        for kw in CATEGORIES:
            if kw in text:
                category = kw.lower()
                break

        # Image (the listing thumbnails are usually in the card)
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

    # Dedupe
    seen, unique = set(), []
    for e in events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)
    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, e.time or "  -  ", "·", e.title, "·", e.url)
