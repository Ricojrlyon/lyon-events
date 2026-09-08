# *nocturne · lyon

Agrégateur d'événements culturels lyonnais — concerts, clubs, danse, expos,
lieux hybrides — scrappés chaque nuit sur les sites d'une quinzaine de salles
et affichés sur une page statique hébergée par GitHub Pages :
<https://ricojrlyon.github.io/nocturne-lyon/>

## Fonctionnement

```
18 scrapers venue ──┐
                    ├─→ dédup 3 passes ─→ events.json ─→ index.html (GitHub Pages)
2 agrégateurs ──────┘         │
(Petit Bulletin,              ├─→ venue_arrondissements.json (géocodage Nominatim)
 Ville Morte)                 └─→ detail_times.json (cache des heures)
```

Le pipeline tourne quotidiennement à 06h00 UTC via GitHub Actions
([.github/workflows/update.yml](.github/workflows/update.yml)) et committe
les trois fichiers de données.

- **`scrapers/*.py`** — un module par salle (`requests` + BeautifulSoup).
  Chaque module expose `fetch() -> List[Event]`. Les échecs d'une salle ne
  font pas tomber le run : la salle est signalée en erreur, les autres passent.
- **`scrapers/mapado.py`** — lecture commune des billetteries Mapado,
  utilisée par `improvidence.py` et `espace_gerson.py`. Ces boutiques sont
  des Next.js dont chaque page embarque son état d'hydratation en JSON :
  on lit ce JSON, pas le HTML, les classes CSS de Mapado étant des
  hachages regénérés à chaque déploiement. Point d'attention : une
  boutique n'est PAS une salle — Improvidence programme aussi à Bordeaux,
  l'Espace Gerson à la Salle Victor Hugo et à la Bourse du Travail (que
  nocturne scrappe déjà). Chaque scraper fournit donc son prédicat de
  lieu, appliqué sur le Venue que Mapado expose en clair.
- **`scrapers/complexe.py`** — Le Complexe café-théâtre, seul scraper à
  exiger un User-Agent PARTICULIER : le pare-feu du site renvoie 403 à
  toute chaîne contenant « Mozilla/5.0 (compatible », donc l'UA y est
  franc, sans déguisement en navigateur. Ne pas l'aligner sur les autres.
  Autre particularité : les dates des séances n'y portent pas d'année,
  déduite de la plage du catalogue puis roulée quand le mois recule — et
  validée par le nom du jour de la semaine, qui écarte toute déduction
  fausse plutôt que de publier une date erronée.
- **`scrapers/aggregators/`** — sources multi-lieux : Petit Bulletin et
  Ville Morte (API Gancio). Priorité inférieure aux scrapers venue : en cas
  de doublon, le scraper de la salle gagne l'identité et hérite des champs
  manquants (heure, catégorie…).
- **`scrapers/dedup.py`** — canonicalisation des noms de lieux
  (`VENUE_CANONICAL`) + déduplication en 3 passes : (lieu, jour) avec
  fuzzy-match des titres ≥ 0,7 (les plages multi-jours sont indexées sur
  chaque jour couvert), cross-venue ≥ 0,85 (titres génériques exclus),
  puis pairing scraper/agrégateur à effectifs égaux avec garde temporel 4 h.
- **`scrapers/categorie.py`** — comble la catégorie quand la source n'en
  donne aucune, après la déduplication et sans jamais écraser une
  catégorie de source. Le TITRE d'abord — ces salles y annoncent le genre
  en clair (« Projection Ciné-Club », « [Punk Rock] », « comedy club ») —
  puis un défaut de LIEU, réservé aux salles réellement mono-genre : à
  Marché Gare les événements sans catégorie comprennent une projection et
  deux formations, au Bieristan des quiz. Ce qui ne se déduit pas reste
  vide, « LP » ou « Face B » ne disant rien. Attention : les étiquettes
  produites doivent être reconnues par `TYPE_BUCKETS` (index.html),
  sinon le comblement ne sert à rien — deux pièges vérifiés, « ciné » ne
  correspond pas à sa propre regex et « électro » accentué non plus.
- **`scrapers/geo.py`** — géocodage Nominatim des lieux inconnus →
  arrondissement, mis en cache dans `venue_arrondissements.json`. Les lieux
  déjà hardcodés dans `VENUE_ARRONDISSEMENT` (index.html, source de vérité,
  parsée au run par aggregate.py) ne sont jamais interrogés.
- **`scrapers/detail_cache.py`** — cache persistant `url → heure` pour les
  6 scrapers qui fetchent des pages détail (TTL 30 j si heure trouvée,
  7 j sinon, purge à 60 j). Divise le temps de run par ~8 dès le 2ᵉ passage.
- **`aggregate.py`** — orchestre le tout, filtre le passé (les événements
  en cours sont conservés jusqu'à leur `date_end`), écrit `events.json`.
  Garde-fou : si toutes les sources échouent ou rendent 0 événement, le
  `events.json` précédent n'est pas écrasé.
- **`index.html`** — frontend vanilla JS autonome : filtres par date/lieu/
  arrondissement/type, recherche insensible aux accents (titre, lieu,
  line-up), expansion des événements multi-jours, groupes de lieux.
- **`logos/`** — marques de salle affichées sur les cartes groupées, une
  par lieu, déclarées dans `VENUE_LOGOS` (index.html). Voir « Logos de
  salle » plus bas.

## Lancer localement

```bash
pip install -r requirements.txt   # requests + beautifulsoup4
pip install tzdata                # Windows uniquement (zoneinfo)

python aggregate.py               # run complet → events.json + caches
python -m scrapers.le_sucre       # tester un scraper isolément
```

Premier run : quelques minutes (remplissage du cache des heures).
Runs suivants : ~30 secondes.

## Ajouter une salle

1. Créer `scrapers/ma_salle.py` exposant `fetch() -> List[Event]`
   (s'inspirer de `heat.py` pour un listing simple, `transbordeur.py` pour
   une API WP REST paginée). Utiliser `detail_cache.get_time()` si les
   heures nécessitent des pages détail.
2. L'enregistrer dans `SCRAPERS` (aggregate.py).
3. Ajouter le lieu dans `VENUE_ARRONDISSEMENT` et `VENUE_GROUPS`
   (index.html) — la liste des lieux connus du géocodage en découle
   automatiquement.
4. Si les agrégateurs orthographient le lieu autrement, ajouter les
   variantes dans `VENUE_CANONICAL` (scrapers/dedup.py). C'est ce qui
   permet à la dédup de regrouper les deux sources : sans l'entrée, elles
   tombent dans deux groupes distincts et ne se croisent jamais.
5. Facultatif : si la salle joue plusieurs fois par soir, lui donner un
   logo (voir « Logos de salle »). Sans entrée, ses cartes groupées
   gardent le motif — c'est le cas de la majorité des lieux.

## Logos de salle

Une carte groupée réunit plusieurs spectacles d'un même lieu le même
jour. N'ayant pas d'affiche à montrer, elle tirait un motif de secours.
Les salles qui jouent plusieurs fois par soir y portent désormais leur
marque : cinq lieux, 245 des 287 cartes groupées.

Le logo est traité comme une affiche — `brightness(0.50) contrast(1.06)`,
trame sérigraphie et voile du haut par-dessus — à deux détails près.

- **Un cartouche blanc sur toute la carte.** Les logos ajourés posaient
  sinon leurs traits sombres sur un fond sombre ; le cartouche leur rend
  le support pour lequel ils ont été dessinés. C'est lui qui porte le
  filtre, pas la marque : un filtre s'appliquant à tout son sous-arbre,
  son blanc et celui qu'un fichier contient déjà subissent le même
  traitement, sans quoi un rectangle se dessinerait autour de la marque.
- **`brightness` à 0,50** et non 0,60 comme les affiches : un aplat n'a
  pas le bruit d'une photographie et ressort plus fort à luminosité
  égale.

Deux règles à respecter en ajoutant un logo :

1. **Recadrer le fichier sur la boîte de son dessin.** Les fichiers
   d'origine portent des marges vides très inégales — 67 % pour
   Improvidence, 55 % pour Le Complexe, 0 % pour Gerson — et sans
   recadrage une même valeur de hauteur donne des dessins de tailles
   très différentes.
2. **Choisir `k` d'après le ratio**, `k` étant la hauteur en pour cent de
   la carte. 150 % convient aux marques compactes (ratios 0,98 à 1,33).
   Les Subsistances sont à 102 % : leur lettrage est un ruban de ratio
   2,12 qui sortirait largement de la carte à 150 %.

Le fichier est committé dans le dépôt plutôt que lié chez la salle : un
lien direct casse au premier changement de thème et ferait dépendre nos
cartes d'un serveur tiers. SVG quand la salle en publie un — l'Institut
Lumière, 25 ko et net à toute échelle —, PNG recadré sinon.

Le motif reste sous le logo, éteint par une classe que l'`onerror`
retire : si le fichier manque, la carte retombe d'elle-même sur le
motif.

## Politique éditoriale

- **Ville Morte : aucun filtre**, tout son agenda remonte. C'est la
  déduplication qui écarte les doublons quand un événement est aussi
  publié par la salle elle-même.
- **Petit Bulletin : aucun filtre**, comme Ville Morte. Deux filtres y
  existaient — musées et galeries d'un côté, une liste de catégories de
  l'autre — parce que les accrochages, courant sur des mois, saturaient
  le feed. Ils sont levés : chaque journée se répartit désormais en
  quatre familles qu'un bouton éteint, et c'est au lecteur de dire qu'il
  ne veut pas d'expositions ce soir. Sans filtre le scraper rapporte 572
  événements au lieu de 400, dont 119 en famille « expos » — laquelle
  n'en comptait que 27 auparavant, et n'apparaissait que sur un jour
  chargé sur quatre.
- **Familles d'affichage** (`FAMILLES`, index.html) : musique, scène,
  expos, autres. Quatre et non dix-huit — les buckets restent la maille
  fine, mais autant de sections dans une journée seraient illisibles.
  Chaque barre de journée porte un bouton par famille : l'état est
  GLOBAL, le compte est celui du JOUR. Au-delà de dix cartes la journée
  se découpe en sections titrées par famille (`SEUIL_SECTIONS`) ; en
  deçà elle reste une grille continue, la journée médiane ne faisant que
  cinq cartes. Tout bucket non rangé dans une
  famille tombe dans « autres », et une alerte console le signale : le
  repli évite de perdre un événement, il ne doit pas masquer un oubli.
- **Événements longs** (expos, festivals au long cours) : conservés sous
  forme de plage `date_start`..`date_end` au lieu d'être jetés. Le frontend
  les affiche avec un badge « en cours » au-delà de 30 jours.
- **Horizon** : les événements à plus de 180 jours sont écartés avant la
  phase de fetch des pages détail (scrapers de salle uniquement).
- **Plages d'agrégateur sur un lieu scrappé** : écartées. Un agrégateur
  qui voit un spectacle joué plusieurs soirs le publie souvent comme une
  seule plage « du 18 au 28 août ». Le frontend déployant une plage sur
  chacun de ses jours, elle doublerait les séances que le scraper de la
  salle rapporte précisément, et en inventerait les soirs sans
  représentation. La dédup ne peut pas rattraper ce cas : il suffit que la
  plage gagne un seul jour pour être émise, puis repeindre toute sa durée.
- **La Rayonne** : ses formations et ateliers professionnels sont écartés
  — c'est une programmation parallèle, pas un choix éditorial.

## Données générées (committées par le bot)

| Fichier | Contenu |
|---|---|
| `events.json` | les événements agrégés, consommés par index.html |
| `venue_arrondissements.json` | cache géocodage lieu → arrondissement |
| `detail_times.json` | cache url → heure des pages détail |
