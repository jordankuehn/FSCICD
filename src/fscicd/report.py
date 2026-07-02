"""Render pipeline results to shareable HTML and machine-readable JSON."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from fscicd.models import PipelineResult, Status

_env = Environment(
    loader=PackageLoader("fscicd", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def _to_jsonable(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, Status):
        return obj.value
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    return obj


def render_html(result: PipelineResult) -> str:
    template = _env.get_template("report.html.j2")
    generated_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return template.render(result=result, generated_at=generated_at)


def render_json(result: PipelineResult) -> str:
    payload = {
        "project_name": result.project_name,
        "commit": result.commit,
        "status": result.status.value,
        "capabilities": [_to_jsonable(c) for c in result.capabilities],
    }
    return json.dumps(payload, indent=2)


def write_reports(result: PipelineResult, output_dir: str | Path) -> dict[str, Path]:
    """Write ``report.html`` and ``report.json`` and return their paths."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / "report.html"
    json_path = out / "report.json"
    html_path.write_text(render_html(result))
    json_path.write_text(render_json(result))
    return {"html": html_path, "json": json_path}
