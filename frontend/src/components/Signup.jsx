import React, { useState } from 'react'
import { api } from '../api.js'

// Create a login linked to an existing Customer ID. Two-step by design: on
// success we just tell the user to sign in - no auto-login.
export default function Signup({ onShowLogin, initialEmail = '' }) {
  const [email, setEmail] = useState(initialEmail)
  const [password, setPassword] = useState('')
  const [customerId, setCustomerId] = useState('')
  const [error, setError] = useState(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await api.signup(email.trim(), password, customerId.trim())
      setDone(true)
    } catch (err) {
      // show the backend's validation message directly
      // (e.g. "customer_id '...' is not a known customer ...")
      setError(err.message || 'Sign up failed')
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <div className="auth-panel">
        <div className="auth-card">
          <h1>Account created</h1>
          <p className="muted">
            Your login is linked to customer{' '}
            <strong className="mono">{customerId.trim()}</strong>. Please sign
            in to continue.
          </p>
          <button className="move-btn auth-submit" onClick={onShowLogin}>
            Go to sign in
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="auth-panel">
      <div className="auth-card">
        <h1>Create a customer login</h1>
        <p className="muted tiny">
          Links a login to a Customer ID the rental pipeline already tracks.
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
              minLength={8}
              autoComplete="new-password"
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>

          <label>
            Customer ID
            <input
              type="text"
              value={customerId}
              required
              placeholder="e.g. CUST01"
              onChange={(e) => setCustomerId(e.target.value)}
            />
          </label>

          {error && <div className="banner error">{error}</div>}

          <button
            className="move-btn auth-submit"
            type="submit"
            disabled={busy}
          >
            {busy ? 'Creating…' : 'Sign up'}
          </button>
        </form>

        <p className="tiny">
          Already have a login?{' '}
          <button className="link-btn" type="button" onClick={onShowLogin}>
            Sign in
          </button>
        </p>
      </div>
    </div>
  )
}
