"""Scraper for Le Transbordeur (transbordeur.fr/agenda).

The agenda page is a JavaScript-rendered SPA: server-side HTML contains only
navigation chrome, all event data is loaded by JS after page load. So
scraping the HTML returns nothing useful (verified via diagnostic).

Strategy: try the WordPress REST API (the SPA almost certainly fetches its
data from there). Common endpoints to probe:
  - /wp-json/wp/v2/event   (custom post type, most likely)
  - /wp-json/wp/v2/events  (alternative naming)
  - /wp-json/wp/v2/posts   (regular posts)

If none return event data, print a diagnostic listing the available
endpoints from /wp-json/ so we can iterate.
"""
from typing import List, Optional
from datetime import datetime, date as Date
import re
import sys
import requests
from bs4 import BeautifulSoup

from .base import Event, parse_french_date, iso

VENUE = "Le Transbordeur"
SLUG = "transbordeur"
SITE = "https://www.transbordeur.fr"
AGENDA_URL = SITE + "/agenda/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# Endpoints to try, in order. The first one that returns JSON-like event
# data with future dates wins.
WP_ENDPOINTS = [
    "/wp-json/wp/v2/event?per_page=100&_embed=1",
    "/wp-json/wp/v2/events?per_page=100&_embed=1",
    "/wp-json/wp/v2/concert?per_page=100&_embed=1",
    "/wp-json/wp/v2/spectacle?per_page=100&_embed=1",
    "/wp-json/wp/v2/posts?per_page=100&_embed=1",
]


def _strip_html(html_text: str) -> str:
    """Render HTML excerpt to plain text."""
    if not html_text:
        return ""
    return BeautifulSoup(html_text, "html.parser").get_text(" ", strip=True)


def _extract_date_from_post(post: dict) -> Optional[Date]:
    """Try multiple common date field locations in a WP REST post."""
    # ACF field commonly named 'date_event' / 'event_date' / 'date_evenement'
    acf = post.get("acf") or {}
    for key in ("date_event", "event_date", "date_evenement", "date", "date_debut"):
        val = acf.get(key)
        if isinstance(val, str) and re.match(r"\d{4}-?\d{2}-?\d{2}", val):
            try:
                clean = val.replace("/", "-").replace(" ", "T").split("T")[0]
                if "-" not in clean:
                    clean = f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}"
                return Date.fromisoformat(clean)
            except (ValueError, IndexError):
                pass

    # Meta fields
    meta = post.get("meta") or {}
    for key in ("date_event", "event_date", "_event_date", "date_evenement"):
        val = meta.get(key)
        if isinstance(val, str):
            try:
                return Date.fromisoformat(val[:10])
            except ValueError:
                pass

    # Fallback: post's publish date (less useful but at least valid)
    for key in ("date", "date_gmt"):
        val = post.get(key)
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
            except ValueError:
                pass

    return None


def _fetch_via_wp_api() -> List[Event]:
    events: List[Event] = []
    for endpoint in WP_ENDPOINTS:
        url = SITE + endpoint
        try:
            resp = requests.get(url, timeout=20, headers=HEADERS)
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue
        try:
            data = resp.json()
        except ValueError:
            continue
        if not isinstance(data, list) or not data:
            continue

        # We have JSON entries. Try to interpret them as events.
        ok = 0
        for post in data:
            d = _extract_date_from_post(post)
            if not d:
                continue
            if d < Date.today():
                continue

            title_html = (post.get("title") or {}).get("rendered", "") if isinstance(
                post.get("title"), dict) else (post.get("title") or "")
            title = _strip_html(title_html).strip()
            if not title:
                continue

            link = post.get("link") or AGENDA_URL
            excerpt_html = (post.get("excerpt") or {}).get("rendered", "") if isinstance(
                post.get("excerpt"), dict) else ""
            subtitle = _strip_html(excerpt_html)[:200] or None

            # Image from _embedded.wp:featuredmedia
            image = None
            embedded = post.get("_embedded") or {}
            media = (embedded.get("wp:featuredmedia") or [None])[0]
            if isinstance(media, dict):
                image = (media.get("source_url")
                         or (media.get("media_details") or {}).get("sizes", {}).get(
                             "medium", {}).get("source_url"))

            events.append(Event(
                venue=VENUE,
                venue_slug=SLUG,
                title=title,
                subtitle=subtitle,
                category="concert",
                date_start=iso(d),
                date_end=None,
                time=None,
                url=link,
                image=image,
            ))
            ok += 1

        if ok > 0:
            print(f"[Transbordeur] Got {ok} events from {endpoint}", file=sys.stderr)
            return events

    return events


def _print_diagnostic():
    """Probe /wp-json/ to list available endpoints."""
    print("=" * 60, file=sys.stderr)
    print("DIAGNOSTIC: Le Transbordeur — WP REST API probe", file=sys.stderr)
    try:
        resp = requests.get(SITE + "/wp-json/", timeout=20, headers=HEADERS)
        print(f"  /wp-json/ status: {resp.status_code}", file=sys.stderr)
        if resp.status_code == 200:
            try:
                data = resp.json()
                routes = list((data.get("routes") or {}).keys())
                print(f"  Available routes ({len(routes)}):", file=sys.stderr)
                for r in routes[:30]:
                    print(f"    - {r}", file=sys.stderr)
                if len(routes) > 30:
                    print(f"    ... ({len(routes) - 30} more)", file=sys.stderr)
            except ValueError:
                print("  (not JSON)", file=sys.stderr)
                print(f"  First 200 chars: {resp.text[:200]!r}", file=sys.stderr)
    except requests.RequestException as e:
        print(f"  /wp-json/ failed: {e}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)


def fetch() -> List[Event]:
    events = _fetch_via_wp_api()
    if not events:
        _print_diagnostic()
    # Dedupe
    seen, unique = set(), []
    for e in events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)
    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, "·", e.title, "·", e.url)
