"""Scraper for Théâtre National Populaire (tnp-villeurbanne.com).

v2: rewrote _find_card to properly tolerate multiple links to the SAME
slug within a card (image link + title link + "réserver" link).
"""
from typing import List, Optional, Tuple
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup, Tag

from .base import Event, iso, FR_MONTHS

VENUE = "TNP"
SLUG = "tnp"
HOST = "https://www.tnp-villeurbanne.com"
URL = HOST + "/programmation/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

DATE_RANGE_TWO_MONTHS = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+)\s*[→–\-]\s*(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
DATE_RANGE_ONE_MONTH = re.compile(
    r"\b(\d{1,2})\s*[→–\-]\s*(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
DATE_TWO = re.compile(
    r"\b(\d{1,2})\s+et\s+(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)
DATE_SINGLE = re.compile(
    r"\b(\d{1,2})\s+([\wéèêôû]+)\s+(\d{4})\b",
    re.IGNORECASE,
)


def _normalize_month(s: str) -> Optional[int]:
    s = s.lower().rstrip(".")
    s = (s.replace("é", "e").replace("è", "e").replace("ê", "e")
           .replace("ô", "o").replace("û", "u"))
    return FR_MONTHS.get(s)


def _slug_from_href(href: str) -> str:
    """Extract /spectacle/<slug>/ portion, normalised."""
    if not href:
        return ""
    href = href.split("?")[0].split("#")[0]
    return href.rstrip("/").lower()


def _extract_dates(text: str) -> Tuple[Optional[Date], Optional[Date]]:
    m = DATE_RANGE_TWO_MONTHS.search(text)
    if m:
        d1, mo1, d2, mo2, yr = m.groups()
        month1 = _normalize_month(mo1)
        month2 = _normalize_month(mo2)
        year = int(yr)
        if month1 and month2:
            try:
                start_year = year - 1 if month1 > month2 else year
                return (Date(start_year, month1, int(d1)),
                        Date(year, month2, int(d2)))
            except ValueError:
                pass

    m = DATE_RANGE_ONE_MONTH.search(text)
    if m:
        d1, d2, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                start = Date(int(yr), month, int(d1))
                end = Date(int(yr), month, int(d2))
                if end >= start:
                    return start, end
            except ValueError:
                pass

    m = DATE_TWO.search(text)
    if m:
        d1, d2, mo, yr = m.groups()
        month = _normalize_month(mo)
        if month:
            try:
                start = Date(int(yr), month, int(d1))
                end = Date(int(yr), month, int(d2))
                if end >= start:
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


def _find_card(link: Tag, target_slug: str, max_levels: int = 8) -> Optional[Tag]:
    """Walk up to find the smallest ancestor that:
    - Contains a date pattern.
    - Does NOT contain links to OTHER /spectacle/<slug>/ slugs.
    Multiple links to the SAME slug are fine (image + title + button).
    """
    el: Optional[Tag] = link
    for _ in range(max_levels):
        parent = el.parent if el else None
        if parent is None or parent.name in ("html", "body"):
            return None
        el = parent
        text = el.get_text(" ", strip=True)
        if not DATE_SINGLE.search(text):
            continue
        # Collect distinct slug URLs in this element
        distinct_slugs = set()
        for a in el.select('a[href*="/spectacle/"]'):
            slug = _slug_from_href(a.get("href", ""))
            if slug:
                distinct_slugs.add(slug)
        # Acceptable if 0 or 1 distinct slug (the target). Any more = too wide.
        if len(distinct_slugs) <= 1:
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

    html = resp.text
    cut = html.lower().find("spectacles passés")
    if cut > 0:
        html = html[:cut]

    soup = BeautifulSoup(html, "html.parser")
    events: List[Event] = []
    seen_slugs: set = set()
    today = Date.today()

    # Anchor on links to /spectacle/<slug>/ — dedupe by slug
    for link in soup.select('a[href*="/spectacle/"]'):
        href = link.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        slug = _slug_from_href(href)
        if not slug or slug in seen_slugs:
            continue
        # Skip the section root
        if slug.endswith("/spectacle"):
            continue

        card = _find_card(link, slug)
        if card is None:
            continue
        text = card.get_text(" ", strip=True)

        d_start, d_end = _extract_dates(text)
        if not d_start:
            continue
        if d_start < today and (d_end is None or d_end < today):
            continue

        # Title: prefer h3 inside the card
        title_el = card.find(["h3", "h2"])
        if title_el:
            title = title_el.get_text(" ", strip=True)
        else:
            title = link.get_text(" ", strip=True)
        if not title or len(title) < 2 or len(title) > 250:
            continue
        if title.lower() in ("réserver", "voir plus", "en savoir plus"):
            continue

        # Subtitle: first non-title, non-date, non-meta text
        subtitle: Optional[str] = None
        for tn in card.stripped_strings:
            if tn == title:
                continue
            tn_lower = tn.lower()
            if (DATE_RANGE_TWO_MONTHS.fullmatch(tn) or
                DATE_RANGE_ONE_MONTH.fullmatch(tn) or
                DATE_SINGLE.fullmatch(tn) or
                DATE_TWO.fullmatch(tn)):
                continue
            if tn_lower.startswith("dès "):
                continue
            if tn_lower in ("réserver", "création", "biennale de la danse",
                            "événement", "evenement", "temps fort",
                            "première française", "hors les murs",
                            "festival sens interdits", "festival écrans mixtes",
                            "lauréat prix incandescences 2024",
                            "avec l'opéra de lyon",
                            "avec les célestins, théâtre de lyon",
                            "ukraine", "chine", "belgique", "suisse", "liban",
                            "hongrie - norvège"):
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
        print("=" * 60, file=sys.stderr)
        print("DIAGNOSTIC: TNP — 0 events", file=sys.stderr)
        try:
            resp2 = requests.get(URL, timeout=15, headers=HEADERS)
            html2 = resp2.text
            cut2 = html2.lower().find("spectacles passés")
            if cut2 > 0:
                html2 = html2[:cut2]
            soup2 = BeautifulSoup(html2, "html.parser")
            spec_links = soup2.select('a[href*="/spectacle/"]')
            distinct_slugs = set()
            for a in spec_links:
                s = _slug_from_href(a.get("href", ""))
                if s:
                    distinct_slugs.add(s)
            print(f"  Distinct /spectacle/ slugs (after cut): {len(distinct_slugs)}",
                  file=sys.stderr)
            # For first 3 slugs, walk up and report
            for slug_url in list(distinct_slugs)[:3]:
                first_link = None
                for a in spec_links:
                    if _slug_from_href(a.get("href", "")) == slug_url:
                        first_link = a
                        break
                if first_link:
                    card = _find_card(first_link, slug_url)
                    if card:
                        text = card.get_text(" ", strip=True)[:150]
                        d_start, d_end = _extract_dates(text)
                        print(f"  slug={slug_url[-50:]!r}", file=sys.stderr)
                        print(f"    card text: {text!r}", file=sys.stderr)
                        print(f"    extracted: {d_start} → {d_end}", file=sys.stderr)
                    else:
                        print(f"  slug={slug_url[-50:]!r}: no card found", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  failed: {e}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    events.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return events


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "→", e.date_end or "  -  ", "·", e.title)
