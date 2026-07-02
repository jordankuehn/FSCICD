"""Abstract LabVIEW runner interface.

A runner is responsible for executing a LabVIEW automation operation and
returning structured results. Two implementations exist:

* :class:`~fscicd.labview.container.ContainerRunner` shells out to the official
  headless NI LabVIEW Docker image via ``LabVIEWCLI``.
* :class:`~fscicd.labview.mock.MockRunner` simulates LabVIEW so the rest of the
  system can be developed and tested without a LabVIEW install or license.
"""

from __future__ import annotations

import abc
from pathlib import Path

from fscicd.config import LabVIEWConfig
from fscicd.models import MassCompileResult, ViAnalyzerResult


class LabVIEWRunner(abc.ABC):
    """Common interface for LabVIEW automation backends."""

    def __init__(self, config: LabVIEWConfig, repo_path: str | Path) -> None:
        self.config = config
        self.repo_path = Path(repo_path)

    @abc.abstractmethod
    def mass_compile(self, vi_globs: list[str], project_globs: list[str]) -> MassCompileResult:
        """Compile every VI/CTL and report broken VIs / missing dependencies."""

    @abc.abstractmethod
    def vi_analyzer(self, config_path: str) -> ViAnalyzerResult:
        """Run NI VI Analyzer static analysis and return findings."""

    def discover(self, globs: list[str]) -> list[Path]:
        """Return repo-relative paths matching any of the given globs."""

        found: list[Path] = []
        seen: set[Path] = set()
        for pattern in globs:
            for match in sorted(self.repo_path.glob(pattern)):
                rel = match.relative_to(self.repo_path)
                if rel not in seen and match.is_file():
                    seen.add(rel)
                    found.append(rel)
        return found
