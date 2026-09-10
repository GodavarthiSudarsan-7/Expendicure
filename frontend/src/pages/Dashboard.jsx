import React from 'react';
import { Link } from 'react-router-dom';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid,
} from 'recharts';
import { twinApi, forecastApi, anomaliesApi, transactionsApi } from '../api';
import { useAsync } from '../hooks/useAsync';
import { useAuth } from '../context/AuthContext';
import {
  Card, CardHead, CardBody, StatCard, Badge, Button, EmptyState, ErrorState,
  Skeleton, SectionHeader, SkeletonCards,
} from '../components/ui';
import { money, signedMoney, dateTiny, dateShort, greeting, titleCase } from '../lib/format';
import { deriveHealthStatus, anomalyMeta, severityTone } from '../lib/status';

export default function Dashboard() {
  const { user } = useAuth();
  const twin = useAsync(() => twinApi.state(), []);
  const forecast = useAsync(() => forecastApi.get({ horizonDays: 30 }), []);
  const anomalies = useAsync(() => anomaliesApi.get(), []);
  const txns = useAsync(() => transactionsApi.list(), []);

  const t = twin.data;
  const f = forecast.data;
  const health = deriveHealthStatus(t, f);
  const nextCommitment = (t?.recurring || [])
    .filter((r) => r.direction === 'debit' && r.active)
    .sort((a, b) => (a.next_date > b.next_date ? 1 : -1))[0];

  const chartData = (f?.projection || []).map((p) => ({ date: p.date, balance: parseFloat(p.balance) }));
  const topInsights = (anomalies.data?.anomalies || [])
    .slice()
    .sort((a, b) => ({ high: 0, medium: 1, low: 2 }[a.severity] - { high: 0, medium: 1, low: 2 }[b.severity]))
    .slice(0, 3);

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">{greeting()}, {user?.name?.split(' ')[0] || 'there'}</div>
          <h1>How financially safe am I right now?</h1>
          <div className="sub">Every figure below comes straight from Expendicure's deterministic financial engine.</div>
        </div>
      </div>

      <div className="hero-band mb-6">
        <div>
          <div className="hb-title">Don't just ask if you can afford it. Ask what it will cost your future.</div>
          <div className="hb-sub">Expendicure simulates the financial consequence of a spending decision before you make it.</div>
        </div>
        <div className="hb-actions">
          <Link to="/before-you-spend" className="btn btn-primary btn-lg">Simulate a purchase</Link>
          <Link to="/ask" className="btn btn-secondary btn-lg">Ask Herman</Link>
        </div>
      </div>

      {twin.error && <ErrorState message={twin.error} onRetry={twin.reload} />}

      {twin.loading ? (
        <SkeletonCards count={3} />
      ) : t ? (
        <div className="grid grid-3">
          <StatCard
            label="Available balance" tone="brand"
            value={money(t.current_balance)}
            meta={<>Opening {money(t.opening_balance)} · net {signedMoney(Math.abs(parseFloat(t.month_net)), parseFloat(t.month_net) >= 0 ? 'credit' : 'debit')} this month</>}
          />
          <StatCard
            label="Safe to spend"
            tone={parseFloat(t.discretionary_buffer) > 0 ? 'ok' : 'warn'}
            value={money(t.discretionary_buffer)}
            meta={<>After {money(t.committed_upcoming)} committed & {money(t.safety_buffer)} safety buffer</>}
          />
          <StatCard
            label="Projected month-end"
            tone={health.tone}
            value={forecast.loading ? '…' : money(f?.projected_end_balance)}
            meta={forecast.loading ? 'Forecasting…' : (
              f?.safety_buffer_breached
                ? <>Buffer reached {dateShort(f.breach_date)}</>
                : <>Low point {money(f?.projected_min_balance)} · confidence {f?.confidence}</>
            )}
          />
        </div>
      ) : null}

      <div className="grid grid-2 mt-6" style={{ gridTemplateColumns: '1.6fr 1fr' }}>
        <Card>
          <CardHead right={<Link to="/forecast" className="btn btn-sm btn-ghost">Open forecast →</Link>}>
            <h3>Projected balance · next 30 days</h3>
          </CardHead>
          <CardBody>
            {forecast.loading ? (
              <Skeleton className="sk-chart" />
            ) : forecast.error ? (
              <ErrorState message={forecast.error} onRetry={forecast.reload} />
            ) : chartData.length ? (
              <>
                <div className="chart-box">
                  <ResponsiveContainer>
                    <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id="balFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="#6366f1" stopOpacity={0.28} />
                          <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="#eef1f6" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={dateTiny} tick={{ fontSize: 11, fill: '#94a3b8' }}
                        axisLine={false} tickLine={false} minTickGap={28} />
                      <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false}
                        width={64} tickFormatter={(v) => money(v, { compact: true })} />
                      <Tooltip formatter={(v) => money(v)} labelFormatter={dateShort} />
                      <ReferenceLine y={parseFloat(f.safety_buffer)} stroke="#f59e0b" strokeDasharray="4 4"
                        label={{ value: 'Safety buffer', position: 'insideTopLeft', fontSize: 11, fill: '#b45309' }} />
                      {f.safety_buffer_breached && f.breach_date && (
                        <ReferenceLine x={f.breach_date} stroke="#ef4444" strokeDasharray="3 3" />
                      )}
                      <Area type="monotone" dataKey="balance" stroke="#6366f1" strokeWidth={2.5} fill="url(#balFill)" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
                <div className="legend-row">
                  <span className="li"><span className="sw" style={{ background: '#6366f1' }} />Projected balance</span>
                  <span className="li"><span className="sw" style={{ background: '#f59e0b' }} />Safety buffer</span>
                  {f.safety_buffer_breached && <span className="li"><span className="sw" style={{ background: '#ef4444' }} />Buffer breach</span>}
                  <span className="li muted">Confidence: {f.confidence}</span>
                </div>
              </>
            ) : (
              <EmptyState emoji="📈" title="Your forecast is still learning">
                It becomes more accurate as Expendicure learns your recurring patterns.
              </EmptyState>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHead><h3>Financial health</h3></CardHead>
          <CardBody>
            {twin.loading ? <Skeleton style={{ height: 160 }} /> : (
              <div className="center">
                <div className={`badge badge-${health.tone}`} style={{ fontSize: '0.9rem', padding: '6px 14px' }}>
                  {health.label}
                </div>
                <p className="soft mt-4">{health.note}</p>
                <div className="kv mt-4" style={{ textAlign: 'left' }}>
                  <span className="k">Current balance</span><span className="v tabular">{money(t?.current_balance)}</span>
                </div>
                <div className="kv" style={{ textAlign: 'left' }}>
                  <span className="k">Safety buffer</span><span className="v tabular">{money(t?.safety_buffer)}</span>
                </div>
                <div className="kv" style={{ textAlign: 'left' }}>
                  <span className="k">Discretionary buffer</span><span className="v tabular">{money(t?.discretionary_buffer)}</span>
                </div>
                <p className="muted mt-4" style={{ fontSize: '0.76rem' }}>
                  Status is a visual mapping of deterministic backend fields — not an AI score.
                </p>
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      <div className="mt-6">
        <SectionHeader title="Signals that need attention"
          hint={anomalies.data ? `${anomalies.data.count} detected` : ''}
          action={<Link to="/insights" className="btn btn-sm btn-ghost">All insights →</Link>} />
        {anomalies.loading ? (
          <div className="grid grid-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="sk-card" />)}</div>
        ) : topInsights.length ? (
          <div className="grid grid-3">
            {topInsights.map((a, i) => (
              <div key={i} className="insight-card">
                <div className="ic-top">
                  <span className="ic-title">{anomalyMeta[a.type]?.emoji} {anomalyMeta[a.type]?.title || titleCase(a.type)}</span>
                  <Badge tone={severityTone(a.severity)}>{a.severity}</Badge>
                </div>
                <div className="ic-lead">{a.reason}</div>
                <Link to="/insights" className="btn btn-sm btn-secondary" style={{ alignSelf: 'flex-start' }}>View details</Link>
              </div>
            ))}
          </div>
        ) : (
          <Card><CardBody>
            <EmptyState emoji="✅" title="You're all clear">No unusual spending patterns detected.</EmptyState>
          </CardBody></Card>
        )}
      </div>

      <div className="mt-6">
        <Card>
          <CardHead right={<Link to="/transactions" className="btn btn-sm btn-ghost">View all →</Link>}>
            <h3>Recent transactions</h3>
          </CardHead>
          <CardBody className="card-body" style={{ padding: 0 }}>
            {txns.loading ? (
              <div style={{ padding: 20 }}><Skeleton className="sk-line" /><Skeleton className="sk-line" /><Skeleton className="sk-line" /></div>
            ) : (txns.data || []).length ? (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th style={{ textAlign: 'right' }}>Amount</th></tr></thead>
                  <tbody>
                    {(txns.data || []).slice(0, 6).map((tx) => (
                      <tr key={tx.id}>
                        <td className="nowrap">{dateShort(tx.payment_date)}</td>
                        <td>{tx.merchant_name}</td>
                        <td><Badge tone="neutral">{tx.category_name}</Badge></td>
                        <td style={{ textAlign: 'right' }} className={tx.direction === 'credit' ? 'amount-pos' : 'amount-neg'}>
                          {signedMoney(tx.amount, tx.direction)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState emoji="🧾" title="No spending history yet"
                action={<Link to="/transactions/add" className="btn btn-primary">Add your first transaction</Link>}>
                Add your first transaction and Expendicure will start building your Financial Digital Twin.
              </EmptyState>
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}
