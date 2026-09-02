import React, { useState } from 'react'
import { api, saveSession } from '../api.js'

// Sign-in / sign-up for the customer view. Signup links a login to a Customer
// ID the pipeline already knows; the backend rejects anything else.
export default function AuthPanel({ onAuthed }) {
  const [mode, setMode] = useState('login') // 'login' | 'signup'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [customerId, setCustomerId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const isSignup = mode === 'signup'

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      // signup just creates the account; log in straight after to get a token
      if (isSignup) {
        await api.signup({
          email: email.trim(),
          password,
          customer_id: customerId.trim(),
        })
      }
      const res = await api.login({ email: email.trim(), password })
      saveSession(res.access_token, res.customer_id)
      onAuthed({ customerId: res.customer_id, email: email.trim() })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-panel">
      <div className="auth-card">
        <h1>{isSignup ? 'Create your customer login' : 'Customer sign in'}</h1>
        <p className="muted tiny">
          {isSignup
            ? 'Links a new login to an existing Customer ID the rental pipeline already tracks.'
            : 'Sign in to view your fleet, alerts and return reminders.'}
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
              minLength={isSignup ? 8 : undefined}
              autoComplete={isSignup ? 'new-password' : 'current-password'}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>

          {isSignup && (
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
          )}

          {error && <div className="banner error">{error}</div>}

          <button
            className="move-btn auth-submit"
            type="submit"
            disabled={busy}
          >
            {busy ? 'Working…' : isSignup ? 'Sign up' : 'Sign in'}
          </button>
        </form>

        <p className="tiny">
          {isSignup
            ? 'Already have a login? '
            : "Don't have a login yet? "}
          <button
            className="link-btn"
            type="button"
            onClick={() => {
              setMode(isSignup ? 'login' : 'signup')
              setError(null)
            }}
          >
            {isSignup ? 'Sign in' : 'Sign up'}
          </button>
        </p>
      </div>
    </div>
  )
}
