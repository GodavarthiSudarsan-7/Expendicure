import React from 'react';
import { anomaliesApi } from '../api';
import { useAsync } from '../hooks/useAsync';
import {
  Card, CardBody, Badge, EmptyState, ErrorState, Skeleton, StatCard, SectionHeader, KV,
} from '../components/ui';
import { money, ratioX, dateShort, titleCase } from '../lib/format';
import { anomalyMeta, severityTone } from '../lib/status';

function InsightBody({ a }) {
  const f = a; // fields are flattened onto the anomaly by the backend
  switch (a.type) {
    case 'category_spike':
      return (
        <div className="ic-compare">
          <div><div className="muted">This week</div><b>{money(f.recent_spending)}</b></div>
          <span className="muted">vs</span>
          <div><div className="muted">Typical weekly</div><b>{money(f.historical_weekly_average)}</b></div>
          <Badge tone="warn">{ratioX(f.ratio)}</Badge>
        </div>
      );
    case 'amount_outlier':
      return (
        <div className="ic-compare">
          <div><div className="muted">This transaction</div><b>{money(f.amount)}</b></div>
          <span className="muted">vs</span>
          <div><div className="muted">Your median</div><b>{money(f.historical_median)}</b></div>
          <Badge tone="warn">{ratioX(f.ratio)}</Badge>
        </div>
      );
    case 'budget_breach':
      return (
        <div className="col gap-2">
          <div className="ic-compare">
            <b>{money(f.spent)}</b><span className="muted">/</span><b>{money(f.budget)}</b>
            <Badge tone="bad">{money(f.over_by)} over</Badge>
          </div>
          <div className="progress bad"><span style={{ width: `${Math.min(100, parseFloat(f.ratio) * 100)}%` }} /></div>
        </div>
      );
    case 'duplicate_transaction':
      return (
        <div className="ic-compare">
          <b>{money(f.amount)}</b>
          <span className="muted">×{(f.transaction_ids || []).length} at {f.merchant}</span>
          <span className="muted">on {(f.dates || []).map(dateShort).join(' & ')}</span>
        </div>
      );
    case 'new_large_merchant':
      return (
        <div className="ic-compare">
          <b>{money(f.amount)}</b>
          <span className="muted">{f.merchant}</span>
          <span className="muted">threshold {money(f.large_threshold)}</span>
        </div>
      );
    default:
      return null;
  }
}

export default function Insights() {
  const { data, loading, error, reload } = useAsync(() => anomaliesApi.get(), []);
  const list = data?.anomalies || [];

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Financial signals</div>
          <h1>Insights</h1>
          <div className="sub">
            Deterministic findings from your own history — facts, not advice. Expendicure never invents a financial conclusion.
          </div>
        </div>
      </div>

      {error && <ErrorState message={error} onRetry={reload} />}

      {loading ? (
        <>
          <div className="grid grid-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="sk-card" />)}</div>
          <div className="grid grid-3 mt-6">{[0, 1, 2].map((i) => <Skeleton key={i} className="sk-card" />)}</div>
        </>
      ) : data ? (
        <>
          <div className="grid grid-4">
            <StatCard label="Signals" tone="brand" value={data.count} meta={`Last ${data.history_days} days`} />
            <StatCard label="High priority" tone={data.high_count ? 'bad' : 'ok'} value={data.high_count} />
            <StatCard label="Medium" tone={data.medium_count ? 'warn' : 'neutral'} value={data.medium_count} />
            <StatCard label="Low" tone="neutral" value={data.low_count} />
          </div>

          <div className="mt-6">
            <SectionHeader
              title={list.length ? `${list.length} thing${list.length === 1 ? '' : 's'} to look at` : 'Nothing to flag'}
              hint={`as of ${dateShort(data.as_of)}`}
            />
            {list.length ? (
              <div className="grid grid-2">
                {list.map((a, i) => (
                  <div key={i} className="insight-card">
                    <div className="ic-top">
                      <span className="ic-title">
                        {anomalyMeta[a.type]?.emoji} {anomalyMeta[a.type]?.title || titleCase(a.type)}
                      </span>
                      <Badge tone={severityTone(a.severity)}>{a.severity}</Badge>
                    </div>
                    <div className="ic-lead">{a.reason}</div>
                    <InsightBody a={a} />
                    {(a.period_start || a.date) && (
                      <div className="muted" style={{ fontSize: '0.76rem' }}>
                        {a.date ? dateShort(a.date) : `${dateShort(a.period_start)} – ${dateShort(a.period_end)}`}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <Card><CardBody>
                <EmptyState emoji="✅" title="You're all clear">
                  No unusual spending patterns detected in the last {data.history_days} days.
                </EmptyState>
              </CardBody></Card>
            )}
          </div>
        </>
      ) : null}
    </>
  );
}
