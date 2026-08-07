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
root cause, tests run and confidence.

ROI model inputs are explicit and tunable via `USD_PER_ACU` and
`ENGINEER_USD_PER_HOUR` environment variables.

## Design decisions

- **Structured output contract**: every session must report
  `{outcome, problem_summary, fix_summary, root_cause, tests_run, confidence,
  pr_url, discovered_issues}` against a JSON schema
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
  api/         webhook ingress, dashboard API, repo + findings management API
  core/        config (env + bootstrap repos.yaml), database
  models/      Remediation audit rows, monitored repos, discovered issues
  services/    Devin client, demo simulator, orchestrator, poller, analytics
frontend/      React dashboard (Vite), Apache-inspired design language
config/        repos.yaml — first-boot seed for monitored repositories
scripts/       simulate_issue.sh — replay a GitHub webhook locally
```

## Related

- Remediated repository (fork): https://github.com/johann95ko/superset —
  remediated issues are labeled `devin-fix`
  ([view them](https://github.com/johann95ko/superset/issues?q=label%3Adevin-fix))
- Devin API docs: https://docs.devin.ai/api-reference/overview
