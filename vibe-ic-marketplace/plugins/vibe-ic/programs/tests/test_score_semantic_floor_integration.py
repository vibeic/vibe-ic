"""Canonical scorer integration for the general semantic-floor program.

The scorer must surface independently cited prompt↔golden contradictions on
functional failures without changing the candidate verdict or raw pass count.
Non-functional failures and unsupported prompt classes must not leak into this
advisory channel.
"""
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN / "benchmark"))
import score_iverilog_tb as S  # noqa: E402


LAYOUT = {
    "prompt_suffix": "_prompt.txt",
    "ref_suffix": "_ref.sv",
    "tb_suffix": "_test.sv",
}


def test_adapter_routes_prompt_and_ref_to_general_core(tmp_path, monkeypatch):
    (tmp_path / "Case_prompt.txt").write_text("machine-readable prompt")
    (tmp_path / "Case_ref.sv").write_text("module RefModule; endmodule")
    seen = {}

    import semantic_spec_floor_check as core

    def fake(prompt, ref):
        seen.update(prompt=prompt, ref=ref)
        return "input a=1: prompt=1, golden=0"

    monkeypatch.setattr(core, "semantic_floor_evidence", fake)
    assert S._semantic_prompt_oracle_evidence(
        "Case", tmp_path, LAYOUT) == "input a=1: prompt=1, golden=0"
    assert seen == {
        "prompt": "machine-readable prompt",
        "ref": "module RefModule; endmodule",
    }


def test_functional_fail_gets_advisory_semantic_evidence_without_reclassifying(
        tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_score_shape_c_impl", lambda *a, **k: {
        "problem": "Case", "verdict": "FAIL",
        "reason": "functional_mismatch (3 mismatches)",
    })
    monkeypatch.setattr(S, "_golden_ref_self_compiles",
                        lambda *a, **k: True)
    monkeypatch.setattr(S, "_semantic_prompt_oracle_evidence",
                        lambda *a, **k: "cited contradiction")
    monkeypatch.setattr(S, "_canonical_disagrees_with_golden",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("semantic evidence must take priority")))

    res = S._score_shape_c(
        "Case", tmp_path / "samples", tmp_path, LAYOUT,
        {"_bench": "synthetic"})
    assert res["verdict"] == "FAIL"
    assert res["reason"].startswith("functional_mismatch")
    assert res["dataset_defect_suspected"] is True
    assert res["dataset_defect_reason"] == \
        "semantic_prompt_oracle_contradiction"
    assert res["semantic_floor_evidence"] == "cited contradiction"


def test_compile_failure_does_not_run_semantic_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_score_shape_c_impl", lambda *a, **k: {
        "problem": "Case", "verdict": "FAIL", "reason": "compile_error",
    })
    monkeypatch.setattr(S, "_golden_ref_self_compiles",
                        lambda *a, **k: True)
    monkeypatch.setattr(S, "_semantic_prompt_oracle_evidence",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("non-functional failure leaked")))

    res = S._score_shape_c(
        "Case", tmp_path / "samples", tmp_path, LAYOUT, {})
    assert res == {
        "problem": "Case", "verdict": "FAIL", "reason": "compile_error",
    }


def test_no_semantic_evidence_preserves_canonical_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_score_shape_c_impl", lambda *a, **k: {
        "problem": "Case", "verdict": "FAIL",
        "reason": "functional_mismatch (1 mismatch)",
    })
    monkeypatch.setattr(S, "_golden_ref_self_compiles",
                        lambda *a, **k: True)
    monkeypatch.setattr(S, "_semantic_prompt_oracle_evidence",
                        lambda *a, **k: None)
    monkeypatch.setattr(S, "_canonical_disagrees_with_golden",
                        lambda *a, **k: "canonical mismatch 4/4")

    res = S._score_shape_c(
        "Case", tmp_path / "samples", tmp_path, LAYOUT,
        {"_bench": "synthetic"})
    assert res["verdict"] == "FAIL"
    assert res["dataset_defect_reason"] == "suspected_defective_golden"
    assert res["canonical_evidence"] == "canonical mismatch 4/4"
