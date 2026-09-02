import React, { useState } from 'react'

// Turn "max_lift_capacity" -> "Max lift capacity"
function prettify(name) {
  const s = name.replace(/[_-]+/g, ' ').trim()
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function healthClass(score) {
  if (score == null) return 'health na'
  if (score >= 75) return 'health good'
  if (score >= 40) return 'health warn'
  return 'health bad'
}

/**
 * @param asset         one record from /customer/{id}/assets (Shared Contract shape)
 * @param customFields  string[] of extra field names for this asset's Type,
 *                      taken from asset_type_config.json (custom_fields). The
 *                      component never hardcodes field names per type - it just
 *                      renders whatever list it is handed.
 */
export default function AssetCard({ asset, customFields = [] }) {
  const [hovered, setHovered] = useState(false)
  const [pinned, setPinned] = useState(false)
  const showReasons = (hovered || pinned) && asset.reasons?.length > 0

  const rec = asset.recommendation
  const df = asset.demand_forecast

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="eq-id">{asset.equipment_id}</div>
          <div className="eq-type">{asset.type}</div>
        </div>
        <div className={healthClass(asset.health_score)}>
          {asset.health_score == null ? 'n/a' : asset.health_score}
          <span className="health-cap">health</span>
        </div>
      </div>

      <div className="card-row muted">
        <span>{asset.customer_id ?? '—'}</span>
        <span>site {asset.site_id ?? '—'}</span>
      </div>

      {/* reallocation: clearly visible when there is a concrete target */}
      {rec && rec.to_site ? (
        <button
          className="move-btn"
          title={rec.reason}
          onClick={() => setPinned((p) => !p)}
        >
          → Move to {rec.to_site}
        </button>
      ) : asset.reallocatable ? (
        <span className="badge reallocatable">Reallocatable — no target yet</span>
      ) : null}

      {/* reasons: on hover, or click "Why?" to pin open */}
      {asset.reasons?.length > 0 && (
        <div
          className="reasons-wrap"
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
        >
          <button
            className="link-btn"
            onClick={() => setPinned((p) => !p)}
          >
            {showReasons ? 'Hide' : 'Why?'} ({asset.reasons.length})
          </button>
          {showReasons && (
            <ul className="reasons">
              {asset.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {df && (
        <div className="card-row tiny muted">
          demand: {df.type} most wanted at {df.site_id}
          {df.predicted_need_days != null && ` (~${df.predicted_need_days}d)`}
        </div>
      )}

      {/* type-specific fields, rendered dynamically from custom_fields */}
      {customFields.length > 0 && (
        <dl className="specs">
          <div className="specs-cap">
            {asset.type} fields <span className="muted">(asset_type_config.json)</span>
          </div>
          {customFields.map((f) => (
            <div className="spec-row" key={f}>
              <dt>{prettify(f)}</dt>
              <dd>{asset[f] != null ? String(asset[f]) : '—'}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}
