import React from 'react'

const TIERS = [
  { key: 'High', cls: 'bad' },
  { key: 'Medium', cls: 'warn' },
  { key: 'Low', cls: 'good' },
]

// Horizontal bar chart of customers per risk tier. Clicking a bar drives the
// table's tier filter (activeTier / onPick come from DealerDashboard).
export default function RiskBreakdown({ rows, activeTier, onPick }) {
  const counts = TIERS.map((t) => ({
    ...t,
    n: rows.filter((r) => r.risk_tier === t.key).length,
  }))
  const unknown = rows.filter(
    (r) => !TIERS.some((t) => t.key === r.risk_tier)
  ).length
  const max = Math.max(1, ...counts.map((c) => c.n), unknown)

  return (
    <section className="risk-breakdown">
      <h3>Risk tier breakdown</h3>
      <div className="rb-bars">
        {counts.map((c) => (
          <button
            key={c.key}
            className={`rb-bar${activeTier === c.key ? ' active' : ''}`}
            onClick={() => onPick(activeTier === c.key ? 'all' : c.key)}
            title={`Filter to ${c.key} risk`}
          >
            <span className="rb-name">{c.key}</span>
            <span className="rb-track">
              <span
                className={`rb-fill ${c.cls}`}
                style={{ width: `${(c.n / max) * 100}%` }}
              />
            </span>
            <span className="rb-count">{c.n}</span>
          </button>
        ))}
        {unknown > 0 && (
          <div className="rb-bar" aria-disabled="true">
            <span className="rb-name muted">Unrated</span>
            <span className="rb-track">
              <span
                className="rb-fill"
                style={{ width: `${(unknown / max) * 100}%` }}
              />
            </span>
            <span className="rb-count">{unknown}</span>
          </div>
        )}
      </div>
    </section>
  )
}
