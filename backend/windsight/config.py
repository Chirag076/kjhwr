"""Settings. Everything that a trader or an operator might argue about lives here."""
from __future__ import annotations

import datetime as dt
import os

UTC = dt.timezone.utc

#: Gate closure for the GB day-ahead auction, on the day before delivery.
#:
#: Nord Pool's N2EX day-ahead auction closes at 09:50 GMT and publishes results
#: by 10:00 GMT. That is the moment this product is built around: a forecast
#: published at 09:51 on D-1 did not exist when the buyer committed, so it must
#: never reach a decision or an error statistic.
#:
#: January is GMT, so there is no daylight-saving ambiguity in the evaluated
#: period. Outside winter this would need to follow UK local time rather than a
#: fixed UTC clock, which is why it is configurable rather than hard-coded.
GATE_CLOSURE = dt.time(
    hour=int(os.getenv("GATE_CLOSURE_HOUR", "9")),
    minute=int(os.getenv("GATE_CLOSURE_MINUTE", "50")),
)

#: The month the brief asks about: decisions made for January 2026 delivery.
EVALUATION_START = dt.date(2026, 1, 1)
EVALUATION_END = dt.date(2026, 1, 31)

ELEXON_BASE = os.getenv("ELEXON_BASE", "https://data.elexon.co.uk/bmrs/api/v1")

#: Seconds to keep an Elexon response. The datasets are published every 30
#: minutes (actuals) and every 2-4 hours (forecasts), so an hour of staleness
#: costs nothing and keeps a serverless deployment from hammering the API.
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

#: Where to read fixtures when ELEXON_OFFLINE is set. Used by the tests and by
#: anyone without network access to the Elexon API.
DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data"))
OFFLINE = os.getenv("ELEXON_OFFLINE", "").lower() in {"1", "true", "yes"}


def gate_closure_for(delivery_day: dt.date) -> dt.datetime:
    """The instant the buyer loses the ability to change their position for `delivery_day`."""
    return dt.datetime.combine(delivery_day - dt.timedelta(days=1), GATE_CLOSURE, tzinfo=UTC)
