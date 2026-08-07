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

## Run it: two modes

| Mode | Devin sessions | Needs credentials | Command |
|---|---|---|---|
| **Demo** (default) | Simulated | None | `docker compose up --build -d` |
| **Live** | Real, via the Devin API | Devin service-user key + org ID | see [Live mode](#live-mode-real-devin-sessions) |

### Quick start — simulate the workflow (zero credentials)

Requires Docker and `jq`.

```bash
git clone https://github.com/johann95ko/github-issues-remediation-hub
cd github-issues-remediation-hub
docker compose up --build -d

# Simulate GitHub delivering "issue labeled devin-fix" webhooks:
./scripts/simulate_issue.sh
./scripts/simulate_issue.sh 207 "SQL Lab autocomplete returns stale schema"
./scripts/simulate_issue.sh 348 "Dashboard filters reset after refresh"

open http://localhost:8000     # macOS; on Linux use xdg-open, or just open it in a browser
```

> Port 8000 already in use? Remap it: `HUB_PORT=8001 docker compose up --build -d`
> and point the simulator at it with `HUB_URL=http://localhost:8001 ./scripts/simulate_issue.sh`.
> (`jq` and `openssl` are the only prerequisites for the simulator script.)

What you should see:
1. Each `simulate_issue.sh` call returns `{"status": "accepted", ...}` — the
   webhook was verified, deduplicated, and queued; a (simulated) Devin session
   launches within a second or two (the launch happens off-request so GitHub
   always gets an immediate acknowledgment).
2. **Executive Overview** shows the sessions under *Active remediations*;
   after 1–2 minutes they complete and the ROI, weekly-impact and throughput
   figures populate.
3. **Engineering** shows each remediation in the audit trail with its
   problem → fix summary, and occasionally a Devin-proposed finding to review.

Demo mode swaps the Devin API for a deterministic simulator: sessions "run"
for 1–2 minutes, most produce PRs, some fail or escalate — so every dashboard
state is demonstrable without spend. Re-running a simulate command for the
same issue number while it's active is deduplicated (no double sessions).

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

3. Give GitHub a URL that reaches the hub. On a local machine, open a free
   tunnel (no hosting or deployment needed — keep it running while you want
   webhooks delivered):

```bash
cloudflared tunnel --url http://localhost:8000   # or: ngrok http 8000
```

4. In each monitored GitHub repository: **Settings → Webhooks → Add webhook**
   - Payload URL: `https://<tunnel-or-host>/webhooks/github`
   - Content type: `application/json`
   - Secret: the same `GITHUB_WEBHOOK_SECRET`
   - Events: *Let me select individual events → Issues*

5. Create (or re-label) an issue with the `devin-fix` label. The hub starts a
   budget-capped Devin session; the PR and problem → fix summary appear on the
   dashboard when Devin finishes. Requests with a bad/missing HMAC signature
   are rejected with 401. (Signature verification is active whenever
   `GITHUB_WEBHOOK_SECRET` is set — in demo mode without a secret, unsigned
   webhooks are accepted so the simulator works out of the box.)

## Monitoring more repositories

Repositories are managed from the **Engineering** view of the dashboard:
"Connect repository" adds a repo with its trigger labels, merge policy, ACU
budget cap and baseline hours — no config file edits, no redeploy. Then point
the repo's GitHub webhook (Issues events) at `/webhooks/github`.

[`config/repos.yaml`](config/repos.yaml) exists only as a bootstrap seed: it
populates an empty database on first boot; after that the UI owns the config.

`merge_policy` is the scrutiny dial: `review` requires a human to approve every
PR; `auto_merge` lets PRs land automatically once CI passes.

## Devin-proposed findings

While remediating one issue, Devin often notices a *different* concrete defect
(the reported bug is a symptom of a deeper problem, or an adjacent bug in the
same code). The structured-output contract asks it to report these as
`discovered_issues` rather than fixing or filing them itself. Findings land in
the Engineering view as proposals with severity; a human either dismisses one
or approves it — approval opens a prefilled GitHub "new issue" form, so the
human stays the author of record and the agent never files issues
unsupervised.

**Proactive scans** work the same way but on demand: the *Scan for issues*
button next to a connected repository starts a read-only, budget-capped Devin
audit of that repo. The scan changes no code and opens no PRs — its only
output is verified, concrete defects routed into the same review queue, with
the scan as their provenance.

## The dashboard — "how do I know this is working?"

`http://localhost:8000` serves two views for two audiences:

**Executive Overview** (default) answers, in reading order:
1. *Investment & return* — estimated value delivered vs. compute cost, ROI
   multiple, resolution rate. Benefit is only claimed for remediations that
   produced a reviewable PR; failures earn zero, keeping the ROI honest.
2. *Impact delivered (last 7 days)* — count + top fixes with what each changed.
3. *Active remediations* — live agents, what each is working on, spend so far.
4. *Requires attention* — PRs waiting on review (ranked by age) and
   escalations needing an engineer. This is the "where to put resources" queue.

**Engineering** view: repository connection management, Devin-proposed
findings awaiting review, and the full per-remediation audit trail. Each row
leads with a one-line *problem → fix* summary so a reviewer can triage without
opening the PR; expanding a row reveals the Devin session link, raw status,
root cause, tests run and confidence. The session link opens a full replay of
the agent's work, and for user-facing fixes the remediation contract asks
Devin to embed visual proof (before/after screenshots or a screen recording of
the fixed behavior) directly in the PR description.

ROI model inputs are explicit and tunable via `USD_PER_ACU` and
`ENGINEER_USD_PER_HOUR` environment variables.

## Design decisions

- **Structured output contract**: every session must report
  `{outcome, problem_summary, fix_summary, root_cause, tests_run, confidence,
  pr_url, discovered_issues}` against a JSON schema
  (`structured_output_schema`), which is what turns agent work into report rows.
- **Budget caps**: `max_acu_limit` on every session — a runaway agent stops at
  the cap, never at the credit card.
- **Deduplication**: webhook redeliveries and re-labels can't double-spend —
  GitHub delivery GUIDs are recorded exactly-once, and at most one active
  remediation per issue is enforced against the database.
- **Ingestion queue**: the webhook handler persists the event and returns 202
  immediately; a bounded worker pool creates Devin sessions off-request, so a
  burst of labeled issues never trips GitHub's delivery timeout. Queued
  launches survive restarts (re-queued from the database on boot).
- **Reconciliation over memory**: the poller re-derives all state from
  `GET /sessions`, so a crashed hub resumes exactly where it left off.
- **Bounded autonomy**: a stuck session gets exactly one automated nudge, then
  escalates to a human — two automated systems should never chat in a loop.
- **Honest failure signals**: sessions that finish without a PR are recorded as
  failures, not successes.

## Repository layout

```
backend/app/
  api/         webhook ingress, dashboard API, repo + findings management API
  core/        config (env + bootstrap repos.yaml), database
  models/      Remediation audit rows, monitored repos, discovered issues
  services/    Devin client, demo simulator, orchestrator, poller, analytics
frontend/      React dashboard (Vite), Apache-inspired design language
config/        repos.yaml — first-boot seed for monitored repositories
scripts/       simulate_issue.sh — replay a GitHub webhook locally
```

## Remediated issues (live proof)

The monitored fork is https://github.com/johann95ko/superset. Issues recreated
from real `apache/superset` bug reports, each remediated end-to-end by this
system with a real Devin session:

| Issue | Devin's PR |
|---|---|
| [#4 Pie Charts do not format Percentage values correctly](https://github.com/johann95ko/superset/issues/4) | [PR #9](https://github.com/johann95ko/superset/pull/9) |
| [#5 Metric Warning text blank after save in Edit Dataset](https://github.com/johann95ko/superset/issues/5) | [PR #8](https://github.com/johann95ko/superset/pull/8) |
| [#6 Timeseries Bar: stacked 'Only Total' sum includes sort metric](https://github.com/johann95ko/superset/issues/6) | [PR #7](https://github.com/johann95ko/superset/pull/7) |

All issues carrying the trigger label:
https://github.com/johann95ko/superset/issues?q=label%3Adevin-fix

## Production hardening roadmap

The current build is sized for a single team monitoring a handful of
repositories. Already in place: an ingestion queue between the webhook and the
Devin API, delivery-GUID idempotency, a concurrent poller, SQLite in WAL mode
with a busy timeout, SQL-side dashboard aggregations, and a paginated audit
API. What's deliberately deferred, in priority order for real multi-user use:

1. **Authentication & authorization** — there is no auth today: anyone who can
   reach the port can read the dashboard and, worse, modify repository config
   (including flipping a repo to `auto_merge`). Front it with an OAuth proxy
   (e.g. oauth2-proxy) or add session auth, with engineering-role gating on
   all write endpoints. **Do this before exposing the hub beyond localhost.**
2. **Approval audit trail** — record who approved/dismissed each finding and
   who changed repository policy, once identities exist.
3. **Postgres** — a connection-string change thanks to SQLAlchemy, needed only
   when running more than one replica; adopt Alembic for migrations at the
   same time.
4. **Horizontal scaling** — split the poller into its own worker process and
   move the ingest queue to an external broker so the API tier can run N
   replicas behind a load balancer.
5. **Push updates** — replace 15s dashboard polling with SSE/WebSocket when
   viewer count grows.
6. **Multi-tenancy** — per-organization isolation of repos, credentials, and
   dashboards; a product decision rather than a hardening step.

## Related

- Devin API docs: https://docs.devin.ai/api-reference/overview
