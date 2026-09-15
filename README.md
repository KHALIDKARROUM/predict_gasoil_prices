# Price Monitor

Application de suivi des prix internationaux du gasoil, du Brent et du bitume
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
| GET | `/api/history?page=1&page_size=50&product=bitume&supplier=ABC&source=devis&date_from=2026-01-01&date_to=2026-09-15&min_price=400&max_price=700` | historique paginé et filtré (clé API) |
| GET | `/api/history/compare?period_a_from=2026-01-01&period_a_to=2026-03-31&period_b_from=2026-04-01&period_b_to=2026-06-30` | comparaison de deux périodes (clé API) |
| POST | `/api/collect` | déclenche une collecte immédiate (clé API) |
| POST | `/api/observations` | ajoute une observation validée (clé API) |
| GET | `/export.csv` / `/export.xlsx` | exports |

En production, une limitation en mémoire s'applique par adresse cliente : 60 requêtes par fenêtre de 60 secondes par défaut. Ajustez `PRICE_MONITOR_RATE_LIMIT_REQUESTS` et `PRICE_MONITOR_RATE_LIMIT_WINDOW_SECONDS` si nécessaire.

## Alertes de prix et de disponibilité

Les alertes sont désactivées par défaut. Pour surveiller les seuils, définissez `PRICE_MONITOR_ALERT_THRESHOLDS` avec un objet JSON :

```text
PRICE_MONITOR_ALERT_THRESHOLDS={"brent":{"above":90,"below":70},"gasoil":{"above":3.5},"bitume":{"above":600}}
```

Une alerte est envoyée lors du franchissement du seuil, puis une notification de rétablissement est envoyée lorsque le prix revient dans la zone normale. L'état est conservé en base afin d'éviter une notification à chaque collecte.

Les notifications peuvent être envoyées vers un webhook compatible Teams ou générique avec `PRICE_MONITOR_ALERT_WEBHOOK_URL`, et/ou par SMTP avec `PRICE_MONITOR_ALERT_EMAIL_TO`, `PRICE_MONITOR_ALERT_SMTP_HOST`, `PRICE_MONITOR_ALERT_SMTP_FROM` et les paramètres SMTP associés. Les échecs de collecte et les sources quotidiennes ou mensuelles devenues obsolètes déclenchent également une alerte. Les sources « à la demande » et jamais collectées ne sont pas considérées comme obsolètes.

Exemple de saisie bitume :

```json
{"product":"bitume","price":528.5,"unit":"USD/tonne","source":"Devis Fournisseur ABC","source_date":"2026-09-08","notes":"FOB Méditerranée"}
```

`source_date` doit respecter le format `YYYY-MM-DD` et `collected_at`, lorsqu'il est fourni, doit être un horodatage ISO 8601 avec fuseau. L'unité doit correspondre à celle du produit. Une nouvelle tentative avec le même produit, la même source, la même date source et le même prix réutilise l'observation existante.

Les exports `/export.csv` et `/export.xlsx` acceptent les mêmes filtres que `/api/history` et exportent tous les résultats correspondants, sans pagination. La page « Historique » permet également de comparer les moyennes, minimums, maximums et volumes de relevés de deux périodes.

## Impact d'un achat

Le formulaire « Évaluer une commande » et la route protégée `POST /api/procurements` enregistrent une estimation d'achat avec le fournisseur, la quantité, la devise, le prix unitaire, le transport, le taux de change et le budget prévu. Le taux de change est exprimé en **USD pour une unité de la devise de l'achat** : `1 EUR = 1.09 USD` se saisit donc `1.09`.

L'application calcule :

- le coût total dans la devise de l'achat et en USD (`quantité × prix unitaire + transport`) ;
- l'écart au budget, positif lorsque l'achat dépasse le budget ;
- l'écart du prix unitaire et l'impact total par rapport au dernier prix marché connu du produit.

L'historique est disponible via `GET /api/procurements?limit=100` et dans la section « Achats » du tableau de bord.

## Passage en production

Le fichier `sql/mysql_schema.sql` contient la structure MySQL correspondant aux tables du rapport : `price_observations`, `data_sources`, `collection_logs` et `schema_migrations`. Le stockage SQLite intégré reste le défaut local ; MySQL peut être activé sans modifier les routes de l'application.

## Déploiement et opérations

Le projet fournit un `Dockerfile`, un `docker-compose.yml` MySQL 8.4 et une pipeline GitHub Actions dans `.github/workflows/ci.yml`. Pour l'installation comme paquet Python :

```powershell
python -m pip install .
price-monitor-migrate
price-monitor
```

Les sondes opérationnelles sont `/health/live`, `/health/ready` et `/health` (readiness), tandis que `/metrics` expose des métriques Prometheus et `/openapi.json` la spécification OpenAPI. Une page d'accès rapide est disponible sur `/docs`.

Les journaux sont structurés en JSON sur stdout. Les migrations SQLite versionnées sont dans `price_monitor/migrations/`; les migrations MySQL existantes sont dans `sql/mysql_migrations/`. La commande `price-monitor-backup` crée une sauvegarde cohérente SQLite ou un dump MySQL ; la stratégie de rétention, de copie hors site et de restauration est décrite dans [`docs/operations.md`](docs/operations.md).
