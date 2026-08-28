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
    exits with `exit_code`. If `slow`, sleep 5s — a child that takes real
    time but exits cleanly, which must be reported by its EXIT STATUS."""
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


def test_a_slow_child_is_not_killed_and_its_verdict_is_its_own(tmp_path: Path) -> None:
    """RE-ANCHORED, because the property it used to assert was DELETED.

    It read `emit_final_summary(..., timeout=1) is False` over a child that
    sleeps 5 s — i.e. it asserted that a fixed one-second bound turns a slow
    child into a failure. That parameter is gone: the helper's own docstring
    says why in as many words — "#525 sized an OUTER bound from the child's OWN
    size-adaptive audit budget, because a fixed 240s cap was killing the child
    before #469's 900-3600s inner budget could even apply. Sizing a bound better
    is still guessing at one." Passing `timeout=` now raises TypeError, so the
    case was failing on the SIGNATURE, never on the behaviour.

    The behaviour worth pinning is the inverse of what it used to pin: a child
    that takes longer than some number of seconds but EXITS CLEANLY must be
    reported by its own exit status, not by the clock. That is the whole point
    of supervising by progress, and it is what a reinstated `timeout=` would
    break first.
    """
    project = tmp_path / "proj"
    project.mkdir()
    pdir = _make_fake_programs_dir(tmp_path, slow=True)          # sleeps, exits 0
    assert emit_final_summary(project, programs_dir=pdir) is True

    alt = tmp_path / "b"
    alt.mkdir()
    pdir_bad = _make_fake_programs_dir(alt, exit_code=3, slow=True)
    assert emit_final_summary(project, programs_dir=pdir_bad) is False


def test_the_helper_takes_no_timeout_parameter(tmp_path: Path) -> None:
    """The deletion is the subject, so it is pinned rather than assumed.

    A helper that quietly regrows a `timeout=` kwarg would pass every other case
    in this file while reintroducing exactly the defect #525 removed. Absence is
    only enforced if something asserts it.
    """
    import inspect
    sig = inspect.signature(emit_final_summary)
    assert "timeout" not in sig.parameters, (
        f"emit_final_summary grew a `timeout` parameter back: {sig}. A fixed "
        f"bound here decides a verdict about a child whose honest runtime is "
        f"size-dependent — that is what it was removed for.")
