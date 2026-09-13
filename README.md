# Price Monitor

Application de suivi des prix internationaux du gasoil, du Brent et du bitume, construite à partir du rapport de proposition de sujet de Khalid Karroum.

## Ce qui est livré

- collecte manuelle ou planifiée cinq fois par jour à **08:00, 11:00, 14:00, 17:00 et 20:00** ;
- historique réel de cinq ans pour le Brent et le gasoil, issu des séries EIA publiées par FRED ;
- connecteurs FRED (séries `DCOILBRENTEU` et `DDFUELNYH`) et Alpha Vantage (`BRENT`) via variables d'environnement ;
- stockage SQLite ou MySQL 8 sélectionnable dans `.env`, avec migrations suivies dans `sql/mysql_migrations/` ;
- contrôle de qualité, validation stricte des dates et unités, déduplication idempotente, date de publication distincte de la date de collecte, variation absolue et en pourcentage ;
- saisie validée des devis, commandes ou factures de bitume ;
- tableau de bord responsive, graphiques de tendance, moyennes/minimums/maximums, journal des collectes ;
- exports CSV et Excel `.xlsx` ;
- notebook d'exploration couvrant tendances, volatilité, corrélation, saisonnalité, anomalies, qualité et prévision naïve ;
- mode démonstration disponible en option avec `PRICE_MONITOR_DEMO=true`.

## Démarrage rapide

Depuis le dossier parent :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r price_monitor\requirements.txt
python -m price_monitor.app
```

Puis ouvrir `http://127.0.0.1:8080`.

Pour utiliser MySQL, copiez `.env.example` vers `.env`, configurez `PRICE_MONITOR_DB_BACKEND=mysql` ainsi que `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER` et `MYSQL_PASSWORD`. L'application crée la base configurée si le compte possède ce droit, applique `sql/mysql_schema.sql`, puis exécute les migrations non encore enregistrées.

## Tests

Installer les dépendances puis lancer la suite automatisée :

```powershell
..\.venv\Scripts\python.exe -m pytest
```

Les tests couvrent la validation et la persistance SQLite, les calculs du tableau de bord, les exports CSV/Excel, l'import du snapshot réel EIA/FRED, les collectes complètes, partielles ou en échec, ainsi que le schéma et le moteur de migrations MySQL. Pour exécuter aussi le test d'intégration MySQL, définissez `RUN_MYSQL_TESTS=1` avec des paramètres `.env` valides.

Le projet démarre avec un snapshot réel de cinq ans dans `data/processed/market_prices.csv`, sans clé API. Pour actualiser les fichiers source et reconstruire le snapshot :

```powershell
python scripts/prepare_market_data.py --years 5 --refresh
```

Pour les collectes quotidiennes en direct, renseigner `FRED_API_KEY` puis conserver `PRICE_MONITOR_DEMO=false`. Le bitume est volontairement saisi depuis les sources internes de l'entreprise, conformément au rapport.

## Analyse exploratoire

Le notebook exécuté est disponible dans `notebooks/market_price_eda.ipynb`. Il peut être relancé après installation des dépendances d'analyse :

```powershell
python -m jupyter notebook notebooks/market_price_eda.ipynb
```

Les séries Brent et gasoil sont conservées dans leurs unités publiées respectives : USD/baril et USD/gallon. Les comparaisons de volatilité et de corrélation utilisent les variations journalières afin d'éviter de confondre échelle de prix et co-mouvement.

## API locale

Les routes d'écriture et l'historique détaillé sont protégés par une clé API. Définissez `PRICE_MONITOR_API_KEY` dans `.env` avec une valeur longue et aléatoire, puis envoyez-la avec `X-API-Key` ou `Authorization: Bearer <clé>`. La clé n'est jamais acceptée dans l'URL.

```powershell
$bytes = [byte[]]::new(32)
[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$env:PRICE_MONITOR_API_KEY = [Convert]::ToBase64String($bytes)
```

Sans clé configurée, `/api/collect` et `/api/observations` répondent avec une erreur de configuration. En production (`PRICE_MONITOR_ENV=production`), le démarrage est refusé tant que la clé n'est pas définie. Le tableau de bord demande la clé au premier appel protégé et la conserve uniquement dans la session du navigateur.

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/api/dashboard?days=30` | indicateurs, séries et derniers relevés |
| GET | `/api/observations?product=bitume` | historique filtré (clé API) |
| POST | `/api/collect` | déclenche une collecte immédiate (clé API) |
| POST | `/api/observations` | ajoute une observation validée (clé API) |
| GET | `/export.csv` / `/export.xlsx` | exports |

En production, une limitation en mémoire s'applique par adresse cliente : 60 requêtes par fenêtre de 60 secondes par défaut. Ajustez `PRICE_MONITOR_RATE_LIMIT_REQUESTS` et `PRICE_MONITOR_RATE_LIMIT_WINDOW_SECONDS` si nécessaire.

Exemple de saisie bitume :

```json
{"product":"bitume","price":528.5,"unit":"USD/tonne","source":"Devis Fournisseur ABC","source_date":"2026-09-08","notes":"FOB Méditerranée"}
```

`source_date` doit respecter le format `YYYY-MM-DD` et `collected_at`, lorsqu'il est fourni, doit être un horodatage ISO 8601 avec fuseau. L'unité doit correspondre à celle du produit. Une nouvelle tentative avec le même produit, la même source, la même date source et le même prix réutilise l'observation existante.

## Passage en production

Le fichier `sql/mysql_schema.sql` contient la structure MySQL correspondant aux tables du rapport : `price_observations`, `data_sources`, `collection_logs` et `schema_migrations`. Le stockage SQLite intégré reste le défaut local ; MySQL peut être activé sans modifier les routes de l'application.
