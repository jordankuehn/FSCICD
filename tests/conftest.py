from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """A minimal LabVIEW-like checkout with clean and problematic VIs."""

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Main.vi").write_text("vi")
    (tmp_path / "src" / "Filter.vi").write_text("vi")
    (tmp_path / "src" / "Config.ctl").write_text("ctl")
    (tmp_path / "Project.lvproj").write_text("<Project/>")
    return tmp_path


@pytest.fixture
def broken_repo(tmp_path: Path) -> Path:
    (tmp_path / "Broken Widget.vi").write_text("vi")
    (tmp_path / "Missing Loader.vi").write_text("vi")
    (tmp_path / "Good.vi").write_text("vi")
    return tmp_path
