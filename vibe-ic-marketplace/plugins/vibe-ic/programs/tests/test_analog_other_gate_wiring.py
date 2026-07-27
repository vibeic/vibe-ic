#!/usr/bin/env python3
"""Wiring tests for the `wire/analog_other` bucket.

Seven analog gates that already existed and already worked, plus one
analog/digital ORDERING gate, were reachable only from skill prose or from
their own unit test — so what they check had never been enforced. These
tests assert the WIRING itself, in the exact places it lives, so it cannot
silently fall out again:

  * seven gates registered in
    ``flow_compliance_check._STRUCTURAL_RTL_GATES`` (the P0 structural
    umbrella), which invokes them as ``python3 <gate>.py <project>``;
  * ``analog_a8_before_floorplan_check`` as a blocking
    ``program_exit_zero`` clause on flow Step 15 (Floorplan + PDN), the
    step whose ``blocks_on: [13, 14, A8]`` it makes deterministic;
  * ``analog_mc_yield_run`` invoked as a PRODUCER subprocess from
    ``analog_one_shot_runner`` on the A4 real-sweep path, which is what
    finally puts ``mc_yield_pct`` into ``corner_results.json`` so the
    already-wired ``analog_corner_sweep_check`` assertion stops being
    dead code.

Where practical each wiring is also proved to still FAIL on a bad input
THROUGH the new channel, not just in isolation.
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parent.parent
PLUGIN = PROGRAMS.parent
FLOW_YAML = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PROGRAMS))
import flow_compliance_check as F  # noqa: E402


# The seven gates wired into the P0 structural umbrella by this change.
UMBRELLA_GATES = (
    "analog_a0_skip_forbidden_check",
    "analog_block_list_emit_check",
    "analog_hardmacro_pinname_consistency_check",
    "analog_lef_gds_outline_check",
    "analog_adc_enob_corner_check",
    "analog_sigma_delta_gain_floor_check",
    "analog_corner_lib_realism_lint",
)


# ─────────────────────── (b) P0 structural umbrella ───────────────────────

@pytest.mark.parametrize("gate", UMBRELLA_GATES)
def test_gate_is_registered_in_the_p0_umbrella(gate):
    """The registry entry IS the wiring. Without it nothing runs the gate."""
    assert gate in F._STRUCTURAL_RTL_GATES, (
        f"{gate} fell out of flow_compliance_check._STRUCTURAL_RTL_GATES — "
        f"nothing else in the tree invokes it, so it would go back to being "
        f"a checker only its own unit test ever runs.")


@pytest.mark.parametrize("gate", UMBRELLA_GATES)
def test_gate_program_exists_for_the_registered_name(gate):
    """The umbrella builds PROGRAMS_DIR/f'{gate}.py' and silently `continue`s
    when that file is absent — a typo in the tuple is a SILENT no-op."""
    assert (PROGRAMS / f"{gate}.py").is_file()


@pytest.mark.parametrize("gate", UMBRELLA_GATES)
def test_gate_self_skips_on_a_digital_only_project(tmp_path, gate):
    """The umbrella's wiring criterion: exit 0 (pass) or 2 (skip) when the
    analog artefacts it audits do not exist. A gate that FAILs an empty
    project would redden every digital run the moment it is registered."""
    r = subprocess.run([sys.executable, str(PROGRAMS / f"{gate}.py"),
                        str(tmp_path)], capture_output=True, text=True,
                       cwd=tmp_path, timeout=120)
    assert r.returncode in (0, 2), (
        f"{gate} returned {r.returncode} on an empty project:\n"
        f"{r.stdout}\n{r.stderr}")


@pytest.mark.parametrize("gate", UMBRELLA_GATES)
def test_gate_obeys_skip_analog_through_the_umbrella(gate):
    """`--skip-analog` suppression is derived from _STRUCTURAL_RTL_GATES by
    analog name prefix, so every gate added here must be covered by it."""
    assert gate in F._skip_analog_p0_gates()


def test_umbrella_call_shape_is_a_bare_project_dir(tmp_path):
    """REGRESSION for the shape that made a registered gate INERT.

    `_run_structural_rtl_gates` invokes every gate as
    `python3 <gate>.py <project>` and passes no other flag.
    `analog_block_list_emit_check` used to need `--project` to look inside a
    project at all; a bare directory fell through to file mode and reported
    VACUOUS_PASS on every project no matter how broken its block list."""
    (tmp_path / "phase3" / "analog").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "ldo", "type": "LDO",
                                "spec_file": "analog/ldo/spec.json"}],
                    "block_count": 5}))
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "analog_block_list_emit_check.py"),
         str(tmp_path)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 1, (
        "a bare project-dir argument must reach project mode; got "
        f"rc={r.returncode}\n{r.stdout}\n{r.stderr}")
    assert "BLOCK_COUNT_MISMATCH" in r.stdout


def _mixed_signal_project(root: Path) -> Path:
    """A project carrying one defect per newly-wired umbrella gate."""
    def wr(rel, txt):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt if isinstance(txt, str) else json.dumps(txt, indent=2))

    # RTL, so the umbrella runs at all.
    wr("phase2/stage1/rtl/top.v",
       "module top (input clk, output reg q);\n"
       "  always @(posedge clk) q <= ~q;\nendmodule\n")
    wr("analog/A0_skip_decision.json", {"decision": "skip"})
    wr("phase3/analog/analog_block_list.json",
       {"blocks": [{"name": "ldo", "type": "LDO",
                    "spec_file": "analog/ldo/nowhere.json"},
                   {"name": "adc0", "type": "ADC",
                    "spec_file": "analog/adc0/spec.json"},
                   {"name": "dsm", "type": "MOD",
                    "spec_file": "analog/dsm/spec.json"}],
        "block_count": 7})
    wr("phase3/analog/ldo/ldo.sp",
       "* deck\n.model toynfet nmos (level=1 vto=0.7)\nm1 d g s b toynfet\n.end\n")
    wr("phase3/analog/ldo/spec.json",
       {"interface": {"pins": [{"name": "vin"}, {"name": "vout"}]}})
    wr("phase3/analog/adc0/spec.json", {"specs": [{"name": "enob",
                                                   "target": 10.0}]})
    wr("phase3/analog/adc0/corner_results.json",
       {"corners": [{"name": "tt_27c", "sndr_db": 63.0},
                    {"name": "ss_125c", "sndr_db": 55.0}]})
    wr("phase3/analog/dsm/spec.json",
       {"converter_type": "delta_sigma",
        "specs": [{"name": "osr", "target": 256}]})
    wr("phase3/analog/dsm/corner_results.json",
       {"corners": [{"name": "ss_125c", "ota_dc_gain_db": 42.8}]})
    wr("phase3/analog/hardmacro/ldo/ldo.lef",
       "MACRO ldo\n  SIZE 100.0 BY 100.0 ;\n"
       "  PIN vin\n  END vin\n  PIN wrongpin\n  END wrongpin\nEND ldo\n")
    wr("phase3/analog/hardmacro/ldo/ldo.v",
       "module ldo (input vin, output vout);\nendmodule\n")
    (root / "phase3/analog/hardmacro/ldo/ldo.gds").write_bytes(
        _build_gds(250.0, 80.0))
    return root


def _gds_rec(rtype, dtype, payload=b""):
    return struct.pack(">HBB", 4 + len(payload), rtype, dtype) + payload


def _gds_real8(v):
    if v == 0:
        return b"\x00" * 8
    sign = 0x80 if v < 0 else 0
    v, exp = abs(v), 0
    while v >= 1:
        v /= 16.0
        exp += 1
    while v < 1 / 16.0:
        v *= 16.0
        exp -= 1
    return bytes([sign | (exp + 64)]) + int(v * (1 << 56)).to_bytes(7, "big")


def _build_gds(w_um, h_um):
    o = _gds_rec(0x00, 0x02, struct.pack(">h", 600))
    o += _gds_rec(0x01, 0x02, struct.pack(">12h", *([2024] + [0] * 11)))
    o += _gds_rec(0x02, 0x06, b"LIB\x00")
    o += _gds_rec(0x03, 0x05, _gds_real8(1e-3) + _gds_real8(1e-9))
    o += _gds_rec(0x05, 0x02, struct.pack(">12h", *([2024] + [0] * 11)))
    o += _gds_rec(0x06, 0x06, b"TOP\x00")
    o += _gds_rec(0x08, 0x00) + _gds_rec(0x0D, 0x02, struct.pack(">h", 1))
    o += _gds_rec(0x0E, 0x02, struct.pack(">h", 0))
    W, H = int(w_um * 1000), int(h_um * 1000)
    pts = [(0, 0), (W, 0), (W, H), (0, H), (0, 0)]
    o += _gds_rec(0x10, 0x03,
                  b"".join(struct.pack(">ii", x, y) for x, y in pts))
    o += _gds_rec(0x11, 0x00) + _gds_rec(0x07, 0x00) + _gds_rec(0x04, 0x00)
    return o


def test_umbrella_actually_fails_through_the_new_wiring(tmp_path, monkeypatch):
    """END-TO-END through the channel: run the umbrella (restricted to the
    seven new gates) on a project carrying one defect per gate and require
    every one of them to be reported failing."""
    project = _mixed_signal_project(tmp_path)
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES", UMBRELLA_GATES)
    passed, fails, _skips, _waivers = F._run_structural_rtl_gates(project)
    assert passed is False
    named = {line.split("—")[0].replace("FAIL:", "").strip()
             for line in fails}
    for gate in UMBRELLA_GATES:
        assert gate in named, (
            f"{gate} did not FAIL through the umbrella on a project built to "
            f"trip it. fails={fails}")


def test_umbrella_passes_a_digital_only_project_through_the_new_wiring(
        tmp_path, monkeypatch):
    """The other half of the contract: the same seven gates must leave a
    pure-digital project alone."""
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "top.v").write_text(
        "module top (input clk, output reg q);\n"
        "  always @(posedge clk) q <= ~q;\nendmodule\n")
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES", UMBRELLA_GATES)
    passed, fails, _skips, _waivers = F._run_structural_rtl_gates(tmp_path)
    assert passed is True, f"digital-only project reddened by: {fails}"


# ──────────────── (a) flow-YAML step gate — Step 15 ordering ───────────────

def _flow_steps():
    return yaml.safe_load(FLOW_YAML.read_text())["steps"]


def _step(step_id):
    return next(s for s in _flow_steps() if str(s.get("id")) == str(step_id))


def test_step15_gate_carries_the_a8_ordering_clause():
    """Step 15 declares `blocks_on: [13, 14, A8]`; nothing verified it. The
    clause is what turns that declaration into a deterministic gate."""
    gate = _step(15)["gate"]
    cmds = [sub["program_exit_zero"] for sub in gate["all_of"]
            if isinstance(sub, dict) and "program_exit_zero" in sub]
    assert any(c.split()[0] == "analog_a8_before_floorplan_check"
               for c in cmds), (
        "Step 15 lost its analog_a8_before_floorplan_check clause — a "
        "floorplan DEF written before A8 packaged its hardmacro LEF would "
        "pass again. gate=" + json.dumps(gate))


def test_step15_a8_clause_is_blocking_not_advisory():
    gate = _step(15)["gate"]
    for sub in gate["all_of"]:
        if not isinstance(sub, dict):
            continue
        for slot in ("advisory_program_exit_zero",
                     "optional_program_exit_zero"):
            spec = sub.get(slot)
            cmd = spec if isinstance(spec, str) else (
                spec.get("command") if isinstance(spec, dict) else "")
            assert "analog_a8_before_floorplan_check" not in (cmd or ""), (
                f"the ordering gate must not be demoted to {slot}: it has a "
                f"real rc=1 path and self-skips on digital / pre-floorplan "
                f"projects")


def test_step15_a8_clause_fails_a_real_ordering_inversion(tmp_path):
    """Prove the clause still catches the defect THROUGH the gate evaluator
    the flow uses, not just when the program is run by hand."""
    (tmp_path / "phase3" / "analog").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "ldo"}], "block_count": 1}))
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (tmp_path / "phase3" / "stage3" / "pnr" / "floorplan.def").write_text(
        "DESIGN top ;\nEND DESIGN\n")
    clause = next(sub for sub in _step(15)["gate"]["all_of"]
                  if isinstance(sub, dict)
                  and sub.get("program_exit_zero", "").startswith(
                      "analog_a8_before_floorplan_check"))
    ok, reasons = F._evaluate_gate(tmp_path, clause)
    assert ok is False, f"ordering inversion not caught: {reasons}"

    # …and clears once A8 has packaged the abstract.
    lef = (tmp_path / "phase3" / "analog" / "hardmacro" / "ldo")
    lef.mkdir(parents=True)
    (lef / "ldo.lef").write_text("MACRO ldo\nEND ldo\n")
    ok2, reasons2 = F._evaluate_gate(tmp_path, clause)
    assert ok2 is True, f"clause still red after A8 packaged the LEF: {reasons2}"


def test_step15_a8_clause_is_transparent_to_a_digital_project(tmp_path):
    (tmp_path / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (tmp_path / "phase3" / "stage3" / "pnr" / "floorplan.def").write_text(
        "DESIGN top ;\nEND DESIGN\n")
    clause = next(sub for sub in _step(15)["gate"]["all_of"]
                  if isinstance(sub, dict)
                  and sub.get("program_exit_zero", "").startswith(
                      "analog_a8_before_floorplan_check"))
    ok, reasons = F._evaluate_gate(tmp_path, clause)
    assert ok is True, f"digital-only floorplan reddened: {reasons}"


# ─────────────── (c) runner subprocess — the MC yield PRODUCER ─────────────

def test_analog_one_shot_runner_invokes_the_mc_yield_producer():
    """`analog_corner_sweep_check` has asserted `mc_yield_pct >= 95` since
    v1.6.x and `analog_mc_yield_run` is the only writer of that key in the
    tree — but nothing ran it, so the branch was dead in every real run."""
    src = (PROGRAMS / "analog_one_shot_runner.py").read_text()
    assert "analog_mc_yield_run.py" in src, (
        "analog_one_shot_runner no longer invokes analog_mc_yield_run — "
        "corner_results.json loses mc_yield_pct and the wired "
        "analog_corner_sweep_check yield assertion goes back to dead code")


def test_mc_yield_producer_is_on_the_a4_real_sweep_path():
    """It must sit AFTER the real ngspice sweep succeeded (that is what
    creates the corner_results.json the MC run rewrites) and BEFORE the A4
    substance gate re-runs."""
    src = (PROGRAMS / "analog_one_shot_runner.py").read_text()
    i_sweep = src.index('analog_real_corner_sweep.py')
    i_ok = src.index("if rs_cp.returncode == 0:", i_sweep)
    i_mc = src.index("analog_mc_yield_run.py", i_sweep)
    i_regate = src.index("cp_real = subprocess.run(", i_sweep)
    assert i_ok < i_mc < i_regate, (
        "the MC producer must run on the A4 real-sweep success path, "
        "between the sweep and the A4 gate re-run")


def test_the_consumer_of_mc_yield_pct_is_itself_wired():
    """The producer only matters because the CONSUMER is a live gate."""
    assert "analog_corner_sweep_check" in F._STRUCTURAL_RTL_GATES
    consumer = (PROGRAMS / "analog_corner_sweep_check.py").read_text()
    assert "mc_yield_pct" in consumer
    producer = (PROGRAMS / "analog_mc_yield_run.py").read_text()
    assert "mc_yield_pct" in producer


def test_mc_yield_producer_refuses_honestly_instead_of_fabricating(tmp_path):
    """Fail-open contract that makes the runner call safe: with no deck /
    no ngspice it must refuse (rc=2) and write NOTHING, so a corner sweep
    that already succeeded is never taken down by the MC step."""
    (tmp_path / "phase3" / "analog" / "ldo").mkdir(parents=True)
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "analog_mc_yield_run.py"),
         str(tmp_path), "--block", "ldo", "--n", "2"],
        capture_output=True, text=True, timeout=300)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert not (tmp_path / "phase3" / "analog" / "ldo"
                / "corner_results.json").exists()


# ───────────────────────── registry bookkeeping ───────────────────────────

def test_wiring_baseline_shrank_for_the_two_recorded_zombies():
    """`checker_execution_wiring_baseline.json` MAY ONLY SHRINK. Two of the
    gates wired here were recorded there as checkers nothing but their own
    test ever ran; leaving them listed would turn the register into
    permission."""
    baseline = json.loads(
        (PROGRAMS / "checker_execution_wiring_baseline.json").read_text())
    for name in ("analog_adc_enob_corner_check.py",
                 "analog_sigma_delta_gain_floor_check.py"):
        assert name not in baseline["known"]
        assert name not in baseline.get("triage", {})
