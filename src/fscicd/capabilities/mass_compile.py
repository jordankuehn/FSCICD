"""Mass Compile capability: compile every VI and flag build breakages."""

from __future__ import annotations

from fscicd.config import MassCompileConfig
from fscicd.labview.base import LabVIEWRunner
from fscicd.models import CapabilityResult, Status


def run_mass_compile(runner: LabVIEWRunner, config: MassCompileConfig) -> CapabilityResult:
    result = runner.mass_compile(config.vi_globs, config.project_globs)
    # Report compiled and skipped counts, not just failures: LabVIEW skipping
    # every file looks identical to a clean build unless the numbers are shown.
    tail = f"{result.compiled} compiled, {result.skipped} skipped"
    if result.status is Status.SKIPPED:
        summary = "No VIs found to compile."
    elif result.status is Status.FAILED:
        summary = f"{result.broken} of {result.total} files failed to compile ({tail})."
    else:
        summary = f"{result.total} files checked ({tail})."
    return CapabilityResult(
        name="Mass Compile",
        status=result.status,
        summary=summary,
        details={
            "total": result.total,
            "compiled": result.compiled,
            "broken": result.broken,
            "skipped": result.skipped,
            "vis": [vars(v) for v in result.vis],
        },
    )
