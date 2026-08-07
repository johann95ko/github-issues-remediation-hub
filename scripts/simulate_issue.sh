#!/usr/bin/env bash
# Replays a realistic GitHub "issues" webhook against the hub so the full
# workflow can be demonstrated without touching GitHub. Usage:
#   ./scripts/simulate_issue.sh [issue_number] [title]
set -euo pipefail

HUB_URL="${HUB_URL:-http://localhost:8000}"
SECRET="${GITHUB_WEBHOOK_SECRET:-}"
NUMBER="${1:-$((RANDOM % 900 + 100))}"
TITLE="${2:-Chart export fails with NullPointerException on empty datasets}"

BODY=$(jq -n --argjson number "$NUMBER" --arg title "$TITLE" '{
  action: "labeled",
  issue: {
    number: $number,
    title: $title,
    body: "Steps to reproduce:\n1. Create a chart with an empty result set\n2. Click Export CSV\n\nExpected: empty CSV\nActual: 500 error, NPE in export serializer",
    html_url: ("https://github.com/johann95ko/superset/issues/" + ($number | tostring)),
    labels: [{name: "devin-fix"}, {name: "bug"}]
  },
  repository: { full_name: "johann95ko/superset" }
}')

HEADERS=(-H "Content-Type: application/json" -H "X-GitHub-Event: issues")
if [[ -n "$SECRET" ]]; then
  SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
  HEADERS+=(-H "X-Hub-Signature-256: sha256=$SIG")
fi

curl -sS -X POST "${HEADERS[@]}" -d "$BODY" "$HUB_URL/webhooks/github" | jq .
