"""Scraper for Le Transbordeur (transbordeur.fr/agenda).

The exact HTML structure could not be verified during development (the site
applies aggressive anti-bot protection). This scraper uses defensive selectors
that match common WordPress agenda layouts:

- Each event is a card with one main link to a sub-page (concert/event detail).
- A date string in long French form ("mercredi 06 mai 2026" or "06 mai 2026")
  or short form ("mer. 06 mai") is present near the card.
- A title heading (<h2> or <h3>) holds the artist/show name.

If the scraper returns 0 events on the first GitHub Actions run, inspect the
real HTML and adjust the LINK_SELECTOR / date regexes below.
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

# CSS selector for event links. Try several common patterns; the first one
# that returns >0 results is used.
LINK_SELECTOR_CANDIDATES = [
    'a[href*="/concert/"]',
    'a[href*="/evenement/"]',
    'a[href*="/event/"]',
    'a[href*="/agenda/"]',
    'article a[href]',
]

# Long form: "mercredi 06 mai 2026" or "06 mai 2026"
DATE_LONG = re.compile(
    r"(?:\w+\s+)?(\d{1,2})\s+(\w+)\s+(\d{4})",
    re.IGNORECASE,
)
# Short form: "mer. 06 mai" or "mer 06 mai"
DATE_SHORT = re.compile(
    r"\b\w+\.?\s+(\d{1,2})\s+(\w+)\b",
    re.IGNORECASE,
)
# Numeric form: 06/05/2026 or 06.05.2026
DATE_NUMERIC = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")

# Time: "20h30", "20:30", "à 20h"
TIME_RE = re.compile(r"(\d{1,2})[h:](\d{2})?")


def _french_month_num(s: str) -> Optional[int]:
    return FR_MONTHS.get(s.lower())


def _extract_date(text: str) -> Optional[str]:
    """Return ISO date 'YYYY-MM-DD' or None."""
    m = DATE_NUMERIC.search(text)
    if m:
        d, mo, y = m.groups()
        try:
            return Date(int(y), int(mo), int(d)).isoformat()
        except ValueError:
            pass
    m = DATE_LONG.search(text)
    if m:
        d, mo, y = m.groups()
        month = _french_month_num(mo)
        if month:
            try:
                return Date(int(y), month, int(d)).isoformat()
            except ValueError:
                pass
    m = DATE_SHORT.search(text)
    if m:
        d_obj = parse_french_date(f"{m.group(1)} {m.group(2)}")
        if d_obj:
            return d_obj.isoformat()
    return None


def _find_card(link, max_levels: int = 6):
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

    # Pick the link selector that yields the most matches.
    links = []
    for sel in LINK_SELECTOR_CANDIDATES:
        candidates = soup.select(sel)
        if len(candidates) > len(links):
            links = candidates

    events: List[Event] = []
    seen_urls: set = set()

    for a in links:
        href = a.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        if not href.startswith("http"):
            continue
        # Filter out menu / footer links
        bad_paths = ("/agenda/", "/agenda", "/", "/contact", "/billetterie",
                     "/infos", "/nos-projets", "/mentions-legales")
        path_part = href.replace(HOST, "")
        if path_part in bad_paths or path_part.endswith("/agenda/"):
            continue
        if href in seen_urls:
            continue

        card = _find_card(a)
        text = card.get_text(" ", strip=True)
        date_iso = _extract_date(text)
        if not date_iso:
            continue

        # Title: first h2/h3 in card, or the link's own text
        title_el = card.find(["h2", "h3"])
        title = title_el.get_text(strip=True) if title_el else a.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 200:
            continue
        if title.lower().startswith(("voir", "menu", "agenda")):
            continue

        # Time
        time_str: Optional[str] = None
        m_time = TIME_RE.search(text)
        if m_time:
            hh = int(m_time.group(1))
            mm = m_time.group(2) or "00"
            if 0 <= hh <= 23:
                time_str = f"{hh:02d}:{mm}"

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
            category="concert",  # Le Transbordeur is a concert venue
            date_start=date_iso,
            date_end=None,
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
