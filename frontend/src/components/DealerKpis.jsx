import React from 'react'

// KPI summary cards, all derived client-side from the /dealer/customers list.
export default function DealerKpis({ rows }) {
  const n = rows.length
  const withScore = rows.filter((r) => r.reliability_score != null)
  const withHealth = rows.filter((r) => r.avg_health_score != null)

  const avg = (xs, key) =>
    xs.length ? xs.reduce((s, r) => s + r[key], 0) / xs.length : null

  const cards = [
    { label: 'Customers', value: n },
    {
      label: 'Renewal risk',
      value: rows.filter((r) => r.renewal_risk).length,
      tone: 'bad',
    },
    {
      label: 'Assets on rent',
      value: rows.reduce((s, r) => s + (r.n_assets || 0), 0),
    },
    {
      label: 'Avg reliability',
      value: withScore.length ? Math.round(avg(withScore, 'reliability_score')) : '—',
    },
    {
      label: 'Avg fleet health',
      value: withHealth.length
        ? avg(withHealth, 'avg_health_score').toFixed(1)
        : '—',
    },
    {
      label: 'Health declining',
      value: rows.filter((r) => r.trend_direction === 'down').length,
      tone: 'warn',
    },
  ]

  return (
    <div className="kpi-row">
      {cards.map((c) => (
        <div key={c.label} className={`kpi-card${c.tone ? ' ' + c.tone : ''}`}>
          <div className="kpi-value">{c.value}</div>
          <div className="kpi-label">{c.label}</div>
        </div>
      ))}
    </div>
  )
}
