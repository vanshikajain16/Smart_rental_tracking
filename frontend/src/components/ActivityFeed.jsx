import React, { useMemo, useState } from 'react'

const CAT = {
  flag: { label: 'Flag', cls: 'bad' },
  penalty: { label: 'Penalty', cls: 'warn' },
  sms_reminder: { label: 'Reminder', cls: 'accent' },
}
const PAGE = 40

// Retroactive activity feed: a sorted-by-date reconstruction, not a live log.
// `events` is already newest-first from the API.
export default function ActivityFeed({
  events,
  showCustomer = true,
  onPickCustomer,
}) {
  const [cat, setCat] = useState('all')
  const [limit, setLimit] = useState(PAGE)

  const filtered = useMemo(
    () => (cat === 'all' ? events : events.filter((e) => e.category === cat)),
    [events, cat]
  )
  const shown = filtered.slice(0, limit)

  const cats = ['all', ...Object.keys(CAT).filter((k) =>
    events.some((e) => e.category === k)
  )]

  return (
    <section className="activity-feed">
      <div className="af-head">
        <h3>Activity feed</h3>
        <div className="af-filters">
          {cats.map((k) => (
            <button
              key={k}
              className={`af-chip${cat === k ? ' active' : ''}`}
              onClick={() => {
                setCat(k)
                setLimit(PAGE)
              }}
            >
              {k === 'all' ? 'All' : CAT[k].label}
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
              <li key={`${e.date}-${e.equipment_id}-${e.category}-${i}`}>
                <span className="af-date mono">{e.date}</span>
                <span className={`chip ${CAT[e.category]?.cls ?? ''}`}>
                  {CAT[e.category]?.label ?? e.category}
                </span>
                {showCustomer && (
                  <button
                    className="link-btn mono af-cust"
                    onClick={() => onPickCustomer?.(e.customer_id)}
                  >
                    {e.customer_id}
                  </button>
                )}
                <span className="af-summary">{e.summary}</span>
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
