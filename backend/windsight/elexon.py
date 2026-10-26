"""
The Elexon BMRS client.

Two datasets, no API key:

  FUELHH   half-hourly metered generation by fuel type. We keep fuelType=WIND.
  WINDFOR  hourly wind forecast, each row carrying the publishTime that makes
           the point-in-time analysis possible.

Responses are cached in memory with a TTL. Both datasets refresh far more
slowly than users click, and a cold serverless function re-fetching five
megabytes on every request would be the slowest thing in the product.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from typing import Any

import httpx

from . import config
from .domain import Actual, Forecast

UTC = dt.timezone.utc


def _parse(ts: str) -> dt.datetime:
    """Elexon returns `2026-01-05T04:30:00Z`; Python wants the offset spelled out."""
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _fmt(ts: dt.datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")


class _TTLCache:
    """Small thread-safe cache. Not an LRU: the key space here is tiny."""

    def __init__(self, ttl: int) -> None:
        self._ttl = ttl
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        with self._lock:
            hit = self._store.get(key)
            if hit is None:
                return None
            stored_at, value = hit
            if time.time() - stored_at > self._ttl:
                del self._store[key]
                return None
            return value

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.time(), value)


_cache = _TTLCache(config.CACHE_TTL)


class ElexonClient:
    """
    Reads the two datasets, live or from fixtures.

    `offline` exists so the test suite and a laptop on a train both work. It
    reads the same JSON the API returns, so nothing about the parsing or the
    analysis differs between the two paths.
    """

    def __init__(self, offline: bool | None = None, data_dir: str | None = None) -> None:
        self.offline = config.OFFLINE if offline is None else offline
        self.data_dir = data_dir or config.DATA_DIR

    # ------------------------------------------------------------------ fetching

    def _fixture(self, name: str) -> list[dict]:
        path = os.path.join(self.data_dir, name)
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Offline mode needs {path}. Run `make data` (see the README) to download it."
            )
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def _stream(self, dataset: str, start: dt.datetime, end: dt.datetime) -> list[dict]:
        key = f"{dataset}:{_fmt(start)}:{_fmt(end)}"
        cached = _cache.get(key)
        if cached is not None:
            return cached

        url = f"{config.ELEXON_BASE}/datasets/{dataset}/stream"
        params = {"publishDateTimeFrom": _fmt(start), "publishDateTimeTo": _fmt(end)}
        with httpx.Client(timeout=60) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            rows = response.json()

        _cache.put(key, rows)
        return rows

    # -------------------------------------------------------------------- public

    def actuals(self, start: dt.datetime, end: dt.datetime) -> list[Actual]:
        """
        Metered wind outturn whose settlement period starts in [start, end).

        FUELHH is filtered by publishTime, and a period is published about
        thirty minutes after it starts, so the request window is widened and
        the result trimmed on startTime. Getting this wrong silently loses the
        first hour of every range.
        """
        rows = (
            self._fixture("fuelhh.json")
            if self.offline
            else self._stream("FUELHH", start, end + dt.timedelta(hours=2))
        )
        out = [
            Actual(start_time=_parse(r["startTime"]), generation=float(r["generation"]))
            for r in rows
            if r.get("fuelType") == "WIND"
        ]
        return sorted((a for a in out if start <= a.start_time < end), key=lambda a: a.start_time)

    def forecasts(self, start: dt.datetime, end: dt.datetime) -> list[Forecast]:
        """
        Every forecast *published* in [start, end), whatever it targets.

        Filtered on publish time, not target time, because the question this
        product answers is "what did they know, and when did they know it".
        """
        rows = (
            self._fixture("windfor.json")
            if self.offline
            else self._stream("WINDFOR", start, end)
        )
        out = [
            Forecast(
                publish_time=_parse(r["publishTime"]),
                start_time=_parse(r["startTime"]),
                generation=float(r["generation"]),
            )
            for r in rows
        ]
        return sorted(
            (f for f in out if start <= f.publish_time < end),
            key=lambda f: (f.publish_time, f.start_time),
        )
