import React from 'react'

// Dealer-wide activity feed - read-only, chronological (newest first from the
// API). Deliberately a plain timeline, not the pill/card look AlertsPanel uses
// for customer-specific alerts.
const TYPE_META = {
  high_risk: { icon: '⚠', cls: 'af-high-risk', label: 'High risk' },
  flag: { icon: '⚑', cls: 'af-flag', label: 'Flag' },
  penalty: { icon: '$', cls: 'af-penalty', label: 'Penalty' },
  sms_reminder: { icon: '✉', cls: 'af-sms', label: 'Reminder' },
}

export default function ActivityFeed({
  events = [],
  heading = 'Dealer activity',
  subtitle = 'Dealer-wide, most recent first — reconstructed from pipeline history.',
}) {
  return (
    <section className="activity-feed">
      <h3>
        {heading} <span className="count">{events.length}</span>
      </h3>
      <p className="tiny muted">{subtitle}</p>

      {events.length === 0 ? (
        <p className="muted tiny">No activity on record.</p>
      ) : (
        <ol className="af-timeline">
          {events.map((e, i) => {
            const m = TYPE_META[e.type] ?? { icon: '•', cls: '', label: e.type }
            return (
              <li
                key={`${e.date}-${e.type}-${e.customer_id}-${i}`}
                className={m.cls}
              >
                <span className="af-dot" aria-hidden="true">
                  {m.icon}
                </span>
                <time className="af-date">{e.date}</time>
                <span className="af-type">{m.label}</span>
                <span className="af-msg">{e.message}</span>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}
