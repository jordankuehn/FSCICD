from __future__ import annotations

import pytest
import responses

from fscicd.bitbucket import (
    API_ROOT,
    BitbucketClient,
    BitbucketCredentials,
    BitbucketError,
    build_status_payload,
)
from fscicd.models import CapabilityResult, PipelineResult, Status


def _result(status: Status) -> PipelineResult:
    return PipelineResult(
        project_name="P",
        commit="abc123",
        capabilities=[CapabilityResult("Mass Compile", status, "summary")],
    )


def test_payload_maps_status():
    payload = build_status_payload(_result(Status.PASSED), "http://x/report")
    assert payload["state"] == "SUCCESSFUL"
    assert payload["url"] == "http://x/report"
    assert payload["key"] == "FSCICD"


def test_payload_failed_state():
    assert build_status_payload(_result(Status.FAILED), None)["state"] == "FAILED"


def test_credentials_from_env():
    creds = BitbucketCredentials.from_env({"BITBUCKET_ACCESS_TOKEN": "tok"})
    assert creds.available is True
    assert BitbucketCredentials.from_env({}).available is False


def test_dry_run_when_no_credentials():
    client = BitbucketClient("w", "r", BitbucketCredentials())
    assert client.dry_run is True
    out = client.post_build_status("abc123", _result(Status.PASSED))
    assert out["dry_run"] is True


@responses.activate
def test_post_build_status_sends_request():
    url = f"{API_ROOT}/repositories/w/r/commit/abc123/statuses/build"
    responses.add(responses.POST, url, json={"key": "FSCICD"}, status=201)
    client = BitbucketClient("w", "r", BitbucketCredentials(access_token="tok"))
    assert client.dry_run is False
    out = client.post_build_status("abc123", _result(Status.PASSED), "http://x")
    assert out["key"] == "FSCICD"
    assert responses.calls[0].request.headers["Authorization"] == "Bearer tok"
    assert b"SUCCESSFUL" in responses.calls[0].request.body


@responses.activate
def test_rejected_status_raises_domain_error():
    url = f"{API_ROOT}/repositories/w/r/commit/abc123/statuses/build"
    responses.add(responses.POST, url, json={"error": "nope"}, status=401)
    client = BitbucketClient("w", "r", BitbucketCredentials(access_token="tok"))
    with pytest.raises(BitbucketError) as excinfo:
        client.post_build_status("abc123", _result(Status.PASSED))
    # The message has to name the coordinates, since wrong workspace/repo_slug is
    # the most common cause.
    assert "w/r" in str(excinfo.value)
