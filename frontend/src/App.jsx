import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import CustomerDashboard from './components/CustomerDashboard.jsx'
import DealerDashboard from './components/DealerDashboard.jsx'

export default function App() {
  const [view, setView] = useState('customer')
  const [assetTypes, setAssetTypes] = useState({})
  const [customers, setCustomers] = useState([])
  const [customerId, setCustomerId] = useState('CUST01')
  const [bootError, setBootError] = useState(null)

  useEffect(() => {
    Promise.all([api.assetTypes(), api.dealerCustomers()])
      .then(([types, custs]) => {
        setAssetTypes(types)
        setCustomers(custs)
        if (custs.length && !custs.some((c) => c.customer_id === customerId)) {
          setCustomerId(custs[0].customer_id)
        }
      })
      .catch((e) => setBootError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
        </nav>
      </header>

      <main className="content">
        {bootError && (
          <div className="banner error">{bootError}</div>
        )}

        {view === 'customer' ? (
          <CustomerDashboard
            customerId={customerId}
            setCustomerId={setCustomerId}
            customers={customers}
            assetTypes={assetTypes}
          />
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
