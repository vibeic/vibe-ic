"""ENV_UNAVAILABLE must name something the environment is actually missing.

The sign-off DRC step declines for two unrelated reasons and reported one
message for both:

  * the native engine is not on PATH   — an environment gap
  * there is no layout to check        — an upstream step produced no GDS

Only the first is an environment gap, and ENV_UNAVAILABLE carries a WAIVER
tier: the compliance gate turns the step's natural verdict into
WAIVED-DEFERRED on the strength of that claim. So the second case silently
suppressed a failing Physical-Verification step by blaming the image.

Measured on a real run: `command -v <engine>` resolved inside the very
container the message named, while the step reported the engine "was not found
on PATH" and Step 31's natural FAIL became WAIVED-DEFERRED. The GDS was absent
because an upstream step had failed and stream-out never ran.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import phase3_one_shot_runner as R  # noqa: E402


class _Pdk:
    drc_deck = None
    calibre_drc = "/some/deck.rule"


@pytest.fixture
def project(tmp_path):
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    return tmp_path


def _patch(monkeypatch, *, engine, gds_present, project, top):
    monkeypatch.setattr(R, "_tool_in_path", lambda *a, **k: False)
    monkeypatch.setattr(R, "_svrfdrc_bin_container", lambda *a, **k: engine)
    # the native path always declines here; the caller must then diagnose WHY
    monkeypatch.setattr(R, "_try_svrf_native_drc", lambda *a, **k: None)
    if gds_present:
        (R._pl.pnr_dir(project) / f"{top}.gds").write_text("gds")


def test_no_layout_is_not_an_environment_gap(project, monkeypatch):
    _patch(monkeypatch, engine="/tools/svrfdrc", gds_present=False,
           project=project, top="topx")
    res = R.step_drc(project, "topx", _Pdk(), "somecontainer")
    assert res.status != "ENV_UNAVAILABLE", (
        "a missing GDS must never claim the environment is missing a tool — "
        "that claim carries a waiver tier")
    assert res.status == "SKIP"
    assert "DRC_NO_LAYOUT" in res.detail
    # it must say the engine IS there, so no reader goes chasing the image
    assert "/tools/svrfdrc" in res.detail
    assert res.extras["missing_input"] == "gds"


def test_a_genuinely_absent_engine_is_still_an_environment_gap(
        project, monkeypatch):
    _patch(monkeypatch, engine=None, gds_present=True,
           project=project, top="topx")
    res = R.step_drc(project, "topx", _Pdk(), "somecontainer")
    assert res.status == "ENV_UNAVAILABLE"
    assert res.extras["missing_tool"] == "calibre|svrfdrc"


def test_engine_absent_and_no_layout_still_reports_the_environment(
        project, monkeypatch):
    """With BOTH absent the environment gap is the one a reader can act on."""
    _patch(monkeypatch, engine=None, gds_present=False,
           project=project, top="topx")
    res = R.step_drc(project, "topx", _Pdk(), "somecontainer")
    assert res.status == "ENV_UNAVAILABLE"


def test_the_native_path_running_is_unchanged(project, monkeypatch):
    """When the engine runs, its own result is returned untouched."""
    monkeypatch.setattr(R, "_tool_in_path", lambda *a, **k: False)
    sentinel = R.StepResult("drc", "FAIL", 0.0, "15 rules fired", [])
    monkeypatch.setattr(R, "_try_svrf_native_drc", lambda *a, **k: sentinel)
    res = R.step_drc(project, "topx", _Pdk(), "somecontainer")
    assert res is sentinel
