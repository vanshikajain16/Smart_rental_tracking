import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import ActivityFeed from './ActivityFeed.jsx'

const TIER_CLASS = { High: 'chip bad', Medium: 'chip warn', Low: 'chip good' }

function healthClass(h) {
  if (h == null) return 'na'
  if (h >= 80) return 'good'
  if (h >= 50) return 'warn'
  return 'bad'
}

// Per-customer drill-down: aggregate + current assets (reuses
// assets_for_customer server-side) + that customer's slice of the feed.
export default function CustomerDrilldown({ customerId, onBack }) {
  const [detail, setDetail] = useState(null)
  const [activity, setActivity] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      api.dealerCustomerDetail(customerId),
      api.dealerActivity({ customerId, limit: 500 }),
    ])
      .then(([d, a]) => {
        if (cancelled) return
        setDetail(d)
        setActivity(a)
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [customerId])

  return (
    <div className="drilldown">
      <button className="link-btn" onClick={onBack}>
        ← Back to all customers
      </button>

      {error && <div className="banner error">{error}</div>}
      {loading && <div className="banner">Loading…</div>}

      {detail && !loading && (
        <>
          <div className="dash-head">
            <h1>
              <span className="mono">{detail.customer_id}</span>{' '}
              <span className={TIER_CLASS[detail.risk_tier] ?? 'chip'}>
                {detail.risk_tier ?? '—'}
              </span>
              {detail.renewal_risk && (
                <span className="chip bad"> ⚠ renewal risk</span>
              )}
            </h1>
            <div className="summary tiny">{detail.phone_number ?? ''}</div>
          </div>

          <div className="stat-strip">
            <div>
              <span className="stat-n">{detail.reliability_score ?? '—'}</span>
              <span className="stat-l">Reliability</span>
            </div>
            <div>
              <span className="stat-n">{detail.n_assets}</span>
              <span className="stat-l">Assets on rent</span>
            </div>
            <div>
              <span className="stat-n">{detail.avg_health_score ?? '—'}</span>
              <span className="stat-l">Avg health (now)</span>
            </div>
            <div>
              <span className="stat-n">
                {detail.avg_health_all_cycles ?? '—'}
              </span>
              <span className="stat-l">Avg health (all cycles)</span>
            </div>
            <div>
              <span className={`stat-n trend ${detail.trend_direction ?? ''}`}>
                {detail.trend_direction ?? '—'}
                {detail.health_trend_slope_per_month != null &&
                  ` (${detail.health_trend_slope_per_month.toFixed(1)}/mo)`}
              </span>
              <span className="stat-l">Health trend</span>
            </div>
            <div>
              <span className="stat-n">{detail.n_cycles_observed ?? '—'}</span>
              <span className="stat-l">Cycles observed</span>
            </div>
          </div>

          <h2>
            Current fleet <span className="count">{detail.assets.length}</span>
          </h2>
          {detail.assets.length === 0 ? (
            <p className="muted">No assets currently out with this customer.</p>
          ) : (
            <table className="grid">
              <thead>
                <tr>
                  <th>Equipment</th>
                  <th>Type</th>
                  <th>Site</th>
                  <th>Health</th>
                  <th>Reallocatable</th>
                  <th>Reasons</th>
                </tr>
              </thead>
              <tbody>
                {detail.assets.map((a) => (
                  <tr key={a.equipment_id}>
                    <td className="mono">{a.equipment_id}</td>
                    <td>{a.type}</td>
                    <td>{a.site_id ?? '—'}</td>
                    <td>
                      <span className={`pill ${healthClass(a.health_score)}`}>
                        {a.health_score ?? '—'}
                      </span>
                    </td>
                    <td>{a.reallocatable ? 'yes' : '—'}</td>
                    <td className="tiny muted">
                      {a.reasons?.length ? a.reasons.join('; ') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <ActivityFeed events={activity} showCustomer={false} />
        </>
      )}
    </div>
  )
}
