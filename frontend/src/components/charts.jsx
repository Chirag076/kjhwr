import React from 'react';
import {
  Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, LineChart,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';

const GRID = 'var(--grid)';
const AXIS = 'var(--axis)';
const MUTED = 'var(--text-muted)';

const axis = { stroke: AXIS, tick: { fill: MUTED, fontSize: 11.5 }, tickLine: false };
const mw = (v) => `${Math.round(v).toLocaleString()}`;

/** One tooltip shape for every chart, so the reading habit transfers. */
function Tip({ active, payload, label, rows, head }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="tip">
      <div className="t-head">{head ? head(label, point) : label}</div>
      {rows(point).map(({ k, v }) => (
        <div className="t-row" key={k}>
          <span>{k}</span>
          <span>{v}</span>
        </div>
      ))}
    </div>
  );
}

export function Legend({ items }) {
  return (
    <p className="legend">
      {items.map(({ label, color, line }) => (
        <span key={label}>
          <i className={line ? 'swatch line' : 'swatch'} style={{ background: color }} />
          {label}
        </span>
      ))}
    </p>
  );
}

/* ------------------------------------------------------- the delivery day */

/**
 * The forecast the buyer held at gate closure, the band history says to allow
 * around it, and what actually turned up.
 *
 * The raw forecast is drawn in muted ink rather than a series colour on
 * purpose: it is the number being corrected, not the number to act on, and
 * giving it a hue of its own would put it on equal footing with the answer.
 */
export function DecisionChart({ hours }) {
  const data = hours.map((h) => ({
    ...h,
    hour: new Date(h.start_time).toISOString().slice(11, 16),
    // Recharts stacks an Area from a [low, high] tuple, which keeps the band
    // tied to the same y-scale as the lines instead of a second axis.
    range: h.low != null && h.high != null ? [h.low, h.high] : null,
  }));
  const hasActual = data.some((d) => d.actual != null);

  return (
    <>
      <Legend
        items={[
          { label: 'Expected wind, corrected', color: 'var(--series-1)', line: true },
          ...(hasActual ? [{ label: 'Metered outturn', color: 'var(--series-2)', line: true }] : []),
          { label: 'Published forecast', color: 'var(--text-muted)', line: true },
          { label: 'P10–P90 range', color: 'var(--band)' },
        ]}
      />
      <div className="chart">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 6, right: 12, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="hour" {...axis} interval={2} />
            {/* The comparison here is between the lines, not against zero, so the
                scale is padded around the data rather than anchored at 0 —
                otherwise half the plot is empty and the gap that matters is
                squeezed into a third of the height. */}
            <YAxis
              {...axis}
              width={56}
              tickFormatter={mw}
              domain={[
                (min) => Math.max(0, Math.floor((min * 0.92) / 1000) * 1000),
                (max) => Math.ceil((max * 1.04) / 1000) * 1000,
              ]}
            />
            <Tooltip
              cursor={{ stroke: AXIS }}
              content={
                <Tip
                  head={(l) => `${l} UTC`}
                  rows={(p) => [
                    { k: 'Corrected', v: `${mw(p.adjusted)} MW` },
                    { k: 'P10–P90', v: `${mw(p.low)} – ${mw(p.high)} MW` },
                    { k: 'Published forecast', v: `${mw(p.forecast)} MW` },
                    ...(p.actual != null
                      ? [
                          { k: 'Outturn', v: `${mw(p.actual)} MW` },
                          { k: 'Forecast error', v: `${p.error > 0 ? '+' : ''}${mw(p.error)} MW` },
                        ]
                      : []),
                  ]}
                />
              }
            />
            <Area
              dataKey="range"
              stroke="none"
              fill="var(--band)"
              isAnimationActive={false}
              activeDot={false}
            />
            <Line
              dataKey="forecast"
              stroke="var(--text-muted)"
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="adjusted"
              stroke="var(--series-1)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            {hasActual && (
              <Line
                dataKey="actual"
                stroke="var(--series-2)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

/* ------------------------------------------------- error against wind level */

/**
 * The finding the headline number hides: the forecast is optimistic almost
 * everywhere, and the optimism grows with how much wind is expected.
 *
 * One series, one colour. Bar length already encodes the magnitude, so
 * shading each bar by its own value would spend the colour channel on
 * information the chart has already shown.
 */
export function LevelChart({ bands }) {
  const data = bands
    .filter((b) => b.n >= 3)
    .map((b) => ({
      ...b,
      band: `${b.lower_mw / 1000}–${b.upper_mw / 1000}`,
    }));

  return (
    <div className="chart short">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 6, right: 12, bottom: 20, left: 4 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis
            dataKey="band"
            {...axis}
            label={{ value: 'Forecast wind (GW)', position: 'insideBottom', offset: -12, fill: MUTED, fontSize: 11.5 }}
          />
          <YAxis {...axis} width={56} tickFormatter={mw} />
          <ReferenceLine y={0} stroke={AXIS} />
          <Tooltip
            cursor={{ fill: 'var(--band)' }}
            content={
              <Tip
                head={(l) => `${l} GW forecast`}
                rows={(p) => [
                  { k: 'Mean error', v: `+${mw(p.mean_error)} MW` },
                  { k: 'Median', v: `+${mw(p.median_error)} MW` },
                  { k: 'P10–P90', v: `${mw(p.p10)} – ${mw(p.p90)} MW` },
                  { k: 'Hours', v: p.n },
                ]}
              />
            }
          />
          <Bar dataKey="mean_error" fill="var(--series-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ----------------------------------------------------- error distribution */

/**
 * Where the errors actually fall. Diverging because the sign carries meaning:
 * to the right the forecast promised wind that never arrived, which is the
 * expensive direction for a buyer.
 */
export function DistributionChart({ daily }) {
  const width = 500;
  const all = daily.flatMap((d) => [d.p10, d.p50, d.p90]);
  const lo = Math.floor(Math.min(...all) / width) * width;
  const hi = Math.ceil(Math.max(...all) / width) * width;

  const counts = new Map();
  for (let edge = lo; edge <= hi; edge += width) counts.set(edge, 0);
  daily.forEach((d) => {
    const edge = Math.floor(d.p50 / width) * width;
    counts.set(edge, (counts.get(edge) || 0) + 1);
  });

  const data = [...counts.entries()].map(([edge, n]) => ({
    edge,
    label: `${edge / 1000}`,
    n,
  }));

  return (
    <div className="chart short">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 6, right: 12, bottom: 20, left: 4 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis
            dataKey="label"
            {...axis}
            label={{ value: 'Median daily error (GW)', position: 'insideBottom', offset: -12, fill: MUTED, fontSize: 11.5 }}
          />
          <YAxis {...axis} width={36} allowDecimals={false} />
          <ReferenceLine x="0" stroke={AXIS} />
          <Tooltip
            cursor={{ fill: 'var(--band)' }}
            content={
              <Tip
                head={(l) => `${l} to ${Number(l) + width / 1000} GW error`}
                rows={(p) => [{ k: 'Delivery days', v: p.n }]}
              />
            }
          />
          <Bar dataKey="n" radius={[4, 4, 0, 0]} isAnimationActive={false}>
            {data.map((d) => (
              <Cell key={d.edge} fill={d.edge >= 0 ? 'var(--diverge-high)' : 'var(--diverge-low)'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------------------------------------- lead time */

/**
 * Both measures are in MW on one scale, so they share one axis. Two axes here
 * would invent a relationship between them that the data does not contain.
 *
 * The axis runs from the furthest-ahead forecast on the left to delivery on
 * the right, so left-to-right is time passing. Plotted the other way the lines
 * climb, and the chart appears to say error grows as delivery nears.
 */
export function LeadTimeChart({ buckets }) {
  const data = buckets
    .map((b) => ({ ...b, lead: `${b.lead_from_hours}` }))
    .slice()
    .reverse();
  return (
    <>
      <Legend
        items={[
          { label: 'Mean absolute error', color: 'var(--series-1)', line: true },
          { label: 'Bias (forecast − outturn)', color: 'var(--series-2)', line: true },
        ]}
      />
      <div className="chart short">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 6, right: 12, bottom: 20, left: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis
              dataKey="lead"
              {...axis}
              label={{ value: 'Hours before delivery  (delivery at right)', position: 'insideBottom', offset: -12, fill: MUTED, fontSize: 11.5 }}
            />
            <YAxis {...axis} width={56} tickFormatter={mw} domain={[0, 'auto']} />
            <Tooltip
              cursor={{ stroke: AXIS }}
              content={
                <Tip
                  head={(l, p) => `${l}–${p.lead_to_hours} hours ahead`}
                  rows={(p) => [
                    { k: 'MAE', v: `${mw(p.mae)} MW` },
                    { k: 'Bias', v: `+${mw(p.bias)} MW` },
                    { k: 'Hours', v: p.n.toLocaleString() },
                  ]}
                />
              }
            />
            <Line dataKey="mae" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
            <Line dataKey="bias" stroke="var(--series-2)" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}
