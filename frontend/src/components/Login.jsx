import React, { useState } from 'react'
import { api } from '../api.js'

// Email + password sign-in. On success api.login() has already stored the JWT
// and customer_id; we hand the customer_id up so App can show the dashboard.
export default function Login({ onLoggedIn, onShowSignup }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const { customer_id } = await api.login(email.trim(), password)
      onLoggedIn(customer_id)
    } catch (err) {
      // 401 -> backend sends "invalid credentials"
      setError(err.message || 'Sign in failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-panel">
      <div className="auth-card">
        <h1>Customer sign in</h1>
        <p className="muted tiny">
          Sign in to view your fleet, alerts and return reminders.
        </p>

        <form onSubmit={submit}>
          <label>
            Email
            <input
              type="email"
              value={email}
              required
              autoComplete="email"
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>

          <label>
            Password
            <input
              type="password"
              value={password}
              required
              autoComplete="current-password"
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>

          {error && <div className="banner error">{error}</div>}

          <button
            className="move-btn auth-submit"
            type="submit"
            disabled={busy}
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="tiny">
          Don&apos;t have a login yet?{' '}
          <button className="link-btn" type="button" onClick={onShowSignup}>
            Create one
          </button>
        </p>
      </div>
    </div>
  )
}
