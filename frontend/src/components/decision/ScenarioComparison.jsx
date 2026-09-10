import React from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid, Cell,
} from 'recharts';
import { money } from '../../lib/format';

/* WITHOUT PURCHASE vs IF YOU BUY — a comparison of the deterministic endpoints
   the engine returned (projected minimum + projected month-end). No series is
   computed in the browser; these are the scalar fields from `data`. */
export default function ScenarioComparison({ data }) {
  if (!data) return null;
  const buffer = parseFloat(data.safety_buffer);

  const rows = [
    {
      name: 'Without purchase',
      low: parseFloat(data.minimum_balance_before),
      monthEnd: parseFloat(data.month_end_balance_before),
    },
    {
      name: 'If you buy this',
      low: parseFloat(data.minimum_balance_after),
      monthEnd: parseFloat(data.month_end_balance_after),
    },
  ];

  return (
    <div>
      <div className="section-header" style={{ marginBottom: 8 }}>
        <div><h2 style={{ fontSize: '1rem' }}>Baseline vs this purchase</h2>
          <div className="hint">Projected low point and month-end balance, with and without the spend.</div>
        </div>
      </div>
      <div className="chart-box" style={{ height: 260 }}>
        <ResponsiveContainer>
          <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={6}>
            <CartesianGrid stroke="#eef1f6" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#475569' }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false}
              width={64} tickFormatter={(v) => money(v, { compact: true })} />
            <Tooltip formatter={(v, key) => [money(v), key === 'low' ? 'Projected low' : 'Month-end']} />
            <ReferenceLine y={buffer} stroke="#f59e0b" strokeDasharray="4 4"
              label={{ value: 'Safety buffer', position: 'insideTopRight', fontSize: 11, fill: '#b45309' }} />
            <Bar dataKey="low" name="Projected low" radius={[4, 4, 0, 0]}>
              {rows.map((r, i) => (
                <Cell key={i} fill={r.low < buffer ? '#ef4444' : '#6366f1'} />
              ))}
            </Bar>
            <Bar dataKey="monthEnd" name="Month-end" radius={[4, 4, 0, 0]} fill="#c7d2fe" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="legend-row">
        <span className="li"><span className="sw" style={{ background: '#6366f1' }} />Projected low point</span>
        <span className="li"><span className="sw" style={{ background: '#c7d2fe' }} />Month-end balance</span>
        <span className="li"><span className="sw" style={{ background: '#f59e0b' }} />Safety buffer</span>
      </div>
    </div>
  );
}
