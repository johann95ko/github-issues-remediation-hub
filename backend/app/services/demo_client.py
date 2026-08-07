"""Deterministic Devin API simulator.

Exists so anyone can run the full workflow — webhook in, sessions "running",
PRs out, dashboard populated — without a Devin API key or ACU spend. The
simulator honors the same interface as the real client and advances each fake
session through a realistic lifecycle on every poll.
"""

from __future__ import annotations

import random
import time
import uuid
from typing import Any

_FAKE_ROOT_CAUSES = [
    "Null check missing on chart metadata before export serialization.",
    "Race condition between async query polling and dashboard refresh.",
    "Timezone offset dropped when caching query results.",
    "SQL Lab autocomplete indexed stale schema after migration.",
    "CSV export streamed rows before headers were flushed.",
]


class DemoDevinClient:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}

    async def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = f"devin-demo-{uuid.uuid4().hex[:10]}"
        # ~85% of runs succeed; the rest exercise the failure/escalation paths
        # so the dashboard demonstrates honest failure reporting too.
        roll = random.random()
        outcome = "fixed" if roll < 0.85 else ("cannot_reproduce" if roll < 0.93 else "blocked")
        self._sessions[session_id] = {
            "session_id": session_id,
            "url": f"https://app.devin.ai/sessions/{session_id}",
            "status": "running",
            "created_at": time.time(),
            # Fake sessions "finish" after 45-120s so a live demo shows movement.
            "duration": random.uniform(45, 120),
            "planned_outcome": outcome,
            "prompt": payload.get("prompt", ""),
            "tags": payload.get("tags", []),
        }
        return {"session_id": session_id, "url": self._sessions[session_id]["url"], "status": "running"}

    async def get_session(self, session_id: str) -> dict[str, Any]:
        record = self._sessions.get(session_id)
        if record is None:
            # Sessions created before a restart: report them finished so the
            # poller can close them out instead of polling forever.
            return {
                "session_id": session_id,
                "url": f"https://app.devin.ai/sessions/{session_id}",
                "status": "exit",
                "status_detail": "finished",
                "acus_consumed": round(random.uniform(2, 9), 2),
                "pull_requests": [],
                "structured_output": {"outcome": "fixed", "root_cause": random.choice(_FAKE_ROOT_CAUSES), "tests_run": "pytest (simulated)", "confidence": "medium"},
            }

        elapsed = time.time() - record["created_at"]
        acus = round(min(elapsed / 12.0, 12.0), 2)
        base = {
            "session_id": session_id,
            "url": record["url"],
            "acus_consumed": acus,
            "pull_requests": [],
            "structured_output": None,
        }
        if elapsed < record["duration"]:
            return {**base, "status": "running", "status_detail": "working"}

        issue_number = _extract_issue_number(record["tags"])
        outcome = record["planned_outcome"]
        finished = {
            **base,
            "status": "exit" if outcome != "blocked" else "error",
            "status_detail": "finished" if outcome != "blocked" else "error",
            "structured_output": {
                "issue_number": issue_number,
                "outcome": outcome,
                "root_cause": random.choice(_FAKE_ROOT_CAUSES),
                "tests_run": "pytest tests/unit (simulated run, 214 passed)",
                "confidence": "high" if outcome == "fixed" else "low",
            },
        }
        if outcome == "fixed":
            finished["pull_requests"] = [
                {
                    "pr_url": f"https://github.com/demo/superset/pull/{9000 + issue_number}",
                    "pr_state": "open",
                }
            ]
        return finished

    async def send_message(self, session_id: str, message: str) -> None:
        return None


def _extract_issue_number(tags: list[str]) -> int:
    for tag in tags:
        if tag.startswith("issue-"):
            try:
                return int(tag.split("-", 1)[1])
            except ValueError:
                pass
    return 0
