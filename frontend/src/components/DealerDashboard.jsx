import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'

const COLUMNS = [
  { key: 'customer_id', label: 'Customer', type: 'str' },
  { key: 'reliability_score', label: 'Reliability', type: 'num' },
  { key: 'risk_tier', label: 'Risk tier', type: 'str' },
  { key: 'avg_health_score', label: 'Avg health', type: 'num' },
  { key: 'trend_direction', label: 'Health trend', type: 'str' },
  { key: 'n_assets', label: 'Assets', type: 'num' },
]

const TIER_CLASS = { High: 'chip bad', Medium: 'chip warn', Low: 'chip good' }
const TREND_MARK = { down: '▼', up: '▲', flat: '▬' }
const TREND_CLASS = { down: 'trend down', up: 'trend up', flat: 'trend flat' }

export default function DealerDashboard() {
  const [rows, setRows] = useState([])
  const [riskIds, setRiskIds] = useState(new Set())
  const [error, setError] = useState(null)
  const [sort, setSort] = useState({ key: 'reliability_score', dir: 'asc' })

  useEffect(() => {
    Promise.all([api.dealerCustomers(), api.dealerRenewalRisk()])
      .then(([custs, risk]) => {
        setRows(custs)
        setRiskIds(new Set(risk.map((r) => r.customer_id)))
      })
      .catch((e) => setError(e.message))
  }, [])

  const sorted = useMemo(() => {
    const col = COLUMNS.find((c) => c.key === sort.key)
    const factor = sort.dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const av = a[sort.key]
      const bv = b[sort.key]
      if (av == null) return 1
      if (bv == null) return -1
      if (col?.type === 'num') return (av - bv) * factor
      return String(av).localeCompare(String(bv)) * factor
    })
  }, [rows, sort])

  function toggleSort(key) {
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'asc' }
    )
  }

  if (error) return <div className="banner error">{error}</div>

  return (
    <div className="dashboard">
      <div className="dash-head">
        <h1>Dealer dashboard</h1>
        <div className="summary">
          {rows.length} customers ·{' '}
          <span className="chip bad">{riskIds.size} renewal risk</span>
        </div>
      </div>

      <table className="grid">
        <thead>
          <tr>
            {COLUMNS.map((c) => (
              <th
                key={c.key}
                onClick={() => toggleSort(c.key)}
                className={sort.key === c.key ? 'sorted' : ''}
              >
                {c.label}
                {sort.key === c.key && (sort.dir === 'asc' ? ' ▲' : ' ▼')}
              </th>
            ))}
            <th>Renewal</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const atRisk = r.renewal_risk || riskIds.has(r.customer_id)
            return (
              <tr key={r.customer_id} className={atRisk ? 'row-risk' : ''}>
                <td className="mono">{r.customer_id}</td>
                <td>{r.reliability_score ?? '—'}</td>
                <td>
                  <span className={TIER_CLASS[r.risk_tier] ?? 'chip'}>
                    {r.risk_tier ?? '—'}
                  </span>
                </td>
                <td>{r.avg_health_score ?? '—'}</td>
                <td>
                  <span className={TREND_CLASS[r.trend_direction] ?? 'trend'}>
                    {TREND_MARK[r.trend_direction] ?? ''}{' '}
                    {r.trend_direction ?? '—'}
                    {r.health_trend_slope_per_month != null &&
                      ` (${r.health_trend_slope_per_month.toFixed(1)}/mo)`}
                  </span>
                </td>
                <td>{r.n_assets}</td>
                <td>
                  {atRisk ? (
                    <span className="chip bad">⚠ renewal risk</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="tiny muted">Click a column header to sort.</p>
    </div>
  )
}
