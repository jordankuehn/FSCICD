"""FSCICD: Full-Stack CI/CD for LabVIEW code.

Runs containerized LabVIEW automation (Mass Compile, VI Analyzer) against a
repository, renders shareable reports, and reports build status back to
Bitbucket. LabVIEW execution is pluggable so the orchestration, reporting and
integration layers can be developed and tested without a LabVIEW install.
"""

__version__ = "0.1.0"
