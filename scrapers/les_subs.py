"""Scraper for Les Subsistances (les-subs.com/agenda).

Each event card on the agenda page contains:
- one or more <a href="/evenement/<slug>/"> links (often wrapping the title or image)
- a title in <h2> or <h3>
- a category pill (Théâtre, Danse, Musique, …)
- a list of dates as bullets like "jeu. 7 Mai | 19:00"

The previous version walked up the DOM looking for any ancestor that contained
a date pattern. The bug: a promotional banner at the top of the page links to a
single event ("Fun Times"), and walking up from that banner's link eventually
reached a common ancestor of BOTH the banner AND many real event cards. The
scraper then attributed all those events' dates to "Fun Times".

The fix: when we walk up looking for a date, we also reject any container that
contains MORE THAN ONE distinct /evenement/ URL. A real event card has at most
one outbound URL (often duplicated across an image-link and a title-link).
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


def _find_card(link, target_href: str, max_levels: int = 6):
    """Walk up from the link until an ancestor:
    - contains a date pattern,
    - AND does NOT contain any other distinct /evenement/ URL.
    Returns the ancestor element, or None if no clean card is found.
    """
    el = link
    for _ in range(max_levels):
        parent = el.parent
        if parent is None or parent.name in ("html", "body"):
            return None
        el = parent
        text = el.get_text(" ", strip=True)
        if not DATE_RE.search(text):
            continue
        # Check we haven't walked too far: the card should reference at most
        # one event URL (target_href). Multiple distinct URLs = contamination.
        other_urls = set()
        for inner_link in el.select('a[href*="/evenement/"]'):
            href = inner_link.get("href", "")
            if href.startswith("/"):
                href = HOST + href
            if href and href != target_href:
                other_urls.add(href)
        if not other_urls:
            return el
        # Card is contaminated — we walked too far. Give up.
        return None
    return None


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

        card = _find_card(a, href)
        if card is None:
            continue
        text = card.get_text(" ", strip=True)
        date_matches = DATE_RE.findall(text)
        if not date_matches:
            continue

        # Title: first h2 or h3 in card
        title_el = card.find(["h2", "h3"])
        if title_el:
            title = title_el.get_text(strip=True)
        else:
            title = a.get_text(" ", strip=True)
        if not title:
            continue

        # Subtitle: second heading element if present (often artist credit)
        subtitle: Optional[str] = None
        headings = card.find_all(["h2", "h3", "h4"])
        if title_el is not None and title_el in headings:
            idx = headings.index(title_el)
            if idx + 1 < len(headings):
                cand = headings[idx + 1].get_text(strip=True)
                if cand and cand != title and len(cand) < 200:
                    subtitle = cand

        # Image: first <img> with a real src
        image: Optional[str] = None
        for img in card.find_all("img"):
            src = img.get("src") or ""
            if src.startswith("http"):
                image = src
                break

        # Category: first matching keyword found in card text
        category: Optional[str] = None
        for kw in CATEGORIES:
            if kw in text:
                category = kw.lower()
                break

        seen_urls.add(href)

        for _, day_num, month_str, hour, minute in date_matches:
            d = parse_french_date(f"{day_num} {month_str}")
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
                time=f"{int(hour):02d}:{minute}",
                url=href,
                image=image,
            ))

    # Deduplicate
    seen, unique = set(), []
    for e in events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)
    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, e.time or "  -  ", "·", e.title, "—", e.subtitle or "", "·", e.url)
