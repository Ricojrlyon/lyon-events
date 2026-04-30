"""Scraper for Le Transbordeur (transbordeur.fr/agenda).

When the scraper returns 0 events, it prints a diagnostic block to stderr
showing what's actually on the page.
"""
from typing import List, Optional
from datetime import date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup

from .base import Event, parse_french_date, iso, FR_MONTHS

VENUE = "Le Transbordeur"
SLUG = "transbordeur"
URL = "https://www.transbordeur.fr/agenda/"
HOST = "https://www.transbordeur.fr"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

DATE_LONG = re.compile(
    r"\w+\s+(\d{1,2})\s+(\w+)\s+(\d{4})",
    re.IGNORECASE,
)
LOOSE_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(janv|f[eé]vr|mars|avr|mai|juin|juil|ao[uû]t|sept|oct|nov|d[eé]c)",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"\b(\d{1,2})[h:](\d{2})\b")

GENRE_TAGS = (
    "ROCK / POP", "DARK / METAL", "ELECTRO / TECHNO", "FUNK / JAZZ",
    "RAP / URBAIN", "SONO MONDIALE / DUB", "VARIETE / CHANSON",
    "FOLK / COUNTRY", "ORIGINAL DUB CULTURE", "ROCK / METAL / HIP HOP",
)


def _french_month_num(s: str) -> Optional[int]:
    return FR_MONTHS.get(s.lower())


def _find_card(link, max_levels: int = 6):
    el = link
    year_re = re.compile(r"\b20\d{2}\b")
    for _ in range(max_levels):
        parent = el.parent
        if parent is None or parent.name in ("html", "body"):
            return el
        el = parent
        if year_re.search(el.get_text(" ", strip=True)):
            return el
    return el


def _print_diagnostic(soup, response_text: str):
    print("=" * 60, file=sys.stderr)
    print("DIAGNOSTIC: Le Transbordeur scraper found 0 events.", file=sys.stderr)
    print(f"  Page size: {len(response_text)} bytes", file=sys.stderr)

    evenement_links = soup.select('a[href*="/evenement/"]')
    agenda_links = soup.select('a[href*="/agenda/"]')
    article_tags = soup.find_all("article")
    h2s = soup.find_all("h2")
    h3s = soup.find_all("h3")

    print(f"  /evenement/ links: {len(evenement_links)}", file=sys.stderr)
    for a in evenement_links[:5]:
        print(f"    - {a.get('href', '')!r}", file=sys.stderr)
    print(f"  /agenda/ links: {len(agenda_links)}", file=sys.stderr)
    for a in agenda_links[:5]:
        print(f"    - {a.get('href', '')!r}", file=sys.stderr)
    print(f"  <article> tags: {len(article_tags)}", file=sys.stderr)
    print(f"  <h2> count: {len(h2s)}", file=sys.stderr)
    for h in h2s[:8]:
        t = h.get_text(strip=True)[:80]
        print(f"    - {t!r}", file=sys.stderr)
    print(f"  <h3> count: {len(h3s)}", file=sys.stderr)
    for h in h3s[:8]:
        t = h.get_text(strip=True)[:80]
        print(f"    - {t!r}", file=sys.stderr)

    # Show the first few unique <a> hrefs to figure out the URL pattern
    all_links = soup.find_all("a", href=True)
    seen_pref = set()
    print(f"  Unique URL prefixes seen ({len(all_links)} total links):", file=sys.stderr)
    for a in all_links:
        href = a["href"]
        if href.startswith("http"):
            # extract path prefix
            try:
                path = href.split("//", 1)[1].split("/", 1)[1]
                pref = "/" + path.split("/", 1)[0]
            except IndexError:
                pref = "/"
        else:
            pref = "/" + href.lstrip("/").split("/", 1)[0]
        if pref not in seen_pref:
            seen_pref.add(pref)
            print(f"    - {pref}", file=sys.stderr)
        if len(seen_pref) >= 15:
            break

    page_text = soup.get_text(" ", strip=True)
    long_dates = DATE_LONG.findall(page_text)
    loose_dates = LOOSE_DATE_RE.findall(page_text)
    print(f"  Long-form dates (day month year): {len(long_dates)}", file=sys.stderr)
    print(f"    First 5: {long_dates[:5]}", file=sys.stderr)
    print(f"  Loose dates (day month): {len(loose_dates)}", file=sys.stderr)
    print(f"    First 5: {loose_dates[:5]}", file=sys.stderr)

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
    seen_urls: set = set()

    for a in soup.select('a[href*="/evenement/"]'):
        href = a.get("href", "")
        if href.startswith("/"):
            href = HOST + href
        if not href.startswith("http"):
            continue
        if href.rstrip("/") in (HOST + "/evenement", HOST + "/agenda"):
            continue
        if href in seen_urls:
            continue

        card = _find_card(a)
        text = card.get_text(" ", strip=True)

        m = DATE_LONG.search(text)
        if not m:
            continue
        d_str, mo_str, yr = m.groups()
        month = _french_month_num(mo_str)
        if not month:
            continue
        try:
            d_iso = Date(int(yr), month, int(d_str)).isoformat()
        except ValueError:
            continue

        time_str: Optional[str] = None
        m_time = TIME_RE.search(text)
        if m_time:
            hh = int(m_time.group(1))
            mm = m_time.group(2)
            if 0 <= hh <= 23:
                time_str = f"{hh:02d}:{mm}"

        title_el = card.find(["h2", "h3"])
        title = title_el.get_text(strip=True) if title_el else a.get_text(" ", strip=True)
        title = title.strip()
        if not title or len(title) < 2 or len(title) > 200:
            continue
        skip_lower = ("agenda", "billetterie", "menu", "fr en",
                      "voir plus", "club transbo", "grande salle")
        if title.lower() in skip_lower:
            continue

        category: Optional[str] = "concert"
        text_upper = text.upper()
        for tag in GENRE_TAGS:
            if tag in text_upper:
                category = tag.lower().split(" / ")[0]
                break

        image: Optional[str] = None
        for img in card.find_all("img"):
            src = img.get("src") or ""
            if src.startswith("http") and not src.endswith(".svg"):
                image = src
                break

        seen_urls.add(href)
        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=None,
            category=category,
            date_start=d_iso,
            date_end=None,
            time=time_str,
            url=href,
            image=image,
        ))

    seen, unique = set(), []
    for e in events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)

    if not unique:
        _print_diagnostic(soup, resp.text)

    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, e.time or "  -  ", "·", e.title, "·", e.url)
