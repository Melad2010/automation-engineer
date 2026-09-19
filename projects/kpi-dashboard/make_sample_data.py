#!/usr/bin/env python3
"""Writes sample-sales.csv — deterministic, so the tests can assert on it.

The data is invented, but its shape is not: seasonality, one region that grows
and one that stalls, a product whose margin erodes, and a handful of the
malformed rows every real export contains.
"""

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

REGIONS = {"Cairo": 1.00, "Alexandria": 0.72, "Delta": 0.55, "Upper Egypt": 0.38}
REGION_GROWTH = {"Cairo": 0.021, "Alexandria": 0.014, "Delta": 0.030, "Upper Egypt": -0.004}
PRODUCTS = {
    "Centrifugal pump": (4200.0, 3100.0, 0.0),
    "Screw compressor": (11800.0, 8900.0, 0.0),
    "Control panel": (2650.0, 1850.0, 0.0018),   # margin erodes month by month
    "Service contract": (1450.0, 900.0, 0.0),
}
CHANNELS = ("Direct", "Distributor", "Online")
CHANNEL_WEIGHT = (0.5, 0.35, 0.15)
# December and Ramadan-season dips, summer peak — a shape, not a flat line.
SEASON = [0.86, 0.92, 1.04, 1.10, 1.06, 0.98, 1.12, 1.18, 1.08, 1.02, 0.95, 0.88]

# Rows that a real export contains and a dashboard must not swallow.
MALFORMED = [
    {"date": "2026-13-05", "region": "Cairo", "product": "Control panel",
     "channel": "Direct", "units": "2", "unit_price": "2650", "unit_cost": "1850"},
    {"date": "2026-04-11", "region": "Delta", "product": "Centrifugal pump",
     "channel": "Online", "units": "three", "unit_price": "4200", "unit_cost": "3100"},
    {"date": "2026-05-02", "region": "", "product": "Service contract",
     "channel": "Direct", "units": "1", "unit_price": "1450", "unit_cost": "900"},
    {"date": "2026-06-18", "region": "Cairo", "product": "Screw compressor",
     "channel": "Distributor", "units": "0", "unit_price": "11800", "unit_cost": "8900"},
]

COLUMNS = ["date", "region", "product", "channel", "units", "unit_price", "unit_cost"]


def generate(months: int = 18, seed: int = 20260919) -> list:
    rng = random.Random(seed)
    start = date(2025, 4, 1)
    rows = []

    for month_index in range(months):
        year = start.year + (start.month - 1 + month_index) // 12
        month = (start.month - 1 + month_index) % 12 + 1
        season = SEASON[month - 1]

        for region, weight in REGIONS.items():
            growth = (1 + REGION_GROWTH[region]) ** month_index
            orders = max(1, int(round(rng.gauss(9 * weight * season * growth, 1.6))))
            for _ in range(orders):
                product = rng.choice(list(PRODUCTS))
                price, cost, erosion = PRODUCTS[product]
                day = rng.randint(1, 28)
                rows.append(
                    {
                        "date": date(year, month, day).isoformat(),
                        "region": region,
                        "product": product,
                        "channel": rng.choices(CHANNELS, CHANNEL_WEIGHT)[0],
                        "units": rng.randint(1, 4),
                        "unit_price": round(price * rng.uniform(0.97, 1.03), 2),
                        "unit_cost": round(cost * (1 + erosion * month_index), 2),
                    }
                )

    rows.sort(key=lambda row: (row["date"], row["region"]))
    # Sprinkle the malformed rows through the file, not all at the end.
    for offset, bad in enumerate(MALFORMED):
        rows.insert(min(len(rows), (offset + 1) * len(rows) // (len(MALFORMED) + 1)), bad)
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="sample-sales.csv")
    parser.add_argument("--months", type=int, default=18)
    args = parser.parse_args(argv)

    rows = generate(args.months)
    path = Path(args.out)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows ({len(MALFORMED)} deliberately malformed) to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
