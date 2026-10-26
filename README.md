# Day-ahead wind position

A web app for a UK utility's day-ahead desk. It shows the wind forecast the
desk actually held when the auction closed, quantifies how wrong that forecast
has been, and turns the answer into a number they can buy against.

Built against Elexon BMRS: `FUELHH` metered outturn (`fuelType = WIND`) and
`WINDFOR` forecasts, for January 2026 delivery.

**Live app:** https://gridbricks-eight.vercel.app

---

## The question the product answers

To decide how much thermal power to buy for tomorrow, the desk needs to know
how much wind will show up. They cannot wait and see: the GB day-ahead auction
closes the morning before delivery, so the decision is made on a forecast.

Two things follow, and they are the two screens:

1. **What did we know at the moment we had to commit?**
2. **How wrong is that usually, and by how much should we allow for it?**

## The rule the whole thing rests on

> A forecast may only inform a decision if it was published **before the gate
> closed** for that delivery day.

Nord Pool's N2EX day-ahead auction closes at **09:50 GMT** on the day before
delivery. `WINDFOR` publishes every two to four hours and each row carries its
`publishTime`, so for any delivery day there is exactly one vintage the desk
could have had — and a dozen better ones that arrived too late to trade on.

This is easy to get wrong and the failure is silent. Take the newest forecast
for each hour and the error statistics come out roughly **half** what the desk
actually faces, because some of those forecasts were published after the trade.
No exception is raised; the dashboard simply lies.

So every function that picks a forecast takes an explicit `as_of` and filters
on `publish_time <= as_of`. Nothing anywhere selects "the latest" without one,
and `backend/tests/test_domain.py` fails if that ever changes.

## What the analysis found

Scored across all 744 hours of January 2026 delivery, using only the
gate-closure vintage:

| | |
|---|---|
| Mean absolute error | **2,123 MW** (18.3% of mean output) |
| Bias (forecast − outturn) | **+1,840 MW** |
| Days the forecast ran high | **28 of 31** |
| P90 hourly shortfall | **+4,312 MW** |

**The error has a direction.** The forecast is optimistic almost everywhere. A
desk treating the published number as its central case systematically
under-procures.

**And the gap grows with the wind:**

| forecast level | mean error |
|---|---|
| 6–9 GW | +294 MW |
| 12–15 GW | +1,340 MW |
| 18–21 GW | **+3,529 MW** |

Correlation between forecast level and error: **+0.56**. One flat error
allowance is therefore wrong in both directions — too fat on calm days, far too
thin on windy ones. The app corrects each hour by the median error observed at
its own forecast level and shows a P10–P90 band around it. On 15 January the
raw forecast was 10.5% above outturn; the corrected figure landed within 0.6%.

**Waiting would not fix it.** Absolute error falls as delivery approaches, as a
weather forecast should — but the bias does not follow it down. An hour before
delivery the forecast still runs ~1.5 GW high. A weather model that close to the
event has very little weather left to get wrong.

The likely explanation is **curtailment**: `WINDFOR` describes the wind that is
*available*, while `FUELHH` reports what was *metered* after the grid turned
some of it down. That would also explain why the gap scales with wind level.
Confirming it needs curtailment volumes, which are outside this pilot's data —
so it is presented as the leading hypothesis, not a finding.

## Design decisions, and what they cost

**Hourly comparison, by averaging the outturn up.** The two datasets do not
share a resolution: outturn is half-hourly settlement periods, the forecast is
hourly. Interpolating the forecast down to half-hours would invent two numbers
where the forecaster published one, and would then score the invention. The
cost is that sub-hourly forecast behaviour is invisible here.

**One vintage per delivery day.** The decision screen uses a single forecast
publication for all 24 hours, because that is what the desk had. Picking the
best available forecast per hour would mix vintages and show a day nobody saw.

**An observed correction, not a model.** The adjustment is the median historical
error in that forecast's own level band. It is transparent and explainable to a
trading desk in one sentence. A regression or a quantile model would likely fit
better; it would also be much harder to defend in a risk meeting, and with one
month of data it would mostly fit noise.

**MAE against mean output, not MAPE.** MAPE divides by the outturn, so a single
near-calm hour produces a four-figure percentage and the headline becomes
meaningless. The cost is that the percentage is not comparable across periods
with very different mean wind.

**In-memory TTL cache, not a database.** Both datasets refresh far more slowly
than anyone clicks, and a month is five megabytes. A database would be
infrastructure to run with nothing to show for it at this scale. The cost is
that a cold serverless instance pays the first fetch.

**FastAPI + React, no state management library.** Two screens and three
endpoints do not need Redux; `useState` and a small async hook cover it.

## Known limitations

- **One month of history.** Every statistic here is January 2026. Wind
  behaviour is seasonal, and a level correction fitted on one winter month
  should not be trusted in June without refitting.
- **National aggregate only.** No regional breakdown, so nothing here reflects
  the grid constraints that probably cause the bias in the first place.
- **The curtailment hypothesis is unconfirmed.** It fits the evidence; it is not
  demonstrated. Elexon publishes bid-offer acceptance data that would settle it.
- **No demand side.** The brief scoped this to wind, so the app shows the wind
  shortfall rather than a procurement volume. The residual the desk actually
  buys is demand minus all renewables.
- **The level bands are coarse.** 3 GW buckets, and the topmost band holds few
  hours, so the UI only quotes bands with at least 20 observations behind them.
- **Gate closure is a fixed UTC clock.** Correct for January (GMT), but it would
  need to follow UK local time across a daylight-saving boundary. It is
  configurable rather than hard-coded for that reason.

## What I would do next

1. **Pull curtailment volumes** and test the hypothesis properly. If it holds,
   the correction becomes explainable rather than empirical.
2. **Refit over a full year**, with the level correction as a rolling window
   rather than a fixed month.
3. **Add demand and the other renewables** so the screen shows the residual to
   procure, not just the wind position.
4. **Quantile regression on level and lead time together**, once there is
   enough history for it to beat the band median.

---

## Running it

Needs Docker, or Python 3.12 and Node 20.

```bash
make data     # download the January 2026 window from Elexon into data/
make up       # docker compose up --build  ->  http://localhost:5173
```

The API is on `http://localhost:8000`, with OpenAPI docs at `/docs`.

Without Docker:

```bash
# terminal 1
cd backend && pip install -r requirements.txt
PYTHONPATH=. ELEXON_OFFLINE=1 DATA_DIR=../data uvicorn windsight.api:app --port 8000

# terminal 2
cd frontend && npm install && npm run dev
```

Tests:

```bash
make test     # 28 tests
```

## Configuration

Everything through the environment; there are no secrets, and the Elexon API
needs no key.

| Variable | Default | Purpose |
|---|---|---|
| `GATE_CLOSURE_HOUR` / `_MINUTE` | `9` / `50` | day-ahead gate closure on D-1, UTC |
| `ELEXON_OFFLINE` | unset | `1` reads `data/*.json` instead of calling Elexon |
| `DATA_DIR` | `./data` | where the fixtures live |
| `CACHE_TTL_SECONDS` | `3600` | how long an Elexon response is reused |
| `ELEXON_BASE` | Elexon BMRS v1 | API base URL |
| `VITE_API_BASE` | same origin | API origin for the built front end |

## Files and directories

```
backend/
  windsight/
    config.py       gate closure, evaluation window, cache and data settings
    domain.py       the analysis as pure functions: vintage selection,
                    resolution bridge, metrics, level bands, lead time
    elexon.py       BMRS client, TTL cache, offline fixtures
    api.py          FastAPI app: /api/decision/{day}, /api/accuracy, /api/lead-time
  tests/
    test_domain.py  19 tests; the first group guards against lookahead bias
    test_api.py     9 tests; sweeps all 31 days for gate-closure violations
  Dockerfile
frontend/
  src/
    App.jsx                 the two screens and the copy that explains them
    api.js                  the only place that knows where the API lives
    styles.css              palette slots, light and dark
    components/charts.jsx   the four charts
  Dockerfile
api/index.py        Vercel entry point; serves the same FastAPI app
scripts/fetch_data.py   downloads the Elexon window into data/
data/               fuelhh.json, windfor.json  (offline fixtures)
docker-compose.yml  one command for the whole stack
vercel.json         build and routing for the deployment
Makefile            data / up / test / build
```

## API

| Endpoint | Returns |
|---|---|
| `GET /api/decision/{YYYY-MM-DD}` | the gate-closure forecast for that delivery day, hour by hour, with the corrected case, the P10–P90 band and the outturn |
| `GET /api/accuracy?band_width_mw=3000` | month-wide metrics, error by forecast level, and a per-day table |
| `GET /api/lead-time` | MAE and bias against how far ahead the forecast was published |
| `GET /api/health` | gate closure in use, evaluation window, data source |

## AI tools

This was built with AI assistance (Claude), as the brief permits. It was used
for implementation, for the exploratory data analysis that surfaced the
level-dependent bias, and for drafting this README. The design decisions above,
the gate-closure rule, and the choice of what to measure are mine, and I can
walk through and modify any part of the code.
