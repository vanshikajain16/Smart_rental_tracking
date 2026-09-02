import React from 'react'

// KPI summary cards. Prefers the server-computed /dealer/summary payload;
// falls back to values derived from the /dealer/customers list.
export default function DealerKpis({ rows, summary }) {
  const declining = rows.filter((r) => r.trend_direction === 'down').length
  const renewalRisk = rows.filter((r) => r.renewal_risk).length

  let cards
  if (summary) {
    cards = [
      { label: 'Customers', value: summary.total_customers },
      { label: 'Assets on rent', value: summary.total_assets },
      {
        label: 'Avg fleet health',
        value: summary.avg_fleet_health_score ?? '—',
      },
      { label: 'High risk', value: summary.high_risk_count, tone: 'bad' },
      { label: 'Pending SMS', value: summary.pending_sms_count },
      {
        label: 'Unpaid penalties',
        value: summary.unpaid_penalty_count,
        tone: 'warn',
      },
      { label: 'Renewal risk', value: renewalRisk, tone: 'bad' },
      { label: 'Health declining', value: declining, tone: 'warn' },
    ]
  } else {
    const withScore = rows.filter((r) => r.reliability_score != null)
    const withHealth = rows.filter((r) => r.avg_health_score != null)
    const avg = (xs, key) =>
      xs.length ? xs.reduce((s, r) => s + r[key], 0) / xs.length : null
    cards = [
      { label: 'Customers', value: rows.length },
      { label: 'Renewal risk', value: renewalRisk, tone: 'bad' },
      {
        label: 'Assets on rent',
        value: rows.reduce((s, r) => s + (r.n_assets || 0), 0),
      },
      {
        label: 'Avg reliability',
        value: withScore.length
          ? Math.round(avg(withScore, 'reliability_score'))
          : '—',
      },
      {
        label: 'Avg fleet health',
        value: withHealth.length
          ? avg(withHealth, 'avg_health_score').toFixed(1)
          : '—',
      },
      { label: 'Health declining', value: declining, tone: 'warn' },
    ]
  }

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
