"""Scraper for Théâtre de la Croix-Rousse (croix-rousse.com).

Page /au-programme/ lists all upcoming events. Each card is wrapped in
<a href="/au-programme/<slug>/"> with image, <h3> title, date, and meta.

Date formats:
- "5 → 7 mai 2026" (range with arrow)
- "lundi 18 mai 2026" (single)
- "9 → 10 juin 2026" (range, single month)
- "28 → 30 avril 2026"

The page may show only one month at a time. We iterate through monthly
filtered URLs to grab everything.
"""
from typing import List, Optional, Tuple
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso, FR_MONTHS

VENUE = "Théâtre de la Croix-Rousse"
SLUG = "croix-rousse"
HOST = "https://www.croix-rousse.com"
URL = HOST + "/au-programme/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Range with arrow: "5 → 7 mai 2026"
DATE_RANGE = re.compile(
    r"\b(\d{1,2})\s*[→–-]\s*(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
# Single: "lundi 18 mai 2026" or "18 mai 2026"
DATE_SINGLE = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)


def _normalize_month(s: str) -> Optional[int]:
    s = s.lower().rstrip(".")
    s = (s.replace("é", "e").replace("è", "e").replace("ê", "e")
           .replace("ô", "o").replace("û", "u"))
    return FR_MONTHS.get(s)


def _extract_dates(text: str) -> Tuple[Optional[Date], Optional[Date]]:
    m = DATE_RANGE.search(text)
    if m:
        d1, d2, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                start = Date(int(yr), month, int(d1))
                end = Date(int(yr), month, int(d2))
                return start, end
            except ValueError:
                pass

    m = DATE_SINGLE.search(text)
    if m:
        d, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                return Date(int(yr), month, int(d)), None
            except ValueError:
                pass

    return None, None


def _scrape(url: str) -> List[Event]:
    try:
        resp = requests.get(url, timeout=20, headers=HEADERS)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    events: List[Event] = []
    seen_urls: set = set()
    today = Date.today()

    # Each event card is an <a href="/au-programme/<slug>/">
    for a in soup.select('a[href*="/au-programme/"]'):
        href = a.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        if href in seen_urls:
            continue
        # Skip the index page itself and category sub-pages
        path_part = href.replace(HOST, "").rstrip("/")
        # path must be /au-programme/<single-slug>
        parts = [p for p in path_part.split("/") if p]
        if len(parts) != 2 or parts[0] != "au-programme":
            continue
        # Skip sub-pages like /au-programme/festiv·iel
        if "festiv" in parts[1].lower():
            continue

        text = a.get_text(" ", strip=True)
        d_start, d_end = _extract_dates(text)
        if not d_start:
            continue
        if d_start < today and (d_end is None or d_end < today):
            continue

        # Title from h3 inside the card
        title_el = a.find(["h3", "h2"])
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 250:
            continue

        # Subtitle: text right after the date (often the company / author)
        text_nodes = [t for t in a.stripped_strings]
        # Drop title and date-like nodes, keep the rest
        rest: List[str] = []
        for tn in text_nodes:
            if tn == title:
                continue
            tn_lower = tn.lower()
            if DATE_RANGE.fullmatch(tn) or DATE_SINGLE.fullmatch(tn):
                continue
            if tn_lower.startswith("dès "):
                continue
            if tn_lower in ("en savoir plus", "réserver", "hors les murs",
                            "voir toute la programmation",
                            "quartier libre - jeunesse en création"):
                continue
            if len(tn) < 2 or len(tn) > 250:
                continue
            rest.append(tn)
        subtitle = rest[0] if rest else None

        # Image
        image: Optional[str] = None
        img = a.find("img")
        if img:
            src = img.get("src", "") or ""
            if src.startswith("http"):
                image = src

        seen_urls.add(href)
        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=subtitle,
            category="théâtre",
            date_start=iso(d_start),
            date_end=iso(d_end) if d_end else None,
            time=None,
            url=href,
            image=image,
        ))

    return events


def fetch() -> List[Event]:
    all_events: List[Event] = []

    # Main page
    all_events.extend(_scrape(URL))

    # Iterate through coming months to catch events filtered out by default
    today = Date.today()
    for offset in range(0, 12):
        month = today.month + offset
        year = today.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        date_param = f"{year}-{month:02d}-01"
        # Try both saison-25-26 and saison-26-27
        for season in ("saison-25-26", "saison-26-27"):
            url_with_filter = f"{URL}?paged=1&season={season}&date={date_param}"
            all_events.extend(_scrape(url_with_filter))

    seen, unique = set(), []
    for e in all_events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)

    if not unique:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: Croix-Rousse — 0 events", file=sys.stderr)
        try:
            resp = requests.get(URL, timeout=15, headers=HEADERS)
            print(f"  {URL} -> {resp.status_code} ({len(resp.text)} bytes)",
                  file=sys.stderr)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                links = soup.select('a[href*="/au-programme/"]')
                print(f"    /au-programme/ links: {len(links)}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  {URL} -> failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    unique.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "·", e.title, "·", e.url)
