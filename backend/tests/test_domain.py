"""
Tests for the analysis.

The first group is the one worth having. Lookahead bias does not raise, does
not crash, and does not look wrong: it just quietly reports an error about half
the size of the one the buyer actually faces. Nothing but a test catches that.
"""
from __future__ import annotations

import datetime as dt

import pytest

from windsight.domain import (
    Actual,
    Forecast,
    Point,
    decision_view,
    error_by_lead_time,
    error_by_level,
    error_stats,
    expected_shortfall,
    forecast_as_of,
    to_hourly,
)

UTC = dt.timezone.utc


def T(day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 1, day, hour, minute, tzinfo=UTC)


# ------------------------------------------------------- the rule the product rests on


def test_a_forecast_published_after_gate_closure_is_never_used():
    target = T(15, 12)
    gate = T(14, 9, 50)
    forecasts = [
        Forecast(publish_time=T(14, 9, 30), start_time=target, generation=9000),
        # published 20 minutes too late: closer to the truth, and unusable
        Forecast(publish_time=T(14, 10, 10), start_time=target, generation=7000),
        Forecast(publish_time=T(15, 6, 0), start_time=target, generation=6500),
    ]

    chosen = forecast_as_of(forecasts, gate)

    assert chosen[target].generation == 9000
    assert chosen[target].publish_time == T(14, 9, 30)


def test_the_latest_forecast_before_the_cutoff_wins():
    target = T(15, 12)
    forecasts = [
        Forecast(publish_time=T(13, 2, 30), start_time=target, generation=5000),
        Forecast(publish_time=T(14, 2, 30), start_time=target, generation=8000),
        Forecast(publish_time=T(14, 7, 30), start_time=target, generation=8800),
    ]
    assert forecast_as_of(forecasts, T(14, 9, 50))[target].generation == 8800


def test_a_forecast_published_exactly_at_gate_closure_is_usable():
    # The auction closes AT 09:50, so a forecast timestamped 09:50 was public.
    # An off-by-one here silently drops a whole vintage.
    target = T(15, 12)
    f = [Forecast(publish_time=T(14, 9, 50), start_time=target, generation=8000)]
    assert forecast_as_of(f, T(14, 9, 50))[target].generation == 8000


def test_nothing_published_yet_yields_nothing_rather_than_guessing():
    f = [Forecast(publish_time=T(14, 12, 0), start_time=T(15, 12), generation=8000)]
    assert forecast_as_of(f, T(14, 9, 50)) == {}


def test_decision_view_uses_one_vintage_for_the_whole_day():
    # A real trap: picking the best forecast per hour would mix vintages and
    # produce a day no buyer ever saw.
    forecasts = []
    for hour in range(24):
        t = T(15, hour)
        forecasts.append(Forecast(publish_time=T(14, 9, 30), start_time=t, generation=9000))
        forecasts.append(Forecast(publish_time=T(14, 15, 30), start_time=t, generation=7000))

    points = decision_view(forecasts, {}, dt.date(2026, 1, 15), T(14, 9, 50))

    assert len(points) == 24
    assert {p.forecast for p in points} == {9000}


# ------------------------------------------------------------- resolution bridge


def test_half_hourly_outturn_is_averaged_onto_the_hour():
    actuals = [
        Actual(start_time=T(5, 0, 0), generation=10000),
        Actual(start_time=T(5, 0, 30), generation=11000),
    ]
    assert to_hourly(actuals) == {T(5, 0): 10500}


def test_an_hour_missing_a_settlement_period_is_dropped_not_half_counted():
    # Counting a lone half-hour as the whole hour would bias the comparison
    # at every month boundary.
    actuals = [
        Actual(start_time=T(5, 0, 0), generation=10000),
        Actual(start_time=T(5, 1, 0), generation=12000),
        Actual(start_time=T(5, 1, 30), generation=12000),
    ]
    hourly = to_hourly(actuals)
    assert T(5, 0) not in hourly
    assert hourly[T(5, 1)] == 12000


def test_the_forecast_is_never_interpolated_down_to_half_hours():
    # Scoring invented half-hourly values would flatter the forecaster.
    forecasts = [Forecast(publish_time=T(14, 9), start_time=T(15, 0), generation=9000)]
    points = decision_view(forecasts, {T(15, 0): 8000}, dt.date(2026, 1, 15), T(14, 9, 50))
    assert len(points) == 1
    assert points[0].start_time.minute == 0


# ---------------------------------------------------------------------- metrics


def test_error_is_forecast_minus_actual_so_positive_means_too_optimistic():
    p = Point(start_time=T(5, 0), forecast=9000, actual=7000)
    assert p.error == 2000


def test_metrics_on_a_known_set():
    points = [
        Point(T(5, 0), forecast=1000, actual=900),    # +100
        Point(T(5, 1), forecast=1000, actual=1200),   # -200
        Point(T(5, 2), forecast=1000, actual=700),    # +300
    ]
    s = error_stats(points)
    assert s is not None
    assert s.n == 3
    assert s.mae == pytest.approx(200)
    assert s.bias == pytest.approx(200 / 3)
    assert s.rmse == pytest.approx(((100**2 + 200**2 + 300**2) / 3) ** 0.5)


def test_unsettled_hours_are_skipped_not_counted_as_zero():
    # A day being traded today has no outturn. Treating that as 0 MW would
    # report a catastrophic error for a day that is simply not over.
    points = [
        Point(T(5, 0), forecast=1000, actual=900),
        Point(T(5, 1), forecast=1000, actual=None),
    ]
    s = error_stats(points)
    assert s is not None and s.n == 1


def test_a_day_with_no_outturn_scores_nothing_rather_than_zero():
    assert error_stats([Point(T(5, 0), forecast=1000, actual=None)]) is None


def test_mae_is_reported_against_mean_output_not_as_mape():
    # MAPE divides by the outturn, so one near-calm hour can produce a
    # thousand-percent error and make the headline meaningless.
    points = [Point(T(5, 0), forecast=1000, actual=10), Point(T(5, 1), forecast=1000, actual=990)]
    s = error_stats(points)
    assert s is not None
    assert s.mae_pct_of_mean < 500


# ------------------------------------------------------------- the level finding


def test_error_is_grouped_by_forecast_level():
    points = [
        Point(T(5, 0), forecast=1000, actual=900),
        Point(T(5, 1), forecast=1500, actual=1400),
        Point(T(5, 2), forecast=7000, actual=5000),
    ]
    bands = error_by_level(points, width_mw=3000)
    assert [(b.lower_mw, b.n) for b in bands] == [(0, 2), (6000, 1)]
    assert bands[0].mean_error == pytest.approx(100)
    assert bands[1].mean_error == pytest.approx(2000)


def test_a_forecast_picks_the_band_it_falls_in():
    points = [Point(T(5, i), forecast=f, actual=f - 500) for i, f in enumerate([1000, 7000])]
    bands = error_by_level(points, width_mw=3000)
    assert expected_shortfall(bands, 1200).lower_mw == 0
    assert expected_shortfall(bands, 7500).lower_mw == 6000


def test_a_forecast_above_every_band_falls_back_to_the_highest():
    # Better a slightly wrong buffer than no buffer on the windiest hour of the year.
    points = [Point(T(5, 0), forecast=1000, actual=900)]
    bands = error_by_level(points, width_mw=3000)
    assert expected_shortfall(bands, 25000) is bands[-1]


def test_no_bands_yields_no_buffer_rather_than_an_exception():
    assert expected_shortfall([], 9000) is None


# -------------------------------------------------------------------- lead time


def test_lead_time_buckets_use_publish_to_target_distance():
    forecasts = [
        Forecast(publish_time=T(14, 12), start_time=T(14, 13), generation=1000),  # 1h
        Forecast(publish_time=T(12, 12), start_time=T(14, 12), generation=1000),  # 48h
    ]
    actual = {T(14, 13): 900, T(14, 12): 800}
    buckets = error_by_lead_time(forecasts, actual, bucket_hours=6)
    assert [b["lead_from_hours"] for b in buckets] == [0, 48]


def test_forecasts_with_no_outturn_are_excluded_from_lead_time():
    forecasts = [Forecast(publish_time=T(14, 12), start_time=T(14, 13), generation=1000)]
    assert error_by_lead_time(forecasts, {}, bucket_hours=6) == []
