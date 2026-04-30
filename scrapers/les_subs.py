"""Scraper for Les Subsistances (les-subs.com/agenda).

Approach: anchor on TITLE elements (h2/h3), not on /evenement/ links.

Why: a previous version anchored on /evenement/ links, but the only such link
on the agenda listing page is a promotional banner ("Fun Times"). The rest of
the events are listed without explicit /evenement/ links visible from the
listing — they're either in non-link form or wrapped in a different URL
pattern. So we look for headings instead, then walk up to find a card that
contains both the heading and a date pattern.

The URL for each event is derived from any link found inside the card; if
none is found, we fall back to the agenda URL.
"""
from typing import List, Optional
import re
import requests
from bs4 import BeautifulSoup

from .base import Event, parse_french_date, iso

VENUE = "Les Subsistances"
SLUG = "les-subs"
URL = "https://www.les-subs.com/agenda/"
HOST = "https://www.les-subs.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Date pattern: "mer. 6 Mai | 18:30"
DATE_RE = re.compile(
    r"\b(\w+)\.?\s+(\d{1,2})\s+(\w+)\s*\|\s*(\d{1,2}):(\d{2})",
    re.IGNORECASE,
)

CATEGORIES = (
    "Théâtre", "Danse", "Musique", "Cirque", "Performance", "DJ Set",
    "Atelier", "Visite", "Cinéma", "Exposition", "Rencontre",
    "Installation", "Littérature", "Festival", "Clubbing",
    "Vidéo", "Arts visuels",
)

# Headings to ignore: navigation, banner, etc.
IGNORE_TITLES = {
    "agenda", "menu", "fermer", "retour", "billetterie",
    "newsletter", "presse", "contact", "search", "recherche",
    "fun times",  # promotional banner
    "les subs", "le projet", "l'histoire", "l'équipe", "les espaces",
    "infos pratiques", "boire & manger", "accès & horaires",
    "mécénat", "privatisation", "médiations",
    "par temps fort", "toutes les catégories",
    "saison 2025-26", "résidence", "création",
    "comment venir en résidence aux subs ?",
    "découvrez les artistes en résidence",
    "artistes", "résidents",
    "offre de noël",
    "subs in english", "mentions légales",
    "ouvrir", "passer",
}


def _find_card_for_title(heading, max_levels: int = 6):
    """Walk up from a heading until we find a parent that contains a date."""
    el = heading
    for _ in range(max_levels):
        parent = el.parent
        if parent is None or parent.name in ("html", "body"):
            return None
        el = parent
        if DATE_RE.search(el.get_text(" ", strip=True)):
            return el
    return None


def _card_url(card, fallback: str) -> str:
    """Pick the most relevant URL from inside a card.

    Prefers /evenement/ links, then /oeuvre/, then /temps-fort/, then any
    link going to the same domain. Falls back to the agenda page URL.
    """
    candidates_priority = ("/evenement/", "/oeuvre/", "/temps-fort/", "/spectacle/")
    for prefix in candidates_priority:
        for a in card.find_all("a", href=True):
            href = a["href"]
            if prefix in href:
                if href.startswith("/"):
                    href = HOST + href
                return href
    return fallback


def fetch() -> List[Event]:
    resp = requests.get(URL, timeout=20, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    events: List[Event] = []
    seen_keys: set = set()

    for h in soup.find_all(["h2", "h3"]):
        title = h.get_text(strip=True)
        if not title or len(title) < 2 or len(title) > 200:
            continue
        if title.lower().strip() in IGNORE_TITLES:
            continue

        card = _find_card_for_title(h)
        if card is None:
            continue

        text = card.get_text(" ", strip=True)
        date_matches = DATE_RE.findall(text)
        if not date_matches:
            continue

        # Subtitle: the next h3/h4 sibling-ish element after the title heading
        subtitle: Optional[str] = None
        headings_in_card = card.find_all(["h2", "h3", "h4"])
        if h in headings_in_card:
            idx = headings_in_card.index(h)
            if idx + 1 < len(headings_in_card):
                cand = headings_in_card[idx + 1].get_text(strip=True)
                if cand and cand != title and len(cand) < 200:
                    subtitle = cand

        image: Optional[str] = None
        for img in card.find_all("img"):
            src = img.get("src") or ""
            if src.startswith("http"):
                image = src
                break

        category: Optional[str] = None
        for kw in CATEGORIES:
            if kw in text:
                category = kw.lower()
                break

        href = _card_url(card, fallback=URL)

        # Build one event per date occurrence
        for _, day_num, month_str, hour, minute in date_matches:
            d = parse_french_date(f"{day_num} {month_str}")
            if not d:
                continue
            key = (title, d.isoformat(), f"{int(hour):02d}:{minute}")
            if key in seen_keys:
                continue
            seen_keys.add(key)
            events.append(Event(
                venue=VENUE,
                venue_slug=SLUG,
                title=title,
                subtitle=subtitle,
                category=category,
                date_start=iso(d),
                date_end=None,
                time=f"{int(hour):02d}:{minute}",
                url=href,
                image=image,
            ))

    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, e.time or "  -  ", "·", e.title, "—", e.subtitle or "", "·", e.url)
