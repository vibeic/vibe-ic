#!/usr/bin/env python3
"""FULLSTACKTB-FX (2026-09-29) — the review round's findings, each pinned.

  HIGH  a MEASURED functional FAIL from `bit_level_full_stack_tb_check` was
        dropped from the run verdict: the gate is in INFORMATIONAL_GATES, so a
        Step 5 whose only failure it was left `failing`, while the same design
        with no functional population stayed NOT_MEASURED and blocked. A
        failure was the cheapest way past Step 5.
  MED   a case with an oracle and a testbench that was built or run but gave
        no verdict (build failure, crash, a timeout) was dropped from the
        denominator — a design-caused hang read green.
  MED   the gate trusted the record's `short_population` label instead of
        re-deriving the case's stated population; the producer checked the
        population only when a golden count was printed, so a property
        oracle's bare PASS satisfied "≥ N" with one scenario.
  LOW   a crash in the functional judgement fell through to the legacy opcode
        check (rc 1, no verdict), which the informational filter then dropped.
  LOW   `ORACLE_TB_DONE n/n` with a non-zero rc scored PASSED untested.

And root ruling R-0929-X-QUALIFIED in the reset-invariant oracle: an output
may be X after reset release only while every qualifier the DESIGN INPUT
declares for it is known and inactive; no declared qualifier -> X is FAIL;
each exempted cycle is reported; nothing is inferred from a port's name.

chip-AGNOSTIC: every fixture is a synthetic design.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bit_level_full_stack_tb_check as gate  # noqa: E402
import reset_invariant_oracle_tb_gen as riv  # noqa: E402
import test_fullstacktb_functional_population as base  # noqa: E402

_GATE_CMD = ("bit_level_full_stack_tb_check . --json "
             "reports/phase2/gates/bit_level_full_stack.json")


def _fsf():
    return importlib.import_module("full_stack_functional_tb")


@pytest.fixture
def arith_class(monkeypatch):
    import testbench_gen as tbg
    monkeypatch.setattr(tbg, "_detect_ic_class",
                        lambda project: "digital_arithmetic_primitive")




# ===========================================================================
# HIGH — a measured functional FAIL keeps Step 5 in `failing`
# ===========================================================================




# ===========================================================================
# MEDIUM — an ERRORED case is part of the population
# ===========================================================================
def test_an_errored_case_is_not_dropped_from_the_denominator(
        tmp_path, arith_class, capsys):
    proj = base._mk_project(tmp_path, die=True)
    inner = base._FakeSim()

    def sim(argv, run_dir, container, tool, timeout):
        if argv[0] == "vvp" and Path(run_dir).name == "reset":
            inner.calls.append(list(argv))
            return 124, "simulation timed out\n"
        return inner(argv, run_dir, container, tool, timeout)

    rec = _fsf().generate(proj, "ctr", dispatch=sim,
                          model_resolver=base._resolver)
    by = {c["name"]: c for c in rec["cases"]}
    assert by["reset"]["state"] == "errored"
    assert by["random_equivalence"]["state"] == "passed"
    assert rec["verdict"] == "NOT_MEASURED", rec["reason"]
    assert rec["reason_class"] == "EXECUTION_ERROR"
    rc, res, out = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["verdict"] == "NOT_MEASURED", res
    assert res["rule"] == "functional_case_errored"
    assert res["errored_cases"] == ["reset"]
    assert out.rstrip().splitlines()[-1].startswith("INCOMPLETE:")


def test_a_record_cannot_hide_a_run_case_as_no_oracle(tmp_path, arith_class,
                                                      capsys):
    proj = base._mk_project(tmp_path, die=True)
    rec = _fsf().generate(proj, "ctr", dispatch=base._FakeSim(),
                          model_resolver=base._resolver)
    c = next(c for c in rec["cases"] if c["name"] == "reset")
    c["state"] = "no_oracle"                         # relabelled, still run
    _fsf().record_path(proj).write_text(json.dumps(rec))
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "functional_record_inconsistent", res


# ===========================================================================
# MEDIUM — the population shortfall is re-derived, never read off the label
# ===========================================================================
def test_gate_rederives_a_short_population_the_record_relabelled(
        tmp_path, arith_class, capsys):
    proj = base._mk_project(tmp_path, die=True)
    sim = base._FakeSim(lambda case, nv: (min(nv, 50), min(nv, 50))
                        if case == "random_equivalence" else (nv, nv))
    rec = _fsf().generate(proj, "ctr", dispatch=sim,
                          model_resolver=base._resolver)
    c = next(c for c in rec["cases"] if c["name"] == "random_equivalence")
    assert c["state"] == "short_population"
    c["state"] = "passed"                  # ONLY the label; hashes untouched
    _fsf().record_path(proj).write_text(json.dumps(rec))
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["verdict"] == "NOT_MEASURED", res
    assert res["rule"] == "functional_population_short"
    assert res["counts"]["short"] == 1 and res["counts"]["executed"] == 2


PROP_CORE = "dut_bus"
PROP_CORE_V = f"""module {PROP_CORE} (input clk, input rst, input [7:0] d,
                  output o_cyc, output o_we, output [7:0] o_data);
  reg c; assign o_cyc = c; assign o_we = 1'b0; assign o_data = d;
  always @(posedge clk) if (rst) c <= 0; else c <= ~c;
endmodule
"""
GLITCH_CASE = {"name": "rst_glitch_race", "kind": "functional_vector",
               "stimulus": "rst glitch 不應導致 bus race,至少 5 iterations",
               "expected": "holds"}


def _prop_project(tmp_path, l9_ports=None, cases=None):
    proj = base._mk_project(tmp_path, die=False,
                            cases=cases or [GLITCH_CASE])
    gd = proj / "phase1" / "generated_docs"
    (proj / "phase2/stage1/rtl" / f"{base.CORE}.v").unlink()
    base._write(proj / "phase2/stage1/rtl" / f"{PROP_CORE}.v", PROP_CORE_V)
    base._write(gd / "L9_INTEGRATION_SPEC.json", json.dumps({
        "top_module": PROP_CORE,
        "top_ports": l9_ports or [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "rst", "direction": "input", "width": 1},
            {"name": "d", "direction": "input", "width": 8},
            {"name": "o_cyc", "direction": "output", "width": 1},
            {"name": "o_we", "direction": "output", "width": 1},
            {"name": "o_data", "direction": "output", "width": 8}]},
        ensure_ascii=False))
    return proj


def test_a_property_pass_does_not_satisfy_a_stated_population(
        tmp_path, capsys, monkeypatch):
    """`[TB x] PASS` is ONE scenario; the case states at least 5."""
    import testbench_gen as tbg
    monkeypatch.setattr(tbg, "_detect_ic_class", lambda project: None)
    proj = _prop_project(tmp_path)
    rec = _fsf().generate(proj, None, dispatch=base._FakeSim(),
                          model_resolver=base._resolver)
    c = rec["cases"][0]
    assert c["family"] == "reset_invariant", c
    assert c["declared_population"] == 5
    assert c["state"] == "short_population", c
    assert rec["verdict"] == "NOT_MEASURED"
    c["state"] = "passed"                      # relabelled: the gate re-derives
    _fsf().record_path(proj).write_text(json.dumps(rec))
    rc, res, _ = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["rule"] == "functional_population_short", res


def test_population_shortfall_each_side():
    fsf = _fsf()
    assert fsf.population_shortfall(None, None) is None
    assert fsf.population_shortfall(1, None) is None
    assert fsf.population_shortfall(100, {"passed": 100, "total": 100}) is None
    assert "50" in fsf.population_shortfall(100, {"passed": 50, "total": 50})
    assert "one scenario" in fsf.population_shortfall(5, None)


# ===========================================================================
# LOW — a crash is NOT_MEASURED, never the legacy check's rc 1
# ===========================================================================
def test_a_malformed_record_entry_is_not_measured(tmp_path, arith_class,
                                                  capsys):
    proj = base._mk_project(tmp_path, die=True)
    rec = _fsf().generate(proj, "ctr", dispatch=base._FakeSim(),
                          model_resolver=base._resolver)
    rec["cases"].append("not a record")
    _fsf().record_path(proj).write_text(json.dumps(rec))
    rc, res, out = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["verdict"] == "NOT_MEASURED", res
    assert "INCOMPLETE:" in out


def test_a_crash_in_the_judgement_is_not_measured(tmp_path, capsys,
                                                  monkeypatch):
    proj = base._mk_project(tmp_path, die=False)

    def boom(project):
        raise RuntimeError("resolver exploded")

    monkeypatch.setattr(gate, "functional_full_stack_verdict", boom)
    rc, res, out = base._run_gate(proj, tmp_path, capsys)
    assert rc == 2 and res["verdict"] == "NOT_MEASURED", res
    assert res["rule"] == "functional_verdict_crashed"
    assert res["reason_class"] == "EXECUTION_ERROR"
    assert out.rstrip().splitlines()[-1].startswith("INCOMPLETE:")


@pytest.mark.parametrize("rc,state", [(0, "passed"), (1, "failed"),
                                      (None, "failed")])
def test_a_full_golden_count_needs_a_clean_exit(rc, state):
    assert _fsf().score_transcript(
        "c1", rc, "ORACLE_TB_DONE pass=28/28\n")["state"] == state


# ===========================================================================
# R-0929-X-QUALIFIED — the reset-invariant oracle
# ===========================================================================
_IN = [("clk", ""), ("rst", ""), ("d", "[7:0]")]
_OUT = [("o_cyc", ""), ("o_we", ""), ("o_data", "[7:0]")]


def test_a_qualifier_is_read_from_the_port_table():
    q = riv.qualifiers_from_statements(
        [("o_data", "寫入資料,於 o_we = 1 時有效"), ("o_we", "寫入啟用")],
        _OUT, _IN)
    assert q == {"o_data": [{"qualifier": "o_we", "active": "1",
                             "evidence": "寫入資料,於 o_we = 1 時有效"}]}


def test_a_qualifier_is_read_from_interface_prose():
    q = riv.qualifiers_from_statements(
        [(None, "Bus rules. o_data is sampled when o_we is high. "
                "o_cyc marks a cycle.")], _OUT, _IN)
    assert [(r["qualifier"], r["active"]) for r in q["o_data"]] == \
        [("o_we", "1")]
    assert "o_cyc" not in q and "o_we" not in q


def test_nothing_is_inferred_from_names_or_a_denied_sentence():
    """`write data` beside `write enable` is a NAME pairing, not a declared
    qualifier; a denied relation declares nothing either."""
    assert riv.qualifiers_from_statements(
        [("o_data", "寫入資料(typical)"), ("o_we", "寫入啟用")],
        _OUT, _IN) == {}
    assert riv.qualifiers_from_statements(
        [(None, "o_data is not qualified by o_we = 1")], _OUT, _IN) == {}
    # naming both under a condition word is not a declaration: the text must
    # bind the qualifier's ACTIVE level
    assert riv.qualifiers_from_statements(
        [("o_data", "write data, valid when o_we is set up")], _OUT, _IN) == {}
    # a multi-bit port is never a qualifier
    assert riv.qualifiers_from_statements(
        [("o_cyc", "valid when o_data = 1")], _OUT, _IN) == {}


def test_declared_output_qualifiers_reads_l9(tmp_path):
    proj = _prop_project(tmp_path, l9_ports=[
        {"name": "o_data", "direction": "output", "width": 8,
         "description": "write data, valid when o_we = 1"},
        {"name": "o_we", "direction": "output", "width": 1,
         "description": "write enable"}])
    # R-0929-X-QUALIFIED-4 (migrated): the oracle reads no description — a
    # sentence in L9 declares nothing until it is a D1-SIGNED structured field
    assert riv.declared_output_qualifiers(proj, _OUT, _IN) == {}
    from _qualified_by_fixture import sign_field
    sign_field(proj, "o_data", "o_we", "high")
    q = riv.declared_output_qualifiers(proj, _OUT, _IN)
    assert [r["qualifier"] for r in q["o_data"]] == ["o_we"]
    assert riv.declared_output_qualifiers(tmp_path / "nowhere", _OUT, _IN) \
        == {}


def _glitch_tb(qualifiers=None):
    case = {"name": "g", "stimulus": "rst glitch 不應導致 fetch race",
            "expected": "holds"}
    if qualifiers is None:
        return riv.emit_case_oracle_from_ports(case, "dut", _IN, _OUT, [])
    return riv.emit_case_oracle_from_ports(case, "dut", _IN, _OUT, [],
                                           qualifiers=qualifiers)


def test_every_cycle_from_the_first_edge_after_release_is_checked():
    tb = _glitch_tb()
    tail = tb.split("inside the reset glitch")[1]
    loop = re.search(r"for \(_i = 0; _i < (\d+); _i = _i \+ 1\) begin\s+"
                     r"@\(posedge clk\); @\(negedge clk\);", tail)
    assert loop and int(loop.group(1)) == riv.POST_RELEASE_CYCLES
    # no settling delay between the release and the first sampled edge
    between = tail[:loop.start()]
    assert "rst = 1'b0;" in between and "repeat" not in between
    # with no declared qualifier, X on ANY output is a FAIL — data included
    for n in ("o_cyc", "o_we", "o_data"):
        assert re.search(rf"if \(\^\({n}\) === 1'bx\) begin\s+errors = "
                         rf"errors \+ 1;", tail), n
    assert "X_EXEMPT" not in tb


def test_a_declared_qualifier_exempts_only_while_known_and_inactive():
    tb = _glitch_tb({"o_data": [{"qualifier": "o_we", "active": "1",
                                 "evidence": "valid when o_we = 1"}]})
    # o_data is the last output, so its block runs to the loop's end
    blk = tb.split("if (^(o_data) === 1'bx) begin")[1].split("endmodule")[0]
    # the exemption is `=== 1'b0` (known AND inactive): an X qualifier or an
    # asserted one falls to the FAIL branch
    assert "if ((o_we === 1'b0))" in blk
    assert "X_EXEMPT: cycle %0d" in blk
    assert re.search(r"else begin\s+errors = errors \+ 1;", blk)
    # the qualifier itself is unqualified: X on it is a FAIL
    we = tb.split("if (^(o_we) === 1'bx) begin")[1][:120]
    assert "errors = errors + 1;" in we
    assert "qualified by 'o_we' active=1" in tb


def test_an_active_low_qualifier_exempts_at_one():
    tb = _glitch_tb({"o_data": [{"qualifier": "o_we", "active": "0",
                                 "evidence": "valid when o_we = 0"}]})
    assert "if ((o_we === 1'b1))" in tb


def test_exempted_cycles_reach_the_record_and_the_gate_row():
    text = ("[TB g] X_EXEMPT: cycle 0 after release: output 'o_data' is X/Z "
            "while its declared qualifier(s) are inactive and known: o_we=0\n"
            "[TB g] PASS — RESET_GLITCH_NO_RACE holds\n")
    s = _fsf().score_transcript("g", 0, text)
    assert s["state"] == "passed"
    assert len(s["x_exemptions"]) == 1 and "o_we=0" in s["x_exemptions"][0]


def test_the_producer_wires_the_design_input_qualifiers(tmp_path,
                                                        monkeypatch):
    import testbench_gen as tbg
    monkeypatch.setattr(tbg, "_detect_ic_class", lambda project: None)
    ports = [{"name": "clk", "direction": "input", "width": 1},
             {"name": "rst", "direction": "input", "width": 1},
             {"name": "d", "direction": "input", "width": 8},
             {"name": "o_cyc", "direction": "output", "width": 1},
             {"name": "o_we", "direction": "output", "width": 1,
              "description": "write enable"},
             {"name": "o_data", "direction": "output", "width": 8,
              "description": "write data, sampled when o_we = 1"}]
    case = dict(GLITCH_CASE, stimulus="rst glitch 不應導致 bus race")
    proj = _prop_project(tmp_path, l9_ports=ports, cases=[case])
    rec = _fsf().generate(proj, None, dispatch=base._FakeSim(),
                          model_resolver=base._resolver)
    tb = (proj / rec["cases"][0]["tb"]).read_text()
    # R-0929-X-QUALIFIED-4 (migrated): the description alone wires nothing
    assert "X_EXEMPT" not in tb
    from _qualified_by_fixture import sign_field
    sign_field(proj, "o_data", "o_we", "high")
    rec = _fsf().generate(proj, None, dispatch=base._FakeSim(),
                          model_resolver=base._resolver)
    tb = (proj / rec["cases"][0]["tb"]).read_text()
    assert "if ((o_we === 1'b0))" in tb
    assert "qualified by 'o_we' active=1" in tb
