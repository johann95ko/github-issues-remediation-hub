"""Application configuration.

Two layers on purpose:
  * environment variables  -> deployment concerns (keys, ports, mode)
  * config/repos.yaml      -> product concerns (which repos, what policy)

Repo onboarding must never require a code change, so everything a technical
user tunes per-repository lives in the YAML file.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class RepoConfig(BaseModel):
    full_name: str
    trigger_labels: list[str] = ["devin-fix"]
    merge_policy: str = "review"  # "review" | "auto_merge"
    max_acu_per_session: int = 15
    baseline_engineer_hours_per_issue: float = 4.0


class Settings(BaseSettings):
    devin_api_key: str = ""
    devin_org_id: str = ""
    devin_api_base: str = "https://api.devin.ai/v3"

    # Shared secret used to verify GitHub webhook signatures (X-Hub-Signature-256).
    github_webhook_secret: str = ""
    # Optional: lets the hub comment status back on the triggering issue.
    github_token: str = ""

    # demo_mode replaces the Devin API with a deterministic simulator so the
    # whole workflow can be exercised without credentials or spend.
    demo_mode: bool = False

    # ROI model inputs surfaced on the leadership dashboard.
    usd_per_acu: float = 2.25
    engineer_usd_per_hour: float = 95.0

    poll_interval_seconds: int = 30
    database_url: str = "sqlite:////data/remediation.db"
    repos_config_path: str = "/config/repos.yaml"

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_repo_configs() -> list[RepoConfig]:
    path = Path(get_settings().repos_config_path)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or {}
    return [RepoConfig(**entry) for entry in raw.get("repositories", [])]


def find_repo_config(full_name: str) -> RepoConfig | None:
    for repo in get_repo_configs():
        if repo.full_name.lower() == full_name.lower():
            return repo
    return None
