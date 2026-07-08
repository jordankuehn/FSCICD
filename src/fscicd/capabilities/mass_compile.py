"""Mass Compile capability: compile every VI and flag build breakages."""

from __future__ import annotations

from fscicd.config import MassCompileConfig
from fscicd.labview.base import LabVIEWRunner
from fscicd.models import CapabilityResult, Status


def run_mass_compile(runner: LabVIEWRunner, config: MassCompileConfig) -> CapabilityResult:
    result = runner.mass_compile(config.vi_globs, config.project_globs)
    if result.status is Status.SKIPPED:
        summary = "No VIs found to compile."
    elif result.status is Status.FAILED:
        summary = f"{result.broken} of {result.total} VIs broken."
    else:
        summary = f"All {result.total} VIs compiled cleanly."
    return CapabilityResult(
        name="Mass Compile",
        status=result.status,
        summary=summary,
        details={
            "total": result.total,
            "compiled": result.compiled,
            "broken": result.broken,
            "vis": [vars(v) for v in result.vis],
        },
    )
