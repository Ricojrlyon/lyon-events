# À l'affiche · Lyon

Agenda culturel personnel : tous les concerts, pièces, expos et soirées
des lieux que tu suis, sur une seule page, mise à jour automatiquement.

![preview](docs/preview.png)

## Comment ça marche

Trois couches simples :

1. **Scrapers** (`scrapers/`) — un module Python par lieu. Chacun va
   chercher la programmation sur le site officiel et renvoie une liste
   d'`Event` standardisés.
2. **Aggregator** (`aggregate.py`) — exécute tous les scrapers, dédoublonne,
   trie par date, écrit `events.json`.
3. **Page web** (`index.html`) — page statique qui charge `events.json`
   et l'affiche avec filtres (période, lieu, type).

L'automatisation est gérée par **GitHub Actions** : le workflow
`.github/workflows/update.yml` relance `aggregate.py` chaque jour à 08h
(heure de Paris) et commit `events.json` mis à jour. La page web étant
statique, elle se met à jour automatiquement à la prochaine visite.

## État des scrapers

| Lieu                          | Statut       |
|------------------------------|--------------|
| Le Sucre                     | ✓ implémenté |
| Les Subsistances             | ✓ implémenté |
| Marché Gare                  | ✓ implémenté |
| Radiant-Bellevue             | · stub       |
| La Rayonne                   | · stub       |
| Le Transbordeur              | · stub       |
| Le Petit Salon               | · stub       |
| Le Sonic                     | · stub       |
| HEAT                         | · stub       |
| Station Mue                  | · stub       |
| La Commune                   | · stub       |
| Théâtre des Célestins        | · stub       |
| TNP                          | · stub       |
| Théâtre de la Croix-Rousse   | · stub       |
| Comédie Odéon                | · stub       |
| Musée des Confluences        | · stub       |
| Musée des Beaux-Arts         | · stub       |
| Musée d'Art Contemporain     | · stub       |
| MAC Bar                      | · stub       |

Les stubs renvoient une liste vide. Il faut les remplir un à un
(voir « Ajouter un lieu » plus bas) — les scrapers déjà implémentés
te servent de référence.

`events.json` est livré avec un seed de **58 vrais événements** (Le
Sucre, Les Subs, Marché Gare, Radiant) extraits manuellement pendant le
setup, pour que la page ait quelque chose à afficher dès le déploiement.

## Installation locale

```bash
git clone https://github.com/<ton-user>/lyon-events
cd lyon-events
pip install -r requirements.txt

# Régénérer le seed (optionnel)
python seed.py

# Lancer tous les scrapers et écrire events.json
python aggregate.py

# Servir la page web localement
python -m http.server 8000
# Puis ouvrir http://localhost:8000
```

## Déploiement gratuit

### Option 1 — GitHub Pages (zéro config)

1. Pousse le repo sur GitHub (en public).
2. Settings → Pages → Source : `main` branch, `/` (root).
3. La page est en ligne à `https://<ton-user>.github.io/lyon-events/`.
4. Le workflow Actions tourne automatiquement chaque jour.

### Option 2 — Cloudflare Pages

1. Pousse le repo sur GitHub.
2. Sur Cloudflare Pages → Create project → Connect GitHub.
3. Framework preset : `None`. Build command : (vide). Output : `/`.
4. La page est en ligne à `https://<ton-projet>.pages.dev`.

Cloudflare offre la bande passante illimitée gratuite — utile si la page
prend du trafic.

## Ajouter un lieu

1. **Inspecter le site** — ouvre la page agenda dans un navigateur, vue
   source (`Ctrl+U`). Identifie le bloc HTML répété (souvent une `<a>`,
   `<article>` ou `<div class="event-card">`).
2. **Repère les champs** : titre, date, heure, URL, image, catégorie.
3. **Implémenter le scraper** — copie `scrapers/le_sucre.py` ou
   `scrapers/les_subs.py` comme point de départ. Adapte les sélecteurs
   CSS (les méthodes `soup.select(...)`).
4. **Tester localement** : `python -m scrapers.<nom_du_module>` doit
   afficher des événements lisibles.
5. **Enregistrer** : ajoute la fonction dans la liste `SCRAPERS` de
   `aggregate.py`.

## Quand un site change sa structure

C'est le gros risque du scraping : les sites changent leur HTML. Trois
défenses dans le code :

- Le wrapper `try/except` dans `aggregate.py` garantit qu'un lieu cassé
  n'interrompt pas les autres.
- Le rapport CLI à la fin de `aggregate.py` te dit quel lieu a renvoyé
  zéro événement (signal de panne).
- Tu peux lancer `python -m scrapers.le_sucre` séparément pour debugger
  un lieu en isolation.

Si un lieu casse souvent, regarde si un flux iCal/RSS ou OpenAgenda existe
— c'est plus stable que le scraping.

## Structure du projet

```
lyon-events/
├── scrapers/
│   ├── __init__.py
│   ├── base.py             # Event dataclass + helpers (parse_french_date, …)
│   ├── le_sucre.py         # ✓ implémenté
│   ├── les_subs.py         # ✓ implémenté
│   ├── marche_gare.py      # ✓ implémenté
│   └── _stubs.py           # 16 stubs à compléter
├── aggregate.py            # Orchestre tous les scrapers, écrit events.json
├── seed.py                 # Génère un events.json initial avec données réelles
├── events.json             # Sortie consommée par index.html
├── index.html              # Frontend statique
├── requirements.txt
└── .github/workflows/update.yml   # cron quotidien
```

## Licence

MIT — fais-en ce que tu veux.
