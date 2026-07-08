"""Report FSCICD results back to Bitbucket Cloud as commit build statuses.

Uses the Bitbucket Cloud REST API 2.0 Build Status endpoint:
``POST /2.0/repositories/{workspace}/{repo_slug}/commit/{node}/statuses/build``

Auth is via an app password (username + app password, HTTP Basic) or a
repository/workspace access token (Bearer). Credentials are read from the
environment so they never live in config files:

* ``BITBUCKET_USERNAME`` + ``BITBUCKET_APP_PASSWORD``  (basic auth), or
* ``BITBUCKET_ACCESS_TOKEN``                            (bearer token).

When no credentials are present the client runs in dry-run mode and logs the
payload instead of sending it, so the pipeline is fully testable offline.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import requests

from fscicd.models import PipelineResult, Status

log = logging.getLogger("fscicd.bitbucket")

_STATE_MAP = {
    Status.PASSED: "SUCCESSFUL",
    Status.FAILED: "FAILED",
    Status.SKIPPED: "STOPPED",
}

API_ROOT = "https://api.bitbucket.org/2.0"


@dataclass
class BitbucketCredentials:
    username: str | None = None
    app_password: str | None = None
    access_token: str | None = None

    @classmethod
    def from_env(cls, env: dict | None = None) -> BitbucketCredentials:
        env = env if env is not None else os.environ
        return cls(
            username=env.get("BITBUCKET_USERNAME"),
            app_password=env.get("BITBUCKET_APP_PASSWORD"),
            access_token=env.get("BITBUCKET_ACCESS_TOKEN"),
        )

    @property
    def available(self) -> bool:
        return bool(self.access_token or (self.username and self.app_password))


def build_status_payload(result: PipelineResult, report_url: str | None) -> dict:
    """Build the Bitbucket build-status JSON payload for a pipeline result."""

    state = _STATE_MAP[result.status]
    parts = [f"{c.name}: {c.status.value}" for c in result.capabilities]
    description = "; ".join(parts) or "No capabilities ran."
    payload = {
        "key": "FSCICD",
        "state": state,
        "name": "FSCICD LabVIEW CI",
        "description": description[:500],
    }
    if report_url:
        payload["url"] = report_url
    return payload


class BitbucketClient:
    """Thin Bitbucket Cloud client for posting commit build statuses."""

    def __init__(
        self,
        workspace: str,
        repo_slug: str,
        credentials: BitbucketCredentials | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.workspace = workspace
        self.repo_slug = repo_slug
        self.credentials = credentials or BitbucketCredentials.from_env()
        self.session = session or requests.Session()

    @property
    def dry_run(self) -> bool:
        return not (self.workspace and self.repo_slug and self.credentials.available)

    def _auth_kwargs(self) -> dict:
        if self.credentials.access_token:
            return {"headers": {"Authorization": f"Bearer {self.credentials.access_token}"}}
        return {"auth": (self.credentials.username, self.credentials.app_password)}

    def post_build_status(
        self, commit: str, result: PipelineResult, report_url: str | None = None
    ) -> dict:
        """Post (or, in dry-run mode, log) the build status for ``commit``."""

        payload = build_status_payload(result, report_url)
        if self.dry_run:
            log.info(
                "[dry-run] Bitbucket build status for %s/%s @ %s: %s",
                self.workspace or "<workspace>",
                self.repo_slug or "<repo>",
                commit,
                payload,
            )
            return {"dry_run": True, "payload": payload}

        url = (
            f"{API_ROOT}/repositories/{self.workspace}/{self.repo_slug}"
            f"/commit/{commit}/statuses/build"
        )
        resp = self.session.post(url, json=payload, timeout=30, **self._auth_kwargs())
        resp.raise_for_status()
        return resp.json()
