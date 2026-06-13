"""tests/test_emit_final_summary.py — v1.6.32

Verifies the shared `_path_layout.emit_final_summary()` helper that the
5 one-shot runners now call before their DONE banners.

Coverage:
  1. helper returns True when final_report_generate.py exits 0
  2. helper returns False when final_report_generate.py exits != 0
  3. helper returns False when final_report_generate.py is absent
  4. helper does not raise on subprocess timeout / OSError
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from programs._path_layout import emit_final_summary


def _make_fake_programs_dir(tmp_path: Path, exit_code: int = 0,
                            slow: bool = False) -> Path:
    """Make a programs/ dir with a fake final_report_generate.py that
    exits with `exit_code`. If `slow`, sleep 5s (to test timeout)."""
    pdir = tmp_path / "programs"
    pdir.mkdir()
    body = ["import sys"]
    if slow:
        body.append("import time; time.sleep(5)")
    body.append(f"sys.exit({exit_code})")
    (pdir / "final_report_generate.py").write_text("\n".join(body))
    return pdir


def test_helper_returns_true_on_success(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    pdir = _make_fake_programs_dir(tmp_path, exit_code=0)
    assert emit_final_summary(project, programs_dir=pdir) is True


def test_helper_returns_false_on_nonzero_exit(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    pdir = _make_fake_programs_dir(tmp_path, exit_code=3)
    assert emit_final_summary(project, programs_dir=pdir) is False


def test_helper_returns_false_when_tool_absent(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    pdir = tmp_path / "empty_programs"
    pdir.mkdir()  # no final_report_generate.py inside
    assert emit_final_summary(project, programs_dir=pdir) is False


def test_helper_returns_false_on_timeout(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    pdir = _make_fake_programs_dir(tmp_path, slow=True)
    assert emit_final_summary(project, programs_dir=pdir, timeout=1) is False
