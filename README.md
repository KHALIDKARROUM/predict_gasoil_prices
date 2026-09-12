# Price Monitor

Application de suivi des prix internationaux du gasoil, du Brent et du bitume, construite à partir du rapport de proposition de sujet de Khalid Karroum.

## Ce qui est livré

- collecte manuelle ou planifiée cinq fois par jour à **08:00, 11:00, 14:00, 17:00 et 20:00** ;
- historique réel de cinq ans pour le Brent et le gasoil, issu des séries EIA publiées par FRED ;
- connecteurs FRED (séries `DCOILBRENTEU` et `DDFUELNYH`) et Alpha Vantage (`BRENT`) via variables d'environnement ;
- stockage local SQLite prêt à démarrer, avec schéma MySQL 8 fourni dans `sql/mysql_schema.sql` ;
- contrôle de qualité, unités normalisées, date de publication distincte de la date de collecte, variation absolue et en pourcentage ;
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

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/api/dashboard?days=30` | indicateurs, séries et derniers relevés |
| GET | `/api/observations?product=bitume` | historique filtré |
| POST | `/api/collect` | déclenche une collecte immédiate |
| POST | `/api/observations` | ajoute une observation validée |
| GET | `/export.csv` / `/export.xlsx` | exports |

Exemple de saisie bitume :

```json
{"product":"bitume","price":528.5,"unit":"USD/tonne","source":"Devis Fournisseur ABC","source_date":"2026-09-08","notes":"FOB Méditerranée"}
```

## Passage en production

Le fichier `sql/mysql_schema.sql` contient la structure MySQL correspondant aux trois tables du rapport : `price_observations`, `data_sources` et `collection_logs`. Le stockage SQLite intégré est parfait pour le prototype et la soutenance ; pour un déploiement entreprise, brancher la couche de persistance sur MySQL et appeler `/api/collect` depuis cron ou le planificateur du serveur.
