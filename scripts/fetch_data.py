#!/usr/bin/env python3
"""
Download the January 2026 window from Elexon into data/.

Only needed for offline mode (the Docker compose default) and the tests; the
deployed app reads Elexon live. No API key: both datasets are public.

    python scripts/fetch_data.py
"""
from __future__ import annotations

import json
import pathlib
import sys

import httpx

BASE = "https://data.elexon.co.uk/bmrs/api/v1/datasets"
OUT = pathlib.Path(__file__).resolve().parent.parent / "data"

# WINDFOR starts two days early on purpose: the decision for 1 January is made
# on 31 December, from a forecast published before that. Starting on 1 January
# would silently drop the first delivery day of the evaluated month.
JOBS = [
    ("FUELHH", "fuelhh.json", "2026-01-01T00:00Z", "2026-02-01T00:00Z"),
    ("WINDFOR", "windfor.json", "2025-12-30T00:00Z", "2026-02-01T00:00Z"),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120) as client:
        for dataset, filename, start, end in JOBS:
            url = f"{BASE}/{dataset}/stream"
            print(f"  {dataset}: {start} .. {end}")
            r = client.get(url, params={"publishDateTimeFrom": start, "publishDateTimeTo": end})
            r.raise_for_status()
            rows = r.json()
            (OUT / filename).write_text(json.dumps(rows), encoding="utf-8")
            print(f"    {len(rows):,} rows -> data/{filename}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
