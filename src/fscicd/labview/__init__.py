"""Pluggable LabVIEW execution backends."""

from __future__ import annotations

from fscicd.config import LabVIEWConfig
from fscicd.labview.base import LabVIEWRunner
from fscicd.labview.container import ContainerRunner
from fscicd.labview.mock import MockRunner


def build_runner(config: LabVIEWConfig, repo_path: str) -> LabVIEWRunner:
    """Return the runner implementation selected by the config."""

    if config.runner == "container":
        return ContainerRunner(config, repo_path)
    return MockRunner(config, repo_path)


__all__ = ["LabVIEWRunner", "ContainerRunner", "MockRunner", "build_runner"]
