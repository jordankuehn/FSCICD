"""FSCICD command-line interface."""

from __future__ import annotations

import logging
import sys

import click

from fscicd import __version__
from fscicd.bitbucket import BitbucketClient, BitbucketError
from fscicd.config import ConfigError, load_config
from fscicd.labview.container import ContainerRunnerError
from fscicd.models import Status
from fscicd.pipeline import run_pipeline
from fscicd.report import write_reports

_EXIT_FAILURE = 2


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


@click.group()
@click.version_option(__version__, prog_name="fscicd")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """FSCICD — Full-Stack CI/CD for LabVIEW code."""

    ctx.ensure_object(dict)
    _configure_logging(verbose)


@main.command()
@click.option("-c", "--config", "config_path", default="fscicd.yml", show_default=True)
@click.option("-p", "--repo-path", default=".", show_default=True, help="Path to the checkout.")
@click.option("--commit", default="HEAD", show_default=True, help="Commit SHA under test.")
@click.option("--report-url", default=None, help="Public URL where the report is published.")
@click.option("--no-status", is_flag=True, help="Do not post a Bitbucket build status.")
def run(config_path, repo_path, commit, report_url, no_status):
    """Run the full pipeline: capabilities -> report -> Bitbucket status."""

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        result = run_pipeline(config, repo_path, commit)
    except ContainerRunnerError as exc:
        # The LabVIEW backend could not be driven at all (no Docker, unreachable
        # daemon, missing image). That is an environment fault, not a code-quality
        # verdict, so report it as one instead of a traceback.
        raise click.ClickException(f"LabVIEW backend unavailable: {exc}") from exc

    paths = write_reports(result, config.report_dir)

    click.echo(f"Project : {result.project_name}")
    click.echo(f"Commit  : {result.commit}")
    for cap in result.capabilities:
        click.echo(f"  - {cap.name}: {cap.status.value} — {cap.summary}")
    click.echo(f"Report  : {paths['html']}")
    click.echo(f"Overall : {result.status.value}")

    if not no_status:
        client = BitbucketClient(config.bitbucket.workspace, config.bitbucket.repo_slug)
        try:
            outcome = client.post_build_status(commit, result, report_url)
        except BitbucketError as exc:
            click.echo(f"Bitbucket: WARNING — {exc}", err=True)
        else:
            if outcome.get("dry_run"):
                click.echo("Bitbucket: dry-run (no credentials/workspace configured).")
            else:
                click.echo("Bitbucket: build status posted.")

    if result.status is Status.FAILED:
        sys.exit(_EXIT_FAILURE)


if __name__ == "__main__":  # pragma: no cover
    main()
