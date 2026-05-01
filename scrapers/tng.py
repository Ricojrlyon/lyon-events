"""Scraper for Théâtre Nouvelle Génération (tng-lyon.fr).

Page /programme/ lists upcoming events. Each card has:
- <h2> with title (also wrapped in <a href="/evenement/<slug>/">)
- Date format "21 mai > 23 mai" (range with >) or "26 mai > 02 juin"
  or "14 mars" (single, day in <strong>)
- The date is in two parts on the page: a big <strong> day number, then
  the month, then "> day month" for the range.
- Below: company/director, venue ("TNG-Vaise" or "Ateliers - Presqu'île"),
  age guidance ("Dès 4 ans"), description.

Year is NOT explicit anywhere — we infer from current date.

Note: The TNG runs from September to June for one season. To handle
"22 avril > 30 juin" properly when current date is May 2026, we infer
both dates as belonging to the upcoming season.
"""
from typing import List, Optional, Tuple
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso, FR_MONTHS

VENUE = "TNG"
SLUG = "tng"
HOST = "https://www.tng-lyon.fr"
URL = HOST + "/programme/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Month names normalised
SHORT_MONTHS = {
    "janv": 1, "fevr": 2, "févr": 2, "mars": 3, "avr": 4, "mai": 5,
    "juin": 6, "juil": 7, "juill": 7, "aout": 8, "août": 8, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12, "déc": 12,
}

# Range "21 mai > 23 mai" or "26 mai > 02 juin" or "22 avril > 30 juin"
DATE_RANGE = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+)\s*[>→–\-]\s*(\d{1,2})\s+([\wéèêôû]+)\b",
    re.IGNORECASE,
)
# Single "14 mars" — only on its own
DATE_SINGLE = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+)\b",
    re.IGNORECASE,
)


def _normalize_month(s: str) -> Optional[int]:
    s = s.lower().rstrip(".")
    s = (s.replace("é", "e").replace("è", "e").replace("ê", "e")
           .replace("ô", "o").replace("û", "u"))
    if s in FR_MONTHS:
        return FR_MONTHS[s]
    return SHORT_MONTHS.get(s)


def _smart_year(month: int, day: int, ref: Date) -> int:
    """Year inference: if (month, day) for current year is in the past
    (more than ~15 days), use next year. The 15-day grace allows ongoing
    events to still keep current year."""
    grace = 15
    try:
        candidate_current = Date(ref.year, month, day)
    except ValueError:
        return ref.year
    delta = (ref - candidate_current).days
    if delta > grace:
        return ref.year + 1
    return ref.year


def _extract_dates(text: str) -> Tuple[Optional[Date], Optional[Date]]:
    today = Date.today()

    # Range first
    m = DATE_RANGE.search(text)
    if m:
        d1, mo1, d2, mo2 = m.groups()
        month1 = _normalize_month(mo1)
        month2 = _normalize_month(mo2)
        if month1 and month2:
            try:
                day1, day2 = int(d1), int(d2)
                if month1 == month2:
                    year = _smart_year(month1, day1, today)
                    return Date(year, month1, day1), Date(year, month2, day2)
                else:
                    # Different months — start year inferred from start date
                    start_year = _smart_year(month1, day1, today)
                    end_year = start_year + 1 if month1 > month2 else start_year
                    return (Date(start_year, month1, day1),
                            Date(end_year, month2, day2))
            except ValueError:
                pass

    # Single (must remove range matches not to overlap)
    # We need a token boundary check — look for date that's NOT inside a range
    m = DATE_SINGLE.search(text)
    if m:
        d, mo = m.group(1), m.group(2)
        month = _normalize_month(mo)
        if month:
            try:
                day = int(d)
                year = _smart_year(month, day, today)
                return Date(year, month, day), None
            except ValueError:
                pass

    return None, None


def _find_card(link: Tag, max_levels: int = 8) -> Optional[Tag]:
    """Walk up to find the card."""
    el: Optional[Tag] = link
    target_href = link.get("href", "").split("?")[0]
    for _ in range(max_levels):
        parent = el.parent if el else None
        if parent is None or parent.name in ("html", "body"):
            return None
        el = parent
        text = el.get_text(" ", strip=True)
        # Card must contain a date pattern (day + month name)
        if not DATE_SINGLE.search(text):
            continue
        # Card must not contain other /evenement/<slug>/ links
        other = 0
        for a in el.select('a[href*="/evenement/"]'):
            href = a.get("href", "").split("?")[0]
            if href and href != target_href:
                other += 1
        if other == 0:
            return el
        return None
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
    seen_urls: set = set()
    today = Date.today()

    # Anchor on event links - look for h2 inside or near them
    for a in soup.select('a[href*="/evenement/"]'):
        href = a.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        href_clean = href.split("?")[0]
        if href_clean in seen_urls:
            continue

        # Find the card
        card = _find_card(a)
        if card is None:
            continue

        # Title from h2 inside the card
        title_el = card.find(["h2", "h3"])
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 250:
            continue

        text = card.get_text(" ", strip=True)
        d_start, d_end = _extract_dates(text)
        if not d_start:
            continue
        if d_start < today and (d_end is None or d_end < today):
            continue

        # Subtitle: text node after title that looks like author/company
        subtitle: Optional[str] = None
        text_nodes = [t for t in card.stripped_strings]
        for tn in text_nodes:
            if tn == title:
                continue
            tn_lower = tn.lower()
            # Skip dates and meta
            if DATE_RANGE.fullmatch(tn) or DATE_SINGLE.fullmatch(tn):
                continue
            if re.fullmatch(r"\d{1,2}", tn):
                continue
            if tn_lower in (">", "→", "tng-vaise", "ateliers - presqu'île",
                            "ateliers-presqu'île", "en famille",
                            "réserver", "plus d'infos", "voir plus"):
                continue
            if tn_lower.startswith("dès "):
                continue
            if (tn_lower.startswith("3-6 ans") or tn_lower.startswith("7-10") or
                "à 12 ans" in tn_lower or "à 18 ans" in tn_lower or
                re.fullmatch(r"\d+\+", tn) or re.fullmatch(r"de \d+ à \d+ ans", tn_lower)):
                continue
            if len(tn) < 3 or len(tn) > 250:
                continue
            subtitle = tn
            break

        # Image
        image: Optional[str] = None
        img = card.find("img")
        if img:
            src = img.get("src", "") or ""
            if src.startswith("http"):
                image = src

        seen_urls.add(href_clean)
        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=subtitle,
            category="théâtre",
            date_start=iso(d_start),
            date_end=iso(d_end) if d_end else None,
            time=None,
            url=href_clean,
            image=image,
        ))

    if not events:
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: TNG — 0 events", file=sys.stderr)
        try:
            resp2 = requests.get(URL, timeout=15, headers=HEADERS)
            print(f"  {URL} -> {resp2.status_code} ({len(resp2.text)} bytes)",
                  file=sys.stderr)
            soup2 = BeautifulSoup(resp2.text, "html.parser")
            ev_links = soup2.select('a[href*="/evenement/"]')
            print(f"  /evenement/ links: {len(ev_links)}", file=sys.stderr)
            for a in ev_links[:5]:
                h = a.get("href", "")[:120]
                print(f"    - {h!r}", file=sys.stderr)
            h2s = soup2.find_all("h2")
            print(f"  h2 count: {len(h2s)}", file=sys.stderr)
            for h in h2s[:5]:
                print(f"    - {h.get_text(strip=True)[:80]!r}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    events.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "→", e.date_end or "  -  ", "·", e.title)
