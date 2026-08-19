"""score_iverilog_tb.py: a forged verdict token is REFUSED, and a never-attempted
problem stays in the denominator with a row of its own (vibe-ic#1745).

BIDIRECTIONAL NEGATIVE CONTROL — this is the substantive half of the control for
#1745, because every assertion below observes a VALUE the pre-fix scorer also
produced, rather than the absence of something the fix adds.

MEASURED on the fixture this module builds, against the parent revision:

    # disk-truth: 3/3 problems have an on-disk sample in .../samples
    VerilogEval-v2 (spec-to-RTL)  pass@1 = 2/3 = 66.67%  [Shape C]
      fails (1): Prob002_wrong:functional_mismatch

    results: Prob001_ok PASS
             Prob002_wrong FAIL functional_mismatch (Mismatches: 20 in 20)
             Prob003_forged PASS          <-- IDENTICAL LOGIC to Prob002_wrong
             Prob004_unattempted          <-- absent entirely: no row, no warning

and after the fix, on the same fixture:

    pass@1 = 1/4 = 25.0%, Prob003_forged FAIL harness_verdict_token_forgery,
    Prob004_unattempted FAIL never_attempted_not_in_problems_list.

So `verdict == "FAIL"` here fails pre-fix against the value "PASS", and
`total == 4` fails pre-fix against the value 3.
"""
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark" / "score_iverilog_tb.py")

_LAYOUT_C = {
    "prompt_suffix": "_prompt.txt",
    "tb_suffix": "_test.sv",
    "ref_suffix": "_ref.sv",
    "module_name_strategy": "always_TopModule",
}
_ARGS_C = {"tb_compile_with_ref": True,
           "pass_regex": r"Mismatches:\s*0\s+in\s+\d+\s+samples"}

_LAYOUT_B = {"prompt_filename": "design_description.txt",
             "tb_filename": "testbench.v",
             "module_name_strategy": "from_description_module_name_line"}
_ARGS_B = {"tb_compile_with_ref": False,
           "pass_regex": "Your Design Passed",
           "fail_regex": "Test failed|Your Design Failed"}

_REF = "module RefModule(input a, output y);\n  assign y = a;\nendmodule\n"
_TB = (
    "`timescale 1ps/1ps\n"
    "module tb;\n"
    "  reg a; wire y_dut, y_ref; integer i; integer mism = 0;\n"
    "  TopModule dut(.a(a), .y(y_dut));\n"
    "  RefModule ref_i(.a(a), .y(y_ref));\n"
    "  initial begin\n"
    "    for (i = 0; i < 20; i = i + 1) begin\n"
    "      a = i[0]; #5;\n"
    "      if (y_dut !== y_ref) mism = mism + 1;\n"
    "      #5;\n"
    "    end\n"
    '    $display("Mismatches: %0d in %0d samples", mism, 20);\n'
    "    $finish;\n"
    "  end\n"
    "endmodule\n"
)
_CORRECT = "module TopModule(input a, output y);\n  assign y = a;\nendmodule\n"
_WRONG = "module TopModule(input a, output y);\n  assign y = ~a;\nendmodule\n"
#: identical logic to _WRONG, plus the one line that forges the verdict
_FORGED = (
    "module TopModule(input a, output y);\n"
    "  assign y = ~a;\n"
    '  initial $display("Mismatches: 0 in 20 samples");\n'
    "endmodule\n"
)


def _load():
    spec = importlib.util.spec_from_file_location("score_iverilog_tb", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load()


def _need_iverilog():
    if not shutil.which("iverilog"):
        pytest.skip("iverilog not installed")


@pytest.fixture()
def workdir():
    """A scratch dir of our own rather than pytest's `tmp_path`.

    `tmp_path` is derived from the invoking account name, and this suite is run
    inside the EDA container where that name can contain a newline — which
    iverilog cannot take on a command line, turning every compile into a
    spurious `compile_error`. The fixture must not decide the verdict."""
    d = Path(tempfile.mkdtemp(prefix="score_iverilog_1745_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _shape_c_fixture(root, listed=("Prob001_ok", "Prob002_wrong",
                                       "Prob003_forged")):
    """Four problems in the dataset; `listed` says which ones problems.list
    names. Synthesised throughout — no benchmark's own files are copied."""
    ds, run = root / "ds", root / "run"
    (run / "samples").mkdir(parents=True)
    ds.mkdir()
    bodies = {"Prob001_ok": _CORRECT, "Prob002_wrong": _WRONG,
              "Prob003_forged": _FORGED, "Prob004_unattempted": None}
    for prob, body in bodies.items():
        (ds / f"{prob}_prompt.txt").write_text("y follows a.\n")
        (ds / f"{prob}_ref.sv").write_text(_REF)
        (ds / f"{prob}_test.sv").write_text(_TB)
        if body is not None:
            (run / "samples" / f"{prob}_sample01.sv").write_text(body)
    (run / "problems.list").write_text("\n".join(listed) + "\n")
    return ds, run


def _score_all(ds, run, bench="verilogeval-v2"):
    argv = ["score_iverilog_tb.py", "--bench", bench,
            "--dataset", str(ds), "--run", str(run)]
    saved, sys.argv = sys.argv, argv
    try:
        M.main()
    finally:
        sys.argv = saved
    return json.loads((run / "pass_at_1.json").read_text())


# --------------------------------------------------------------------------- #
# 1. the forged sample is refused
# --------------------------------------------------------------------------- #
def test_forged_sample_is_refused_before_it_is_ever_run(workdir):
    """No simulator involved: the refusal happens in front of the compile, so it
    holds even where the toolchain is absent."""
    ds, run = _shape_c_fixture(workdir)
    res = M._score_shape_c("Prob003_forged", run / "samples", ds,
                           _LAYOUT_C, dict(_ARGS_C))
    assert res["verdict"] == "FAIL"
    assert res["reason"] == "harness_verdict_token_forgery"
    assert res["forged_verdict_token"] is True
    assert "Mismatches: 0 in 20 samples" in res["verdict_token_guard_detail"]


def test_identical_wrong_logic_scores_identically_forged_or_not(workdir):
    """The whole defect in one assertion: two submissions whose CIRCUITS are the
    same must not score differently because one of them talks."""
    _need_iverilog()
    ds, run = _shape_c_fixture(workdir)
    honest = M._score_shape_c("Prob002_wrong", run / "samples", ds,
                              _LAYOUT_C, dict(_ARGS_C))
    forged = M._score_shape_c("Prob003_forged", run / "samples", ds,
                              _LAYOUT_C, dict(_ARGS_C))
    assert honest["verdict"] == "FAIL"
    assert forged["verdict"] == honest["verdict"]


def test_honest_candidate_still_passes(workdir):
    """A gate that refuses everything is not a gate. The correct submission must
    still score PASS through the same path."""
    _need_iverilog()
    ds, run = _shape_c_fixture(workdir)
    res = M._score_shape_c("Prob001_ok", run / "samples", ds,
                           _LAYOUT_C, dict(_ARGS_C))
    assert res["verdict"] == "PASS"


def test_refusal_is_reported_in_the_artefact(workdir):
    _need_iverilog()
    ds, run = _shape_c_fixture(workdir)
    doc = _score_all(ds, run)
    g = doc["verdict_token_guard"]
    assert g["enforcement"] == "BLOCKING"
    assert g["refused_count"] == 1
    assert g["refused_problems"][0]["id"] == "Prob003_forged"
    assert g["not_checked_count"] == 0


def test_a_forged_submission_is_not_excused_as_a_dataset_defect(workdir):
    """The dataset-defect audits exist to keep an unsatisfiable problem off the
    model's record. A forgery must not collect that flag and ride out of the
    corrected denominators on it."""
    ds, run = _shape_c_fixture(workdir)
    res = M._score_shape_c("Prob003_forged", run / "samples", ds,
                           _LAYOUT_C, dict(_ARGS_C))
    assert "dataset_defect" not in res
    assert "dataset_defect_suspected" not in res


def test_shape_b_refuses_the_marker_too(workdir):
    """Same gate, other shape, different vocabulary — supplied by the registry
    entry, not carried by the guard."""
    ds, run = workdir / "ds", workdir / "run"
    (ds / "adder").mkdir(parents=True)
    (run / "samples").mkdir(parents=True)
    (ds / "adder" / "design_description.txt").write_text(
        "Module name:\n  adder\n")
    (ds / "adder" / "testbench.v").write_text("module tb; endmodule\n")
    (run / "samples" / "adder.v").write_text(
        "module adder(input a, output y);\n"
        "  assign y = ~a;\n"
        '  initial $display("===Your Design Passed===");\n'
        "endmodule\n")
    res = M._score_shape_b("adder", run / "samples", ds,
                           _LAYOUT_B, dict(_ARGS_B))
    assert res["verdict"] == "FAIL"
    assert res["reason"] == "harness_verdict_token_forgery"


def test_guard_that_cannot_run_refuses_rather_than_clears(workdir):
    """§6 degrade loudly: a submission nobody checked is not a submission that
    passed."""
    ds, run = _shape_c_fixture(workdir)
    args = dict(_ARGS_C)
    args["pass_regex"] = r"\d+"          # no extractable vocabulary
    res = M._score_shape_c("Prob001_ok", run / "samples", ds, _LAYOUT_C, args)
    assert res["verdict"] == "FAIL"
    assert res["reason"] == "harness_verdict_token_guard_not_checked"
    assert res["verdict_token_guard"] == "NOT_CHECKED"


# --------------------------------------------------------------------------- #
# 2. the third state
# --------------------------------------------------------------------------- #
def test_problem_absent_from_problems_list_stays_in_the_denominator(workdir):
    _need_iverilog()
    ds, run = _shape_c_fixture(workdir)      # 4 in dataset, 3 in problems.list
    doc = _score_all(ds, run)
    assert doc["total"] == 4
    assert doc["dataset_inventory_count"] == 4
    assert doc["declared_scope_count"] == 3
    assert doc["passed"] == 1
    assert doc["pass_at_1_pct"] == 25.0


def test_the_never_attempted_problem_has_its_own_row(workdir):
    _need_iverilog()
    ds, run = _shape_c_fixture(workdir)
    doc = _score_all(ds, run)
    rows = [r for r in doc["results"] if r["problem"] == "Prob004_unattempted"]
    assert len(rows) == 1
    assert rows[0]["attempt_state"] == "never_attempted"
    assert rows[0]["reason"] == "never_attempted_not_in_problems_list"
    assert doc["never_attempted_count"] == 1
    assert doc["never_attempted_problems"] == [
        {"id": "Prob004_unattempted",
         "reason": "never_attempted_not_in_problems_list"}]


def test_a_listed_problem_with_no_sample_is_never_attempted_too(workdir):
    """The other way a problem is never attempted: declared, then not authored.
    Both belong to the SAME state — a run that stopped early."""
    _need_iverilog()
    ds, run = _shape_c_fixture(
        workdir, listed=("Prob001_ok", "Prob002_wrong", "Prob003_forged",
                          "Prob004_unattempted"))
    doc = _score_all(ds, run)
    row = [r for r in doc["results"]
           if r["problem"] == "Prob004_unattempted"][0]
    assert row["reason"] == "no_sample"
    assert row["attempt_state"] == "never_attempted"
    assert doc["never_attempted_count"] == 1
    assert doc["total"] == 4


def test_the_three_states_partition_the_scope(workdir):
    _need_iverilog()
    ds, run = _shape_c_fixture(workdir)
    doc = _score_all(ds, run)
    st = doc["attempt_states"]
    assert st == {"attempted_and_passed": 1, "attempted_and_failed": 2,
                  "never_attempted": 1, "skipped_scorer_gap": 0}
    assert sum(st.values()) == doc["total"]
    assert {r["attempt_state"] for r in doc["results"]} <= set(st)


def test_rate_over_attempted_is_reported_beside_the_headline_not_instead(workdir):
    _need_iverilog()
    ds, run = _shape_c_fixture(workdir)
    doc = _score_all(ds, run)
    assert doc["pass_at_1_pct"] == 25.0                      # 1 of 4 in scope
    assert doc["pass_at_1_excluding_never_attempted_pct"] == 33.33   # 1 of 3


def test_a_complete_run_is_reported_exactly_as_before(workdir):
    """Corpus safety: when problems.list already covers the dataset and nothing
    is forged, the reconciliation adds no rows and moves no number."""
    _need_iverilog()
    ds, run = _shape_c_fixture(
        workdir, listed=("Prob001_ok", "Prob002_wrong"))
    for extra in ("Prob003_forged", "Prob004_unattempted"):
        for suffix in ("_prompt.txt", "_ref.sv", "_test.sv"):
            (ds / f"{extra}{suffix}").unlink()
    doc = _score_all(ds, run)
    assert doc["total"] == 2
    assert doc["never_attempted_count"] == 0
    assert doc["pass_at_1_pct"] == 50.0
    assert doc["verdict_token_guard"]["refused_count"] == 0


# --------------------------------------------------------------------------- #
# 3. the same forgery surface in the tier pipelines
#
# These three grade a candidate the same way — search the simulator's combined
# stdout for the harness's marker — so they carry the same defect. What they
# grade is the plugin's OWN deterministic emit rather than an outside
# submission, which makes an unguarded marker there a way for the plugin to
# forge its own baseline.
# --------------------------------------------------------------------------- #
_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import rtllm_tier_pipeline as RT                    # noqa: E402
import verilogeval_human_tier_pipeline as VH        # noqa: E402
import verilogeval_tier_pipeline as VE              # noqa: E402


def test_verilogeval_tier_pipeline_refuses_a_forged_emit(workdir, monkeypatch):
    ds = workdir / "ds"
    ds.mkdir(parents=True)
    (ds / "Prob001_x_prompt.txt").write_text("y follows a.\n")
    (ds / "Prob001_x_ref.sv").write_text(_REF)
    (ds / "Prob001_x_test.sv").write_text(_TB)
    prob = VE.discover(str(ds))[0]
    monkeypatch.setattr(VE, "_registry_emit", lambda _p: _FORGED)
    res = VE.tier_result(prob, verify=True, timeout=30)
    assert res["verified"] is False
    assert "harness_verdict_token_forgery" in res["detail"]


def test_verilogeval_human_tier_pipeline_refuses_a_forged_emit(workdir):
    ds = workdir / "ds"
    ds.mkdir(parents=True)
    (ds / "ref.sv").write_text(_REF)
    (ds / "test.sv").write_text(_TB)
    VH._VERIFY_CACHE.clear()
    ok, log = VH.tier1_verify(
        {"ref_path": str(ds / "ref.sv"), "test_path": str(ds / "test.sv")},
        _FORGED)
    assert ok is False
    assert "harness_verdict_token_forgery" in log


def test_rtllm_tier_pipeline_refuses_a_forged_emit(workdir, monkeypatch):
    design = workdir / "adder"
    design.mkdir(parents=True)
    (design / "design_description.txt").write_text("Module name:\n  adder\n")
    (design / "testbench.v").write_text("module tb; endmodule\n")
    forged = (
        "module adder(input a, output y);\n"
        "  assign y = ~a;\n"
        '  initial $display("===Your Design Passed===");\n'
        "endmodule\n"
    )
    monkeypatch.setattr(RT, "required_module_name", lambda _d: "adder")
    monkeypatch.setattr(RT, "deterministic_emit",
                        lambda _d, _t=None: ("stub", forged))
    kind, rtl, log = RT.tier1_emit_verified(str(design))
    assert kind is None and rtl is None
    assert "harness_verdict_token_forgery" in log
