import React, { useMemo, useState } from 'react'

const TYPE = {
  high_risk: { label: 'High risk', cls: 'bad' },
  flag: { label: 'Flag', cls: 'warn' },
  penalty: { label: 'Penalty', cls: 'bad' },
  sms_reminder: { label: 'Reminder', cls: 'accent' },
}
const PAGE = 40

// Retroactive activity feed: a sorted-by-date reconstruction, not a live log.
// `events` is already newest-first from the API: { date, type, customer_id, message }.
export default function ActivityFeed({
  events,
  showCustomer = true,
  onPickCustomer,
}) {
  const [type, setType] = useState('all')
  const [limit, setLimit] = useState(PAGE)

  const filtered = useMemo(
    () => (type === 'all' ? events : events.filter((e) => e.type === type)),
    [events, type]
  )
  const shown = filtered.slice(0, limit)

  const types = ['all', ...Object.keys(TYPE).filter((k) =>
    events.some((e) => e.type === k)
  )]

  return (
    <section className="activity-feed">
      <div className="af-head">
        <h3>Activity feed</h3>
        <div className="af-filters">
          {types.map((k) => (
            <button
              key={k}
              className={`af-chip${type === k ? ' active' : ''}`}
              onClick={() => {
                setType(k)
                setLimit(PAGE)
              }}
            >
              {k === 'all' ? 'All' : TYPE[k].label}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="muted tiny">No activity on record.</p>
      ) : (
        <>
          <ul className="af-list">
            {shown.map((e, i) => (
              <li key={`${e.date}-${e.type}-${e.customer_id}-${i}`}>
                <span className="af-date mono">{e.date}</span>
                <span className={`chip ${TYPE[e.type]?.cls ?? ''}`}>
                  {TYPE[e.type]?.label ?? e.type}
                </span>
                {showCustomer && (
                  <button
                    className="link-btn mono af-cust"
                    onClick={() => onPickCustomer?.(e.customer_id)}
                  >
                    {e.customer_id}
                  </button>
                )}
                <span className="af-summary">{e.message}</span>
              </li>
            ))}
          </ul>
          {limit < filtered.length && (
            <button
              className="link-btn"
              onClick={() => setLimit((n) => n + PAGE)}
            >
              Show more ({filtered.length - limit} more)
            </button>
          )}
        </>
      )}
    </section>
  )
}
