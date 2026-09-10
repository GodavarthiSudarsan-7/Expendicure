import React, { useState } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
  ReferenceDot, CartesianGrid,
} from 'recharts';
import { forecastApi } from '../api';
import { useAsync } from '../hooks/useAsync';
import {
  Card, CardHead, CardBody, StatCard, Badge, PillTabs, Skeleton, ErrorState, EmptyState,
  SectionHeader, KV,
} from '../components/ui';
import { money, dateShort, dateTiny, titleCase } from '../lib/format';

const HORIZONS = [
  { value: 7, label: '7D' }, { value: 30, label: '30D' },
  { value: 60, label: '60D' }, { value: 90, label: '90D' },
];

export default function Forecast() {
  const [horizon, setHorizon] = useState(30);
  const { data: f, loading, error, reload } = useAsync(
    () => forecastApi.get({ horizonDays: horizon }), [horizon]
  );

  const series = (f?.projection || []).map((p) => ({ date: p.date, balance: parseFloat(p.balance) }));
  const eventByDate = {};
  (f?.events || []).forEach((e) => { eventByDate[e.date] = e; });

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Projected — not guaranteed</div>
          <h1>Where your balance is heading</h1>
          <div className="sub">Your current balance rolled forward through known recurring money movements. These are projections that update as your patterns change, not a promise.</div>
        </div>
        <div className="actions">
          <PillTabs options={HORIZONS} value={horizon} onChange={setHorizon} />
        </div>
      </div>

      {error && <ErrorState message={error} onRetry={reload} />}

      {loading ? (
        <><div className="grid grid-4"><Skeleton className="sk-card" /><Skeleton className="sk-card" /><Skeleton className="sk-card" /><Skeleton className="sk-card" /></div>
          <Skeleton className="sk-chart mt-6" /></>
      ) : f ? (
        <>
          <div className="grid grid-4">
            <StatCard label="Starting balance" tone="brand" value={money(f.starting_balance)}
              meta={`As of ${dateShort(f.as_of)}`} />
            <StatCard label="Projected low point"
              tone={f.safety_buffer_breached ? 'bad' : 'ok'}
              value={money(f.projected_min_balance)}
              meta={`On ${dateShort(f.projected_min_balance_date)}`} />
            <StatCard label="Projected end balance" tone="neutral" value={money(f.projected_end_balance)}
              meta={`Net ${money(f.projected_net)} over ${f.horizon_days}d`} />
            <StatCard label="Forecast confidence"
              tone={f.confidence === 'high' ? 'ok' : f.confidence === 'medium' ? 'warn' : 'neutral'}
              value={titleCase(f.confidence)}
              meta={`${(f.assumptions || []).filter((a) => a.source !== 'none').length} recurring assumptions`} />
          </div>

          {f.safety_buffer_breached && (
            <div className="alert alert-warn mt-6">
              <strong>Safety buffer reached on {dateShort(f.breach_date)}.</strong>
              &nbsp;Your projected balance dips below {money(f.safety_buffer)} within this horizon. Consider a what-if to see how a change helps.
            </div>
          )}

          <Card className="mt-6">
            <CardHead><h3>Projected balance</h3></CardHead>
            <CardBody>
              {series.length ? (
                <>
                  <div className="chart-box tall">
                    <ResponsiveContainer>
                      <AreaChart data={series} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
                        <defs>
                          <linearGradient id="fFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#6366f1" stopOpacity={0.26} />
                            <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid stroke="#eef1f6" vertical={false} />
                        <XAxis dataKey="date" tickFormatter={dateTiny} tick={{ fontSize: 11, fill: '#94a3b8' }}
                          axisLine={false} tickLine={false} minTickGap={30} />
                        <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false}
                          width={70} tickFormatter={(v) => money(v, { compact: true })} />
                        <Tooltip
                          formatter={(v) => money(v)}
                          labelFormatter={(d) => {
                            const ev = eventByDate[d];
                            return ev ? `${dateShort(d)} — ${ev.label} (${ev.direction} ${money(ev.amount)})` : dateShort(d);
                          }}
                        />
                        <ReferenceLine y={parseFloat(f.safety_buffer)} stroke="#f59e0b" strokeDasharray="5 4"
                          label={{ value: 'Safety buffer', position: 'insideTopLeft', fontSize: 11, fill: '#b45309' }} />
                        {f.breach_date && (
                          <ReferenceLine x={f.breach_date} stroke="#ef4444" strokeDasharray="3 3"
                            label={{ value: `Buffer reached ${dateTiny(f.breach_date)}`, position: 'top', fontSize: 11, fill: '#b91c1c' }} />
                        )}
                        <Area type="monotone" dataKey="balance" stroke="#6366f1" strokeWidth={2.5} fill="url(#fFill)" />
                        {(f.events || []).map((e, i) => {
                          const pt = series.find((s) => s.date === e.date);
                          if (!pt) return null;
                          return (
                            <ReferenceDot key={i} x={e.date} y={pt.balance} r={4}
                              fill={e.direction === 'credit' ? '#10b981' : '#6366f1'} stroke="#fff" strokeWidth={1.5} />
                          );
                        })}
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="legend-row">
                    <span className="li"><span className="sw" style={{ background: '#6366f1' }} />Projected balance</span>
                    <span className="li"><span className="sw" style={{ background: '#f59e0b' }} />Safety buffer</span>
                    <span className="li"><span className="sw" style={{ background: '#10b981', borderRadius: 99 }} />Recurring income</span>
                    <span className="li"><span className="sw" style={{ background: '#6366f1', borderRadius: 99 }} />Recurring expense</span>
                  </div>
                </>
              ) : (
                <EmptyState emoji="📈" title="Not enough signal yet">
                  Your forecast becomes more accurate as Expendicure learns your recurring patterns.
                </EmptyState>
              )}
            </CardBody>
          </Card>

          <div className="grid grid-2 mt-6">
            <Card>
              <CardHead><h3>Recurring assumptions</h3></CardHead>
              <CardBody>
                {(f.assumptions || []).filter((a) => a.source !== 'none').length ? (
                  <div className="timeline">
                    {f.assumptions.filter((a) => a.source !== 'none').map((a, i) => (
                      <div key={i} className="ti">
                        <div className="when">{dateTiny(a.next_date)}<small>{a.cadence}</small></div>
                        <div className="track" />
                        <div className="flex-1">
                          <div className="row between">
                            <strong>{a.label}</strong>
                            <span className={a.direction === 'credit' ? 'amount-pos' : 'amount-neg'}>
                              {a.direction === 'credit' ? '+' : '−'}{money(a.amount)}
                            </span>
                          </div>
                          <div className="row gap-2 mt-2">
                            <Badge tone={a.source === 'recurring' ? 'brand' : 'neutral'}>{a.source === 'recurring' ? 'You added this' : 'Detected'}</Badge>
                            <Badge tone={a.confidence === 'high' ? 'ok' : a.confidence === 'medium' ? 'warn' : 'neutral'}>{a.confidence} confidence</Badge>
                            <span className="muted" style={{ fontSize: '0.78rem' }}>{a.occurrences_in_horizon}× in horizon</span>
                          </div>
                          {a.note && <div className="muted mt-2" style={{ fontSize: '0.78rem' }}>{a.note}</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState emoji="🧭" title="No recurring patterns yet">
                    Add recurring commitments or record a few months of transactions — the forecast sharpens as patterns emerge.
                  </EmptyState>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHead><h3>Forecast summary</h3></CardHead>
              <CardBody>
                <KV k="Horizon" v={`${f.horizon_days} days`} />
                <KV k="Projected income" v={<span className="amount-pos">+{money(f.projected_income)}</span>} />
                <KV k="Projected expenses" v={<span className="amount-neg">−{money(f.projected_expenses)}</span>} />
                <KV k="Projected net" v={<strong className="tabular">{money(f.projected_net)}</strong>} />
                <KV k="Safety buffer" v={money(f.safety_buffer)} />
                <KV k="Buffer breach" v={f.safety_buffer_breached ? <Badge tone="bad">Yes · {dateShort(f.breach_date)}</Badge> : <Badge tone="ok">No</Badge>} />
              </CardBody>
            </Card>
          </div>
        </>
      ) : null}
    </>
  );
}
