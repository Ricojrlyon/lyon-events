"""Scraper for Le Transbordeur (transbordeur.fr/agenda).

The agenda page is a JS-rendered SPA. Diagnostic confirmed the WordPress
REST API exposes /wp/v2/evenement (singular, French). This scraper hits
that endpoint directly and parses the JSON response.

If /wp/v2/evenement returns no useful data, falls back to inspecting one
post in detail and printing all its keys for further iteration.
"""
from typing import List, Optional, Any
from datetime import datetime, date as Date
import json
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

# Keys to probe for an event date in ACF / meta / top-level fields.
DATE_KEY_CANDIDATES = (
    "date_event", "date_evenement", "date_concert", "event_date",
    "date_debut", "start_date", "date", "date_de_l_evenement",
    "date_de_levenement", "jour", "concert_date",
)

TIME_KEY_CANDIDATES = (
    "heure", "heure_evenement", "heure_debut", "horaire",
    "start_time", "time",
)


def _strip_html(html_text: str) -> str:
    if not html_text:
        return ""
    return BeautifulSoup(html_text, "html.parser").get_text(" ", strip=True)


def _normalize_date(val: Any) -> Optional[Date]:
    if not val or not isinstance(val, str):
        return None
    val = val.strip()
    # ACF dates can be 'YYYYMMDD'
    if re.fullmatch(r"\d{8}", val):
        try:
            return Date(int(val[:4]), int(val[4:6]), int(val[6:8]))
        except ValueError:
            return None
    # ISO date or datetime
    try:
        cleaned = val.replace("Z", "+00:00").replace(" ", "T")
        return datetime.fromisoformat(cleaned).date()
    except ValueError:
        pass
    try:
        return Date.fromisoformat(val[:10])
    except ValueError:
        pass
    # 'DD/MM/YYYY' or 'DD-MM-YYYY'
    m = re.match(r"(\d{2})[/-](\d{2})[/-](\d{4})", val)
    if m:
        d, mo, y = m.groups()
        try:
            return Date(int(y), int(mo), int(d))
        except ValueError:
            return None
    return None


def _normalize_time(val: Any) -> Optional[str]:
    if not val or not isinstance(val, str):
        return None
    val = val.strip()
    m = re.search(r"(\d{1,2})\s*[h:]\s*(\d{2})", val)
    if m:
        hh, mm = int(m.group(1)), m.group(2)
        if 0 <= hh <= 23:
            return f"{hh:02d}:{mm}"
    m = re.fullmatch(r"(\d{1,2})h", val)
    if m:
        hh = int(m.group(1))
        if 0 <= hh <= 23:
            return f"{hh:02d}:00"
    return None


def _extract_date(post: dict) -> Optional[Date]:
    acf = post.get("acf") or {}
    if isinstance(acf, dict):
        for k in DATE_KEY_CANDIDATES:
            d = _normalize_date(acf.get(k))
            if d:
                return d
    meta = post.get("meta") or {}
    if isinstance(meta, dict):
        for k in DATE_KEY_CANDIDATES + tuple("_" + x for x in DATE_KEY_CANDIDATES):
            d = _normalize_date(meta.get(k))
            if d:
                return d
    # Top-level fields
    for k in DATE_KEY_CANDIDATES:
        d = _normalize_date(post.get(k))
        if d:
            return d
    return None


def _extract_time(post: dict) -> Optional[str]:
    acf = post.get("acf") or {}
    if isinstance(acf, dict):
        for k in TIME_KEY_CANDIDATES:
            t = _normalize_time(acf.get(k))
            if t:
                return t
    meta = post.get("meta") or {}
    if isinstance(meta, dict):
        for k in TIME_KEY_CANDIDATES + tuple("_" + x for x in TIME_KEY_CANDIDATES):
            t = _normalize_time(meta.get(k))
            if t:
                return t
    for k in TIME_KEY_CANDIDATES:
        t = _normalize_time(post.get(k))
        if t:
            return t
    return None


def _extract_image(post: dict) -> Optional[str]:
    embedded = post.get("_embedded") or {}
    media_list = embedded.get("wp:featuredmedia") or []
    if media_list and isinstance(media_list[0], dict):
        m = media_list[0]
        url = m.get("source_url")
        if isinstance(url, str) and url.startswith("http"):
            return url
        sizes = (m.get("media_details") or {}).get("sizes") or {}
        for size_name in ("medium", "large", "full", "thumbnail"):
            size = sizes.get(size_name) or {}
            url = size.get("source_url")
            if isinstance(url, str) and url.startswith("http"):
                return url
    return None


def _diagnose_first_post():
    """Fetch one post from /wp/v2/evenement and print its full key tree."""
    print("=" * 60, file=sys.stderr)
    print("DIAGNOSTIC: Le Transbordeur — inspecting first post", file=sys.stderr)
    try:
        resp = requests.get(SITE + "/wp-json/wp/v2/evenement?per_page=1&_embed=1",
                            timeout=20, headers=HEADERS)
        if resp.status_code != 200:
            print(f"  status: {resp.status_code}", file=sys.stderr)
            print(f"  body[:300]: {resp.text[:300]!r}", file=sys.stderr)
            return
        data = resp.json()
        if not isinstance(data, list) or not data:
            print(f"  Empty result. Type: {type(data).__name__}", file=sys.stderr)
            print(f"  Sample: {str(data)[:400]}", file=sys.stderr)
            return
        post = data[0]
        print(f"  Top-level keys: {sorted(post.keys())}", file=sys.stderr)
        if "acf" in post and isinstance(post["acf"], dict):
            print(f"  acf keys: {sorted(post['acf'].keys())}", file=sys.stderr)
            # Show first few acf values for inspection
            for k, v in list(post["acf"].items())[:10]:
                v_repr = repr(v)
                if len(v_repr) > 120:
                    v_repr = v_repr[:120] + "..."
                print(f"    acf[{k!r}] = {v_repr}", file=sys.stderr)
        if "meta" in post and isinstance(post["meta"], dict):
            print(f"  meta keys: {sorted(post['meta'].keys())[:20]}",
                  file=sys.stderr)
        # Title and link
        title = post.get("title")
        if isinstance(title, dict):
            title = title.get("rendered", "")
        print(f"  title: {_strip_html(str(title))[:80]!r}", file=sys.stderr)
        print(f"  link: {post.get('link', '')!r}", file=sys.stderr)
        print(f"  date: {post.get('date', '')!r}", file=sys.stderr)
    except (requests.RequestException, ValueError, json.JSONDecodeError) as e:
        print(f"  Failed: {e}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)


def fetch() -> List[Event]:
    url = SITE + "/wp-json/wp/v2/evenement?per_page=100&_embed=1"
    try:
        resp = requests.get(url, timeout=30, headers=HEADERS)
    except requests.RequestException as e:
        print(f"[Transbordeur] request failed: {e}", file=sys.stderr)
        return []

    if resp.status_code != 200:
        print(f"[Transbordeur] /wp/v2/evenement returned {resp.status_code}",
              file=sys.stderr)
        return []

    try:
        data = resp.json()
    except ValueError:
        print(f"[Transbordeur] non-JSON response", file=sys.stderr)
        return []

    if not isinstance(data, list):
        print(f"[Transbordeur] unexpected JSON type: {type(data).__name__}",
              file=sys.stderr)
        return []

    events: List[Event] = []
    today = Date.today()
    for post in data:
        if not isinstance(post, dict):
            continue
        d = _extract_date(post)
        if not d or d < today:
            continue

        title_field = post.get("title")
        if isinstance(title_field, dict):
            title = _strip_html(title_field.get("rendered", "")).strip()
        else:
            title = _strip_html(str(title_field or "")).strip()
        if not title:
            continue

        link = post.get("link") or SITE + "/agenda/"
        time_str = _extract_time(post)
        image = _extract_image(post)

        events.append(Event(
            venue=VENUE,
            venue_slug=SLUG,
            title=title,
            subtitle=None,
            category="concert",
            date_start=iso(d),
            date_end=None,
            time=time_str,
            url=link,
            image=image,
        ))

    if not events:
        _diagnose_first_post()

    seen, unique = set(), []
    for e in events:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)
    unique.sort(key=lambda e: (e.date_start, e.time or "00:00"))
    return unique


if __name__ == "__main__":
    for e in fetch():
        print(e.date_start, e.time or "  -  ", "·", e.title, "·", e.url)
