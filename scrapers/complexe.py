"""Scraper for Le Complexe café-théâtre (Lyon 1er, 7 rue des Capucins).

ATTENTION AU USER-AGENT. Le pare-feu du site renvoie 403 à toute chaîne
contenant « Mozilla/5.0 (compatible » — une règle classique contre les
robots qui se déguisent en navigateur. L'UA franc utilisé ici passe en
200, et `curl/8.0` aussi : le site ne refuse pas les robots, il refuse le
déguisement. Son robots.txt autorise d'ailleurs tout. Ne pas remplacer
cet UA par celui des autres scrapers, qui casserait la salle.

Le site est un WordPress. The Events Calendar y est installé mais
INUTILISÉ — tous ses endpoints REST rendent 0 (événements comme lieux) —
et il n'existe pas d'API publique côté billetterie (Slidebooker). On lit
donc le HTML, qui a l'avantage de porter des classes sémantiques stables
préfixées « tly_ », et non des hachages regénérés à chaque déploiement.

Deux étapes :
  1. /actuellement/ porte DEUX choses. Un accordéon des sept prochains
     jours, et — hors accordéon — le catalogue complet des spectacles.
     C'est le catalogue qu'on lit : chaque entrée donne l'URL, le titre,
     l'affiche et la plage de dates AVEC les années.
  2. chaque page spectacle porte la table de ses représentations :
     .tly_day (date française SANS année), .tly_hour, et la salle.

L'année est déduite de la plage du catalogue, puis roulée dès que le mois
recule d'une séance à la suivante. Le nom du JOUR DE LA SEMAINE sert de
contrôle : si la date calculée ne tombe pas ce jour-là, la déduction est
fausse et la séance est écartée plutôt que publiée de travers. Mesuré à
l'écriture : 214 séances sur 214 validées.
"""
from __future__ import annotations

import re
import sys
import time
import unicodedata
from datetime import date as Date, timedelta
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from .base import Event

# Même graphie que le Petit Bulletin, qui remonte aussi cette salle :
# c'est ce qui permet à la dédup de regrouper les deux sources.
VENUE = "Le Complexe café-théâtre"
SLUG = "le-complexe"
BASE = "https://www.lecomplexelyon.com"
LISTING = BASE + "/actuellement/"

# Catégorie fixe : le site n'expose pas de genre exploitable, et
# « café-théâtre » tombe dans le bucket humour du frontend, ce qui est
# juste pour cette salle.
CATEGORY = "café-théâtre"

HORIZON_DAYS = 180
MIN_INTERVAL = 0.4

# PAS de « Mozilla/5.0 (compatible » ici : voir le docstring, le pare-feu
# du site le renvoie en 403.
HEADERS = {
    "User-Agent": "nocturne-lyon-events/1.0 "
                  "(+https://github.com/Ricojrlyon/nocturne-lyon)",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
        "juin": 6, "juillet": 7, "aout": 8, "septembre": 9,
        "octobre": 10, "novembre": 11, "decembre": 12}
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi",
         "dimanche")

_SEANCE_RE = re.compile(
    r"(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
    r"\s+(\d{1,2})\s+([a-z]+)")
_PLAGE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_HEURE_RE = re.compile(r"\b(\d{1,2})[:h](\d{2})\b")
_URL_CSS_RE = re.compile(r"url\((.*?)\)")


def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def _image(item) -> Optional[str]:
    """L'affiche est une image de fond CSS, pas une balise <img>."""
    div = item.select_one(".tly_featuredImg")
    if div is None:
        return None
    m = _URL_CSS_RE.search(div.get("style") or "")
    if not m:
        return None
    url = m.group(1).strip("'\" ")
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE + url
    return url if url.startswith("http") else None


def _catalogue(session: requests.Session) -> List[dict]:
    """Spectacles du catalogue, avec leur plage de dates annotée d'années.

    On écarte les entrées de l'accordéon : ce sont les séances des sept
    prochains jours, et leur date ne porte pas d'année.
    """
    r = session.get(LISTING, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out = []
    for item in soup.select(".tly_productItem"):
        if item.find_parent(class_="tly_accordionContent"):
            continue
        a = item.select_one("a.tly_moreLink")
        titre = item.select_one(".tly_productTitle")
        plage = item.select_one(".tly_productDate")
        if not (a and a.get("href") and titre and plage):
            continue
        m = _PLAGE_RE.search(plage.get_text(" ", strip=True))
        if not m:
            continue                     # sans année, l'inférence est aveugle
        out.append({
            "url": a["href"],
            "titre": titre.get_text(strip=True),
            "annee": int(m.group(3)),
            "image": _image(item),
        })

    # Un même spectacle figure PLUSIEURS fois au catalogue, une entrée par
    # saison — « IMPRO'MINOTS » y apparaît trois fois — mais toutes
    # pointent vers la MÊME page, dont la table contient déjà l'intégralité
    # des séances. Sans cette déduplication on récupérait la page autant de
    # fois qu'elle a d'entrées, et la passe partie de l'année la plus
    # tardive échouait en bloc : le contrôle du jour de la semaine
    # rejetait ses 20 à 23 séances, déjà captées par la bonne passe.
    # On garde donc l'année la plus ANCIENNE, celle où commence la table,
    # le roulement d'année faisant le reste.
    par_url: dict = {}
    for c in out:
        vu = par_url.get(c["url"])
        if vu is None or c["annee"] < vu["annee"]:
            par_url[c["url"]] = c
    return list(par_url.values())


def _seances(session: requests.Session, url: str,
             annee: int, tag: str) -> List[tuple]:
    """(date ISO, heure) de chaque représentation d'un spectacle.

    La sélection est cadrée sur la table des représentations : la classe
    .tly_productDate sert aussi aux plages du catalogue et pourrait
    apparaître dans d'éventuels blocs de spectacles liés.
    """
    r = session.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    blocs = soup.select(".tly_productDatesTable .tly_productDate")
    out, precedent, ecartees = [], None, 0
    for bloc in blocs:
        jour = bloc.select_one(".tly_day")
        if jour is None:
            continue
        m = _SEANCE_RE.search(_norm(jour.get_text(" ", strip=True)))
        if not m:
            continue
        dow, jj, mois = m.group(1), int(m.group(2)), MOIS.get(m.group(3))
        if not mois:
            continue
        if precedent and (mois, jj) < precedent:
            annee += 1                   # le mois recule : année suivante
        precedent = (mois, jj)
        try:
            d = Date(annee, mois, jj)
        except ValueError:
            continue
        # Contrôle : la date calculée doit tomber le jour annoncé. Sinon
        # l'année déduite est fausse et on préfère perdre la séance que
        # publier une date erronée.
        if JOURS[d.weekday()] != dow:
            ecartees += 1
            continue
        h = bloc.select_one(".tly_hour")
        mh = _HEURE_RE.search(h.get_text(strip=True)) if h else None
        heure = f"{int(mh.group(1)):02d}:{mh.group(2)}" if mh else None
        out.append((d.isoformat(), heure))

    if ecartees:
        print(f"[{tag}] {ecartees} séance(s) écartée(s), jour de la semaine "
              f"incohérent — {url}", file=sys.stderr)
    return out


def fetch() -> List[Event]:
    today = Date.today()
    horizon = (today + timedelta(days=HORIZON_DAYS)).isoformat()
    today_iso = today.isoformat()

    session = requests.Session()
    shows = _catalogue(session)
    if not shows:
        # Page lisible mais catalogue vide : la structure a changé. On le
        # signale, plutôt que de rendre une liste vide silencieuse
        # qu'aggregate.py ne distinguerait pas d'une panne.
        print("[Le Complexe] catalogue vide sur /actuellement/ — structure "
              "du site modifiée ?", file=sys.stderr)
        return []

    events: List[Event] = []
    illisibles = 0
    for i, show in enumerate(shows):
        if i:
            time.sleep(MIN_INTERVAL)
        try:
            seances = _seances(session, show["url"], show["annee"],
                               "Le Complexe")
        except requests.RequestException as exc:
            # Une page qui tombe ne doit pas emporter les autres.
            print(f"[Le Complexe] {show['url']}: {exc}", file=sys.stderr)
            illisibles += 1
            continue

        for jour, heure in seances:
            if jour < today_iso or jour > horizon:
                continue
            events.append(Event(
                venue=VENUE,
                venue_slug=SLUG,
                title=show["titre"],
                subtitle=None,
                category=CATEGORY,
                date_start=jour,
                date_end=None,
                time=heure,
                url=show["url"],
                image=show["image"],
            ))

    if illisibles:
        print(f"[Le Complexe] {illisibles} page(s) spectacle illisible(s)",
              file=sys.stderr)
    return events
