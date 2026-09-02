import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import AssetCard from './AssetCard.jsx'
import ActivityFeed from './ActivityFeed.jsx'

const TIER_CLASS = { High: 'chip bad', Medium: 'chip warn', Low: 'chip good' }

// Per-customer drill-down opened from a dealer table row. Shows the customer's
// aggregate, their assets (GET /dealer/customer/{id}/assets, rendered with the
// same AssetCard grid CustomerDashboard uses), and their slice of the activity
// feed. `onBack` returns to the table with its sort/filter/search intact.
export default function CustomerDrilldown({ customerId, assetTypes = {}, onBack }) {
  const [detail, setDetail] = useState(null)
  const [assets, setAssets] = useState([])
  const [activity, setActivity] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      api.dealerCustomerDetail(customerId),
      api.dealerCustomerAssets(customerId),
      api.dealerActivityFeed(),
    ])
      .then(([d, as, a]) => {
        if (cancelled) return
        setDetail(d)
        setAssets(as)
        setActivity(a.filter((e) => e.customer_id === customerId))
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
            Current fleet <span className="count">{assets.length}</span>
          </h2>
          {assets.length === 0 ? (
            <p className="muted">No assets currently out with this customer.</p>
          ) : (
            <div className="card-grid">
              {assets.map((a) => (
                <AssetCard
                  key={a.equipment_id}
                  asset={a}
                  customFields={assetTypes[a.type]?.custom_fields ?? []}
                />
              ))}
            </div>
          )}

          <ActivityFeed
            events={activity}
            heading="Activity"
            subtitle="This customer's events, most recent first."
          />
        </>
      )}
    </div>
  )
}
