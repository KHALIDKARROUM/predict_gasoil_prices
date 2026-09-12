# Market data

The bundled snapshot contains five years of real daily observations for the two public market series used in the project:

| Column | Series | Unit | Provider |
|---|---|---|---|
| `brent` | Europe Brent Spot Price FOB (`RBRTE.D`, published as FRED `DCOILBRENTEU`) | USD/barrel | U.S. Energy Information Administration |
| `gasoil` | New York Harbor Ultra-Low Sulfur No. 2 Diesel Spot Price (`EER_EPD2DXL0_PF4_Y35NY_DPG.D`, published as FRED `DDFUELNYH`) | USD/gallon | U.S. Energy Information Administration |

The raw JSON files are public EIA observations retrieved through the DBnomics mirror. The normalized file used by the application is `data/processed/market_prices.csv`. Rebuild it with:

```powershell
python scripts/prepare_market_data.py --years 5
```

Use `--refresh` to retrieve a newer snapshot. The downloader keeps the latest 2–5 years, preserves missing market days as empty values, and records the source series codes in this document.

Primary source references:

- [FRED: Brent Europe, DCOILBRENTEU](https://fred.stlouisfed.org/series/DCOILBRENTEU)
- [FRED: New York Harbor diesel, DDFUELNYH](https://fred.stlouisfed.org/series/DDFUELNYH)
- [EIA Petroleum data](https://www.eia.gov/petroleum/data.php)
