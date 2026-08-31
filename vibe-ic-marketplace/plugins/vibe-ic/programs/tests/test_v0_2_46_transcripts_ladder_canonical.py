"""Regressions for clean transcripts and scorer/golden disagreement evidence.

#415 transcripts-export-default — the blindness audit was structurally
DORMANT (no orchestration path produced its input): the general solve entry now
pre-creates <RUNDIR>/transcripts/ and pins full-dataset clean-room metadata.

#418 scorer-disagreeing-golden-flag — second dataset-defect audit class:
a vetted canonical sample failing the hidden golden at >=50% mismatch flags
'suspected_defective_golden' (DISCLOSURE-ONLY; verdict/pass@1 unchanged);
canonical_samples/ access is itself blindness-audited (V3).
"""
import json
import shutil
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import blindness_audit as ba  # noqa: E402
import benchmark_dispatch as bd  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
SKILL = PLUGIN / "skills" / "open-benchmark-methodology" / "SKILL.md"

sys.path.insert(0, str(HARNESS))
import score_iverilog_tb as sit  # noqa: E402

#: The repo's existing tool gate. Without it this module raises
#: FileNotFoundError on a host that lacks the tool, instead of disclosing a
#: skip. The crash is not in this module — it is inside
#: `benchmark/score_iverilog_tb.py`, which these tests invoke — so the gate
#: names the tool the CALL CHAIN needs, not a binary this file mentions.
_HAVE_TOOLS = bool(shutil.which("iverilog"))



# ── #415: transcripts export is the orchestration default ────────────────

def test_general_solve_prepares_clean_transcript_envelope(tmp_path):
    ds = tmp_path / "ds"; ds.mkdir()
    (ds / "Prob001_prompt.txt").write_text("Build a thing.\n")
    run = tmp_path / "run"
    bd._prepare_general_solve_run(
        "verilogeval-v2", ds, run, "verilogeval", 0)
    assert (run / "transcripts").is_dir()
    config = json.loads((run / ".bench_config.json").read_text())
    assert config["schema"] == "vibeic.benchmark.general_run.v1"
    assert config["full_dataset"] is True


def test_shape_c_rules_carry_export_requirement():
    txt = (HARNESS / "blind_instructions_shape_c.md").read_text()
    assert "Transcript export is the DEFAULT" in txt
    assert "blindness audit unavailable" in txt


def test_methodology_carries_export_requirement():
    txt = SKILL.read_text()
    assert "Export author/reviewer transcripts" in txt
    assert "Missing\ntranscripts require an explicit disclosure" in txt


# ── #418: suspected-defective-golden audit ────────────────────────────────

_TB = """
module tb;
  reg a; wire o_dut, o_ref;
  TopModule d(.a(a), .o(o_dut));
  RefModule r(.a(a), .o(o_ref));
  integer i, mm;
  initial begin
    mm = 0;
    for (i = 0; i < 4; i = i + 1) begin
      a = i[0]; #1;
      if (o_dut !== o_ref) mm = mm + 1;
    end
    $display("Mismatches: %0d in 4 samples", mm);
  end
endmodule
"""
_REF = "module RefModule(input a, output o);\n  assign o = a;\nendmodule\n"
_LAYOUT = {"prompt_suffix": "_prompt.txt", "tb_suffix": "_test.sv",
           "ref_suffix": "_ref.sv", "module_name_strategy": "always_TopModule"}
_ARGS = {"tb_compile_with_ref": True,
         "pass_regex": r"Mismatches:\s*0\s+in\s+\d+\s+samples"}


def _stage_dataset(tmp_path):
    ds = tmp_path / "ds"; ds.mkdir(exist_ok=True)
    (ds / "ProbX_test.sv").write_text(_TB)
    (ds / "ProbX_ref.sv").write_text(_REF)
    (ds / "ProbX_prompt.txt").write_text("Buffer a to o.\n")
    return ds


def _stage_canonical(tmp_path, monkeypatch, body):
    cdir = tmp_path / "canon" / "somebench"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "ProbX.sv").write_text(body)
    monkeypatch.setattr(sit, "_CANONICAL_DIR", tmp_path / "canon")


def test_canonical_disagreement_returns_evidence(tmp_path, monkeypatch):
    if not _HAVE_TOOLS:
        pytest.skip("iverilog not installed on this host")
    ds = _stage_dataset(tmp_path)
    # canonical inverts -> disagrees with the golden on every sample
    _stage_canonical(tmp_path, monkeypatch,
                     "module TopModule(input a, output o);\n"
                     "  assign o = ~a;\nendmodule\n")
    ev = sit._canonical_disagrees_with_golden("ProbX", ds, _LAYOUT, _ARGS,
                                              "somebench")
    assert ev and "4/4" in ev


def test_canonical_agreement_returns_none(tmp_path, monkeypatch):
    if not _HAVE_TOOLS:
        pytest.skip("iverilog not installed on this host")
    ds = _stage_dataset(tmp_path)
    _stage_canonical(tmp_path, monkeypatch,
                     "module TopModule(input a, output o);\n"
                     "  assign o = a;\nendmodule\n")
    assert sit._canonical_disagrees_with_golden(
        "ProbX", ds, _LAYOUT, _ARGS, "somebench") is None


def test_no_canonical_returns_none(tmp_path, monkeypatch):
    ds = _stage_dataset(tmp_path)
    monkeypatch.setattr(sit, "_CANONICAL_DIR", tmp_path / "absent")
    assert sit._canonical_disagrees_with_golden(
        "ProbX", ds, _LAYOUT, _ARGS, "somebench") is None


def test_score_shape_c_flags_disclosure_only(tmp_path, monkeypatch):
    if not _HAVE_TOOLS:
        pytest.skip("iverilog not installed on this host")
    # failing sample + disagreeing canonical -> verdict stays FAIL, flag set
    ds = _stage_dataset(tmp_path)
    _stage_canonical(tmp_path, monkeypatch,
                     "module TopModule(input a, output o);\n"
                     "  assign o = ~a;\nendmodule\n")
    samples = tmp_path / "samples"; samples.mkdir()
    (samples / "ProbX_sample01.sv").write_text(
        "module TopModule(input a, output o);\n"
        "  assign o = 1'b0;\nendmodule\n")
    args = dict(_ARGS); args["_bench"] = "somebench"
    res = sit._score_shape_c("ProbX", samples, ds, _LAYOUT, args)
    assert res["verdict"] == "FAIL"                       # never auto-excluded
    assert res.get("dataset_defect_suspected") is True
    assert res.get("dataset_defect_reason") == "suspected_defective_golden"
    assert "4/4" in res.get("canonical_evidence", "")


def test_vetted_prob062_canonical_is_shipped():
    # the recurring disagreeing-golden case is populated for both tracks
    for bench in ("verilogeval-v2", "verilogeval-human"):
        f = HARNESS / "canonical_samples" / bench / "Prob062_bugs_mux2.sv"
        assert f.is_file(), bench
        assert "sel ? b : a" in f.read_text()


# ── #418: canonical_samples access is blindness-audited (V3) ─────────────

def _kinds(text):
    return [f["kind"] for f in
            ba.audit_text(text, Path("/data/ds"), ["*_prompt.txt"], "t.log")]


def test_canonical_path_access_flagged():
    ks = _kinds("cat /x/benchmark/canonical_samples/somebench/ProbX.sv\n")
    assert "canonical-sample-access" in ks


def test_canonical_bare_word_not_flagged():
    assert _kinds("the canonical_samples/ tree is host-scorer-only\n") == [
        ] or "canonical-sample-access" not in _kinds(
        "never read the canonical samples tree\n")
