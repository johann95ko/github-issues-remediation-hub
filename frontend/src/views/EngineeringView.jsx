import React, { useEffect, useState } from 'react'

const ts = (t) => (t ? new Date(t * 1000).toLocaleString() : '—')

// The technical audit surface: connected repos + full per-remediation trail
// (session link, raw Devin status, root cause, tests, PR). Expandable rows
// keep the table scannable while preserving depth on demand.
export default function EngineeringView() {
  const [repos, setRepos] = useState([])
  const [rows, setRows] = useState([])
  const [open, setOpen] = useState(null)

  useEffect(() => {
    fetch('/api/repos').then((r) => r.json()).then(setRepos).catch(() => {})
    const load = () => fetch('/api/remediations').then((r) => r.json()).then(setRows).catch(() => {})
    load()
    const timer = setInterval(load, 15000)
    return () => clearInterval(timer)
  }, [])

  return (
    <>
      <h2 className="section-title">Connected repositories</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Repository</th><th>Trigger labels</th><th>Merge policy</th>
              <th>ACU cap / session</th><th>Baseline hrs / issue</th>
            </tr>
          </thead>
          <tbody>
            {repos.map((r) => (
              <tr key={r.full_name}>
                <td><a href={`https://github.com/${r.full_name}`} target="_blank" rel="noreferrer">{r.full_name}</a></td>
                <td>{r.trigger_labels.join(', ')}</td>
                <td>
                  <span className={`badge ${r.merge_policy === 'auto_merge' ? 'ok' : 'awaiting_review'}`}>
                    {r.merge_policy === 'auto_merge' ? 'auto-merge on green CI' : 'human review required'}
                  </span>
                </td>
                <td>{r.max_acu_per_session}</td>
                <td>{r.baseline_engineer_hours_per_issue}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="empty" style={{ marginTop: 10 }}>
          To connect another repository, add an entry to <code>config/repos.yaml</code> and point its
          GitHub webhook at <code>/webhooks/github</code>. No code changes required.
        </p>
      </div>

      <h2 className="section-title">Remediation audit trail</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Issue</th><th>State</th><th>Outcome</th><th>PR</th><th>ACUs</th><th>Started</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <React.Fragment key={r.id}>
                <tr className="expandable" onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <td>
                    <a href={r.issue_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                      {r.repo}#{r.issue_number}
                    </a>{' '}
                    {r.issue_title}
                  </td>
                  <td><span className={`badge ${r.state}`}>{r.state.replace('_', ' ')}</span></td>
                  <td>{r.outcome || '—'}</td>
                  <td>
                    {r.pr_url
                      ? <a href={r.pr_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{r.pr_state || 'view'}</a>
                      : '—'}
                  </td>
                  <td>{r.acus_consumed}</td>
                  <td>{ts(r.created_at)}</td>
                </tr>
                {open === r.id && (
                  <tr className="detail-row">
                    <td colSpan={6}>
                      <dl className="detail-grid">
                        <dt>Devin session</dt>
                        <dd>{r.session_url ? <a href={r.session_url} target="_blank" rel="noreferrer">{r.session_id}</a> : '—'}</dd>
                        <dt>Raw status</dt>
                        <dd>{r.devin_status}{r.devin_status_detail ? ` / ${r.devin_status_detail}` : ''}</dd>
                        <dt>Root cause</dt>
                        <dd>{r.root_cause || 'Not reported yet'}</dd>
                        <dt>Tests run</dt>
                        <dd>{r.tests_run || 'Not reported yet'}</dd>
                        <dt>Confidence</dt>
                        <dd>{r.confidence || '—'}</dd>
                        <dt>Merge policy</dt>
                        <dd>{r.merge_policy}</dd>
                        <dt>Completed</dt>
                        <dd>{ts(r.completed_at)}</dd>
                      </dl>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={6} className="empty">No remediations yet. Label an issue in a monitored repo (or run the simulator) to begin.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}
