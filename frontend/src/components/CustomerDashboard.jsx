import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import AssetCard from './AssetCard.jsx'
import AlertsPanel from './AlertsPanel.jsx'

export default function CustomerDashboard({ customerId, assetTypes }) {
  const [assets, setAssets] = useState([])
  const [alerts, setAlerts] = useState([])
  const [sms, setSms] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!customerId) return
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      api.customerAssets(customerId),
      api.customerAlerts(customerId),
      api.customerSmsReminders(customerId),
    ])
      .then(([a, al, s]) => {
        if (cancelled) return
        setAssets(a)
        setAlerts(al)
        setSms(s)
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [customerId])

  return (
    <div className="dashboard">
      <div className="dash-head">
        <h1>Customer dashboard</h1>
        <span className="picker">
          Signed in as&nbsp;<strong className="mono">{customerId}</strong>
        </span>
      </div>

      {error && <div className="banner error">{error}</div>}
      {loading && <div className="banner">Loading…</div>}

      {!loading && !error && (
        <>
          <AlertsPanel alerts={alerts} smsReminders={sms} />

          <section>
            <h2>
              Fleet <span className="count">{assets.length}</span>
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
          </section>
        </>
      )}
    </div>
  )
}
