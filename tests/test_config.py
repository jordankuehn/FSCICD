from __future__ import annotations

import pytest

from fscicd.config import ConfigError, load_config, parse_config


def test_parse_minimal_config():
    cfg = parse_config({"project": {"name": "Demo"}})
    assert cfg.project_name == "Demo"
    assert cfg.labview.runner == "mock"
    assert cfg.labview.version == "2026"
    assert cfg.capabilities.mass_compile.enabled is True
    assert cfg.capabilities.vi_analyzer.enabled is True


def test_project_name_required():
    with pytest.raises(ConfigError):
        parse_config({"project": {}})


def test_invalid_runner_rejected():
    with pytest.raises(ConfigError):
        parse_config({"project": {"name": "X"}, "labview": {"runner": "gpu"}})


def test_bitbucket_configured_flag():
    cfg = parse_config(
        {"project": {"name": "X", "bitbucket": {"workspace": "w", "repo_slug": "r"}}}
    )
    assert cfg.bitbucket.is_configured is True


def test_load_config_reads_example(tmp_path):
    p = tmp_path / "fscicd.yml"
    p.write_text(
        "project:\n  name: Sample\nlabview:\n  runner: container\n"
        "capabilities:\n  vi_analyzer:\n    fail_on_severity: medium\n"
    )
    cfg = load_config(p)
    assert cfg.labview.runner == "container"
    assert cfg.capabilities.vi_analyzer.fail_on_severity == "medium"


def test_load_missing_config_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yml")
