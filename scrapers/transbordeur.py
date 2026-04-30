"""Scraper for Le Transbordeur (transbordeur.fr/agenda).

The agenda page is a JavaScript SPA: HTML contains only nav chrome.
The site exposes a WordPress REST API with 855+ routes (per a previous
diagnostic). This version probes likely event endpoints, and if none
work, prints a focused diagnostic listing routes containing the words
"event", "concert", "agenda", "spectacle", "artist", "show", or "post".
"""
from typing import List, Optional
from datetime import datetime, date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup

from .base import Event, iso

VENUE = "Le Transbordeur"
SLUG = "transbordeur"
SITE = "https://www.transbordeur.fr"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Common WP custom-post-type slugs to try.
WP_ENDPOINTS = [
    "/wp-json/wp/v2/event?per_page=100&_embed=1",
    "/wp-json/wp/v2/events?per_page=100&_embed=1",
    "/wp-json/wp/v2/concert?per_page=100&_embed=1",
    "/wp-json/wp/v2/concerts?per_page=100&_embed=1",
    "/wp-json/wp/v2/spectacle?per_page=100&_embed=1",
    "/wp-json/wp/v2/spectacles?per_page=100&_embed=1",
    "/wp-json/wp/v2/agenda?per_page=100&_embed=1",
    "/wp-json/wp/v2/show?per_page=100&_embed=1",
    "/wp-json/wp/v2/programmation?per_page=100&_embed=1",
]

# Keywords used to filter routes for diagnostic output.
INTERESTING_KEYWORDS = (
    "event", "concert", "agenda", "spectacle", "show",
    "artist", "programmation", "salle", "billet",
)


def _strip_html(html_text: str) -> str:
    if not html_text:
        return ""
    return BeautifulSoup(html_text, "html.parser").get_text(" ", strip=True)


def _date_from_post(post: dict) -> Optional[Date]:
    acf = post.get("acf") or {}
    for key in ("date_event", "event_date", "date_evenement", "date_concert",
                "date", "date_debut", "start_date"):
        val = acf.get(key) if isinstance(acf, dict) else None
        if isinstance(val, str) and val:
            try:
                clean = val.replace("/", "-").replace(" ", "T").split("T")[0]
                if "-" not in clean and len(clean) == 8:
                    clean = f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}"
                return Date.fromisoformat(clean[:10])
            except (ValueError, IndexError):
                pass

    meta = post.get("meta") or {}
    for key in ("date_event", "event_date", "_event_date", "date_evenement",
                "_event_start", "_start_date"):
        val = meta.get(key) if isinstance(meta, dict) else None
        if isinstance(val, str):
            try:
                return Date.fromisoformat(val[:10])
            except ValueError:
                pass

    for key in ("date", "date_gmt"):
        val = post.get(key)
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
            except ValueError:
                pass

    return None


def _try_endpoint(endpoint: str) -> List[Event]:
    url = SITE + endpoint
    try:
        resp = requests.get(url, timeout=20, headers=HEADERS)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    if not isinstance(data, list) or not data:
        return []

    events: List[Event] = []
    for post in data:
        d = _date_from_post(post)
        if not d or d < Date.today():
            continue
        title_field = post.get("title") or ""
        if isinstance(title_field, dict):
            title = _strip_html(title_field.get("rendered", "")).strip()
        else:
            title = _strip_html(str(title_field)).strip()
        if not title:
            continue
        link = post.get("link") or SITE + "/agenda/"
        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=None,
            category="concert",
            date_start=iso(d),
            date_end=None,
            time=None,
            url=link,
            image=None,
        ))
    return events


def _diagnose():
    print("=" * 60, file=sys.stderr)
    print("DIAGNOSTIC: Le Transbordeur — looking for event routes", file=sys.stderr)
    try:
        resp = requests.get(SITE + "/wp-json/", timeout=20, headers=HEADERS)
        if resp.status_code != 200:
            print(f"  /wp-json/ status: {resp.status_code}", file=sys.stderr)
            return
        data = resp.json()
        routes = list((data.get("routes") or {}).keys())
        relevant = [r for r in routes
                    if any(k in r.lower() for k in INTERESTING_KEYWORDS)]
        print(f"  Total routes: {len(routes)}", file=sys.stderr)
        print(f"  Routes matching event keywords: {len(relevant)}",
              file=sys.stderr)
        for r in relevant[:50]:
            print(f"    - {r}", file=sys.stderr)

        # Also list all top-level WP /v2 custom post types
        v2_types = [r for r in routes
                    if r.startswith("/wp/v2/") and r.count("/") <= 3]
        print(f"  All /wp/v2/* routes ({len(v2_types)}):", file=sys.stderr)
        for r in v2_types[:50]:
            print(f"    - {r}", file=sys.stderr)
    except (requests.RequestException, ValueError) as e:
        print(f"  Failed: {e}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)


def fetch() -> List[Event]:
    for endpoint in WP_ENDPOINTS:
        events = _try_endpoint(endpoint)
        if events:
            print(f"[Transbordeur] Got {len(events)} events from {endpoint}",
                  file=sys.stderr)
            seen, unique = set(), []
            for e in events:
                if e.id not in seen:
                    seen.add(e.id)
                    unique.append(e)
            return unique
    _diagnose()
    return []


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "·", e.title, "·", e.url)
