"""Scraper for Le Transbordeur (transbordeur.fr/agenda).

Event detail URLs use the pattern /evenement/<numeric_id>/ (e.g.
/evenement/28489/). The listing card text reads like:
    "Club transbo · LA MAISON TELLIER + OPAC · Mercredi 06 mai 2026 · 19:00"
"""
from typing import List, Optional
from datetime import date as Date
import re
import requests
from bs4 import BeautifulSoup

from .base import Event, parse_french_date, iso, FR_MONTHS

VENUE = "Le Transbordeur"
SLUG = "transbordeur"
URL = "https://www.transbordeur.fr/agenda/"
HOST = "https://www.transbordeur.fr"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Long form like "Mercredi 06 mai 2026" or "Dimanche 24 mai 2026"
DATE_LONG = re.compile(
    r"\w+\s+(\d{1,2})\s+(\w+)\s+(\d{4})",
    re.IGNORECASE,
)
# Time: "19:00" or "20h30"
TIME_RE = re.compile(r"\b(\d{1,2})[h:](\d{2})\b")

# Genre tags from Transbordeur
GENRE_TAGS = (
    "ROCK / POP", "DARK / METAL", "ELECTRO / TECHNO", "FUNK / JAZZ",
    "RAP / URBAIN", "SONO MONDIALE / DUB", "VARIETE / CHANSON",
    "FOLK / COUNTRY", "ORIGINAL DUB CULTURE", "ROCK / METAL / HIP HOP",
)


def _french_month_num(s: str) -> Optional[int]:
    return FR_MONTHS.get(s.lower())


def _find_card(link, max_levels: int = 6):
    """Walk up until ancestor contains a year-form date."""
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
        # Filter out the agenda root itself
        if href.rstrip("/") in (HOST + "/evenement", HOST + "/agenda"):
            continue
        if href in seen_urls:
            continue

        card = _find_card(a)
        text = card.get_text(" ", strip=True)

        m = DATE_LONG.search(text)
        if not m:
            continue
        d_str, mo_str, yr = m.groups()
        month = _french_month_num(mo_str)
        if not month:
            continue
        try:
            d_iso = Date(int(yr), month, int(d_str)).isoformat()
        except ValueError:
            continue

        # Time
        time_str: Optional[str] = None
        m_time = TIME_RE.search(text)
        if m_time:
            hh = int(m_time.group(1))
            mm = m_time.group(2)
            if 0 <= hh <= 23:
                time_str = f"{hh:02d}:{mm}"

        # Title: first h2/h3 in card, or the link's own text
        title_el = card.find(["h2", "h3"])
        title = title_el.get_text(strip=True) if title_el else a.get_text(" ", strip=True)
        title = title.strip()
        if not title or len(title) < 2 or len(title) > 200:
            continue

        # Skip non-event titles (configuration labels etc.)
        skip_lower = ("agenda", "billetterie", "menu", "fr en",
                      "voir plus", "club transbo", "grande salle")
        if title.lower() in skip_lower:
            continue

        # Category from genre tag
        category: Optional[str] = "concert"
        text_upper = text.upper()
        for tag in GENRE_TAGS:
            if tag in text_upper:
                category = tag.lower().split(" / ")[0]
                break

        # Image
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
            date_start=d_iso,
            date_end=None,
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
