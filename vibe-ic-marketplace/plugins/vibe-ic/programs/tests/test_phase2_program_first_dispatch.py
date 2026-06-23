"""Tests for the v0.1.10 program-first wiring of the deterministic RTL dispatcher
into design_one_shot_runner.step_rtl_gen.

Contract: if the project ships a structured RTL spec at a conventional location,
step_rtl_gen emits RTL DETERMINISTICALLY (no LLM) and returns PASS before any
class-registry / AI-fallback path. No spec — or a non-mechanically-derivable spec
— falls through to the existing behaviour.
"""
import json
import sys
import tempfile
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import design_one_shot_runner as p2  # noqa: E402
import _path_layout as _pl  # noqa: E402

FSM_SPEC = {
    "module": "chip_top", "kind": "moore_comb",
    "input": "in", "state_in": "state", "next_state_out": "next_state", "output": "out",
    "encoding": {"A": 0, "B": 1, "C": 2, "D": 3},
    "transitions": {"A": {"0": "A", "1": "B"}, "B": {"0": "C", "1": "B"},
                    "C": {"0": "A", "1": "D"}, "D": {"0": "C", "1": "B"}},
    "outputs": {"A": 0, "B": 0, "C": 0, "D": 1},
}
VEC_SPEC = {"module": "chip_top", "op": "reverse", "chunk": 8,
            "inputs": [{"name": "in", "width": 32}],
            "outputs": [{"name": "out", "width": 32}]}


def _proj(tmp, spec=None, rel="phase2/stage1/rtl_spec.json"):
    proj = Path(tmp) / "demo"
    if spec is not None:
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(spec))
    else:
        proj.mkdir(parents=True, exist_ok=True)
    return proj


def test_fsm_spec_generates_deterministically(tmp_path):
    proj = _proj(tmp_path, FSM_SPEC)
    res = p2.step_rtl_gen(proj, ic_class="digital-combinational-primitive")
    assert res.status == "PASS", res.detail
    assert res.extras.get("program_first") is True
    assert res.extras.get("deterministic_generator") in ("fsm_table", "FSM-table")
    rtl = _pl.rtl_dir(proj) / "chip_top.sv"
    assert rtl.is_file()
    body = rtl.read_text()
    assert "case (state)" in body and "next_state" in body


def test_vector_spec_generates_deterministically(tmp_path):
    proj = _proj(tmp_path, VEC_SPEC)
    res = p2.step_rtl_gen(proj, ic_class="digital-combinational-primitive")
    assert res.status == "PASS", res.detail
    assert res.extras.get("program_first") is True
    rtl = _pl.rtl_dir(proj) / "chip_top.sv"
    assert "assign out = {in[7:0], in[15:8], in[23:16], in[31:24]};" in rtl.read_text()


def test_no_spec_falls_through(tmp_path):
    # No rtl_spec → not program-first; unregistered class → existing WAIVED path.
    proj = _proj(tmp_path, None)
    res = p2.step_rtl_gen(proj, ic_class="__no_such_class__")
    assert res.status != "PASS"           # did not vacuously claim deterministic PASS
    assert not res.extras.get("program_first")


def test_non_derivable_spec_falls_through(tmp_path):
    # Spec present but no transitions/rows/gates/op → dispatcher exit 3 → fall through.
    proj = _proj(tmp_path, {"module": "chip_top", "description": "a complex datapath"})
    res = p2.step_rtl_gen(proj, ic_class="__no_such_class__")
    assert not res.extras.get("program_first")
    # falls to the class path → WAIVED (unregistered class)
    assert res.status in ("WAIVED", "FAIL", "SKIP")


def test_input_dir_spec_location_also_works(tmp_path):
    proj = _proj(tmp_path, FSM_SPEC, rel="input/rtl_spec.json")
    res = p2.step_rtl_gen(proj, ic_class="digital-combinational-primitive")
    assert res.status == "PASS", res.detail
    assert res.extras.get("program_first") is True
