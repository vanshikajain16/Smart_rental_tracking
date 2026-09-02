import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

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

function initials(name) {
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean)
  return (parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? parts[0]?.[1] ?? '')
}

const MAX_CONTACTS = 4
const ROLES = ['operator', 'site lead', 'site contact']
const EMPTY_FORM = {
  name: '',
  phone: '',
  role: 'operator',
  notify_due_date: true,
  notify_health: true,
  notify_demand: false, // account-level info — off by default (see spec)
}

/**
 * @param asset          one record from /customer/{id}/assets (Shared Contract shape)
 * @param customFields   string[] of extra field names for this asset's Type
 * @param manageContacts when true, render the "Connected" section (customer view
 *                       only — the dealer drill-down reuses this card without it,
 *                       so it never hits the auth-only contacts endpoints).
 */
export default function AssetCard({ asset, customFields = [], manageContacts = false }) {
  const [hovered, setHovered] = useState(false)
  const [pinned, setPinned] = useState(false)
  const showReasons = (hovered || pinned) && asset.reasons?.length > 0

  const rec = asset.recommendation
  const df = asset.demand_forecast

  // --- connected contacts ------------------------------------------------ //
  const [contacts, setContacts] = useState([])
  const [contactsError, setContactsError] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [busy, setBusy] = useState(false)

  const customerId = asset.customer_id
  const equipmentId = asset.equipment_id
  const canManage = manageContacts && customerId && equipmentId

  useEffect(() => {
    if (!canManage) return
    let cancelled = false
    api
      .assetContacts(customerId, equipmentId)
      .then((list) => !cancelled && setContacts(list))
      .catch((e) => !cancelled && setContactsError(e.message))
    return () => {
      cancelled = true
    }
  }, [canManage, customerId, equipmentId])

  async function submitContact(e) {
    e.preventDefault()
    setBusy(true)
    setContactsError(null)
    try {
      const list = await api.addAssetContact(customerId, equipmentId, {
        ...form,
        name: form.name.trim(),
        phone: form.phone.trim(),
      })
      setContacts(list)
      setForm(EMPTY_FORM)
      setShowForm(false)
    } catch (err) {
      setContactsError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function removeContact(contactId) {
    setContactsError(null)
    try {
      const list = await api.removeAssetContact(
        customerId,
        equipmentId,
        contactId
      )
      setContacts(list)
    } catch (err) {
      setContactsError(err.message)
    }
  }

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
          <button className="link-btn" onClick={() => setPinned((p) => !p)}>
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

      {/* connected operators — customer view only */}
      {canManage && (
        <div className="connected">
          <div className="connected-cap">Connected — notified on this asset</div>
          <div className="connected-row">
            {contacts.map((c) => (
              <span className="contact-chip" key={c.contact_id}>
                <span className="contact-initials">{initials(c.name)}</span>
                <span className="contact-name">{c.name}</span>
                <span className="contact-role">{c.role}</span>
                <button
                  type="button"
                  className="contact-x"
                  title="Remove from this asset"
                  onClick={() => removeContact(c.contact_id)}
                >
                  ×
                </button>
              </span>
            ))}
            {contacts.length < MAX_CONTACTS && !showForm && (
              <button
                type="button"
                className="contact-chip add"
                onClick={() => setShowForm(true)}
              >
                + Add contact
              </button>
            )}
          </div>

          {contactsError && (
            <div className="tiny contact-err">{contactsError}</div>
          )}

          {showForm && (
            <form className="contact-form" onSubmit={submitContact}>
              <input
                placeholder="Name"
                value={form.name}
                required
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
              <input
                placeholder="Phone"
                value={form.phone}
                required
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
              />
              <select
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>

              <label className="toggle">
                <input
                  type="checkbox"
                  checked={form.notify_due_date}
                  onChange={(e) =>
                    setForm({ ...form, notify_due_date: e.target.checked })
                  }
                />
                Due-date reminders
              </label>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={form.notify_health}
                  onChange={(e) =>
                    setForm({ ...form, notify_health: e.target.checked })
                  }
                />
                Health &amp; idle alerts
              </label>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={form.notify_demand}
                  onChange={(e) =>
                    setForm({ ...form, notify_demand: e.target.checked })
                  }
                />
                Demand &amp; reallocation insights
                <span className="toggle-cap">Account-level — off by default</span>
              </label>

              <div className="contact-form-actions">
                <button className="move-btn" type="submit" disabled={busy}>
                  {busy ? 'Adding…' : 'Add'}
                </button>
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => {
                    setShowForm(false)
                    setForm(EMPTY_FORM)
                    setContactsError(null)
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
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
