"""v0.2.100 — flow #488 (#486 residual): test_program_reachability_check
was dormant on BOTH trees because TOOL_REL pointed at repo-root tools/
while the tool lives under vibe-ic-marketplace/tools/, and the skip
wording misleadingly blamed the two-tree not-shipped case.

Pins:
  * TOOL_REL is marketplace-relative and resolves on the source tree
    (the 4 reachability tests RUN, not skip);
  * repo_resource_or_skip(required_on_source=True) FAILs with the
    path-misplaced diagnosis on a source tree missing the resource —
    never the not-shipped skip wording;
  * the flattened cache tree (no repo root) still yields the legitimate
    NAMED not-shipped skip, required_on_source notwithstanding.
"""
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
import _plugin_tree as PT  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


def test_tool_rel_resolves_on_source_tree():
    rr = PT.repo_root()
    if rr is None:
        pytest.skip("cache tree — source-resolution pin runs on the source tree")
    assert (rr / "vibe-ic-marketplace" / "tools"
            / "program_reachability_check.py").is_file()


def test_reachability_tests_run_not_skip_on_source():
    # 驗收①: SOURCE 樹 pytest test_program_reachability_check → 4 passed（非 skip）
    if PT.repo_root() is None:
        pytest.skip("cache tree — acceptance pin runs on the source tree")
    r = _pr.run(
        [sys.executable, "-m", "pytest", "-q",
         str(TESTS / "test_program_reachability_check.py")],
        capture_output=True, text=True, cwd=str(PT.plugin_root()))
    assert "4 passed" in r.stdout, r.stdout + r.stderr
    assert "skipped" not in r.stdout, r.stdout


def test_required_on_source_fails_loud_when_misplaced(monkeypatch, tmp_path):
    # source tree present, resource absent + required_on_source=True
    # → pytest.fail with the path-misplaced diagnosis (not a skip).
    monkeypatch.setattr(PT, "repo_root", lambda: tmp_path)
    with pytest.raises(BaseException) as ei:
        PT.repo_resource_or_skip("tools", "nope.py", required_on_source=True)
    msg = str(ei.value)
    assert "path misplaced" in msg
    assert "not shipped" not in msg.lower()
    assert ei.value.__class__.__name__ == "Failed"   # fail, not skip


def test_cache_tree_still_named_skip(monkeypatch):
    # no repo root (flattened cache) → legitimate NAMED not-shipped skip,
    # even with required_on_source=True (驗收②).
    monkeypatch.setattr(PT, "repo_root", lambda: None)
    with pytest.raises(BaseException) as ei:
        PT.repo_resource_or_skip("vibe-ic-marketplace", "tools", "x.py",
                                 required_on_source=True)
    assert ei.value.__class__.__name__ == "Skipped"
    assert PT.NOT_SHIPPED_REASON.split("—")[0].strip() in str(ei.value) \
        or "not shipped" in str(ei.value)


def test_default_missing_resource_still_skips(monkeypatch, tmp_path):
    # regression guard: default callers (no required_on_source) keep the
    # honest skip for resources legitimately absent on a source checkout.
    monkeypatch.setattr(PT, "repo_root", lambda: tmp_path)
    with pytest.raises(BaseException) as ei:
        PT.repo_resource_or_skip("benchmark_dir_that_may_be_absent")
    assert ei.value.__class__.__name__ == "Skipped"
