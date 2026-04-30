"""Scraper for Les Subsistances (les-subs.com/agenda)."""
from typing import List
import re
import requests
from bs4 import BeautifulSoup

from .base import Event, parse_french_date, iso

VENUE = "Les Subsistances"
SLUG = "les-subs"
URL = "https://www.les-subs.com/agenda/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}


def fetch() -> List[Event]:
    """Scrape the Subs agenda page.

    Each event card has its title, optional subtitle (artist), category,
    image and one or several date+time entries.
    """
    resp = requests.get(URL, timeout=20, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    events: List[Event] = []

    # Each event renders a link to /evenement/<slug>/
    for a in soup.select('a[href*="/evenement/"]'):
        href = a.get("href", "")
        if not href.startswith("http"):
            continue

        # The card structure typically wraps title + meta in a parent block.
        card = a.find_parent() or a
        title_el = card.find(["h2", "h3"])
        title = title_el.get_text(strip=True) if title_el else a.get_text(" ", strip=True)
        if not title:
            continue

        # Subtitle: the smaller second line below the title
        subtitle = None
        all_titles = card.find_all(["h3", "h4"])
        if title_el in all_titles:
            idx = all_titles.index(title_el)
            if idx + 1 < len(all_titles):
                subtitle = all_titles[idx + 1].get_text(strip=True)

        # Image
        img_tag = card.find("img")
        image = img_tag.get("src") if img_tag else None

        # Category: pulled from the categories pills (Théâtre, Danse, Musique, etc.)
        category = None
        cat_keywords = ("Théâtre", "Danse", "Musique", "Cirque", "Performance",
                        "Atelier", "Visite", "Cinéma", "Exposition", "DJ Set",
                        "Rencontre", "Installation", "Littérature")
        card_text = card.get_text(" ", strip=True)
        for kw in cat_keywords:
            if kw in card_text:
                category = kw.lower()
                break

        # Dates: match patterns like "jeu. 7 Mai" or "ven. 8 Mai | 19:00"
        date_pattern = re.compile(
            r"\b\w+\.?\s+(\d{1,2})\s+(\w+)(?:\s*\|\s*(\d{1,2}:\d{2}))?",
            re.IGNORECASE,
        )
        dates_found = date_pattern.findall(card_text)

        for day_str, month_str, time_str in dates_found:
            d = parse_french_date(f"{day_str} {month_str}")
            if not d:
                continue
            events.append(Event(
                venue=VENUE,
                venue_slug=SLUG,
                title=title,
                subtitle=subtitle,
                category=category,
                date_start=iso(d),
                date_end=None,
                time=time_str or None,
                url=href,
                image=image,
            ))

    # Deduplicate by id (same title/date/time)
    seen, unique = set(), []
    for e in events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)
    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, e.time or "  -  ", "·", e.title, "·", e.url)
