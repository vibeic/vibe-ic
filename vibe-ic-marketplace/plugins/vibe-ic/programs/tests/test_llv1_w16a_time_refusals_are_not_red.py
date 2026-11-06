"""llv1 W16a (review wave 8): a refusal caused by TIME is never a plain red.

`librelane_contract.run_container` raises `LL_TOOL_DEADLINE` when a probe runs
past its deadline and `LL_TOOL_STALLED` when the watchdog reaps a tool whose CPU
and output were flat for the grace. Neither is a verdict about the design or the
tool's output. The binding rule is that only a plain FAIL is red; NOT_MEASURED
carries the reason. Before this, every consumer booked any LibreLane refusal as
FAIL:
  * phase 3 step 15 (`_prepare_librelane_floorplan_for_route`) and step 31
    (`_step31_librelane`) returned status FAIL;
  * the analog A6 / A7 producers exited rc 1 with the `FAIL:` token;
  * the ADVISORY SI helpers let the refusal escape (their contract is "on any
    unavailability leave sbody untouched and keep the floating-victim screen").

A refusal that IS about the tool (LL_STEP_FAILED) stays FAIL: the control.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import librelane_contract as contract  # noqa: E402
import phase3_one_shot_runner as runner  # noqa: E402

TIME = ["LL_TOOL_DEADLINE", "LL_TOOL_STALLED"]  # pinned below against contract.TIME_REFUSALS


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"w16a_{name}", PROGRAMS / "tests" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_time_refusals_are_the_two_run_container_raises():
    assert contract.TIME_REFUSALS == {"LL_TOOL_DEADLINE", "LL_TOOL_STALLED"}


# ── phase 3 step 15 ─────────────────────────────────────────────────────────

def _step15(tmp_path, monkeypatch, code):
    f30 = _load("test_f30_ll_chain_gaps")
    real = f30._drive_branch.__globals__["contract"]

    def refusing_chain(*_a, **_k):
        raise contract.Refusal(code, "the chain was stopped")
    # `_drive_branch` installs its own chain; wrap setattr so ours wins.
    original = monkeypatch.setattr

    def setattr_(target, name, value, *a, **k):
        if target is real and name == "run_chain":
            value = refusing_chain
        return original(target, name, value, *a, **k)
    monkeypatch.setattr = setattr_
    try:
        result, consumer, _calls, _pdk = f30._drive_branch(tmp_path, monkeypatch, {})
    finally:
        monkeypatch.setattr = original
    return result, consumer


@pytest.mark.parametrize("code", TIME)
def test_step15_books_a_time_refusal_not_measured(tmp_path, monkeypatch, code):
    result, consumer = _step15(tmp_path, monkeypatch, code)
    assert consumer is None
    assert result.status == "NOT_MEASURED", (result.status, result.detail)
    assert result.detail.startswith(code)
    assert result.reason_class == {
        "LL_TOOL_STALLED": runner._V.ReasonClass.STALLED.value,
        "LL_TOOL_DEADLINE": runner._V.ReasonClass.BUDGET_EXHAUSTED.value,
    }[code]


def test_step15_still_books_a_tool_refusal_fail(tmp_path, monkeypatch):
    result, _consumer = _step15(tmp_path, monkeypatch, "LL_STEP_FAILED")
    assert result.status == "FAIL" and result.detail.startswith("LL_STEP_FAILED")


# ── phase 3 step 31 ─────────────────────────────────────────────────────────







# ── analog A6 / A7 ──────────────────────────────────────────────────────────

def _refusing_resolve(code):
    def resolve(*_a, **_k):
        raise contract.Refusal(code, "the probe was stopped")
    return resolve


@pytest.mark.parametrize("code", TIME)
def test_a6_exits_env_refused_on_a_time_refusal(tmp_path, monkeypatch, capsys, code):
    t6 = _load("test_analog_a6_librelane_drc")
    import _analog_producer_common as pc
    t6.state_the_image(monkeypatch)
    d = tmp_path / "bin"
    d.mkdir()
    (d / "docker").write_text(t6.STUB)
    (d / "docker").chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(contract, "resolve_step_config", _refusing_resolve(code))
    project = t6._project(tmp_path)
    assert t6.A6.run(project, "blk", t6.IMAGE, {}) == pc.EX_ENV_REFUSED
    assert pc.ENV_REFUSED_TOKEN in capsys.readouterr().err


@pytest.mark.parametrize("code", TIME)
def test_a7_exits_env_refused_on_a_time_refusal(tmp_path, monkeypatch, code):
    t7 = _load("test_analog_a7_post_layout_emit")
    import _analog_producer_common as pc
    t7.state_the_image(monkeypatch)
    d = tmp_path / "bin"
    d.mkdir()
    (d / "docker").write_text(t7.STUB)
    (d / "docker").chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("STUB_ROOT", str(tmp_path))
    monkeypatch.setenv("STUB_DIGEST", t7.PIN.IMAGE_DIGEST)
    monkeypatch.setenv("VIBEIC_DESIGNS_HOST_ROOT", str(tmp_path))
    monkeypatch.setattr(contract, "resolve_step_config", _refusing_resolve(code))
    project = t7._project(tmp_path)
    assert t7.A7.run(project, "blk", "vibeic-eda", t7.IMAGE) == pc.EX_ENV_REFUSED


# ── the advisory SI helpers ─────────────────────────────────────────────────
