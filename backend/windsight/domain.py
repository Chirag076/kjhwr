"""
The analysis, as pure functions. No network, no clock, no framework.

The whole product rests on one rule, so it is worth stating plainly:

    A forecast may only inform a decision if it was published before the
    gate closed for that delivery day.

Breaking that rule is easy and silent. Take the most recent forecast for each
hour and the error statistics come out roughly half what a buyer actually
faces, because some of those forecasts were published after the trade. Every
function here that selects a forecast takes an explicit `as_of` and filters on
`publish_time <= as_of`; nothing selects "the latest" without one.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import fmean
from typing import Iterable, Sequence

UTC = dt.timezone.utc


# --------------------------------------------------------------------------- records


@dataclass(frozen=True)
class Actual:
    """One half-hourly metered wind outturn (FUELHH, fuelType=WIND)."""

    start_time: dt.datetime
    generation: float


@dataclass(frozen=True)
class Forecast:
    """One hourly wind forecast point, with the moment it became public."""

    publish_time: dt.datetime
    start_time: dt.datetime
    generation: float


@dataclass(frozen=True)
class Point:
    """A forecast and the outturn it was trying to predict, at one hour."""

    start_time: dt.datetime
    forecast: float
    actual: float | None

    @property
    def error(self) -> float | None:
        """Forecast minus actual. Positive means the forecast was too optimistic."""
        return None if self.actual is None else self.forecast - self.actual


# ----------------------------------------------------------------- resolution bridge


def to_hourly(actuals: Iterable[Actual]) -> dict[dt.datetime, float]:
    """
    Average half-hourly outturn onto the hour.

    The two datasets do not share a resolution: outturn is half-hourly
    (settlement periods), the forecast is hourly. Something has to give.

    Averaging the outturn up is the honest direction. Interpolating the
    forecast down to half-hours would invent two numbers where the forecaster
    published one, and would then flatter the error statistics by scoring the
    invention rather than the forecast. Energy over the hour is also what a
    day-ahead position is actually bought in.

    An hour with only one of its two settlement periods is dropped rather than
    half-counted; at month boundaries that is the first and last hour.
    """
    buckets: dict[dt.datetime, list[float]] = defaultdict(list)
    for a in actuals:
        buckets[a.start_time.replace(minute=0, second=0, microsecond=0)].append(a.generation)
    return {hour: fmean(vals) for hour, vals in buckets.items() if len(vals) == 2}


# -------------------------------------------------------------- vintage selection


def forecast_as_of(
    forecasts: Iterable[Forecast], as_of: dt.datetime
) -> dict[dt.datetime, Forecast]:
    """
    The best view of the future that existed at `as_of`.

    For each target hour, the most recently published forecast that was already
    public at `as_of`. Forecasts published later are not "more accurate data" —
    at `as_of` they did not exist.
    """
    best: dict[dt.datetime, Forecast] = {}
    for f in forecasts:
        if f.publish_time > as_of:
            continue
        seen = best.get(f.start_time)
        if seen is None or f.publish_time > seen.publish_time:
            best[f.start_time] = f
    return best


def decision_view(
    forecasts: Iterable[Forecast],
    actual_hourly: dict[dt.datetime, float],
    delivery_day: dt.date,
    gate_closure: dt.datetime,
) -> list[Point]:
    """
    What the buyer saw for `delivery_day`, and what in the end happened.

    `actual` is None for hours that have not settled yet, which is the normal
    state for a day being traded today. The view is still complete; only the
    scoring half is missing.
    """
    available = forecast_as_of(forecasts, gate_closure)
    points: list[Point] = []
    for hour in range(24):
        t = dt.datetime.combine(delivery_day, dt.time(hour), tzinfo=UTC)
        f = available.get(t)
        if f is None:
            continue
        points.append(Point(start_time=t, forecast=f.generation, actual=actual_hourly.get(t)))
    return points


# ------------------------------------------------------------------------- metrics


@dataclass(frozen=True)
class ErrorStats:
    n: int
    mae: float          # mean absolute error, MW
    rmse: float         # root mean squared error, MW — punishes the big misses
    bias: float         # mean error, MW. Positive = forecast too optimistic
    p10: float
    p50: float
    p90: float
    mean_actual: float
    mae_pct_of_mean: float   # MAE as % of mean outturn. Readable; unlike MAPE it
                             # does not explode when the wind drops to near zero.

    @property
    def shortfall_p90(self) -> float:
        """How far wind fell short of forecast on the worst 1 day in 10."""
        return self.p90


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile. `q` in [0, 1]. Input must be sorted."""
    if not sorted_vals:
        return math.nan
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return sorted_vals[int(pos)]
    return sorted_vals[low] + (sorted_vals[high] - sorted_vals[low]) * (pos - low)


def error_stats(points: Iterable[Point]) -> ErrorStats | None:
    """Score only the hours that have both a forecast and a settled outturn."""
    scored = [p for p in points if p.actual is not None]
    if not scored:
        return None

    errors = [p.error for p in scored]  # type: ignore[misc]
    actuals = [p.actual for p in scored]  # type: ignore[misc]
    ordered = sorted(errors)
    mae = fmean(abs(e) for e in errors)
    mean_actual = fmean(actuals)

    return ErrorStats(
        n=len(scored),
        mae=mae,
        rmse=math.sqrt(fmean(e * e for e in errors)),
        bias=fmean(errors),
        p10=_percentile(ordered, 0.10),
        p50=_percentile(ordered, 0.50),
        p90=_percentile(ordered, 0.90),
        mean_actual=mean_actual,
        mae_pct_of_mean=100 * mae / mean_actual if mean_actual else math.nan,
    )


# ------------------------------------------------------- the level-dependent finding


@dataclass(frozen=True)
class LevelBand:
    """Error behaviour in one slice of forecast output."""

    lower_mw: float
    upper_mw: float
    n: int
    mean_error: float
    median_error: float
    p10: float
    p90: float


def error_by_level(points: Iterable[Point], width_mw: float = 3000) -> list[LevelBand]:
    """
    Group the error by how much wind was forecast.

    This is the part a flat accuracy number hides. On this data the forecast is
    optimistic almost everywhere, and the optimism grows with the forecast: a
    few hundred MW when 7 GW is expected, several GW when 19 GW is expected.

    A buyer who budgets one average error therefore under-buys exactly on the
    days when the shortfall is largest. The practical answer is a buffer that
    scales with the forecast, which is what these bands provide.
    """
    scored = [p for p in points if p.actual is not None]
    buckets: dict[int, list[float]] = defaultdict(list)
    for p in scored:
        buckets[int(p.forecast // width_mw)].append(p.error)  # type: ignore[arg-type]

    bands: list[LevelBand] = []
    for idx in sorted(buckets):
        errs = sorted(buckets[idx])
        bands.append(
            LevelBand(
                lower_mw=idx * width_mw,
                upper_mw=(idx + 1) * width_mw,
                n=len(errs),
                mean_error=fmean(errs),
                median_error=_percentile(errs, 0.5),
                p10=_percentile(errs, 0.10),
                p90=_percentile(errs, 0.90),
            )
        )
    return bands


def expected_shortfall(bands: Sequence[LevelBand], forecast_mw: float) -> LevelBand | None:
    """The band a given forecast falls into, so the UI can show a buffer that fits it."""
    for band in bands:
        if band.lower_mw <= forecast_mw < band.upper_mw:
            return band
    return bands[-1] if bands else None


# --------------------------------------------------------------------- lead time


def error_by_lead_time(
    forecasts: Iterable[Forecast],
    actual_hourly: dict[dt.datetime, float],
    bucket_hours: int = 6,
    max_lead_hours: int = 72,
) -> list[dict]:
    """
    How the error decays as delivery approaches.

    Context rather than a decision input: the day-ahead buyer is stuck with the
    vintage available at gate closure and cannot wait for the better one. It is
    here to show how much accuracy that constraint costs them.
    """
    buckets: dict[int, list[float]] = defaultdict(list)
    for f in forecasts:
        actual = actual_hourly.get(f.start_time)
        if actual is None:
            continue
        lead = (f.start_time - f.publish_time).total_seconds() / 3600
        if lead < 0 or lead > max_lead_hours:
            continue
        buckets[int(lead // bucket_hours)].append(f.generation - actual)

    out = []
    for idx in sorted(buckets):
        errs = buckets[idx]
        out.append(
            {
                "lead_from_hours": idx * bucket_hours,
                "lead_to_hours": (idx + 1) * bucket_hours,
                "n": len(errs),
                "mae": fmean(abs(e) for e in errs),
                "bias": fmean(errs),
            }
        )
    return out
