"""One-way Bitbucket -> GitHub repository mirror.

Option B of the FSCICD design keeps the GitHub-Actions-based LabVIEW CI engine
and mirrors Bitbucket repositories into GitHub so Actions can drive CI. This is
a thin wrapper around ``git`` that performs a mirror push. It supports a
``dry_run`` mode that returns the commands it would run without executing them.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class MirrorPlan:
    source_remote: str
    target_remote: str

    def commands(self) -> list[list[str]]:
        return [
            ["git", "remote", "set-url", "--push", "origin", self.target_remote],
            ["git", "push", "--mirror", self.target_remote],
        ]


def mirror(source_remote: str, target_remote: str, dry_run: bool = True) -> list[list[str]]:
    """Mirror ``source_remote`` to ``target_remote``.

    Returns the list of git commands. When ``dry_run`` is False they are also
    executed in order.
    """

    plan = MirrorPlan(source_remote=source_remote, target_remote=target_remote)
    cmds = plan.commands()
    if not dry_run:
        for cmd in cmds:
            subprocess.run(cmd, check=True)  # noqa: S603
    return cmds
