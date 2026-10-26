"""
Endpoint tests against the committed January 2026 fixtures.

These are coarser than the domain tests on purpose: they check that the wiring
holds and that the one rule survives the trip through HTTP, rather than
re-testing arithmetic that `test_domain.py` already pins.
"""
from __future__ import annotations

import datetime as dt
import os

import pytest
from fastapi.testclient import TestClient

os.environ["ELEXON_OFFLINE"] = "1"
os.environ.setdefault(
    "DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data")
)

from windsight.api import app  # noqa: E402

client = TestClient(app)


def test_health_reports_the_gate_it_is_using():
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["gate_closure_utc"] == "09:50"


def test_a_delivery_day_uses_a_forecast_published_before_its_gate():
    body = client.get("/api/decision/2026-01-15").json()
    published = dt.datetime.fromisoformat(body["forecast_published"])
    gate = dt.datetime.fromisoformat(body["gate_closure"])
    assert published <= gate


def test_every_delivery_day_in_the_month_respects_its_own_gate():
    # The guard that matters, swept across the whole evaluated period: one
    # off-by-one in date handling would show up on exactly one day.
    for day in range(1, 32):
        body = client.get(f"/api/decision/2026-01-{day:02d}").json()
        published = dt.datetime.fromisoformat(body["forecast_published"])
        gate = dt.datetime.fromisoformat(body["gate_closure"])
        assert published <= gate, f"2026-01-{day:02d} used a forecast from after gate closure"
        assert len(body["hours"]) == 24


def test_a_day_outside_the_pilot_says_so_rather_than_returning_nothing():
    r = client.get("/api/decision/2026-03-01")
    assert r.status_code == 404
    assert "pilot covers" in r.json()["detail"]


def test_accuracy_scores_every_hour_of_the_month():
    body = client.get("/api/accuracy").json()
    assert body["overall"]["n"] == 31 * 24
    assert len(body["daily"]) == 31


def test_the_level_bands_cover_the_observed_range():
    body = client.get("/api/accuracy").json()
    bands = body["by_level"]
    assert bands, "expected at least one level band"
    assert sum(b["n"] for b in bands) == body["overall"]["n"]


def test_band_width_is_a_parameter_not_a_constant():
    narrow = client.get("/api/accuracy?band_width_mw=1000").json()["by_level"]
    wide = client.get("/api/accuracy?band_width_mw=6000").json()["by_level"]
    assert len(narrow) > len(wide)


def test_an_absurd_band_width_is_rejected_rather_than_silently_clamped():
    assert client.get("/api/accuracy?band_width_mw=1").status_code == 422


def test_lead_time_buckets_are_ordered_and_populated():
    buckets = client.get("/api/lead-time").json()["buckets"]
    assert buckets
    assert [b["lead_from_hours"] for b in buckets] == sorted(
        b["lead_from_hours"] for b in buckets
    )
    assert all(b["n"] > 0 for b in buckets)
