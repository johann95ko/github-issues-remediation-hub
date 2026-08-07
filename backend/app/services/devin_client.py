"""Thin async client for the Devin v3 API.

Only the endpoints the hub needs. The interface (DevinClientProtocol) exists
so demo mode can swap in a simulator without the orchestrator or poller
knowing the difference.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Structured output contract every remediation session must fill in before it
# finishes. This is what turns free-form agent work into report rows.
REMEDIATION_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "issue_number": {"type": "integer"},
        "outcome": {
            "type": "string",
            "enum": ["fixed", "partial", "cannot_reproduce", "blocked"],
        },
        "pr_url": {"type": "string"},
        "root_cause": {"type": "string"},
        "tests_run": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["issue_number", "outcome", "root_cause"],
}


class DevinClientProtocol(Protocol):
    async def create_session(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def get_session(self, session_id: str) -> dict[str, Any]: ...
    async def send_message(self, session_id: str, message: str) -> None: ...


class DevinClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._org_base = f"{settings.devin_api_base}/organizations/{settings.devin_org_id}"
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {settings.devin_api_key}"},
            timeout=30.0,
        )

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        # 429s are expected under burst load (many issues filed at once);
        # linear backoff is enough because the poller retries next cycle anyway.
        for attempt in range(3):
            response = await self._client.request(method, url, **kwargs)
            if response.status_code != 429:
                response.raise_for_status()
                return response
            await asyncio.sleep(2 * (attempt + 1))
        response.raise_for_status()
        return response

    async def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("POST", f"{self._org_base}/sessions", json=payload)
        return response.json()

    async def get_session(self, session_id: str) -> dict[str, Any]:
        response = await self._request("GET", f"{self._org_base}/sessions/{session_id}")
        return response.json()

    async def send_message(self, session_id: str, message: str) -> None:
        await self._request(
            "POST",
            f"{self._org_base}/sessions/{session_id}/messages",
            json={"message": message},
        )

    async def close(self) -> None:
        await self._client.aclose()


def build_remediation_prompt(repo: str, issue_number: int, title: str, body: str, issue_url: str) -> str:
    return (
        f"You are remediating GitHub issue #{issue_number} in the repository {repo}.\n\n"
        f"Issue: {title}\n"
        f"URL: {issue_url}\n\n"
        f"Issue description:\n{body}\n\n"
        "Instructions:\n"
        "1. Reproduce and root-cause the issue.\n"
        "2. Implement a minimal, well-scoped fix following the repository's conventions.\n"
        "3. Run relevant tests/linting to validate the fix.\n"
        "4. Open a pull request that references the issue (e.g. 'Fixes #"
        f"{issue_number}').\n"
        "5. Fill in the structured output with your outcome, root cause, and the PR URL.\n"
        "If you cannot reproduce or are blocked, say so honestly in the structured "
        "output rather than forcing a change."
    )
