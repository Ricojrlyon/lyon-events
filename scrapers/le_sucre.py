"""Scraper for Le Sucre (le-sucre.eu/agenda)."""
from datetime import date
from typing import List
import requests
from bs4 import BeautifulSoup

from .base import Event, parse_french_date, iso

VENUE = "Le Sucre"
SLUG = "le-sucre"
URL = "https://le-sucre.eu/agenda/"


def fetch() -> List[Event]:
    """Scrape Le Sucre's agenda page.

    The agenda is a flat list of <a> elements, each containing the date
    (e.g. "jeu. 30 avr."), category, image, title (h2), and artist names (h3).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9",
    }
    resp = requests.get(URL, timeout=20, headers=headers)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    events: List[Event] = []

    # Each event is wrapped in a link to /events/<slug>/
    for a in soup.select('a[href*="/events/"]'):
        href = a.get("href", "")
        if "agenda-archives" in href or not href.startswith("http"):
            continue

        h2 = a.find("h2")
        if not h2:
            continue
        title = h2.get_text(strip=True)

        # Subtitle = concatenation of <h3> elements (artist names)
        h3s = a.find_all("h3")
        subtitle = " · ".join(h.get_text(strip=True) for h in h3s) if h3s else None

        # Try to find the date and category in the same anchor
        # The HTML pattern places category text and a date string near the top
        text = a.get_text(" ", strip=True)
        # Date pattern: "jeu. 30 avr." or "sam. 14 nov." etc.
        # parse_french_date is permissive
        date_str = None
        # Heuristic: take the first ~50 chars (where the date sits)
        head = text[:50]
        d = parse_french_date(head)
        if not d:
            # Fallback: try the whole text
            d = parse_french_date(text)
        if not d:
            continue
        date_str = iso(d)

        # Category: the first label like "Club", "Concert", "Event"
        category = None
        for token in ("Club", "Concert", "Event"):
            if token in head:
                category = token.lower()
                break

        # Image
        img_tag = a.find("img")
        image = img_tag.get("src") if img_tag else None

        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=subtitle,
            category=category,
            date_start=date_str,
            date_end=None,
            time=None,
            url=href,
            image=image,
        ))

    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "·", e.title, "—", e.subtitle or "", "·", e.url)
