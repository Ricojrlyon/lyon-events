"""Scraper for Le Petit Salon (lpslyon.fr/evenements-le-petit-salon/).

Page structure (verified by inspection): a flat list of event blocks.
Each block contains, in this order:
- Date pill: short day name like "Jeu." then "30/04" (DD/MM, no year)
- Image (img.src on lpslyon.fr/wp-content/uploads/)
- Title in <h2> (e.g. "OLYMPE / SOONS / TRY & MORE")
- Description paragraphs (GRANDE SALLE, PETITE SALLE)
- Réserver button linking to a Yurplan ticket URL

Strategy: anchor on <h2> elements (each h2 = one event), then walk
backward in the DOM to find the date pill that precedes it.

The site doesn't show year, but Le Petit Salon programs months in
advance — events from Jan-Apr are next year, May-Dec are this year.
We use a "smart" year inference based on today's date.
"""
from typing import List, Optional
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso

VENUE = "Le Petit Salon"
SLUG = "petit-salon"
URL = "https://www.lpslyon.fr/evenements-le-petit-salon/"
HOST = "https://www.lpslyon.fr"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Date pill format: "30/04" (DD/MM)
DATE_RE = re.compile(r"(\d{2})/(\d{2})")
# Day prefix "Jeu.", "Ven.", "Sam." etc. (used to recognize the pill)
DAY_PREFIX_RE = re.compile(
    r"^(lun|mar|mer|jeu|ven|sam|dim)\.?$",
    re.IGNORECASE,
)


def _smart_year(month: int, day: int) -> int:
    """Pick the next occurrence of (month, day) from today (forward-looking)."""
    today = Date.today()
    candidate = Date(today.year, month, day)
    if candidate < today:
        # Bump to next year if the date is past
        return today.year + 1
    return today.year


def _find_preceding_date(h2: Tag) -> Optional[str]:
    """Walk backwards from h2 in document order to find a 'DD/MM' pill."""
    # Limit to siblings of ancestors — gather text from preceding nodes
    # in document order
    seen_text_chunks: List[str] = []
    el = h2
    # Walk previous siblings/parents. We collect text from the preceding
    # ~5 sibling-like elements until we find a date.
    for _ in range(20):
        el = el.find_previous(string=False) if el else None
        if el is None:
            break
        if hasattr(el, "get_text"):
            txt = el.get_text(" ", strip=True)
            if txt:
                seen_text_chunks.append(txt)
                # Look for DD/MM in this chunk
                m = DATE_RE.search(txt)
                if m:
                    return m.group(0)
    return None


def fetch() -> List[Event]:
    resp = requests.get(URL, timeout=20, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    events: List[Event] = []
    seen_keys: set = set()

    h2_list = soup.find_all("h2")
    for h2 in h2_list:
        title = h2.get_text(" ", strip=True)
        if not title or len(title) < 3 or len(title) > 250:
            continue
        # Skip nav-like h2s (rare on this site, but defensive)
        if title.lower() in ("nos évènements", "menu", "accès"):
            continue

        date_str = _find_preceding_date(h2)
        if not date_str:
            continue
        m = DATE_RE.match(date_str)
        if not m:
            continue
        day, month = int(m.group(1)), int(m.group(2))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        try:
            year = _smart_year(month, day)
            d = Date(year, month, day)
        except ValueError:
            continue

        # Image: first sibling/parent <img> nearby
        image: Optional[str] = None
        # Look at preceding siblings of h2's parent
        container = h2.find_parent()
        if container:
            img = container.find("img")
            if img and img.get("src", "").startswith("http"):
                image = img["src"]

        # URL: the "Réserver" link is usually after the h2
        href = URL
        next_link = h2.find_next("a", href=True)
        if next_link:
            cand = next_link["href"]
            if cand.startswith("http"):
                href = cand
            elif cand.startswith("/"):
                href = HOST + cand

        # All Petit Salon events are nightclub electronic music events
        category = "club"

        # Default time: opening listed as 23h30 in description text
        time_str: Optional[str] = "23:30"

        key = (title, iso(d))
        if key in seen_keys:
            continue
        seen_keys.add(key)

        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=None,
            category=category,
            date_start=iso(d),
            date_end=None,
            time=time_str,
            url=href,
            image=image,
        ))

    if not events:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: Le Petit Salon — 0 events", file=sys.stderr)
        print(f"  Page size: {len(resp.text)} bytes", file=sys.stderr)
        print(f"  <h2> count: {len(h2_list)}", file=sys.stderr)
        for h2 in h2_list[:8]:
            print(f"    - {h2.get_text(' ', strip=True)[:80]!r}",
                  file=sys.stderr)
        page_text = soup.get_text(" ", strip=True)
        date_count = len(DATE_RE.findall(page_text))
        print(f"  DD/MM matches in page: {date_count}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    events.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, e.time, "·", e.title, "·", e.url)
