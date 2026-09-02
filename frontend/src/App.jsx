import React, { useEffect, useState } from 'react'
import {
  api,
  getToken,
  getStoredCustomerId,
  clearSession,
  setUnauthorizedHandler,
} from './api.js'
import AuthPanel from './components/AuthPanel.jsx'
import CustomerDashboard from './components/CustomerDashboard.jsx'
import DealerDashboard from './components/DealerDashboard.jsx'

export default function App() {
  const [view, setView] = useState('customer')
  const [assetTypes, setAssetTypes] = useState({})
  const [session, setSession] = useState(() =>
    getToken() ? { customerId: getStoredCustomerId() } : null
  )
  const [bootError, setBootError] = useState(null)

  // A rejected token (expired etc.) drops us back to the login form.
  useEffect(() => {
    setUnauthorizedHandler(() => setSession(null))
  }, [])

  useEffect(() => {
    api.assetTypes().then(setAssetTypes).catch((e) => setBootError(e.message))
  }, [])

  // A stored token is trusted on load; if it's stale the first authenticated
  // customer call returns 401 and the api-layer handler drops us to the login.

  function signOut() {
    clearSession()
    setSession(null)
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">▤</span> Smart Rental Tracking
        </div>
        <nav className="tabs">
          <button
            className={view === 'customer' ? 'tab active' : 'tab'}
            onClick={() => setView('customer')}
          >
            Customer view
          </button>
          <button
            className={view === 'dealer' ? 'tab active' : 'tab'}
            onClick={() => setView('dealer')}
          >
            Dealer view
          </button>
          {session && (
            <span className="session-tag">
              {session.customerId}
              <button className="link-btn" onClick={signOut}>
                Sign out
              </button>
            </span>
          )}
        </nav>
      </header>

      <main className="content">
        {bootError && <div className="banner error">{bootError}</div>}

        {view === 'customer' ? (
          session ? (
            <CustomerDashboard
              customerId={session.customerId}
              assetTypes={assetTypes}
            />
          ) : (
            <AuthPanel
              onAuthed={({ customerId, email }) =>
                setSession({ customerId, email })
              }
            />
          )
        ) : (
          <DealerDashboard />
        )}
      </main>

      <footer className="foot">
        Data served live from the Stage 1-5 pipeline outputs via the FastAPI
        backend.
      </footer>
    </div>
  )
}
