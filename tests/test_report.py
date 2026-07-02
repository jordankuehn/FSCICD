from __future__ import annotations

import json

from fscicd.models import CapabilityResult, PipelineResult, Status
from fscicd.report import render_html, render_json, write_reports


def _sample_result() -> PipelineResult:
    return PipelineResult(
        project_name="Signal Generator",
        commit="deadbeef",
        capabilities=[
            CapabilityResult(
                "Mass Compile",
                Status.PASSED,
                "All 3 VIs compiled cleanly.",
                {"total": 3, "compiled": 3, "broken": 0, "vis": []},
            ),
            CapabilityResult(
                "VI Analyzer",
                Status.FAILED,
                "1 high finding.",
                {
                    "tested_vis": 3,
                    "findings": [
                        {
                            "vi_path": "Main.vi",
                            "test": "Error Cluster Wired",
                            "category": "Correctness",
                            "severity": "high",
                            "message": "Error cluster not wired.",
                        }
                    ],
                },
            ),
        ],
    )


def test_render_html_contains_key_content():
    html = render_html(_sample_result())
    assert "Signal Generator" in html
    assert "deadbeef" in html
    assert "Error Cluster Wired" in html
    assert "FAILED" in html


def test_render_json_roundtrips():
    payload = json.loads(render_json(_sample_result()))
    assert payload["status"] == "FAILED"
    assert payload["project_name"] == "Signal Generator"
    assert payload["capabilities"][0]["name"] == "Mass Compile"


def test_write_reports_creates_files(tmp_path):
    paths = write_reports(_sample_result(), tmp_path / "out")
    assert paths["html"].is_file()
    assert paths["json"].is_file()
    assert "<html" in paths["html"].read_text().lower()
