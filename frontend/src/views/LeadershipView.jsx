import React from 'react'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend,
} from 'recharts'

const money = (n) => n == null ? '—' : `$${Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`

// Answers the four leadership questions in reading order:
// return on investment, impact delivered, current activity, and where
// attention or resources are needed.
export default function LeadershipView({ overview }) {
  if (!overview) return <p className="empty">Loading…</p>
  const { cost_vs_benefit: roi, weekly_impact, live_agents, attention_needed, throughput } = overview

  return (
    <>
      <h2 className="section-title">Investment &amp; return</h2>
      <div className="kpi-row">
        <div className="card kpi">
          <div className="label">Estimated value delivered</div>
          <div className="value ok">{money(roi.benefit_usd)}</div>
          <div className="hint">{roi.engineer_hours_saved} engineer-hours saved at ${roi.assumptions.engineer_usd_per_hour}/hr</div>
        </div>
        <div className="card kpi">
          <div className="label">Compute cost to date</div>
          <div className="value">{money(roi.cost_usd)}</div>
          <div className="hint">{roi.total_acus} ACUs at ${roi.assumptions.usd_per_acu}/ACU</div>
        </div>
        <div className="card kpi">
          <div className="label">Return on investment</div>
          <div className="value accent">{roi.roi_multiple ? `${roi.roi_multiple}×` : '—'}</div>
          <div className="hint">estimated value delivered ÷ compute cost</div>
        </div>
        <div className="card kpi">
          <div className="label">Resolution rate</div>
          <div className="value">{throughput.success_rate != null ? `${Math.round(throughput.success_rate * 100)}%` : '—'}</div>
          <div className="hint">{throughput.succeeded} resolved · {throughput.failed} escalated to engineers</div>
        </div>
      </div>

      <div className="grid-2" style={{ marginTop: 24 }}>
        <div>
          <h2 className="section-title">Impact delivered — last 7 days</h2>
          <div className="card">
            <p style={{ marginBottom: 8 }}>
              <strong>{weekly_impact.resolved_last_7_days}</strong> issues remediated in the last 7 days
            </p>
            <ul className="list">
              {weekly_impact.highlights.map((h) => (
                <li key={`${h.repo}-${h.issue_number}`}>
                  <span>
                    <a href={h.pr_url || '#'} target="_blank" rel="noreferrer">#{h.issue_number}</a>{' '}
                    {h.title}
                    <div className="meta">{h.fix_summary || h.root_cause}</div>
                  </span>
                </li>
              ))}
              {weekly_impact.highlights.length === 0 && <li className="empty">No completed remediations in the last 7 days.</li>}
            </ul>
          </div>
        </div>

        <div>
          <h2 className="section-title">Active remediations</h2>
          <div className="card">
            <p style={{ marginBottom: 8 }}>
              <strong>{live_agents.length}</strong> agent{live_agents.length === 1 ? '' : 's'} active
            </p>
            <ul className="list">
              {live_agents.map((a) => (
                <li key={a.session_url || a.issue_number}>
                  <span>
                    <span className="pulse" />
                    #{a.issue_number} {a.title}
                    <div className="meta">
                      {a.status_detail} · {Math.round(a.running_seconds / 60)} min · {a.acus_so_far} ACUs
                    </div>
                  </span>
                </li>
              ))}
              {live_agents.length === 0 && <li className="empty">No remediations in progress.</li>}
            </ul>
          </div>
        </div>
      </div>

      <h2 className="section-title">Requires attention</h2>
      <div className="grid-2">
        <div className="card">
          <p style={{ marginBottom: 8 }}><strong>Pull requests waiting on human review</strong></p>
          <ul className="list">
            {attention_needed.review_queue.map((r) => (
              <li key={`${r.repo}-${r.issue_number}`}>
                <span>
                  <a href={r.pr_url} target="_blank" rel="noreferrer">#{r.issue_number}</a> {r.title}
                </span>
                <span className="badge awaiting_review">{r.waiting_hours}h waiting</span>
              </li>
            ))}
            {attention_needed.review_queue.length === 0 && <li className="empty">Review queue is clear.</li>}
          </ul>
        </div>
        <div className="card">
          <p style={{ marginBottom: 8 }}><strong>Escalations needing an engineer</strong></p>
          <ul className="list">
            {attention_needed.escalations.map((e) => (
              <li key={`${e.repo}-${e.issue_number}`}>
                <span>
                  <a href={e.session_url} target="_blank" rel="noreferrer">#{e.issue_number}</a> {e.title}
                </span>
                <span className="badge escalated">{e.outcome}</span>
              </li>
            ))}
            {attention_needed.escalations.length === 0 && <li className="empty">No escalations.</li>}
          </ul>
        </div>
      </div>

      <h2 className="section-title">Throughput</h2>
      <div className="card" style={{ height: 260 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={throughput.daily} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
            <XAxis dataKey="date" tick={{ fontSize: 12 }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
            <Tooltip />
            <Legend />
            <Bar dataKey="succeeded" name="Resolved" stackId="a" fill="#1e7d43" radius={[3, 3, 0, 0]} />
            <Bar dataKey="failed" name="Escalated" stackId="a" fill="#d22128" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {throughput.median_minutes_to_pr != null && (
        <p className="footer-note" style={{ textAlign: 'left', marginTop: 8 }}>
          Median time from issue to reviewable PR: <strong>{throughput.median_minutes_to_pr} minutes</strong>
        </p>
      )}
    </>
  )
}
