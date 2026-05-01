"""Scraper for Musée des Beaux-Arts de Lyon (mba-lyon.fr).

The site is built on Drupal. The exhibitions listing is at
/fr/taxonomy/term/269. Each entry has:
- Category badge: "#Exposition" or "#Exposition archivée" (we filter the
  archived ones out)
- <h1> with title
- "Du DD mois YYYY au DD mois YYYY" date range
- Image
- Description

Each exhibition lives at /fr/article/<slug> or /fr/exposition/<slug>.

The page lists everything together (current, upcoming, archived) on
multiple pages. We paginate and stop when we've seen too many archived
events in a row (cheap heuristic).
"""
from typing import List, Optional, Tuple
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso, FR_MONTHS

VENUE = "Musée des Beaux-Arts"
SLUG = "mba-lyon"
HOST = "https://www.mba-lyon.fr"
URLS = [
    HOST + "/fr/taxonomy/term/269",
    HOST + "/fr/taxonomy/term/269?page=1",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# "Du 24 octobre 2025 au 10 mai 2026" — full range French
DATE_RANGE = re.compile(
    r"\b[Dd]u\s+(\d{1,2})(?:er)?\s+([\wéèêôû]+)\s+(\d{4})\s+au\s+"
    r"(\d{1,2})(?:er)?\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)


def _normalize_month(s: str) -> Optional[int]:
    s = s.lower().rstrip(".")
    s = (s.replace("é", "e").replace("è", "e").replace("ê", "e")
           .replace("ô", "o").replace("û", "u"))
    return FR_MONTHS.get(s)


def _slug_from_href(href: str) -> str:
    if not href:
        return ""
    return href.split("?")[0].split("#")[0].rstrip("/").lower()


def _extract_dates(text: str) -> Tuple[Optional[Date], Optional[Date]]:
    m = DATE_RANGE.search(text)
    if m:
        d1, mo1, y1, d2, mo2, y2 = m.groups()
        month1 = _normalize_month(mo1)
        month2 = _normalize_month(mo2)
        if month1 and month2:
            try:
                start = Date(int(y1), month1, int(d1))
                end = Date(int(y2), month2, int(d2))
                if end >= start:
                    return start, end
            except ValueError:
                pass
    return None, None


def _scrape_page(url: str) -> List[Event]:
    try:
        resp = requests.get(url, timeout=20, headers=HEADERS)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    events: List[Event] = []
    seen_slugs: set = set()
    today = Date.today()

    # Each exhibition is in an <article> typically, with an h1 and a category
    # badge. Find h1 elements that are likely titles.
    for h1 in soup.find_all(["h1", "h2"]):
        title = h1.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 250:
            continue
        # Skip section headings
        if title.lower() in ("expositions", "expositions archivées",
                              "expositions à venir", "exposition en cours",
                              "musée des beaux-arts de lyon",
                              "site musée des beaux arts de lyon"):
            continue

        # Find the parent article block
        article = h1
        # Walk up to article or div containing the date
        for _ in range(8):
            parent = article.parent
            if parent is None or parent.name in ("html", "body"):
                break
            article = parent
            text = article.get_text(" ", strip=True)
            if DATE_RANGE.search(text):
                break

        block_text = article.get_text(" ", strip=True)
        # Skip archived exhibitions
        if "exposition archivée" in block_text.lower():
            continue

        d_start, d_end = _extract_dates(block_text)
        if not d_start:
            continue
        # For exhibitions, we keep ongoing ones
        if d_end and d_end < today:
            continue
        if not d_end and d_start < today:
            continue

        # Image
        image: Optional[str] = None
        img = article.find("img")
        if img:
            src = img.get("src", "") or ""
            if src.startswith("http"):
                image = src
            elif src.startswith("/"):
                image = HOST + src

        # Slug for dedup. There's not always a clean URL — use title hash.
        # First try to find a /fr/exposition/... or /fr/article/... link
        href = HOST + "/fr/home_programmation"
        for a in article.find_all("a", href=True):
            h = a.get("href", "")
            if h.startswith("/fr/exposition/") or h.startswith("/fr/article/exposition"):
                if h.startswith("/"):
                    h = HOST + h
                href = h
                break

        # Build a stable id from title
        title_key = re.sub(r"\s+", "-", title.lower().strip())[:80]
        if title_key in seen_slugs:
            continue
        seen_slugs.add(title_key)

        # Category from the # badge (e.g., "#Exposition", "#Collections", "#Événement")
        category: Optional[str] = "exposition"
        cat_match = re.search(r"#(Exposition|Collections|Événement|Evénement|Conférence)", block_text)
        if cat_match:
            category = cat_match.group(1).lower()

        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=None,
            category=category,
            date_start=iso(d_start),
            date_end=iso(d_end) if d_end else None,
            time=None,
            url=href,
            image=image,
        ))

    return events


def fetch() -> List[Event]:
    all_events: List[Event] = []
    for url in URLS:
        all_events.extend(_scrape_page(url))

    seen, unique = set(), []
    for e in all_events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)

    if not unique:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: MBA Lyon — 0 events", file=sys.stderr)
        try:
            resp = requests.get(URLS[0], timeout=15, headers=HEADERS)
            print(f"  {URLS[0]} -> {resp.status_code} ({len(resp.text)} bytes)",
                  file=sys.stderr)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                h1s = soup.find_all("h1")
                print(f"  h1 count: {len(h1s)}", file=sys.stderr)
                for h in h1s[:5]:
                    print(f"    - {h.get_text(strip=True)[:80]!r}",
                          file=sys.stderr)
                # Count date ranges
                page_text = soup.get_text(" ", strip=True)
                ranges = DATE_RANGE.findall(page_text)
                print(f"  Date ranges found: {len(ranges)}", file=sys.stderr)
                for r in ranges[:3]:
                    print(f"    - {r}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    unique.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "→", e.date_end or "  -  ", "·", e.title)
