import React from 'react'

function healthClass(score) {
  if (score == null) return 'pill na'
  if (score >= 75) return 'pill good'
  if (score >= 40) return 'pill warn'
  return 'pill bad'
}

export default function AlertsPanel({ alerts = [], smsReminders = [] }) {
  const nothing = alerts.length === 0 && smsReminders.length === 0

  return (
    <section className="alerts">
      <h2>
        Alerts{' '}
        <span className="count">
          {alerts.length + smsReminders.length}
        </span>
      </h2>

      {nothing && <p className="muted">No active alerts for this customer.</p>}

      {alerts.length > 0 && (
        <div className="alert-block">
          <h3>Flagged assets ({alerts.length})</h3>
          <ul className="alert-list">
            {alerts.map((a) => (
              <li key={a.equipment_id}>
                <span className={healthClass(a.health_score)}>
                  {a.health_score ?? 'n/a'}
                </span>
                <span className="al-id">{a.equipment_id}</span>
                <span className="al-type">{a.type}</span>
                <span className="al-reason">
                  {a.reasons?.[0] ?? 'flagged'}
                  {a.reasons?.length > 1 && ` +${a.reasons.length - 1} more`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {smsReminders.length > 0 && (
        <div className="alert-block">
          <h3>Pending SMS reminders ({smsReminders.length})</h3>
          <ul className="alert-list">
            {smsReminders.map((s, i) => (
              <li key={i}>
                <span
                  className={
                    s.lead_days >= 3 ? 'pill bad' : 'pill warn'
                  }
                >
                  {s.lead_days}-day
                </span>
                <span className="al-id">{s.equipment_id}</span>
                <span className="sms-msg">{s.message}</span>
              </li>
            ))}
          </ul>
          <p className="tiny muted">
            {smsReminders.some((s) => s.lead_days >= 3)
              ? 'High-risk customers are reminded 3 days ahead instead of 1.'
              : 'Reminders go out 1 day before the expected return date.'}
          </p>
        </div>
      )}
    </section>
  )
}
