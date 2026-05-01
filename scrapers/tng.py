"""Scraper for Théâtre Nouvelle Génération (tng-lyon.fr).

v4: completely rewrite. The structure on this site is:
    <a href="/evenement/<slug>/">
      <strong>04</strong> juin > <strong>06</strong> juin
      <h2>Mathieu au milieu</h2>
      Author...
      Venue
      Description...
    </a>

So the <h2> is INSIDE the <a>. Walking up from h2 we hit the <a>, which
contains all the data we need. Don't search for the link — the <a> IS
the card.
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

SHORT_MONTHS = {
    "janv": 1, "fevr": 2, "févr": 2, "mars": 3, "avr": 4, "mai": 5,
    "juin": 6, "juil": 7, "juill": 7, "aout": 8, "août": 8, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12, "déc": 12,
}

DATE_RANGE = re.compile(
    r"(\d{1,2})\s+([\wéèêôû]+)\s*[>→–\-]\s*(\d{1,2})\s+([\wéèêôû]+)",
    re.IGNORECASE | re.DOTALL,
)
DATE_SINGLE = re.compile(
    r"(\d{1,2})\s+([\wéèêôû]+)",
    re.IGNORECASE,
)


def _normalize_month(s: str) -> Optional[int]:
    s = s.lower().rstrip(".")
    s = (s.replace("é", "e").replace("è", "e").replace("ê", "e")
           .replace("ô", "o").replace("û", "u"))
    if s in FR_MONTHS:
        return FR_MONTHS[s]
    return SHORT_MONTHS.get(s)


def _slug_from_href(href: str) -> str:
    if not href:
        return ""
    href = href.split("?")[0].split("#")[0]
    return href.rstrip("/").lower()


def _smart_year(month: int, day: int, ref: Date) -> int:
    grace = 15
    try:
        candidate = Date(ref.year, month, day)
    except ValueError:
        return ref.year
    delta = (ref - candidate).days
    if delta > grace:
        return ref.year + 1
    return ref.year


def _extract_dates(text: str) -> Tuple[Optional[Date], Optional[Date]]:
    today = Date.today()

    m = DATE_RANGE.search(text)
    if m:
        d1, mo1, d2, mo2 = m.groups()
        month1 = _normalize_month(mo1)
        month2 = _normalize_month(mo2)
        if month1 and month2:
            try:
                day1, day2 = int(d1), int(d2)
                if not (1 <= day1 <= 31 and 1 <= day2 <= 31):
                    pass
                elif month1 == month2:
                    year = _smart_year(month1, day1, today)
                    return Date(year, month1, day1), Date(year, month2, day2)
                else:
                    start_year = _smart_year(month1, day1, today)
                    end_year = start_year + 1 if month1 > month2 else start_year
                    return (Date(start_year, month1, day1),
                            Date(end_year, month2, day2))
            except ValueError:
                pass

    for m in DATE_SINGLE.finditer(text):
        d, mo = m.group(1), m.group(2)
        month = _normalize_month(mo)
        if month:
            try:
                day = int(d)
                if not (1 <= day <= 31):
                    continue
                year = _smart_year(month, day, today)
                return Date(year, month, day), None
            except ValueError:
                continue

    return None, None


def _find_event_link_ancestor(node: Tag, max_levels: int = 8) -> Optional[Tag]:
    """Walk up from node until we find an <a href="/evenement/..."> ancestor."""
    el: Optional[Tag] = node.parent
    for _ in range(max_levels):
        if el is None or el.name in ("html", "body"):
            return None
        if el.name == "a":
            href = el.get("href", "") or ""
            if "/evenement/" in href:
                slug = _slug_from_href(href)
                # Make sure it's not just the /evenement/ root
                if slug and not slug.endswith("/evenement"):
                    return el
        el = el.parent
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

    # Anchor on <a href="/evenement/..."> elements directly. Iterate distinct slugs.
    for a in soup.select('a[href*="/evenement/"]'):
        href = a.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        slug = _slug_from_href(href)
        if not slug or slug in seen_slugs:
            continue
        if slug.endswith("/evenement"):
            continue

        # The <a> must contain a <h2>; otherwise it's the image-only link.
        # We want the link that wraps the title block.
        h2 = a.find(["h2", "h3"])
        if not h2:
            continue

        title = h2.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 250:
            continue

        text = a.get_text(" ", strip=True)
        d_start, d_end = _extract_dates(text)
        if not d_start:
            continue
        if d_start < today and (d_end is None or d_end < today):
            continue

        # Subtitle: text node after title in stripped_strings
        subtitle: Optional[str] = None
        for tn in a.stripped_strings:
            if tn == title:
                continue
            tn_lower = tn.lower()
            if DATE_RANGE.fullmatch(tn) or DATE_SINGLE.fullmatch(tn):
                continue
            if re.fullmatch(r"\d{1,2}", tn):
                continue
            if tn_lower in (">", "→", "tng-vaise", "ateliers - presqu'île",
                            "ateliers-presqu'île", "ateliers - presqu’île",
                            "en famille", "réserver", "plus d'infos",
                            "voir plus", "gratuit", "spectacle", "atelier"):
                continue
            if tn_lower.startswith("dès "):
                continue
            if (tn_lower.startswith("3-6 ans") or
                "à 12 ans" in tn_lower or "à 18 ans" in tn_lower or
                re.fullmatch(r"\d+\+", tn) or
                re.fullmatch(r"de \d+ à \d+ ans", tn_lower) or
                re.fullmatch(r"\d+\s*[->>]\s*\d+\s*ans", tn_lower)):
                continue
            # Discard month names alone
            if _normalize_month(tn):
                continue
            if len(tn) < 3 or len(tn) > 250:
                continue
            subtitle = tn
            break

        # Image
        image: Optional[str] = None
        img = a.find("img")
        if img:
            src = img.get("src", "") or ""
            if src.startswith("http"):
                image = src

        seen_slugs.add(slug)
        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=subtitle,
            category="théâtre",
            date_start=iso(d_start),
            date_end=iso(d_end) if d_end else None,
            time=None,
            url=href.split("?")[0],
            image=image,
        ))

    if not events:
        # Diagnostic — dump HTML of first event link to see the actual structure
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: TNG — 0 events", file=sys.stderr)
        try:
            resp2 = requests.get(URL, timeout=15, headers=HEADERS)
            soup2 = BeautifulSoup(resp2.text, "html.parser")
            ev_links = soup2.select('a[href*="/evenement/"]')
            print(f"  /evenement/ <a> count: {len(ev_links)}", file=sys.stderr)
            for a in ev_links[:3]:
                href = a.get("href", "")
                has_h2 = a.find(["h2", "h3"]) is not None
                text = a.get_text(" ", strip=True)[:200]
                # Truncated raw HTML
                raw = str(a)[:400]
                print(f"  href={href!r} has_h2={has_h2}", file=sys.stderr)
                print(f"    text: {text!r}", file=sys.stderr)
                print(f"    raw[:400]: {raw!r}", file=sys.stderr)
            # Also show first h2 raw context
            h2s = soup2.find_all(["h2", "h3"])
            if h2s:
                h2 = h2s[0]
                # Walk up 4 levels showing each
                el = h2
                for lvl in range(4):
                    parent = el.parent
                    if parent is None:
                        break
                    el = parent
                    summary = f"<{el.name}"
                    if el.get('class'):
                        summary += f" class={'.'.join(el.get('class'))[:40]}"
                    summary += ">"
                    print(f"  h2 ancestor lvl{lvl}: {summary}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    events.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "→", e.date_end or "  -  ", "·", e.title)
