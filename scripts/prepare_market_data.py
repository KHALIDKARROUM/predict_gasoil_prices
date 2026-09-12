"""Download and normalize the real EIA/FRED market snapshot used by the project."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUTPUT_PATH = ROOT / "data" / "processed" / "market_prices.csv"

SERIES = {
    "brent": {
        "file": "EIA_PET_RBRTE_D.json",
        "url": "https://api.db.nomics.world/v22/series/EIA/PET/RBRTE.D?observations=1",
    },
    "gasoil": {
        "file": "EIA_PET_DIESEL_NYH_D.json",
        "url": "https://api.db.nomics.world/v22/series/EIA/PET/EER_EPD2DXL0_PF4_Y35NY_DPG.D?observations=1",
    },
}


def download(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "PriceMonitor/1.0"})
    with urlopen(request, timeout=30) as response:
        destination.write_bytes(response.read())


def read_series(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    document = payload["series"]["docs"][0]
    values: dict[str, float] = {}
    for period, raw_value in zip(document["period"], document["value"]):
        if raw_value in (None, "", "."):
            continue
        try:
            values[str(period)[:10]] = float(str(raw_value).replace(",", "."))
        except ValueError:
            continue
    return values


def build_dataset(years: int, refresh: bool) -> tuple[int, str, str]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    series_data: dict[str, dict[str, float]] = {}
    for name, metadata in SERIES.items():
        raw_path = RAW_DIR / metadata["file"]
        if refresh or not raw_path.exists():
            download(metadata["url"], raw_path)
        series_data[name] = read_series(raw_path)

    all_dates = sorted(set().union(*(values.keys() for values in series_data.values())))
    if not all_dates:
        raise RuntimeError("Aucune observation valide trouvée dans les fichiers source.")
    latest = date.fromisoformat(all_dates[-1])
    first_allowed = latest - timedelta(days=365 * years)
    dates = [item for item in all_dates if date.fromisoformat(item) >= first_allowed]

    with OUTPUT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "brent", "gasoil"])
        writer.writeheader()
        for item in dates:
            writer.writerow({
                "date": item,
                "brent": series_data["brent"].get(item, ""),
                "gasoil": series_data["gasoil"].get(item, ""),
            })
    return len(dates), dates[0], dates[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, choices=range(2, 6), default=5, help="Fenêtre historique à conserver (2 à 5 ans).")
    parser.add_argument("--refresh", action="store_true", help="Retélécharger les fichiers source avant normalisation.")
    args = parser.parse_args()
    count, first, last = build_dataset(args.years, args.refresh)
    print(f"{count} dates ecrites dans {OUTPUT_PATH.relative_to(ROOT)} ({first} -> {last}).")


if __name__ == "__main__":
    main()
