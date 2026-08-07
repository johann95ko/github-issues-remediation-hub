import React, { useEffect, useState } from 'react'
import LeadershipView from './views/LeadershipView.jsx'
import EngineeringView from './views/EngineeringView.jsx'

// Leadership is the default tab on purpose: the audience with the least time
// gets their answer with zero clicks (Hick's law — one decision, two tabs).
export default function App() {
  const [tab, setTab] = useState('leadership')
  const [overview, setOverview] = useState(null)

  useEffect(() => {
    let cancelled = false
    const load = () =>
      fetch('/api/overview')
        .then((r) => r.json())
        .then((data) => { if (!cancelled) setOverview(data) })
        .catch(() => {})
    load()
    const timer = setInterval(load, 15000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [])

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="feather">&#10047;</span>
          <h1>Remediation Hub</h1>
          <span className="sub">autonomous issue remediation, powered by Devin</span>
        </div>
        <nav className="tabs">
          <button className={tab === 'leadership' ? 'active' : ''} onClick={() => setTab('leadership')}>
            Executive Overview
          </button>
          <button className={tab === 'engineering' ? 'active' : ''} onClick={() => setTab('engineering')}>
            Engineering
          </button>
        </nav>
      </header>
      <main className="page">
        {overview?.demo_mode && (
          <div className="demo-banner">
            Demo mode — Devin sessions are simulated. Set DEVIN_API_KEY and DEMO_MODE=false for live operation.
          </div>
        )}
        {tab === 'leadership'
          ? <LeadershipView overview={overview} />
          : <EngineeringView />}
        <p className="footer-note">
          Data refreshes automatically every 15 seconds · All figures derived from the remediation audit log
        </p>
      </main>
    </>
  )
}
