from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from fscicd.cli import main


def _write_config(path: Path, runner: str = "mock") -> Path:
    cfg = path / "fscicd.yml"
    cfg.write_text(f"project:\n  name: Demo\nlabview:\n  runner: {runner}\n")
    return cfg


def test_cli_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "fscicd" in result.output


def test_cli_run_passes_on_clean_repo(sample_repo, tmp_path):
    cfg = _write_config(tmp_path)
    result = CliRunner().invoke(
        main,
        ["run", "-c", str(cfg), "-p", str(sample_repo), "--commit", "c1", "--no-status"],
    )
    assert result.exit_code == 0
    assert "Overall : PASSED" in result.output


def test_cli_run_fails_on_broken_repo(broken_repo, tmp_path):
    cfg = _write_config(tmp_path)
    result = CliRunner().invoke(
        main,
        ["run", "-c", str(cfg), "-p", str(broken_repo), "--commit", "c1", "--no-status"],
    )
    assert result.exit_code == 2
    assert "FAILED" in result.output


def test_cli_run_dry_run_status(sample_repo, tmp_path):
    cfg = _write_config(tmp_path)
    result = CliRunner().invoke(
        main,
        ["run", "-c", str(cfg), "-p", str(sample_repo), "--commit", "c1"],
    )
    assert result.exit_code == 0
    assert "dry-run" in result.output
