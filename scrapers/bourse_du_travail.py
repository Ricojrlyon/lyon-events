"""Scraper for La Bourse du Travail (bourse-du-travail.com).

Page structure (verified):
- Page lists events grouped by month (<h2>"Mai 2026", "Juin 2026", etc.)
- Each event card:
    - <a href="/<slug>-<id>.html"><img></a>
    - "DD/MM/YYYY" date as plain text
    - <h3><a href="/<slug>-<id>.html">Title</a></h3>
    - "En savoir plus" link

We anchor on <h3> elements with a /-<digits>.html link inside.
"""
from typing import List, Optional, Tuple
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso, absolutize_url

VENUE = "Bourse du Travail"
SLUG = "bourse-du-travail"
HOST = "https://www.bourse-du-travail.com"
URL = HOST + "/programmation.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# DD/MM/YYYY
DATE_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")


def _slug_from_href(href: str) -> str:
    if not href:
        return ""
    return href.split("?")[0].split("#")[0].rstrip("/").lower()


def _is_event_link(href: str) -> bool:
    """An event link looks like /some-slug-NNNNNN.html (digits at end)."""
    if not href:
        return False
    # Strip the prefix
    path = href.replace(HOST, "")
    # Must end with -<digits>.html
    return bool(re.search(r"-\d{4,}\.html$", path))


def _find_card(h3: Tag, max_levels: int = 6) -> Optional[Tag]:
    """Walk up from h3 to find the smallest ancestor that contains both
    the h3 and a date pattern."""
    el: Optional[Tag] = h3
    for _ in range(max_levels):
        parent = el.parent if el else None
        if parent is None or parent.name in ("html", "body"):
            return None
        el = parent
        text = el.get_text(" ", strip=True)
        if DATE_RE.search(text):
            return el
    return None


def fetch() -> List[Event]:
    try:
        resp = requests.get(URL, timeout=20, headers=HEADERS)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    events: List[Event] = []
    seen_slugs: set = set()
    today = Date.today()

    # Anchor on h3 elements that wrap an event link
    for h3 in soup.find_all("h3"):
        link = h3.find("a", href=True)
        if not link:
            continue
        href = link.get("href", "")
        href = absolutize_url(href, HOST)
        if not _is_event_link(href):
            continue
        slug = _slug_from_href(href)
        if slug in seen_slugs:
            continue

        title = link.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 250:
            continue

        # Find the card container
        card = _find_card(h3)
        if card is None:
            continue
        text = card.get_text(" ", strip=True)
        m = DATE_RE.search(text)
        if not m:
            continue
        try:
            day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            d = Date(year, month, day)
        except ValueError:
            continue
        if d < today:
            continue

        # Image: the previous sibling <a> with image
        image: Optional[str] = None
        img = card.find("img")
        if img:
            src = img.get("src", "") or ""
            if src.startswith("http"):
                image = src
            elif src.startswith("/"):
                image = HOST + src

        # Category: try to detect from title keywords
        category: Optional[str] = None
        title_lower = title.lower()
        if any(kw in title_lower for kw in ("hommage", "tribute", "covertramp")):
            category = "concert"
        elif any(kw in title_lower for kw in ("ballet", "lac des cygnes",
                                                "casse-noisette")):
            category = "danse"
        elif any(kw in title_lower for kw in ("symphonique", "symphony",
                                                "orchestre", "concert dessiné",
                                                "harmonie")):
            category = "musique classique"
        elif any(kw in title_lower for kw in ("festival",)):
            category = "festival"
        elif any(kw in title_lower for kw in ("musical", "comédie musicale",
                                                "le tribute")):
            category = "spectacle musical"
        else:
            # Default to humour (most common at Bourse du Travail)
            category = "humour"

        seen_slugs.add(slug)
        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=None,
            category=category,
            date_start=iso(d),
            date_end=None,
            time=None,
            url=href,
            image=image,
        ))

    if not events:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: Bourse du Travail — 0 events", file=sys.stderr)
        try:
            resp2 = requests.get(URL, timeout=15, headers=HEADERS)
            print(f"  {URL} -> {resp2.status_code} ({len(resp2.text)} bytes)",
                  file=sys.stderr)
            soup2 = BeautifulSoup(resp2.text, "html.parser")
            h3s = soup2.find_all("h3")
            print(f"  h3 count: {len(h3s)}", file=sys.stderr)
            for h in h3s[:5]:
                link = h.find("a", href=True)
                href = link.get("href") if link else "no link"
                print(f"    - h3: {h.get_text(strip=True)[:60]!r} | {href!r}",
                      file=sys.stderr)
            page_text = soup2.get_text(" ", strip=True)
            dates = DATE_RE.findall(page_text)
            print(f"  DD/MM/YYYY matches: {len(dates)}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    events.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "·", e.title, "·", e.url)
