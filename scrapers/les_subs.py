"""Scraper for Les Subsistances (les-subs.com/agenda).

When the scraper returns 0 events, it prints a diagnostic block to stderr
showing what's actually on the page so we can see what HTML pattern to
target next.
"""
from typing import List, Optional
import re
import sys
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

# Bullet date pattern: "mer. 6 Mai | 18:30"
DATE_RE = re.compile(
    r"\b(\w+)\.?\s+(\d{1,2})\s+(\w+)\s*\|\s*(\d{1,2}):(\d{2})",
    re.IGNORECASE,
)
# Generic date keyword pattern (looser): "6 Mai" / "06 mai 2026"
LOOSE_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(janv|f[eé]vr|mars|avr|mai|juin|juil|ao[uû]t|sept|oct|nov|d[eé]c)",
    re.IGNORECASE,
)

CATEGORIES = (
    "Théâtre", "Danse", "Musique", "Cirque", "Performance", "DJ Set",
    "Atelier", "Visite", "Cinéma", "Exposition", "Rencontre",
    "Installation", "Littérature", "Festival", "Clubbing",
    "Vidéo", "Arts visuels",
)

IGNORE_TITLES = {
    "agenda", "menu", "fermer", "retour", "billetterie",
    "newsletter", "presse", "contact", "search", "recherche",
    "fun times",
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
    candidates_priority = ("/evenement/", "/oeuvre/", "/temps-fort/", "/spectacle/")
    for prefix in candidates_priority:
        for a in card.find_all("a", href=True):
            href = a["href"]
            if prefix in href:
                if href.startswith("/"):
                    href = HOST + href
                return href
    return fallback


def _print_diagnostic(soup, response_text: str):
    """Print structural diagnostic info to stderr."""
    print("=" * 60, file=sys.stderr)
    print("DIAGNOSTIC: Les Subsistances scraper found 0 events.", file=sys.stderr)
    print(f"  Page size: {len(response_text)} bytes", file=sys.stderr)
    evenement_links = soup.select('a[href*="/evenement/"]')
    print(f"  /evenement/ links: {len(evenement_links)}", file=sys.stderr)
    for a in evenement_links[:3]:
        print(f"    - {a.get('href', '')!r}", file=sys.stderr)
    h2s = soup.find_all("h2")
    h3s = soup.find_all("h3")
    print(f"  <h2> count: {len(h2s)}", file=sys.stderr)
    print(f"  <h3> count: {len(h3s)}", file=sys.stderr)
    print("  First 8 h2 texts:", file=sys.stderr)
    for h in h2s[:8]:
        t = h.get_text(strip=True)[:80]
        print(f"    - {t!r}", file=sys.stderr)
    print("  First 8 h3 texts:", file=sys.stderr)
    for h in h3s[:8]:
        t = h.get_text(strip=True)[:80]
        print(f"    - {t!r}", file=sys.stderr)

    page_text = soup.get_text(" ", strip=True)
    strict_dates = DATE_RE.findall(page_text)
    loose_dates = LOOSE_DATE_RE.findall(page_text)
    print(f"  Strict date matches (with time): {len(strict_dates)}", file=sys.stderr)
    print(f"    First 5: {strict_dates[:5]}", file=sys.stderr)
    print(f"  Loose date matches (day+month): {len(loose_dates)}", file=sys.stderr)
    print(f"    First 5: {loose_dates[:5]}", file=sys.stderr)

    # Show a sample of the body text for visual inspection
    body = soup.find("body")
    if body:
        body_text = body.get_text(" ", strip=True)
        print(f"  First 400 chars of body text:", file=sys.stderr)
        print(f"    {body_text[:400]!r}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)


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

    if not events:
        _print_diagnostic(soup, resp.text)

    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, e.time or "  -  ", "·", e.title, "·", e.url)
