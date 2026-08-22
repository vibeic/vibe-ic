"""ORGANIC #797 — the testbench_gen.py PRODUCER was never wired into any one-shot
runner, so L10 `functional_vector` cases got NO Step-4 id-substring trace
evidence and the l10_tb_conformance gate reported `N/M cases lack evidence`.

FIX: `step_l10_unit_tb_gen` runs the producer (kind-scoped to functional_vector)
in the Phase-2 plan after step_full_stack_tb_gen, before reference_tb/simulate.
§4.05 no-leak: kind-scoping means a `cmd_response` case never gets manufactured
evidence — it STILL fails the Step-4 gate when uncovered; an IC with no L10 / no
functional_vector case SKIPs with no side effect.

chip-AGNOSTIC: L10 kind grammar; no chip literal.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import testbench_gen as TBG          # noqa: E402
import design_one_shot_runner as R   # noqa: E402
import _path_layout as _pl            # noqa: E402


# #209 — the producer now needs REAL RTL to emit against. It used to emit a
# `PASS_PLACEHOLDER` skeleton with the DUT commented out, which needed no RTL at
# all; these fixtures inherited that and so passed with an empty rtl/ tree. The
# producer now instantiates the DUT or emits nothing, so a fixture that wants a
# TB must supply a DUT. Everything these tests actually assert — the runner
# wiring, kind-scoping, the §4.05 cmd_response no-leak, and the SKIP paths — is
# unchanged; only the missing precondition is added.
_DUT = """\
module chip_top (
    input        clk,
    input        reset_n,
    input  [7:0] d_in,
    output reg [7:0] d_out
);
  always @(posedge clk or negedge reset_n)
    if (!reset_n) d_out <= 8'h00;
    else          d_out <= d_in;
endmodule
"""


def _project(tmp_path, cases, rtl=_DUT):
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (_pl.sim_dir(proj) / "tb").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L10_TEST_CASES.json").write_text(
        json.dumps({"test_cases": cases}))
    if rtl is not None:
        _pl.rtl_dir(proj).mkdir(parents=True, exist_ok=True)
        (_pl.rtl_dir(proj) / "chip_top.v").write_text(rtl)
    return proj


_FV = [{"name": "vec_add_basic", "kind": "functional_vector",
        "stimulus": "a=1,b=2", "expected": "3"},
       {"name": "vec_mul_edge", "kind": "functional_vector",
        "stimulus": "a=255,b=2", "expected": "510"}]


def test_797_runner_step_exists_and_wired():
    assert hasattr(R, "step_l10_unit_tb_gen")
    import inspect
    src = inspect.getsource(R.main if hasattr(R, "main") else R)
    assert "step_l10_unit_tb_gen" in src


def test_797_producer_emits_functional_vector_skeletons(tmp_path):
    proj = _project(tmp_path, _FV)
    res = R.step_l10_unit_tb_gen(proj, "chip_top")
    assert res.status == "PASS", res.detail
    tb_dir = _pl.sim_dir(proj) / "tb"
    names = {p.stem for p in tb_dir.glob("*.v")}
    assert "vec_add_basic" in names and "vec_mul_edge" in names


def test_797_noleak_cmd_response_case_gets_no_skeleton(tmp_path):
    proj = _project(tmp_path, [
        {"name": "vec_alu_op", "kind": "functional_vector",
         "stimulus": "x", "expected": "y"},
        {"name": "cmd_read_id", "kind": "cmd_response",
         "opcode": "0x9C", "expected": "0xDE"}])
    R.step_l10_unit_tb_gen(proj, "chip_top")
    names = {p.stem for p in (_pl.sim_dir(proj) / "tb").glob("*.v")}
    assert "vec_alu_op" in names              # functional_vector → emitted
    assert "cmd_read_id" not in names         # cmd_response → NOT emitted (no-leak)


def test_797_no_l10_skips(tmp_path):
    proj = tmp_path / "p2"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    res = R.step_l10_unit_tb_gen(proj, "chip_top")
    assert res.status == "SKIP"


def test_797_no_functional_vector_case_skips(tmp_path):
    proj = _project(tmp_path, [{"name": "c1", "kind": "cmd_response",
                                "opcode": "0x1", "expected": "0x2"}])
    res = R.step_l10_unit_tb_gen(proj, "chip_top")
    assert res.status == "SKIP"


def test_797_emit_unit_tbs_kind_filter_directly(tmp_path):
    proj = _project(tmp_path, _FV + [
        {"name": "other", "kind": "cmd_response"}])
    assert TBG.emit_unit_tbs(proj, "chip_top", kind="functional_vector") == 2
    assert TBG.emit_unit_tbs(tmp_path / "absent", "chip_top") == -1


def test_797_step_skips_with_a_reason_when_dut_unresolvable(tmp_path):
    """#209 — L10 cases exist but there is no RTL to instantiate. The step must
    SKIP and SAY SO. It must NOT report PASS, and it must NOT write a
    placeholder: a fabricated Step-4 evidence file is exactly what #209 found
    140 of."""
    proj = _project(tmp_path, _FV, rtl=None)
    res = R.step_l10_unit_tb_gen(proj, "chip_top")
    assert res.status == "SKIP", res.detail
    assert "refused to fabricate" in res.detail
    assert list((_pl.sim_dir(proj) / "tb").glob("*.v")) == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
