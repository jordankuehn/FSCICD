"""Pipeline configuration loading and validation.

The pipeline is driven by a single YAML file (``fscicd.yml``) so enabling a
capability or changing the target LabVIEW version is a one-line edit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigError(ValueError):
    """Raised when the pipeline configuration is missing or invalid."""


@dataclass
class BitbucketConfig:
    workspace: str = ""
    repo_slug: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.workspace and self.repo_slug)


@dataclass
class LabVIEWConfig:
    # FSCICD targets LabVIEW 2026 64-bit exclusively; there is no support for
    # older versions or 32-bit, so these are fixed rather than configurable.
    version: str = "2026"
    runner: str = "mock"  # "mock" | "container"
    image: str = "nationalinstruments/labview:2026q1-linux"
    headless: bool = True

    def __post_init__(self) -> None:
        if self.runner not in ("mock", "container"):
            raise ConfigError(f"labview.runner must be 'mock' or 'container', got {self.runner!r}")


@dataclass
class MassCompileConfig:
    enabled: bool = True
    project_globs: list[str] = field(default_factory=lambda: ["**/*.lvproj"])
    vi_globs: list[str] = field(default_factory=lambda: ["**/*.vi", "**/*.ctl"])


@dataclass
class ViAnalyzerConfig:
    enabled: bool = True
    config_path: str = ""
    fail_on_severity: str = "high"  # high | medium | low | none


@dataclass
class CapabilitiesConfig:
    mass_compile: MassCompileConfig = field(default_factory=MassCompileConfig)
    vi_analyzer: ViAnalyzerConfig = field(default_factory=ViAnalyzerConfig)


@dataclass
class Config:
    project_name: str
    labview: LabVIEWConfig = field(default_factory=LabVIEWConfig)
    bitbucket: BitbucketConfig = field(default_factory=BitbucketConfig)
    capabilities: CapabilitiesConfig = field(default_factory=CapabilitiesConfig)
    report_dir: str = "build/reports"


def _as_dict(value: object, key: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"'{key}' must be a mapping, got {type(value).__name__}")
    return value


def load_config(path: str | Path) -> Config:
    """Load and validate a pipeline config from a YAML file."""

    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - passthrough
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    return parse_config(raw)


def parse_config(raw: dict) -> Config:
    """Build a validated :class:`Config` from an already-parsed mapping."""

    raw = _as_dict(raw, "<root>")
    project = _as_dict(raw.get("project"), "project")
    name = project.get("name")
    if not name:
        raise ConfigError("project.name is required")

    bb = _as_dict(project.get("bitbucket"), "project.bitbucket")
    bitbucket = BitbucketConfig(
        workspace=bb.get("workspace", ""),
        repo_slug=bb.get("repo_slug", ""),
    )

    lv = _as_dict(raw.get("labview"), "labview")
    labview = LabVIEWConfig(
        version=str(lv.get("version", "2026")),
        runner=lv.get("runner", "mock"),
        image=lv.get("image", "nationalinstruments/labview:2026q1-linux"),
        headless=bool(lv.get("headless", True)),
    )

    caps = _as_dict(raw.get("capabilities"), "capabilities")
    mc = _as_dict(caps.get("mass_compile"), "capabilities.mass_compile")
    via = _as_dict(caps.get("vi_analyzer"), "capabilities.vi_analyzer")
    capabilities = CapabilitiesConfig(
        mass_compile=MassCompileConfig(
            enabled=bool(mc.get("enabled", True)),
            project_globs=list(mc.get("project_globs", ["**/*.lvproj"])),
            vi_globs=list(mc.get("vi_globs", ["**/*.vi", "**/*.ctl"])),
        ),
        vi_analyzer=ViAnalyzerConfig(
            enabled=bool(via.get("enabled", True)),
            config_path=via.get("config_path", ""),
            fail_on_severity=via.get("fail_on_severity", "high"),
        ),
    )

    return Config(
        project_name=name,
        labview=labview,
        bitbucket=bitbucket,
        capabilities=capabilities,
        report_dir=raw.get("report", {}).get("output_dir", "build/reports")
        if isinstance(raw.get("report"), dict)
        else "build/reports",
    )
