import React, { useEffect, useState } from 'react';
import { getAccuracy, getDecision, getLeadTime } from './api.js';
import { DecisionChart, DistributionChart, LeadTimeChart, LevelChart } from './components/charts.jsx';

const DAYS = Array.from({ length: 31 }, (_, i) => `2026-01-${String(i + 1).padStart(2, '0')}`);
const mw = (v) => Math.round(v).toLocaleString();
const gwh = (v) => (v / 1000).toFixed(1);

function Tile({ label, value, unit, note, tone }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value">
        {value}
        {unit && <span className="unit">{unit}</span>}
      </div>
      {note && <div className={`note${tone ? ` ${tone}` : ''}`}>{note}</div>}
    </div>
  );
}

function useAsync(fn, deps) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  useEffect(() => {
    let live = true;
    setState({ loading: true, data: null, error: null });
    fn()
      .then((data) => live && setState({ loading: false, data, error: null }))
      .catch((e) => live && setState({ loading: false, data: null, error: e.message }));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

function State({ loading, error }) {
  if (loading) return <div className="state">Loading…</div>;
  return <div className="state error">{error}</div>;
}

/* ------------------------------------------------------------- decision */

function DecisionView() {
  const [day, setDay] = useState('2026-01-15');
  const { loading, data, error } = useAsync(() => getDecision(day), [day]);

  return (
    <>
      <div className="controls">
        <label htmlFor="day">Delivery day</label>
        <select id="day" value={day} onChange={(e) => setDay(e.target.value)}>
          {DAYS.map((d) => (
            <option key={d} value={d}>
              {new Date(`${d}T00:00:00Z`).toLocaleDateString('en-GB', {
                weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC',
              })}
            </option>
          ))}
        </select>
      </div>

      {loading || error ? (
        <State loading={loading} error={error} />
      ) : (
        <>
          <div className="tiles">
            <Tile
              label="Wind to plan for"
              value={gwh(data.totals.adjusted_mwh)}
              unit="GWh"
              note="corrected central case"
            />
            <Tile
              label="Forecast said"
              value={gwh(data.totals.forecast_mwh)}
              unit="GWh"
              note={`${mw(data.totals.forecast_mwh - data.totals.adjusted_mwh)} MWh above the corrected case`}
            />
            {data.totals.actual_mwh > 0 && (
              <Tile
                label="Actually delivered"
                value={gwh(data.totals.actual_mwh)}
                unit="GWh"
                note={
                  Math.abs(data.totals.adjusted_mwh - data.totals.actual_mwh) <
                  Math.abs(data.totals.forecast_mwh - data.totals.actual_mwh)
                    ? 'correction was closer than the raw forecast'
                    : 'raw forecast was closer on this day'
                }
                tone={
                  Math.abs(data.totals.adjusted_mwh - data.totals.actual_mwh) <
                  Math.abs(data.totals.forecast_mwh - data.totals.actual_mwh)
                    ? 'good'
                    : undefined
                }
              />
            )}
            <Tile
              label="Lead time"
              value={data.lead_time_hours}
              unit="h"
              note="to the first hour of delivery"
            />
          </div>

          <div className="card">
            <h2>What you could see when the auction closed</h2>
            <p className="sub">
              Gate closure {new Date(data.gate_closure).toUTCString().slice(0, 22)} UTC. The newest
              forecast published by then went out at{' '}
              {new Date(data.forecast_published).toUTCString().slice(0, 22)} UTC. Nothing published
              after that moment is used here, however much better it turned out to be.
            </p>
            <DecisionChart hours={data.hours} />
            <div className="callout">
              The published forecast is drawn faint because it is the number being corrected, not the
              number to act on. The solid line removes the bias this forecast carries at this wind
              level; the shaded band is the range it landed in on 8 days out of 10.
            </div>
          </div>
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------- accuracy */

function AccuracyView() {
  const acc = useAsync(getAccuracy, []);
  const lead = useAsync(getLeadTime, []);

  if (acc.loading || acc.error) return <State loading={acc.loading} error={acc.error} />;
  const { overall, by_level, daily } = acc.data;
  // The highest band with enough hours behind it to be worth quoting. The
  // topmost band can hold a handful of hours, and a headline built on six
  // observations is the kind of thing a reviewer pulls on first.
  const solid = by_level.filter((b) => b.n >= 20);
  const worst = solid[solid.length - 1];
  const highDays = daily.filter((d) => d.bias > 0).length;

  return (
    <>
      <div className="tiles">
        <Tile
          label="Mean absolute error"
          value={mw(overall.mae)}
          unit="MW"
          note={`${overall.mae_pct_of_mean}% of mean output`}
        />
        <Tile
          label="Bias"
          value={`+${mw(overall.bias)}`}
          unit="MW"
          note="forecast runs high"
          tone="bad"
        />
        <Tile
          label="Days forecast ran high"
          value={`${highDays} of ${daily.length}`}
          note="January 2026 delivery days"
        />
        <Tile
          label="Worst case in 10"
          value={`+${mw(overall.p90)}`}
          unit="MW"
          note="P90 hourly shortfall against forecast"
        />
      </div>

      <div className="card">
        <h2>The error is not noise, it has a direction</h2>
        <p className="sub">
          Across {overall.n.toLocaleString()} hours of January 2026 delivery, scored only against the
          forecast available at gate closure, wind came in below forecast on {highDays} of{' '}
          {daily.length} days. A buyer who treats the published number as the central case
          systematically under-procures.
        </p>
        <LevelChart bands={by_level} />
        <div className="callout">
          And the gap widens with the wind. At {worst.lower_mw / 1000}–{worst.upper_mw / 1000} GW the
          forecast is <strong>{mw(worst.mean_error)} MW</strong> too high on average, against a few
          hundred MW in the mid range. One flat error allowance is therefore wrong in both
          directions: too fat on calm days, far too thin on windy ones.
        </div>
      </div>

      <div className="card">
        <h2>Waiting does not fix it</h2>
        <p className="sub">
          Absolute error falls steadily as delivery approaches, which is what a weather forecast
          should do. The bias does not follow it down: an hour before delivery the forecast is
          still around 1.5 GW high. A weather model that close to the event has very little weather
          left to get wrong, so something other than forecast skill is holding that gap open.
        </p>
        {lead.loading || lead.error ? (
          <State loading={lead.loading} error={lead.error} />
        ) : (
          <LeadTimeChart buckets={lead.data.buckets} />
        )}
        <div className="callout">
          The likely explanation is curtailment: the forecast describes the wind that is{' '}
          <strong>available</strong>, while the outturn is what was <strong>metered</strong> after
          the grid turned some of it down. That would also explain why the gap grows with wind
          level. Confirming it needs curtailment volumes, which are outside this pilot's data.
        </div>
      </div>

      <div className="card">
        <h2>Spread across the month</h2>
        <p className="sub">
          Each delivery day's median hourly error. To the right of zero the forecast promised wind
          that never arrived.
        </p>
        <DistributionChart daily={daily} />
      </div>

      <div className="card">
        <h2>Day by day</h2>
        <p className="sub">Every delivery day, scored on the vintage available at its own gate closure.</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Delivery day</th>
                <th>Hours</th>
                <th>MAE (MW)</th>
                <th>RMSE (MW)</th>
                <th>Bias (MW)</th>
                <th>Mean outturn (MW)</th>
                <th>MAE %</th>
              </tr>
            </thead>
            <tbody>
              {daily.map((d) => (
                <tr key={d.day}>
                  <td>{new Date(`${d.day}T00:00:00Z`).toLocaleDateString('en-GB', {
                    weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' })}</td>
                  <td>{d.n}</td>
                  <td>{mw(d.mae)}</td>
                  <td>{mw(d.rmse)}</td>
                  <td>{d.bias > 0 ? '+' : ''}{mw(d.bias)}</td>
                  <td>{mw(d.mean_actual)}</td>
                  <td>{d.mae_pct_of_mean}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ shell */

export default function App() {
  const [tab, setTab] = useState('decision');
  return (
    <div className="wrap">
      <header className="top">
        <div>
          <h1>Day-ahead wind position</h1>
          <p>
            What the wind forecast said when the auction closed, how far wrong it has been, and how
            much to allow for that when buying the balance.
          </p>
        </div>
        <nav>
          <button
            type="button"
            onClick={() => setTab('decision')}
            aria-current={tab === 'decision' ? 'page' : undefined}
          >
            Delivery day
          </button>
          <button
            type="button"
            onClick={() => setTab('accuracy')}
            aria-current={tab === 'accuracy' ? 'page' : undefined}
          >
            Forecast accuracy
          </button>
        </nav>
      </header>

      {tab === 'decision' ? <DecisionView /> : <AccuracyView />}

      <footer className="foot">
        National wind, Elexon BMRS: FUELHH metered outturn (fuelType WIND) and WINDFOR forecasts.
        Every figure is scored against the forecast published before the 09:50 GMT day-ahead gate
        closure on the day before delivery.
      </footer>
    </div>
  );
}
