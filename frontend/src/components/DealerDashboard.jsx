import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import DealerKpis from './DealerKpis.jsx'
import RiskBreakdown from './RiskBreakdown.jsx'
import ActivityFeed from './ActivityFeed.jsx'
import CustomerDrilldown from './CustomerDrilldown.jsx'

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
const TIER_FILTERS = ['all', 'High', 'Medium', 'Low']

export default function DealerDashboard() {
  const [rows, setRows] = useState([])
  const [riskIds, setRiskIds] = useState(new Set())
  const [activity, setActivity] = useState([])
  const [error, setError] = useState(null)
  const [sort, setSort] = useState({ key: 'reliability_score', dir: 'asc' })

  const [tier, setTier] = useState('all')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(null) // customer_id being drilled into

  useEffect(() => {
    Promise.all([
      api.dealerCustomers(),
      api.dealerRenewalRisk(),
      api.dealerActivity({ limit: 500 }),
    ])
      .then(([custs, risk, acts]) => {
        setRows(custs)
        setRiskIds(new Set(risk.map((r) => r.customer_id)))
        setActivity(acts)
      })
      .catch((e) => setError(e.message))
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return rows.filter((r) => {
      if (tier !== 'all' && r.risk_tier !== tier) return false
      if (!q) return true
      return (
        r.customer_id.toLowerCase().includes(q) ||
        (r.phone_number || '').toLowerCase().includes(q)
      )
    })
  }, [rows, tier, query])

  const sorted = useMemo(() => {
    const col = COLUMNS.find((c) => c.key === sort.key)
    const factor = sort.dir === 'asc' ? 1 : -1
    return [...filtered].sort((a, b) => {
      const av = a[sort.key]
      const bv = b[sort.key]
      if (av == null) return 1
      if (bv == null) return -1
      if (col?.type === 'num') return (av - bv) * factor
      return String(av).localeCompare(String(bv)) * factor
    })
  }, [filtered, sort])

  function toggleSort(key) {
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'asc' }
    )
  }

  if (error) return <div className="banner error">{error}</div>

  if (selected) {
    return (
      <div className="dashboard">
        <CustomerDrilldown
          customerId={selected}
          onBack={() => setSelected(null)}
        />
      </div>
    )
  }

  return (
    <div className="dashboard">
      <div className="dash-head">
        <h1>Dealer dashboard</h1>
        <div className="summary">
          {filtered.length === rows.length
            ? `${rows.length} customers`
            : `${filtered.length} of ${rows.length} customers`}{' '}
          · <span className="chip bad">{riskIds.size} renewal risk</span>
        </div>
      </div>

      <DealerKpis rows={rows} />

      <RiskBreakdown rows={rows} activeTier={tier} onPick={setTier} />

      <div className="table-controls">
        <div className="seg">
          {TIER_FILTERS.map((t) => (
            <button
              key={t}
              className={`seg-btn${tier === t ? ' active' : ''}`}
              onClick={() => setTier(t)}
            >
              {t === 'all' ? 'All tiers' : t}
            </button>
          ))}
        </div>
        <input
          className="search"
          type="search"
          placeholder="Search customer or phone…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
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
              <tr
                key={r.customer_id}
                className={`row-click${atRisk ? ' row-risk' : ''}`}
                onClick={() => setSelected(r.customer_id)}
                title="View customer detail"
              >
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
          {sorted.length === 0 && (
            <tr>
              <td colSpan={COLUMNS.length + 1} className="muted">
                No customers match this filter.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <p className="tiny muted">
        Click a column header to sort · click a row to drill in.
      </p>

      <ActivityFeed events={activity} onPickCustomer={setSelected} />
    </div>
  )
}
