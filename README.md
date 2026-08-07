# Devin Remediation Hub

Event-driven automation that remediates GitHub issues autonomously using the
[Devin API](https://docs.devin.ai/api-reference/overview), with a
leadership-grade reporting dashboard.

**The loop:** an issue labeled `devin-fix` in a monitored repository (e.g. a
fork of [apache/superset](https://github.com/johann95ko/superset)) fires a
webhook → the hub starts a budget-capped Devin session → Devin root-causes the
issue, fixes it, and opens a pull request → a human approves (or, for
low-scrutiny repos, the PR auto-merges on green CI) → every step lands in an
audit trail that powers the dashboard.

```
GitHub issue (labeled devin-fix)
        │  webhook (HMAC-verified)
        ▼
┌─────────────────────────── Remediation Hub (this repo) ───────────────────────────┐
│  webhook ingress ──► orchestrator ──► Devin API (create session, ACU cap,        │
│       │                   │            structured-output contract)               │
│       │                   ▼                                                       │
│       │              SQLite audit log ◄── poller (reconciles session status,     │
│       │                   │                nudges stuck sessions, escalates)     │
│       │                   ▼                                                       │
│       └──────────► dashboard: Executive Overview + Engineering views             │
└───────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
Pull request referencing the issue  ──►  human review  (or auto-merge on green CI)
```

## Quick start (zero credentials — simulated Devin)

Requires Docker and `jq`.

```bash
docker compose up --build -d
./scripts/simulate_issue.sh                 # replay a GitHub issue webhook
./scripts/simulate_issue.sh 207 "SQL Lab autocomplete returns stale schema"
open http://localhost:8000                  # watch the dashboard update live
```

Demo mode (the default) swaps the Devin API for a deterministic simulator:
sessions "run" for 1–2 minutes, most produce PRs, some fail or escalate — so
every dashboard state is demonstrable without spend.

## Live mode (real Devin sessions)

1. Create a **service user** at app.devin.ai → Settings → Service users
   (role: Member) and copy the `cog_...` key and your org ID.
2. Run with credentials:

```bash
DEMO_MODE=false \
DEVIN_API_KEY=cog_... \
DEVIN_ORG_ID=org-... \
GITHUB_WEBHOOK_SECRET=$(openssl rand -hex 20) \
docker compose up --build -d
```

3. In each monitored GitHub repository: **Settings → Webhooks → Add webhook**
   - Payload URL: `https://<your-host>/webhooks/github`
   - Content type: `application/json`
   - Secret: the same `GITHUB_WEBHOOK_SECRET`
   - Events: *Issues*

4. Label an issue `devin-fix`. The hub starts a session; the PR appears on the
   dashboard when Devin finishes.

> For a local machine, expose the port with a tunnel (e.g. `ngrok http 8000`)
> and use the tunnel URL as the webhook payload URL.

## Monitoring more repositories

Repository onboarding is configuration, not code — append to
[`config/repos.yaml`](config/repos.yaml):

```yaml
repositories:
  - full_name: your-org/another-repo
    trigger_labels: [devin-fix]
    merge_policy: review        # or auto_merge for low-scrutiny repos
    max_acu_per_session: 15     # hard compute budget per remediation
    baseline_engineer_hours_per_issue: 4
```

`merge_policy` is the scrutiny dial: `review` requires a human to approve every
PR; `auto_merge` lets PRs land automatically once CI passes.

## The dashboard — "how do I know this is working?"

`http://localhost:8000` serves two views for two audiences:

**Executive Overview** (default) answers, in reading order:
1. *Is it worth it?* — value delivered vs. compute cost, ROI multiple, success
   rate. Benefit is only claimed for remediations that produced a reviewable
   PR; failures earn zero, keeping the ROI honest.
2. *What did it resolve this week?* — count + top fixes with root causes.
3. *What is it doing right now?* — live agents, what each is working on, spend so far.
4. *Where is my attention needed?* — PRs waiting on review (ranked by age) and
   escalations needing an engineer. This is the "where to put resources" queue.

**Engineering** view: connected repositories with their policies, and the full
per-remediation audit trail — Devin session link, raw status, root cause,
tests run, confidence, PR state — so a human SWE can judge whether each fix
makes sense.

ROI model inputs are explicit and tunable via `USD_PER_ACU` and
`ENGINEER_USD_PER_HOUR` environment variables.

## Design decisions

- **Structured output contract**: every session must report
  `{outcome, root_cause, tests_run, confidence, pr_url}` against a JSON schema
  (`structured_output_schema`), which is what turns agent work into report rows.
- **Budget caps**: `max_acu_limit` on every session — a runaway agent stops at
  the cap, never at the credit card.
- **Deduplication**: webhook redeliveries and re-labels can't double-spend; one
  active remediation per issue, enforced against the database.
- **Reconciliation over memory**: the poller re-derives all state from
  `GET /sessions`, so a crashed hub resumes exactly where it left off.
- **Bounded autonomy**: a stuck session gets exactly one automated nudge, then
  escalates to a human — two automated systems should never chat in a loop.
- **Honest failure signals**: sessions that finish without a PR are recorded as
  failures, not successes.

## Repository layout

```
backend/app/
  api/         webhook ingress + dashboard API
  core/        config (env + repos.yaml), database
  models/      the Remediation audit-log row
  services/    Devin client, demo simulator, orchestrator, poller, analytics
frontend/      React dashboard (Vite), Apache-inspired design language
config/        repos.yaml — monitored repositories and policies
scripts/       simulate_issue.sh — replay a GitHub webhook locally
```

## Related

- Remediated repository (fork): https://github.com/johann95ko/superset
- Devin API docs: https://docs.devin.ai/api-reference/overview
