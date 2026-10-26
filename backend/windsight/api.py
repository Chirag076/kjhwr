"""
HTTP surface.

Three endpoints, matching the two questions the brief asks and one piece of
supporting evidence:

  /api/decision/{day}   what the buyer could see at gate closure, and the
                        buffer the history says to add
  /api/accuracy         how wrong the day-ahead forecast has been, including
                        the part that varies with the forecast level
  /api/lead-time        how much accuracy the day-ahead deadline costs
"""
from __future__ import annotations

import datetime as dt

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import config, domain
from .elexon import ElexonClient

UTC = dt.timezone.utc

app = FastAPI(
    title="Day-ahead wind forecast review",
    version="1.0.0",
    description=(
        "Wind forecasts and their accuracy, scored only against what was "
        "publicly available when the day-ahead position had to be committed."
    ),
)

# The front end is served from a different origin in dev and on Vercel.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

client = ElexonClient()


def _window() -> tuple[dt.datetime, dt.datetime]:
    """
    The span to pull for a month-wide analysis.

    It starts two days before the evaluated month: a decision for 1 January is
    made on 31 December, from a forecast published earlier still. Starting on
    1 January would quietly drop the first delivery day.
    """
    start = dt.datetime.combine(config.EVALUATION_START, dt.time(), tzinfo=UTC) - dt.timedelta(days=2)
    end = dt.datetime.combine(config.EVALUATION_END, dt.time(), tzinfo=UTC) + dt.timedelta(days=1)
    return start, end


def _all_points() -> list[domain.Point]:
    """Every delivery day in the evaluated month, each scored on its own gate-closure vintage."""
    start, end = _window()
    actual_hourly = domain.to_hourly(client.actuals(start, end))
    forecasts = client.forecasts(start, end)

    points: list[domain.Point] = []
    day = config.EVALUATION_START
    while day <= config.EVALUATION_END:
        points.extend(
            domain.decision_view(forecasts, actual_hourly, day, config.gate_closure_for(day))
        )
        day += dt.timedelta(days=1)
    return points


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "gate_closure_utc": config.GATE_CLOSURE.strftime("%H:%M"),
        "evaluation": {
            "from": config.EVALUATION_START.isoformat(),
            "to": config.EVALUATION_END.isoformat(),
        },
        "offline": client.offline,
    }


@app.get("/api/decision/{delivery_day}")
def decision(delivery_day: dt.date) -> dict:
    """
    The decision screen for one delivery day.

    `forecast` is the latest vintage published at or before gate closure.
    `adjusted` corrects it by the median error history shows at that forecast
    level, and `p10`/`p90` bracket it, so the buyer sees a realistic central
    case and a range rather than a single optimistic line.
    """
    gate = config.gate_closure_for(delivery_day)
    start, end = _window()
    if not (config.EVALUATION_START <= delivery_day <= config.EVALUATION_END):
        raise HTTPException(
            status_code=404,
            detail=(
                f"This pilot covers {config.EVALUATION_START} to {config.EVALUATION_END}, "
                f"the period the analysis was commissioned for."
            ),
        )

    actual_hourly = domain.to_hourly(client.actuals(start, end))
    forecasts = client.forecasts(start, end)
    points = domain.decision_view(forecasts, actual_hourly, delivery_day, gate)
    if not points:
        raise HTTPException(status_code=404, detail=f"No forecast was published before {gate:%Y-%m-%d %H:%M}Z.")

    bands = domain.error_by_level(_all_points())
    vintage = max(
        (f.publish_time for f in forecasts if f.publish_time <= gate), default=None
    )

    hours = []
    for p in points:
        band = domain.expected_shortfall(bands, p.forecast)
        hours.append(
            {
                "start_time": p.start_time.isoformat(),
                "forecast": round(p.forecast, 1),
                "actual": None if p.actual is None else round(p.actual, 1),
                "error": None if p.error is None else round(p.error, 1),
                "adjusted": round(p.forecast - band.median_error, 1) if band else None,
                "low": round(p.forecast - band.p90, 1) if band else None,
                "high": round(p.forecast - band.p10, 1) if band else None,
            }
        )

    stats = domain.error_stats(points)
    return {
        "delivery_day": delivery_day.isoformat(),
        "gate_closure": gate.isoformat(),
        "forecast_published": vintage.isoformat() if vintage else None,
        "lead_time_hours": round((points[0].start_time - vintage).total_seconds() / 3600, 1)
        if vintage
        else None,
        "hours": hours,
        "totals": {
            "forecast_mwh": round(sum(h["forecast"] for h in hours)),
            "adjusted_mwh": round(sum(h["adjusted"] for h in hours if h["adjusted"] is not None)),
            "actual_mwh": round(sum(h["actual"] for h in hours if h["actual"] is not None)),
        },
        "day_stats": None if stats is None else _stats_json(stats),
    }


def _stats_json(s: domain.ErrorStats) -> dict:
    return {
        "n": s.n,
        "mae": round(s.mae, 1),
        "rmse": round(s.rmse, 1),
        "bias": round(s.bias, 1),
        "p10": round(s.p10, 1),
        "p50": round(s.p50, 1),
        "p90": round(s.p90, 1),
        "mean_actual": round(s.mean_actual, 1),
        "mae_pct_of_mean": round(s.mae_pct_of_mean, 1),
    }


@app.get("/api/accuracy")
def accuracy(band_width_mw: int = Query(3000, ge=500, le=10000)) -> dict:
    """Month-wide scoring of the forecasts that were actually usable."""
    points = _all_points()
    stats = domain.error_stats(points)
    if stats is None:
        raise HTTPException(status_code=503, detail="No settled outturn to score against yet.")

    bands = domain.error_by_level(points, width_mw=band_width_mw)

    by_day: dict[str, list[domain.Point]] = {}
    for p in points:
        by_day.setdefault(p.start_time.date().isoformat(), []).append(p)
    daily = []
    for day, pts in sorted(by_day.items()):
        s = domain.error_stats(pts)
        if s:
            daily.append({"day": day, **_stats_json(s)})

    return {
        "gate_closure_utc": config.GATE_CLOSURE.strftime("%H:%M"),
        "overall": _stats_json(stats),
        "by_level": [
            {
                "lower_mw": b.lower_mw,
                "upper_mw": b.upper_mw,
                "n": b.n,
                "mean_error": round(b.mean_error, 1),
                "median_error": round(b.median_error, 1),
                "p10": round(b.p10, 1),
                "p90": round(b.p90, 1),
            }
            for b in bands
        ],
        "daily": daily,
    }


@app.get("/api/lead-time")
def lead_time() -> dict:
    """Error against how far ahead the forecast was made."""
    start, end = _window()
    actual_hourly = domain.to_hourly(client.actuals(start, end))
    forecasts = client.forecasts(start, end)
    return {"buckets": domain.error_by_lead_time(forecasts, actual_hourly)}
