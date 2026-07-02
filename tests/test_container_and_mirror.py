from __future__ import annotations

import json

from fscicd.config import LabVIEWConfig
from fscicd.labview.container import (
    ContainerRunner,
    parse_masscompile_report,
    parse_vianalyzer_report,
)
from fscicd.mirror import MirrorPlan, mirror
from fscicd.models import Status


def test_masscompile_command_is_headless(tmp_path):
    runner = ContainerRunner(LabVIEWConfig(runner="container"), tmp_path)
    cmd = runner.build_masscompile_command(tmp_path / "out")
    assert cmd[0] == "docker"
    assert "LabVIEWCLI" in cmd
    assert "MassCompile" in cmd
    assert "-Headless" in cmd
    assert any("LV_RTE_HEADLESS=1" in part for part in cmd)


def test_vianalyzer_command_uses_config_path(tmp_path):
    runner = ContainerRunner(LabVIEWConfig(runner="container"), tmp_path)
    cmd = runner.build_vianalyzer_command(tmp_path / "out", "/work/my.viancfg")
    assert "RunVIAnalyzer" in cmd
    assert "/work/my.viancfg" in cmd
    assert "-Headless" in cmd


def test_parse_masscompile_report(tmp_path):
    report = tmp_path / "mc.json"
    report.write_text(
        json.dumps(
            {"vis": [{"path": "A.vi", "ok": True}, {"path": "B.vi", "ok": False, "broken": True}]}
        )
    )
    result = parse_masscompile_report(report)
    assert result.status is Status.FAILED
    assert result.broken == 1


def test_parse_vianalyzer_report(tmp_path):
    report = tmp_path / "via.json"
    report.write_text(
        json.dumps(
            {
                "tested_vis": 1,
                "findings": [
                    {"vi_path": "A.vi", "test": "T", "category": "Style", "severity": "high"}
                ],
            }
        )
    )
    result = parse_vianalyzer_report(report)
    assert result.status is Status.FAILED
    assert result.tested_vis == 1


def test_mirror_dry_run_returns_commands():
    cmds = mirror("origin", "https://github.com/o/r.git", dry_run=True)
    assert ["git", "push", "--mirror", "https://github.com/o/r.git"] in cmds


def test_mirror_plan_commands():
    plan = MirrorPlan("origin", "https://github.com/o/r.git")
    assert plan.commands()[-1][1] == "push"
