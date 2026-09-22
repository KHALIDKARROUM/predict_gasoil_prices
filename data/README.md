# Market data

The bundled snapshot contains five years of real daily observations for the two public market series used in the project:

| Column | Series | Unit | Provider |
|---|---|---|---|
| `brent` | Europe Brent Spot Price FOB (`RBRTE.D`, published as FRED `DCOILBRENTEU`) | USD/barrel | U.S. Energy Information Administration |
| `gasoil` | New York Harbor Ultra-Low Sulfur No. 2 Diesel Spot Price (`EER_EPD2DXL0_PF4_Y35NY_DPG.D`, published as FRED `DDFUELNYH`) | USD/gallon | U.S. Energy Information Administration |

The raw CSV files are public EIA observations downloaded from FRED. The normalized file used by the application is `data/processed/market_prices.csv`


Raw files:

- `data/raw/FRED_DCOILBRENTEU.csv`
- `data/raw/FRED_DDFUELNYH.csv`

Primary source references:

- [FRED: Brent Europe, DCOILBRENTEU](https://fred.stlouisfed.org/series/DCOILBRENTEU)
- [FRED: New York Harbor diesel, DDFUELNYH](https://fred.stlouisfed.org/series/DDFUELNYH)
- [EIA Petroleum data](https://www.eia.gov/petroleum/data.php)
