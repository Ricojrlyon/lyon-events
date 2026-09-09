# *nocturne · lyon

Agrégateur d'événements culturels lyonnais — concerts, clubs, danse, expos,
lieux hybrides — scrappés chaque nuit sur les sites d'une quinzaine de salles
et affichés sur une page statique hébergée par GitHub Pages :
<https://ricojrlyon.github.io/nocturne-lyon/>

## Fonctionnement

```
25 scrapers venue ──┐
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
- **`scrapers/agendarts.py`** — agend'Arts, qui n'a pas de site à soi :
  la salle publie sur un blog WordPress.com, un billet par spectacle,
  servi sans clé par l'API publique. La date de publication n'est pas
  celle du spectacle — un billet de juin annonce un concert de décembre
  — et la vraie date s'écrit en toutes lettres dans la première phrase.
  Elle est lue par deux sources indépendantes : la prose, et les liens
  de billetterie HelloAsso dont le slug porte la date complète. Sur 325
  couples jour+mois, elles concordent 324 fois ; le désaccord restant
  est un cas que la prose seule ne peut pas voir. L'année, elle, n'est
  presque jamais écrite : quatre sources y répondent dans l'ordre, et à
  défaut la date est abandonnée plutôt que projetée sur l'année en
  cours. Deux règles évitent des dates fausses — seule la suite de
  quantièmes COLLÉE au nom du mois compte, sans quoi « Les 3 becs »
  produirait un 3 septembre ; et une suite introduite par une
  annulation est écartée, publier une séance annulée étant plus grave
  que d'en manquer une.
- **`scrapers/auditorium.py`** — l'Auditorium-Orchestre national de
  Lyon. Drupal, lu en deux temps : une page d'agenda par mois donne les
  cartes, la fiche donne les dates. La carte ne suffit pas — elle écrit
  « jeu. 1 oct », sans millésime ni horaire — là où la fiche écrit « Jeu.
  1 oct 2026 à 20h Ven. 2 oct 2026 à 18h ». L'heure change d'une séance à
  l'autre du même concert, 20h le jeudi et 18h le vendredi : publier la
  première pour les deux serait faux un soir sur deux. Trois pièges :
  le HTML sert les cartes en double (199 balises pour 148 spectacles) ;
  l'orchestre joue hors les murs jusqu'à Bruxelles, et la Salle Molière
  est déjà dans nocturne — d'où une liste BLANCHE de salles maison, les
  lieux extérieurs étant un ensemble ouvert quand les salles du bâtiment
  sont une liste fermée ; enfin les séances scolaires, facturées « 8 €
  par élève » et réservées aux classes, sont écartées.
- **`scrapers/comedie_odeon.py`** — la Comédie Odéon. Le type
  « spectacle » n'est pas exposé à l'API REST, mais /spectacle/ porte
  TOUT en une requête : les cartes et un calendrier mensuel dont chaque
  cellule nomme les spectacles du jour. C'est le calendrier qui fait foi
  pour les dates — la fiche ne décrit qu'un rythme en français (« Du
  mercredi au samedi à 20h », « Relâches : 15/10 + 16/10 ») qu'il serait
  fragile de régénérer. Le gain est net : le Petit Bulletin publiait
  « La Machine de Turing » comme une plage de 53 jours, relâches
  comprises ; le scraper en rend les 29 vraies dates, dont celle à 19h
  au lieu de 20h.
- **`scrapers/croix_rousse.py`** — le Théâtre de la Croix-Rousse.
  WordPress dont l'API REST est OUVERTE, à la différence du TNP : elle
  donne la liste de la saison avec titres, affiches et genres. Les dates
  n'y sont pas — l'ACF est vide partout — et viennent du HTML des
  fiches. Deux pièges : `title.rendered` est du HTML, pas du texte, et
  treize titres portaient des entités qui se seraient affichées telles
  quelles ; et la taxonomie nommée `genre` contient en réalité les noms
  d'ARTISTES, ce sont les termes `event_type` qui portent les genres.
  Un lien de billetterie par séance permet de distinguer « 14h30 19h30 »
  — deux séances — de « 17h > 17h50 », une seule avec son heure de fin.
- **`scrapers/maison_de_la_danse.py`** — la Maison de la Danse, seul
  site du dépôt à demander un `Crawl-delay` (10 s). Il est respecté, et
  c'est ce qui rend `detail_cache` indispensable : le délai est posé DANS
  le fetcher, donc il ne frappe que les fiches réellement téléchargées —
  216 s au premier passage, 11 s aux suivants. Trois pièges y ont coûté
  des spectacles entiers, tous silencieux : les séries à cheval sur deux
  mois portent un titre « NOVEMBRE - DÉCEMBRE » et non un mois unique ;
  un quantième qui se répète un mois plus tard (mercredi 28 octobre puis
  samedi 28 novembre) ne recule pas, seul le nom du jour distingue ce cas
  d'une double séance ; et une fiche sans bloc « Lieu » n'est pas un
  accueil extérieur mais un lieu non précisé — les accueils, eux, le
  renseignent toujours.
- **`scrapers/tnp.py`** — le TNP, seul scraper à s'être vu REFUSER une
  API qui existe : le site est un WordPress mais son robots.txt interdit
  /wp-json/. On lit donc /agenda/, qui a l'avantage de rendre la saison
  entière en une requête, avec des attributs `datetime` lisibles à la
  machine. Les affiches viennent de l'`og:image` des fiches spectacle —
  dix-sept fiches pour cent vingt-trois représentations, le même
  spectacle se jouant dix à dix-sept fois.
- **`scrapers/celestins.py`** — Les Célestins, seule salle du dépôt à
  offrir une API JSON DOCUMENTÉE : le site tourne sous Roadiz, son
  robots.txt n'interdit que /api/docs, et /api/docs.json rend la
  spécification OpenAPI complète. Deux appels sont nécessaires,
  /api/event_dates pour les représentations et /api/events pour les
  affiches, que la première sérialisation n'embarque pas — or c'est
  précisément l'image qui manquait, le Petit Bulletin remontant cette
  salle sans une seule. Point d'attention : les Célestins programment
  HORS LES MURS, 17 représentations sur 228 au TNP, au TNG et à la
  Croix-Rousse. Sans filtre de lieu elles seraient publiées sous
  « Célestins », et la dédup ne pourrait rien y faire puisqu'elle
  regroupe justement par lieu.
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
  Les deux premières passes portent un garde supplémentaire
  (`_seances_distinctes`) : au sein d'une MÊME source, deux horaires
  connus et différents sont deux représentations, jamais un doublon. Sans
  lui, une matinée et sa soirée fusionnaient — 44 couples de séances
  réelles perdus sur sept salles avant correction.
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
marque : six lieux, 324 des 384 cartes groupées.

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
   la carte. 150 % convient aux marques compactes (ratios 0,98 à 1,37).
   Les Subsistances sont à 102 % : leur lettrage est un ruban de ratio
   2,12 qui sortirait largement de la carte à 150 %.

Le fichier est committé dans le dépôt plutôt que lié chez la salle : un
lien direct casse au premier changement de thème et ferait dépendre nos
cartes d'un serveur tiers. SVG quand la salle en publie un — l'Institut
Lumière et les Célestins, 1 à 25 ko et nets à toute échelle —, PNG
recadré sinon.

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
