#!/usr/bin/env python3
"""Tests for analog_one_shot_runner.py — A1-A9 analog flow orchestrator.

Wave 83 — coverage for previously untested orchestrator.

The runner walks each declared analog block through 9 steps. When no
deterministic program ships for a step it returns WAIVED with the skill
name. When no analog blocks are declared the runner SKIPs cleanly.

Cases:
  1. SKIP_PURE_DIGITAL — no analog_block_list.json + L5 absent → SKIP exit 0,
                           reports/analog_one_shot.json verdict=SKIP.
  2. POSITIVE_FAIL_MISSING_PROJECT — non-existent project dir → exit 2.
  3. PASS_WITH_WAIVERS_ONE_BLOCK — one block declared and nothing else staged
                                     → 9 steps emitted, verdict FAIL / rc 1.
                                     Since the `required_inputs` pre-flight was
                                     wired into this runner, A1-A7 are BLOCKED
                                     (refused for want of input, NEVER RAN) and
                                     name the artefact they were owed; A8/A9
                                     declare no inputs and still WAIVE. The
                                     verdict and exit code are unchanged.
  4. INTEGRATION_REPORT_SHAPE — phase=analog, blocks list, steps list.
  5. SKIP_VIA_L5_NO_ANALOG — L5_ADI_SPEC.json#no_analog=true → SKIP.
  6. EDGE_BLOCKS_FILTER — `--blocks <name>` selects subset of declared blocks.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / \
    "analog_one_shot_runner.py"


def _run(args: list, timeout: int = 60) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True)


def _write_block_list(project: Path, blocks: list) -> None:
    a = project / "phase3" / "analog"
    a.mkdir(parents=True, exist_ok=True)
    (a / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}, indent=2))


def test_fail_no_block_list_when_missing(tmp_path):
    """v1.6.128 (#50 Fix 1) — when neither analog/analog_block_list.json
    NOR generated_docs/L5_ADI_SPEC.json exists, the runner refuses
    to silently SKIP. It emits FAIL_NO_BLOCK_LIST so the caller
    knows phase1 / spec-extract was missed.
    """
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 2, cp.stderr
    rep = project / "reports" / "phase3" / "analog_one_shot.json"
    body = json.loads(rep.read_text())
    assert body["phase"] == "analog"
    assert body["verdict"] == "FAIL_NO_BLOCK_LIST"
    assert body["blocks"] == []


def test_skip_pure_digital_with_empty_block_list(tmp_path):
    """v1.6.128 (#50 Fix 1) — explicit empty block list `[]` is the
    canonical "this project has no analog" signal. Runner SKIPs
    cleanly with rc=0 + verdict=SKIP.
    """
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_block_list(project, [])  # explicit empty list
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stderr
    assert "[SKIP]" in cp.stdout
    rep = project / "reports" / "phase3" / "analog_one_shot.json"
    body = json.loads(rep.read_text())
    assert body["phase"] == "analog"
    assert body["verdict"] == "SKIP"
    assert body["blocks"] == []


def test_positive_fail_missing_project(tmp_path):
    missing = tmp_path / "no_such"
    cp = _run([str(missing)])
    assert cp.returncode == 2
    assert "not a directory" in cp.stderr


def test_pass_with_waivers_one_block(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_block_list(project, [
        {"name": "tst_bandgap", "type": "bandgap"},
    ])
    cp = _run([str(project)])
    body = json.loads(
        (project / "reports" / "phase3" / "analog_one_shot.json").read_text())
    assert "tst_bandgap" in body["blocks"]
    # 9 A* steps × 1 block = 9 step entries (A1-A9 canonical).
    assert len(body["steps"]) == 9
    # The top-level verdict and the exit code are UNCHANGED by the
    # `required_inputs` pre-flight: FAIL / rc 1, exactly as before.
    assert body["verdict"] == "FAIL"
    assert cp.returncode == 1
    step_status = {s["name"]: s["status"] for s in body["steps"]}

    # WHAT CHANGED IS THE ATTRIBUTION, and that is the point.
    #
    # This fixture declares a block and stages NOTHING else — no L-docs, no
    # spec, no netlist, no layout. It used to be recorded as `A6_block_pv:
    # FAIL — no parseable LVS result`, with A1/A7 WAIVED. That charges the
    # absence to A6, a step that never had a layout to verify, and it left the
    # ROOT cause (Phase 1 produced no L1/L5 at all, so A1 could not start)
    # invisible behind seven downstream symptoms.
    #
    # With the pre-flight wired, every step of the chain is BLOCKED and NAMES
    # the artefact it was owed and the step that owed it, so a reader is
    # pointed at the first absence instead of the last symptom. `BLOCKED` is in
    # `_aggregate_verdict._FAIL_STATUSES`, so nothing became greener: the
    # distinction preserved here is exactly `step_preflight`'s —
    #   BLOCKED = refused for want of input, NEVER RAN
    #   FAIL    = ran and did not pass
    for name in ("A1_spec_extract", "A2_topology_select", "A3_netlist_gen",
                 "A4_corner_sweep", "A5_layout", "A6_block_pv",
                 "A7_post_layout_resim"):
        assert step_status[name] == "BLOCKED", (
            f"{name} should be refused for want of input, not run")
    a1 = next(s for s in body["steps"] if s["name"] == "A1_spec_extract")
    assert "L5_ADI_SPEC.json" in a1["detail"] and "owed by step D1" in a1["detail"]
    assert a1["extras"]["finding"] == "REQUIRED_INPUT_ABSENT"
    # A8/A9 declare NO required_inputs in the flow, so nothing can be charged
    # to them and they still run and WAIVE on their own evidence.
    for name in ("A8_hardmacro_gen", "A9_hw_verify"):
        assert step_status[name] == "WAIVED"


def test_integration_report_shape(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_block_list(project, [{"name": "tst_ldo"}])
    cp = _run([str(project)])
    body = json.loads(
        (project / "reports" / "phase3" / "analog_one_shot.json").read_text())
    for k in ("phase", "project", "blocks", "steps", "verdict"):
        assert k in body
    # Each step entry has name + block + status fields.
    for s in body["steps"]:
        assert "name" in s and "block" in s and "status" in s


def test_skip_via_l5_no_analog(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({"no_analog": True}))
    cp = _run([str(project)])
    assert cp.returncode == 0
    body = json.loads(
        (project / "reports" / "phase3" / "analog_one_shot.json").read_text())
    assert body["verdict"] == "SKIP"


def test_edge_blocks_filter(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_block_list(project, [
        {"name": "tst_bandgap"},
        {"name": "tst_ldo"},
        {"name": "tst_pll"},
    ])
    cp = _run([str(project), "--blocks", "tst_ldo"])
    body = json.loads(
        (project / "reports" / "phase3" / "analog_one_shot.json").read_text())
    assert body["blocks"] == ["tst_ldo"]
    # 9 steps × 1 selected block (A1-A9 canonical).
    assert len(body["steps"]) == 9


# ---------------------------------------------------------------------------
# vibe-ic#2010 items 1-2 — the macro/RTL interface check is ENFORCED at A8:
# invoked inline, per block, and its rc 1 is the block's A8 FAIL.
# ---------------------------------------------------------------------------

def _drive_a8(tmp_path, monkeypatch, iface_rc, iface_out):
    """Run A8 for one block with the two spawn channels stubbed: the
    `subprocess` module (the fail-open producers) and `_progress_run.run`
    (the gates). Returns (StepResult, argv list handed to `_pr.run`)."""
    import subprocess as _sp
    import analog_one_shot_runner as AOSR

    class _Quiet:
        def run(self, argv, **kw):
            return _sp.CompletedProcess(argv, 0, "", "")

        def __getattr__(self, name):
            return getattr(_sp, name)

    monkeypatch.setattr(AOSR, "subprocess", _Quiet())
    seen = []

    class _Gates:
        @staticmethod
        def run(argv, **kw):
            seen.append([str(a) for a in argv])
            prog = Path(argv[1]).name
            if prog == "analog_macro_rtl_interface_check.py":
                return _sp.CompletedProcess(argv, iface_rc, iface_out, "")
            return _sp.CompletedProcess(argv, 0, "PASS: stubbed gate\n", "")

    monkeypatch.setattr(AOSR, "_pr", _Gates())
    proj = tmp_path / "proj"
    (proj / "phase3" / "analog").mkdir(parents=True, exist_ok=True)
    r = AOSR.step_for_block(proj, {"name": "bandgap"}, "A8_hardmacro_gen", None)
    return r, seen


def test_a8_fails_the_block_when_the_macro_and_rtl_interfaces_disagree(
        tmp_path, monkeypatch):
    r, seen = _drive_a8(tmp_path, monkeypatch, 1,
                        "  [bandgap] MACRO_RTL_INTERFACE_DISAGREES\n"
                        "FAIL: 1/1 block(s) disagree\n")
    assert r.status == "FAIL", r
    assert "interface disagrees" in r.detail and "1/1" in r.detail
    assert r.extras["macro_rtl_interface_rc"] == 1
    iface = [c for c in seen
             if Path(c[1]).name == "analog_macro_rtl_interface_check.py"]
    assert len(iface) == 1, seen
    argv = iface[0]
    assert "--block" in argv and "bandgap" in argv and "--json" in argv, argv
    assert str(tmp_path / "proj") in argv


def test_a8_stands_on_the_gates_pass_when_the_interfaces_agree_or_cannot_compare(
        tmp_path, monkeypatch):
    r, _ = _drive_a8(tmp_path, monkeypatch, 0, "PASS: 1/1 block(s) agree\n")
    assert r.status == "PASS", r
    # rc 2 — no comparable pair yet — is a disclosed skip, not a FAIL
    r2, _ = _drive_a8(tmp_path, monkeypatch, 2, "VACUOUS: nothing could be compared\n")
    assert r2.status == "PASS", r2


def test_the_interface_check_runs_at_a8_and_only_there(tmp_path, monkeypatch):
    import subprocess as _sp
    import analog_one_shot_runner as AOSR

    class _Quiet:
        def run(self, argv, **kw):
            return _sp.CompletedProcess(argv, 0, "", "")

        def __getattr__(self, name):
            return getattr(_sp, name)

    monkeypatch.setattr(AOSR, "subprocess", _Quiet())
    seen = []

    class _Gates:
        @staticmethod
        def run(argv, **kw):
            seen.append(Path(argv[1]).name)
            return _sp.CompletedProcess(argv, 0, "PASS: stubbed\n", "")

    monkeypatch.setattr(AOSR, "_pr", _Gates())
    proj = tmp_path / "proj"
    (proj / "phase3" / "analog").mkdir(parents=True)
    for step in ("A5_layout", "A7_post_layout_resim", "A9_hw_verify"):
        seen.clear()
        AOSR.step_for_block(proj, {"name": "b"}, step, None)
        assert "analog_macro_rtl_interface_check.py" not in seen, (step, seen)
