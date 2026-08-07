import React, { useCallback, useEffect, useState } from 'react'

const ts = (t) => (t ? new Date(t * 1000).toLocaleString() : '—')

const EMPTY_FORM = {
  full_name: '',
  trigger_labels: 'devin-fix',
  merge_policy: 'review',
  max_acu_per_session: 15,
  baseline_engineer_hours_per_issue: 4,
  enabled: true,
}

// The technical operations surface: repository connections are managed here
// (not in config files) so onboarding a repo never requires a redeploy, and
// the audit trail leads with problem→fix so reviewers triage without clicking.
export default function EngineeringView() {
  const [repos, setRepos] = useState([])
  const [rows, setRows] = useState([])
  const [findings, setFindings] = useState([])
  const [scans, setScans] = useState([])
  const [scanError, setScanError] = useState('')
  const [open, setOpen] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [editingId, setEditingId] = useState(null)
  const [formError, setFormError] = useState('')

  const loadAll = useCallback(() => {
    fetch('/api/repos').then((r) => r.json()).then(setRepos).catch(() => {})
    fetch('/api/remediations').then((r) => r.json()).then(setRows).catch(() => {})
    fetch('/api/discovered-issues').then((r) => r.json()).then(setFindings).catch(() => {})
    fetch('/api/scans').then((r) => r.json()).then(setScans).catch(() => {})
  }, [])

  useEffect(() => {
    loadAll()
    const timer = setInterval(loadAll, 15000)
    return () => clearInterval(timer)
  }, [loadAll])

  const submitRepo = async (e) => {
    e.preventDefault()
    setFormError('')
    const body = {
      ...form,
      trigger_labels: form.trigger_labels.split(',').map((s) => s.trim()).filter(Boolean),
      max_acu_per_session: Number(form.max_acu_per_session),
      baseline_engineer_hours_per_issue: Number(form.baseline_engineer_hours_per_issue),
    }
    const res = await fetch(editingId ? `/api/repos/${editingId}` : '/api/repos', {
      method: editingId ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}))
      setFormError(typeof detail.detail === 'string' ? detail.detail : 'Check the repository name (owner/name) and values.')
      return
    }
    setShowForm(false)
    setForm(EMPTY_FORM)
    setEditingId(null)
    loadAll()
  }

  const editRepo = (r) => {
    setForm({
      full_name: r.full_name,
      trigger_labels: r.trigger_labels.join(', '),
      merge_policy: r.merge_policy,
      max_acu_per_session: r.max_acu_per_session,
      baseline_engineer_hours_per_issue: r.baseline_engineer_hours_per_issue,
      enabled: r.enabled,
    })
    setEditingId(r.id)
    setShowForm(true)
    setFormError('')
  }

  const removeRepo = async (r) => {
    if (!window.confirm(`Disconnect ${r.full_name}? Historical remediations are kept.`)) return
    await fetch(`/api/repos/${r.id}`, { method: 'DELETE' })
    loadAll()
  }

  const startScan = async (r) => {
    setScanError('')
    const res = await fetch(`/api/repos/${r.id}/scan`, { method: 'POST' })
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}))
      setScanError(typeof detail.detail === 'string' ? detail.detail : 'Could not start the scan.')
    }
    loadAll()
  }

  const reviewFinding = async (finding, action) => {
    const res = await fetch(`/api/discovered-issues/${finding.id}/${action}`, { method: 'POST' })
    if (res.ok && action === 'approve') {
      // Approval opens a prefilled GitHub issue form — the human stays the
      // author of record for anything the agent proposed.
      window.open(finding.file_url, '_blank', 'noreferrer')
    }
    loadAll()
  }

  const proposed = findings.filter((f) => f.status === 'proposed')
  const reviewed = findings.filter((f) => f.status !== 'proposed')

  return (
    <>
      <div className="section-head">
        <h2 className="section-title">Connected repositories</h2>
        <button className="btn primary" onClick={() => { setShowForm(!showForm); setEditingId(null); setForm(EMPTY_FORM); setFormError('') }}>
          {showForm && !editingId ? 'Cancel' : '+ Connect repository'}
        </button>
      </div>

      {showForm && (
        <form className="card form-card" onSubmit={submitRepo}>
          <div className="form-grid">
            <label>
              Repository (owner/name)
              <input required value={form.full_name} placeholder="apache/superset"
                onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
            </label>
            <label>
              Trigger labels (comma separated)
              <input value={form.trigger_labels}
                onChange={(e) => setForm({ ...form, trigger_labels: e.target.value })} />
            </label>
            <label>
              Merge policy
              <select value={form.merge_policy} onChange={(e) => setForm({ ...form, merge_policy: e.target.value })}>
                <option value="review">Human review required</option>
                <option value="auto_merge">Auto-merge on green CI</option>
              </select>
            </label>
            <label>
              Budget cap (ACUs per session)
              <input type="number" min="1" max="100" value={form.max_acu_per_session}
                onChange={(e) => setForm({ ...form, max_acu_per_session: e.target.value })} />
            </label>
            <label>
              Baseline engineer hours per issue
              <input type="number" min="0" step="0.5" value={form.baseline_engineer_hours_per_issue}
                onChange={(e) => setForm({ ...form, baseline_engineer_hours_per_issue: e.target.value })} />
            </label>
            <label className="checkline">
              <input type="checkbox" checked={form.enabled}
                onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
              Active (receive new events)
            </label>
          </div>
          {formError && <p className="form-error">{formError}</p>}
          <div className="form-actions">
            <button className="btn primary" type="submit">{editingId ? 'Save changes' : 'Connect'}</button>
            <span className="hint">Then point the repository's GitHub webhook (Issues events) at <code>/webhooks/github</code>.</span>
          </div>
        </form>
      )}

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Repository</th><th>Trigger labels</th><th>Merge policy</th>
              <th>ACU cap</th><th>Baseline hrs</th><th>Status</th><th></th>
            </tr>
          </thead>
          <tbody>
            {repos.map((r) => (
              <tr key={r.id}>
                <td><a href={`https://github.com/${r.full_name}`} target="_blank" rel="noreferrer">{r.full_name}</a></td>
                <td>{r.trigger_labels.map((l) => <span key={l} className="chip">{l}</span>)}</td>
                <td>
                  <span className={`badge ${r.merge_policy === 'auto_merge' ? 'ok' : 'awaiting_review'}`}>
                    {r.merge_policy === 'auto_merge' ? 'auto-merge on green CI' : 'human review required'}
                  </span>
                </td>
                <td>{r.max_acu_per_session}</td>
                <td>{r.baseline_engineer_hours_per_issue}</td>
                <td><span className={`badge ${r.enabled ? 'ok' : 'failed'}`}>{r.enabled ? 'active' : 'paused'}</span></td>
                <td className="row-actions">
                  <button
                    className="btn ghost"
                    disabled={scans.some((s) => s.repo === r.full_name && (s.state === 'queued' || s.state === 'running'))}
                    title="Ask Devin to proactively audit this repository for defects. Findings land in the review queue below — nothing is changed or filed automatically."
                    onClick={() => startScan(r)}
                  >
                    {scans.some((s) => s.repo === r.full_name && (s.state === 'queued' || s.state === 'running')) ? 'Scanning…' : 'Scan for issues'}
                  </button>
                  <button className="btn ghost" onClick={() => editRepo(r)}>Edit</button>
                  <button className="btn ghost danger" onClick={() => removeRepo(r)}>Disconnect</button>
                </td>
              </tr>
            ))}
            {repos.length === 0 && (
              <tr><td colSpan={7} className="empty">No repositories connected yet — use "Connect repository" above.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {scanError && <p className="form-error">{scanError}</p>}

      {scans.length > 0 && (
        <div className="card" style={{ marginTop: 12 }}>
          <p className="hint" style={{ marginBottom: 8 }}>Proactive scans — read-only Devin audits of a connected repository; findings feed the review queue below.</p>
          <ul className="scan-list">
            {scans.slice(0, 5).map((s) => (
              <li key={s.id} className="scan-row">
                <span className={`badge ${s.state === 'completed' ? 'ok' : s.state === 'failed' ? 'failed' : 'running'}`}>{s.state}</span>
                <span className="scan-repo">{s.repo}</span>
                <span className="meta">
                  {s.state === 'completed' ? `${s.findings_count} finding${s.findings_count === 1 ? '' : 's'}` : ''}
                  {s.summary ? ` — ${s.summary}` : ''}
                </span>
                {s.session_url && <a href={s.session_url} target="_blank" rel="noreferrer">session</a>}
                <span className="meta">{ts(s.created_at)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="section-head" style={{ marginTop: 40 }}>
        <h2 className="section-title">Findings proposed by Devin</h2>
        {proposed.length > 0 && <span className="badge awaiting_review">{proposed.length} awaiting review</span>}
      </div>
      <div className="card">
        <p className="hint" style={{ marginBottom: 10 }}>
          Defects Devin surfaced — noticed while remediating something else, or found by a
          proactive scan. Approving opens a prefilled GitHub issue for you to file; the agent
          never files issues on its own.
        </p>
        <ul className="finding-list">
          {proposed.map((f) => (
            <li key={f.id} className="finding">
              <div className="finding-main">
                <div className="finding-title">
                  <span className={`badge sev-${f.severity}`}>{f.severity}</span> {f.title}
                </div>
                <div className="finding-desc">{f.description}</div>
                <div className="meta">{f.scan_id ? `Found by a proactive scan of ${f.repo}` : `Found while remediating ${f.repo}#${f.source_issue_number}`} · {ts(f.created_at)}</div>
              </div>
              <div className="finding-actions">
                <button className="btn primary" onClick={() => reviewFinding(f, 'approve')}>Approve &amp; file</button>
                <button className="btn ghost" onClick={() => reviewFinding(f, 'dismiss')}>Dismiss</button>
              </div>
            </li>
          ))}
          {proposed.length === 0 && <li className="empty">No findings awaiting review.</li>}
        </ul>
        {reviewed.length > 0 && (
          <details className="reviewed-findings">
            <summary>{reviewed.length} previously reviewed</summary>
            <ul className="finding-list">
              {reviewed.map((f) => (
                <li key={f.id} className="finding dim">
                  <div className="finding-main">
                    <div className="finding-title">{f.title}</div>
                    <div className="meta">{f.status} · {f.scan_id ? `${f.repo} (scan)` : `${f.repo}#${f.source_issue_number}`}</div>
                  </div>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      <h2 className="section-title" style={{ marginTop: 40 }}>Remediation audit trail</h2>
      <div className="card">
        <table className="audit">
          <thead>
            <tr>
              <th style={{ width: '38%' }}>Issue</th>
              <th style={{ width: '32%' }}>Problem → fix</th>
              <th>State</th><th>PR</th><th>ACUs</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <React.Fragment key={r.id}>
                <tr className="expandable" onClick={() => setOpen(open === r.id ? null : r.id)}>
                  <td>
                    <a href={r.issue_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                      {r.repo}#{r.issue_number}
                    </a>
                    <div className="issue-title">{r.issue_title}</div>
                    <div className="meta">{ts(r.created_at)}</div>
                  </td>
                  <td className="summary-cell">
                    {r.problem_summary
                      ? (
                        <>
                          <div className="problem">{r.problem_summary}</div>
                          <div className="fix">{r.fix_summary}</div>
                        </>
                      )
                      : <span className="meta">{r.state === 'running' || r.state === 'queued' ? 'In progress…' : 'Not reported'}</span>}
                  </td>
                  <td><span className={`badge ${r.state}`}>{r.state.replace('_', ' ')}</span></td>
                  <td>
                    {r.pr_url
                      ? <a href={r.pr_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{r.pr_state || 'view'}</a>
                      : '—'}
                  </td>
                  <td>{r.acus_consumed}</td>
                </tr>
                {open === r.id && (
                  <tr className="detail-row">
                    <td colSpan={5}>
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
              <tr><td colSpan={5} className="empty">No remediations yet. Label an issue in a connected repo (or run the simulator) to begin.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}
