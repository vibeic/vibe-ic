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
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

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

def _step31(tmp_path, monkeypatch, code):
    import _gdsii
    import librelane_pv_signoff as pv

    project = tmp_path / "p"
    project.mkdir()
    views = {"gds": str(_gdsii.write_gdsii(project / "chip.gds", cell="chip"))}
    for role, body in {
        "def": "VERSION 5.8 ;\nDESIGN chip ;\nEND DESIGN\n",
        "nl": "module chip(); endmodule\n",
        "sdc": "create_clock -name clk -period 10 [get_ports clk]\n",
    }.items():
        path = project / f"chip.{role}"
        path.write_text(body)
        views[role] = str(path)
    (project / "state_out.json").write_text(json.dumps(views))

    def refusing(*_a, **_k):
        raise contract.Refusal(code, "the half was stopped")
    monkeypatch.setattr(contract, "resolve_image", lambda p: "img")
    monkeypatch.setattr(contract, "resolve_pdk_root", lambda *a, **k: tmp_path)
    monkeypatch.setattr(pv, "run_half", refusing)
    return runner._step31_librelane(project, "chip", SimpleNamespace(name="procA"), "drc",
                                    publish=False)


@pytest.mark.parametrize("code", TIME)
def test_step31_books_a_time_refusal_not_measured(tmp_path, monkeypatch, code):
    row = _step31(tmp_path, monkeypatch, code)
    assert row.status == "NOT_MEASURED", (row.status, row.detail)
    assert code in row.detail


def test_step31_still_books_a_tool_refusal_fail(tmp_path, monkeypatch):
    assert _step31(tmp_path, monkeypatch, "LL_STEP_FAILED").status == "FAIL"


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

def _si(monkeypatch, code):
    import librelane_signoff as ls

    def refusing(*_a, **_k):
        raise contract.Refusal(code, "the STA run was stopped")
    monkeypatch.setattr(ls, "run_sta_script", refusing)
    mod = SimpleNamespace(build_opensta_si_tcl=lambda *a, **k: "# tcl",
                          kernel_overlap_rows=lambda *a, **k: ([], 0),
                          kernel_overlap_tcl=lambda rows: "# tcl")
    monkeypatch.setattr(runner, "_si_timing_aware_module", lambda: mod)
    return {"liberties": ["a.lib"], "netlist": "n.v", "design": "top", "sdc": "c.sdc",
            "spef": "x.spef", "image": "img", "mounts": [], "corner": "nom"}


@pytest.mark.parametrize("code", TIME)
def test_the_si_windows_helper_keeps_the_floating_screen(tmp_path, monkeypatch, code):
    tool = _si(monkeypatch, code)
    notes: list = []
    assert runner._librelane_si_windows_json(tmp_path, "top", tool, tmp_path / "si.json", notes) is False
    assert code in notes[-1] and "floating-victim screen" in notes[-1]


@pytest.mark.parametrize("code", TIME)
def test_the_si_kernel_check_withdraws_to_not_measured(tmp_path, monkeypatch, code):
    tool = _si(monkeypatch, code)
    spef = tmp_path / "x.spef"
    spef.write_text("*SPEF\n")
    sbody = {"delta_delay": {"verdict": "PASS"}}
    notes: list = []
    runner._librelane_si_kernel_check(tmp_path, "top", tool, spef, tmp_path / "t.json", sbody, notes)
    assert sbody["kernel_cross_check"]["verdict"] == "NOT_MEASURED"
    assert code in sbody["kernel_cross_check"]["reason"]
    assert sbody["delta_delay"]["verdict"] == "NOT_MEASURED"
    assert sbody["delta_delay_verdict"] == "NOT_MEASURED"
