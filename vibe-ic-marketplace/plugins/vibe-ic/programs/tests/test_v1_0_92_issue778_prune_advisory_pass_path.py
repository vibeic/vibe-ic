"""ORGANIC #778 (P2) — the catalog-glue over-broad PRUNE advisory was gated
behind `if verdict in (DUPLICATE, STAGED_DUPLICATE)` (design_one_shot_runner.py),
so on a PASS verdict with files_prunable>0 the advisory was suppressed entirely
and the runner fed the FULL flat glob to yosys-slang with ZERO diagnostic. An
unreachable prunable-tail file using a cross-file macro it never `include`s then
crashes slang opaquely ('unknown macro') with no author hint. Distinct from #774
(the STAGED_DUPLICATE crash hard-gate).

Fix: a NON-FATAL advisory hoisted onto the PASS path — `_prune_tail_advisory`
emits a (dict, log_line) when files_prunable>0, naming the count + example
prunable files + a prune-to-closure recommendation. Never auto-drops; never
changes the verdict.

§4.05: files_prunable==0 emits NO advisory (no false noise); the advisory must
not change the PASS verdict (it rides in extras only).
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import catalog_glue_closure_resolver as CG  # noqa: E402
import design_one_shot_runner as P  # noqa: E402


def _mk_rtl(tmp_path):
    """top reaches child; orphan is unreachable (a prunable tail file)."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.sv").write_text(
        "module top(input a, output b); child u(.x(a), .y(b)); endmodule\n")
    (rtl / "child.sv").write_text(
        "module child(input x, output y); assign y = x; endmodule\n")
    (rtl / "orphan.sv").write_text(
        "module orphan(input p, output q); assign q = ~p; endmodule\n")
    return rtl


# ── NEW-PATH: PASS verdict with a prunable tail → non-fatal advisory ─────────
def test_778_pass_with_prunable_tail_emits_advisory(tmp_path):
    rtl = _mk_rtl(tmp_path)
    rep = CG.resolve("top", rtl)
    assert rep["verdict"] == "PASS" and rep["files_prunable"] == 1, rep
    adv, log = P._prune_tail_advisory(rep, "top")
    assert adv is not None and log is not None
    assert adv["files_prunable"] == 1
    assert "orphan.sv" in adv["examples"]
    assert adv["synth_top"] == "top"
    assert "prun" in log.lower() and "orphan.sv" in log   # prune / pruning
    assert "closure" in log.lower()
    assert "prune" in adv["recommendation"]
    assert "#778" in log


# ── §4.05: files_prunable==0 → NO advisory (no false noise) ──────────────────
def test_778_noleak_zero_prunable_no_advisory():
    adv, log = P._prune_tail_advisory(
        {"verdict": "PASS", "files_prunable": 0, "prunable": [],
         "files_reachable": 3, "files_total": 3}, "top")
    assert adv is None and log is None


def test_778_noleak_missing_or_bad_count_no_advisory():
    # absent / non-int count must not crash and must not emit noise.
    assert P._prune_tail_advisory({}, "top") == (None, None)
    assert P._prune_tail_advisory(
        {"files_prunable": "x", "prunable": []}, "top") == (None, None)


# ── the advisory is a PURE describer — it never mutates the report/verdict ───
def test_778_advisory_does_not_mutate_report(tmp_path):
    rtl = _mk_rtl(tmp_path)
    rep = CG.resolve("top", rtl)
    before = dict(rep)
    P._prune_tail_advisory(rep, "top")
    assert rep["verdict"] == before["verdict"]
    assert rep["files_prunable"] == before["files_prunable"]


# ── a clean single-design (no prunable tail) gets no advisory ───────────────
def test_778_noleak_clean_closure_no_advisory(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.sv").write_text(
        "module top(input a, output b); child u(.x(a), .y(b)); endmodule\n")
    (rtl / "child.sv").write_text(
        "module child(input x, output y); assign y = x; endmodule\n")
    rep = CG.resolve("top", rtl)
    assert rep["files_prunable"] == 0, rep
    assert P._prune_tail_advisory(rep, "top") == (None, None)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
