#!/usr/bin/env python3
"""ORGANIC #761 — one L10 layer, two readers, two private scopes.

Measured on a full Phase-1 -> Phase-2 run: Phase 1 emitted 95 L10 cases typed
{happy_path 16, addr_max 32, len_max 32, pre_wake_false 15} and ZERO
`functional_vector`. The TB producer filtered on that one literal and reported

    SKIP  l10_unit_tb_gen   no functional_vector L10 cases — nothing to produce

while `l10_tb_conformance_check` graded every case in the layer and reported

    {"total": 95, "ok": 0, "fail": 95, "waived": 0}

Both statements were true; together they were unreadable. The SKIP stated a fact
about the FILTER in the shape of a fact about the LAYER, so the Step-4 FAIL read
as an extraction gap when it was a scope mismatch.

What this file pins, and what it deliberately does NOT:

  * the SKIP message states the LAYER fact — case count, kind histogram, the
    producer's own scope, and the named consequence (who grades the rest);
  * the gate NAMES BOTH SCOPES in its artefact (`producer_scope`,
    `producer_scope_gap`) and on stderr;
  * ONE definition of the scope, imported, so the two readers cannot drift;
  * the REAL per-case oracle emitters are no longer gated on the kind TOKEN —
    they are content-keyed and fail-closed, so a case Phase 1 typed
    `happy_path` now gets a genuine golden when one is derivable;
  * the substance-floor SCAFFOLD stays kind-scoped (§4.05 no-leak);
  * THE VERDICT IS UNCHANGED. 95 cases with no testbench still FAIL, rc is
    still 1, and the scope annotation never waives anything. "The checker stops
    caring" is the one outcome this fix must not have.

chip-AGNOSTIC: L10 kind grammar + a synthetic clocked core. No chip/vendor/SKU
literal anywhere.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import testbench_gen as TBG               # noqa: E402
import l10_tb_conformance_check as GATE   # noqa: E402
import design_one_shot_runner as R        # noqa: E402
import _path_layout as _pl                # noqa: E402


# --------------------------------------------------------------------------
# fixtures — the measured kind histogram, and a clocked core to bind a TB to
# --------------------------------------------------------------------------
_DUT_MODULE = "unit_core"
_DUT_RTL = """\
module unit_core (
    input        i_clk,
    input        i_rst,
    output       o_cyc,
    output [7:0] o_data
);
  reg cyc_q;
  always @(posedge i_clk) cyc_q <= !i_rst;
  assign o_cyc  = cyc_q;
  assign o_data = 8'hAA;
endmodule
"""

#: The histogram measured on the run that produced #761.
_MEASURED_HIST = (("happy_path", 16), ("addr_max", 32),
                  ("len_max", 32), ("pre_wake_false", 15))


def _measured_cases():
    cases = []
    for kind, n in _MEASURED_HIST:
        for i in range(n):
            cases.append({
                "id": f"{kind}_{i:02d}",
                "name": f"{kind}_{i:02d}",
                "kind": kind,
                "stimulus": f"drive opcode {i} under {kind}",
                "expected": f"response for {kind} {i}",
            })
    assert len(cases) == 95
    return cases


def _project(tmp_path, cases, rtl=_DUT_RTL, name="proj", key="test_cases") -> Path:
    proj = tmp_path / name
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L10_TEST_CASES.json").write_text(json.dumps({key: cases}))
    if rtl is not None:
        _pl.rtl_dir(proj).mkdir(parents=True, exist_ok=True)
        (_pl.rtl_dir(proj) / f"{_DUT_MODULE}.v").write_text(rtl)
    (_pl.sim_dir(proj) / "tb").mkdir(parents=True, exist_ok=True)
    return proj


def _run_gate(monkeypatch, proj: Path, extra=()):
    """Run the CONSUMER exactly as the flow runs it, returning (rc, artefact)."""
    monkeypatch.chdir(proj)
    out = "reports/phase2/gates/l10_tb_conformance.json"
    rc = GATE.main([
        "--l10", "phase1/generated_docs/L10_TEST_CASES.json",
        "--tb-dir", "phase2/stage1/sim/tb",
        "--summary", "phase2/stage1/sim/work/summary.txt",
        "--out", out, *extra,
    ])
    return rc, json.loads((proj / out).read_text())


# --------------------------------------------------------------------------
# 1. the SKIP message must state the LAYER fact, not the FILTER fact
# --------------------------------------------------------------------------
def test_761_skip_states_the_layer_not_the_filter(tmp_path):
    proj = _project(tmp_path, _measured_cases())
    res = R.step_l10_unit_tb_gen(proj, _DUT_MODULE)
    assert res.status == "SKIP", res.detail
    d = res.detail

    # the LAYER: how many cases exist, and of which kinds
    assert "95" in d, d
    for kind, n in _MEASURED_HIST:
        assert f"{kind} {n}" in d, d
    # the FILTER: what this producer is actually scoped for
    assert "functional_vector" in d and "scope" in d, d
    # the CONSEQUENCE: who grades the remainder, and what happens to them
    assert "l10_tb_conformance_check" in d, d
    assert "FAIL" in d, d
    # and the sentence that made the two scopes look like one is gone
    assert "nothing to produce" not in d, d


# --------------------------------------------------------------------------
# 2. the gate names BOTH scopes — and still fails all 95
# --------------------------------------------------------------------------
def test_761_gate_names_both_scopes_and_still_fails_all_95(
        tmp_path, monkeypatch, capsys):
    proj = _project(tmp_path, _measured_cases())
    R.step_l10_unit_tb_gen(proj, _DUT_MODULE)
    rc, art = _run_gate(monkeypatch, proj)

    # THE VERDICT IS UNCHANGED — this is the load-bearing assertion. A design
    # that ships no testbench for 95 declared cases is still marked down.
    assert rc == 1
    assert (art["total"], art["ok"], art["fail"], art["waived"]) == (95, 0, 95, 0)

    # what changed: the disagreement is now a first-class number in the artefact
    assert art["producer_scope_gap"] == 95
    scope = art["producer_scope"]
    assert scope["total"] == 95
    assert scope["kind_histogram"] == {k: n for k, n in sorted(
        _MEASURED_HIST, key=lambda kv: (-kv[1], kv[0]))}
    assert scope["in_scaffold_scope"] == 0
    assert scope["out_of_scaffold_scope"] == 95
    assert "functional_vector" in scope["scaffold_kinds"]

    # …and it is said out loud where the FAIL is reported
    err = capsys.readouterr().err
    assert "SCOPE DISAGREEMENT" in err, err
    assert "95 case(s)" in err and "happy_path 16" in err, err
    assert "grades ALL 95" in err, err

    # every out-of-scope failure carries the reason on the case itself
    miss = [r for r in art["results"] if r["status"] == "fail"]
    assert len(miss) == 95
    assert all(r["producer_scaffold_scope"] == "out" for r in miss)
    assert all(any("NO PRODUCER" in e for e in r["evidence"]) for r in miss)


# --------------------------------------------------------------------------
# 3. ONE definition of the scope, read by both — they cannot drift
# --------------------------------------------------------------------------
def test_761_one_scope_definition_read_by_both_readers():
    assert TBG.SCAFFOLD_KINDS, "the producer must DECLARE its scope"
    # the consumer's functional-vector vocabulary IS the producer's scope
    assert GATE._FUNCTIONAL_VECTOR_KINDS == TBG.SCAFFOLD_KINDS
    # the runner asks for the scope by the shared constant, not a local literal
    assert TBG.DEFAULT_SCAFFOLD_KIND in TBG.SCAFFOLD_KINDS
    # a kind inside the family resolves to the WHOLE family: a producer that
    # recognised only `functional_vector` while the consumer waived five tokens
    # was the same defect one level down
    assert TBG.scaffold_kind_scope("functional") == TBG.SCAFFOLD_KINDS
    assert TBG.scaffold_kind_scope("cmd_response") == frozenset({"cmd_response"})
    assert TBG.scaffold_kind_scope(None) is None


def test_761_both_readers_find_the_cases_in_the_same_places(tmp_path):
    """The same defect one field over: the producer read the case list under
    `test_cases`/`cases` only, while the gate read five keys. An L10 keyed
    `vectors` was 0 cases to the producer and N cases to the gate — a second
    private scope over the same layer. One tuple, imported by both."""
    assert tuple(GATE._L10_CASE_LIST_KEYS) == tuple(TBG.L10_CASE_LIST_KEYS)
    for key in TBG.L10_CASE_LIST_KEYS:
        proj = _project(tmp_path, [
            {"id": "c0", "name": "c0", "kind": "functional_vector",
             "stimulus": "s", "expected": "e"}], name=f"k_{key}", key=key)
        assert len(TBG.load_l10_cases(proj)) == 1, key
        assert len(GATE.load_l10(str(
            proj / "phase1/generated_docs/L10_TEST_CASES.json"))) == 1, key


# --------------------------------------------------------------------------
# 4. the REAL oracle emitters are no longer gated on the kind TOKEN
# --------------------------------------------------------------------------
def test_761_real_oracle_not_gated_on_kind_token(tmp_path, monkeypatch):
    """A boot-latency-shaped case that Phase 1 typed `happy_path` instead of
    `functional_vector`. The oracle emitters are content-keyed and fail-closed,
    so gating them on the token denied a genuine golden to a case whose only
    defect was its label. It now gets the REAL oracle — and the gate credits
    it, because the evidence is real."""
    case = {
        "id": "boot_first_fetch", "name": "boot_first_fetch",
        "kind": "happy_path",          # NOT functional_vector — the whole point
        "stimulus": "after reset release the first instruction fetch occurs",
        "expected": "within 8 cycles of reset release",
    }
    proj = _project(tmp_path, [case])
    res = R.step_l10_unit_tb_gen(proj, _DUT_MODULE)
    assert res.status == "PASS", res.detail

    tb = (_pl.sim_dir(proj) / "tb" / "boot_first_fetch.v").read_text()
    assert TBG.ORACLE_NONE_MARKER not in tb, "a REAL oracle, not the floor"
    assert f"{_DUT_MODULE} u_dut (" in tb
    assert "$fatal(1);" in tb

    rc, art = _run_gate(monkeypatch, proj)
    assert rc == 0
    assert (art["total"], art["ok"], art["fail"]) == (1, 1, 0)
    assert art["producer_scope_gap"] == 0


# --------------------------------------------------------------------------
# 5. §4.05 no-leak — the SUBSTANCE FLOOR stays kind-scoped
# --------------------------------------------------------------------------
def test_761_scaffold_stays_kind_scoped_and_case_still_fails(
        tmp_path, monkeypatch):
    """The scaffold is the part with a §4.05 side effect (a live driver flips
    off the #206 evidence suppression), so widening the oracle emitters must NOT
    drag the scaffold along. A `cmd_response` case that grounds no real oracle
    gets no testbench and still FAILs the gate."""
    proj = _project(tmp_path, [
        {"id": "cmd_read_id", "name": "cmd_read_id", "kind": "cmd_response",
         "opcode": "0x9C", "stimulus": "host sends 0x9C", "expected": "0xDE"}])
    report: dict = {}
    emitted = TBG.emit_unit_tbs(proj, _DUT_MODULE,
                                kind=TBG.DEFAULT_SCAFFOLD_KIND, report=report)
    assert emitted == 0, report
    assert list((_pl.sim_dir(proj) / "tb").glob("*.v")) == []
    assert report["scope"]["out_of_scaffold_scope"] == 1
    assert report["out_of_scaffold_scope"][0]["kind"] == "cmd_response"

    rc, art = _run_gate(monkeypatch, proj)
    assert rc == 1
    assert (art["ok"], art["fail"]) == (0, 1)
    assert art["producer_scope_gap"] == 1


# --------------------------------------------------------------------------
# 6. the annotation is not a back door
# --------------------------------------------------------------------------
def test_761_scope_annotation_never_waives(tmp_path):
    """`producer_scaffold_scope` is recorded on every result and consulted by
    NOTHING in the pass/fail decision. Feed evaluate() a layer entirely outside
    the producer's scope with no TB text at all: every case must still FAIL and
    nothing may be waived."""
    cases = _measured_cases()
    results, ok, fail = GATE.evaluate(
        cases, tb_blob="", summary="",
        producer_scaffold_kinds=TBG.SCAFFOLD_KINDS)
    assert (ok, fail) == (0, 95)
    assert GATE.count_waived(results) == 0
    assert GATE.count_checklist_gaps(results) == 0
    assert GATE.count_producer_scope_gap(results) == 95

    # and with the annotation switched off entirely the verdict is identical —
    # proving the scope record changed no decision, only the report.
    r2, ok2, fail2 = GATE.evaluate(cases, tb_blob="", summary="")
    assert (ok2, fail2) == (ok, fail)
    assert [r["status"] for r in r2] == [r["status"] for r in results]


# --------------------------------------------------------------------------
# 7. the MEASUREMENT the scope decision rests on
# --------------------------------------------------------------------------
_VACUOUS_TB = """\
`timescale 1ns/1ps
module tb_placeholder;
  initial begin
    $display("[TB traced_case] PASS_PLACEHOLDER (replace with real stimulus)");
    // unit_core u_dut (.i_clk(i_clk));   <-- DUT instantiation commented out
    $finish;
  end
endmodule
"""

_LIVE_SCAFFOLD = """\
// %s
`timescale 1ns/1ps
module live_scaffold;
  reg i_clk = 0; reg i_rst = 0;
  wire o_cyc; wire [7:0] o_data;
  unit_core u_dut (.i_clk(i_clk), .i_rst(i_rst), .o_cyc(o_cyc), .o_data(o_data));
  always #5 i_clk = ~i_clk;
  initial begin #100 i_rst = 1; #1000; $finish; end
endmodule
""" % TBG.ORACLE_NONE_MARKER


def test_761_why_the_scaffold_stayed_kind_scoped(tmp_path, monkeypatch):
    """This is the EVIDENCE for stopping the widening where it stopped, run as
    code rather than asserted in a comment.

    A scaffold is a LIVE driver. `l10_tb_conformance_check` suppresses its whole
    evidence blob only while NOTHING under the sim tree drives the DUT (#206), so
    ONE scaffold dropped beside a vacuous placeholder restores the blob and the
    placeholder's id-substring then CREDITS its case: rc goes 1 -> 0 with no new
    verification whatsoever. Widening the scaffold to all 95 cases would have
    done exactly this at scale — the "visible FAIL traded for an invisible one"
    the issue warned about.

    If a future change to the #206 suppression makes these two runs agree, this
    test FAILs — and that is the intended signal: the constraint that kept the
    scaffold kind-scoped would no longer hold, and the widening could be
    revisited. Do not delete it to make it green.
    """
    case = {"id": "traced_case", "name": "traced_case", "kind": "happy_path",
            "stimulus": "s", "expected": "e"}
    verdicts = {}
    for label, extra_tb in (("placeholder_only", None),
                            ("plus_live_scaffold", _LIVE_SCAFFOLD)):
        proj = _project(tmp_path, [case], name=label)
        tb = _pl.sim_dir(proj) / "tb"
        (tb / "tb_placeholder.v").write_text(_VACUOUS_TB)
        if extra_tb:
            (tb / "live_scaffold.v").write_text(extra_tb)
        verdicts[label] = _run_gate(monkeypatch, proj)

    rc_a, art_a = verdicts["placeholder_only"]
    rc_b, art_b = verdicts["plus_live_scaffold"]
    assert (rc_a, art_a["ok"], art_a["fail"]) == (1, 0, 1)
    assert art_a["vacuous_sim_tree"] is True
    # one live driver, zero new verification — and the case is now "covered"
    assert (rc_b, art_b["ok"], art_b["fail"]) == (0, 1, 0)
    assert art_b["vacuous_sim_tree"] is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
