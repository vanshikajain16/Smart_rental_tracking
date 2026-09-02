import React, { useEffect, useState } from 'react'
import { api, getToken, getCustomerId, logout, setUnauthorizedHandler } from './api.js'
import Login from './components/Login.jsx'
import Signup from './components/Signup.jsx'
import CustomerDashboard from './components/CustomerDashboard.jsx'
import DealerDashboard from './components/DealerDashboard.jsx'

export default function App() {
  const [view, setView] = useState('customer')
  const [assetTypes, setAssetTypes] = useState({})
  const [bootError, setBootError] = useState(null)

  // customer-side auth
  const [token, setToken] = useState(() => getToken())
  const [customerId, setCustomerId] = useState(() => getCustomerId())
  const [authScreen, setAuthScreen] = useState('login') // 'login' | 'signup'
  const [signupEmail, setSignupEmail] = useState('') // pre-fill from Login
  const isAuthed = Boolean(token)

  function showSignup(prefillEmail = '') {
    setSignupEmail(prefillEmail)
    setAuthScreen('signup')
  }

  useEffect(() => {
    api.assetTypes().then(setAssetTypes).catch((e) => setBootError(e.message))
  }, [])

  // A rejected/expired token (from any authenticated call) drops us to Login.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null)
      setCustomerId(null)
      setAuthScreen('login')
    })
  }, [])

  function handleLoggedIn(id) {
    setToken(getToken()) // api.login already wrote it to localStorage
    setCustomerId(id)
    setAuthScreen('login')
  }

  function handleLogout() {
    logout()
    setToken(null)
    setCustomerId(null)
    setAuthScreen('login')
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
          {view === 'customer' && isAuthed && (
            <span className="session-tag">
              {customerId}
              <button className="link-btn" onClick={handleLogout}>
                Log out
              </button>
            </span>
          )}
        </nav>
      </header>

      <main className="content">
        {bootError && <div className="banner error">{bootError}</div>}

        {view === 'dealer' ? (
          <DealerDashboard />
        ) : isAuthed ? (
          <CustomerDashboard customerId={customerId} assetTypes={assetTypes} />
        ) : authScreen === 'signup' ? (
          <Signup
            initialEmail={signupEmail}
            onShowLogin={() => setAuthScreen('login')}
          />
        ) : (
          <Login onLoggedIn={handleLoggedIn} onShowSignup={showSignup} />
        )}
      </main>

      <footer className="foot">
        Data served live from the Stage 1-5 pipeline outputs via the FastAPI
        backend.
      </footer>
    </div>
  )
}
