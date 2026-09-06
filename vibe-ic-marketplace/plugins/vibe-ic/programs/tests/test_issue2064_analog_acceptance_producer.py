#!/usr/bin/env python3
"""ORGANIC #2064 — a PRODUCER for analog-acceptance testbenches.

WHAT WAS MEASURED, u_hawaii_adc at v1.18.3 (lane czacctb, 8HD-6, front door,
image 0.3.46 `sha256:06537f7e`): the design's own `## Verification intent`
section becomes four L10 rows of `kind: verification_intent`;
`testbench_gen`'s scaffold scope is the functional-vector family, so it
reported "0 in scope, 4 out of scope"; and no other producer in the tree could
author one either. Step 4's denominator was therefore four with a numerator
nothing could raise. Adding `verification_intent` to
`cpu_functional_oracle_waiver_check._NON_EXECUTABLE_TEST_KINDS` would have
passed Step 4 on an EMPTY denominator and was refused by ruling.

These tests pin the producer's contract and, above all, its FOUR verdicts,
which must never collapse into two:

    PASS          the declared bound holds at every EXECUTED corner
    FAIL          a measured value is outside the declared bound
    NOT_MEASURED  the acceptance is derivable and nothing measured it
    REFUSED       the input states no acceptance for this row / quantity

Every check below is proven in BOTH directions: the fixture that must be green
and the byte-adjacent fixture that must be red. A check that cannot fail is not
a check.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import analog_acceptance_tb_gen as A      # noqa: E402
import testbench_gen as T                 # noqa: E402
import _sim_results_bridge as SRB         # noqa: E402


# --------------------------------------------------------------------------
# Fixtures. Every name below is a GENERIC placeholder: no chip, vendor, node,
# SKU or part literal appears in this file (see `test_no_design_literal`).
# --------------------------------------------------------------------------
_ROW_VALUE = "dc_point_and_regulation_for_block_a"
_ROW_CORNERS = "multi_corner_tt_ss_ff_over_temperature"
_ROW_GOLDEN = "golden_cross_check_against_the_fabricated_part"
_ROW_PROSE = "tool_disclosure_the_kit_ships_corner_libraries"


def _write(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    return path


def _l10(project: Path, names) -> Path:
    return _write(project / "phase1/generated_docs/L10_TEST_CASES.json", {
        "test_cases": [
            {"name": n, "kind": "verification_intent",
             "stimulus": s,
             "expected": "verification intent satisfied",
             "evidence": "input/docs/spec.md (Verification intent section)"}
            for n, s in names]})


def _l22(project: Path, *, block_a_specs, block_b_specs=None,
         scoped_intent=None, unscoped_intent=None) -> Path:
    analog = [{"block": "block_a", "block_type": "regulator",
               "specifications": block_a_specs,
               "verification_intent": scoped_intent or []}]
    if block_b_specs is not None:
        analog.append({"block": "block_b", "block_type": "converter",
                       "specifications": block_b_specs,
                       "verification_intent": []})
    return _write(project / "phase1/generated_docs/L22_VERIFICATION_PLAN.json",
                  {"fields": {"verification_plan": {
                      "schema_version": 1, "track": "analog_mixed_signal",
                      "analog": analog,
                      "unscoped_intent": unscoped_intent or []}}})


def _a4(project: Path, block: str, *, quantity="vout", values=None,
        executed=True) -> Path:
    """An A4 corner-sweep record in the shape `analog_real_corner_sweep` writes."""
    values = values if values is not None else [
        ("mos_tt", -40, 1.192), ("mos_tt", 27, 1.191), ("mos_tt", 125, 1.190),
        ("mos_ss", -40, 1.192), ("mos_ss", 27, 1.191), ("mos_ss", 125, 1.189),
        ("mos_ff", -40, 1.193), ("mos_ff", 27, 1.192), ("mos_ff", 125, 1.191)]
    corners = [{"name": f"{p}_{t}c", "process": p, "temp_c": t,
                "simulator_run": executed, f"{quantity}_v": v}
               for p, t, v in values]
    return _write(project / f"phase3/analog/{block}/corner_results.json", {
        "block": block, "_provenance": "real_ngspice",
        "total_corners": len(corners), "corners_executed": len(corners),
        "corners": corners,
        "spec_results": [{"name": quantity, "status": "PASS",
                          "value": corners[0][f"{quantity}_v"]}]})


_BOUNDED_VOUT = {"name": "Vout", "target_raw": "1.2", "range_raw": "1.1-1.3",
                 "unit": "V", "target": 1.2, "min": 1.1, "max": 1.3}
_UNBOUNDED_REG = {"name": "Load reg", "target_raw": "best-effort",
                  "range_raw": "-", "unit": "-"}
_TARGET_ONLY = {"name": "Iload", "target_raw": "0.5", "range_raw": "-",
                "unit": "mA", "target": 0.5}


def _value_project(tmp_path: Path, **kw) -> Path:
    project = tmp_path / "proj"
    _l10(project, [(_ROW_VALUE, "DC operating point + load regulation "
                                "(Vout) for the block")])
    _l22(project,
         block_a_specs=kw.pop("specs", [_BOUNDED_VOUT]),
         scoped_intent=[{"phase": _ROW_VALUE,
                         "method": "DC operating point + load regulation "
                                   "(Vout) for the block",
                         "evidence": "input/docs/spec.md"}])
    if kw.pop("record", True):
        _a4(project, "block_a", **kw)
    return project


# --------------------------------------------------------------------------
# 1. The no-op control. A design with no analog verification plan must be
#    byte-for-byte unchanged — no directory, no file, no report.
# --------------------------------------------------------------------------
def test_digital_only_project_is_a_byte_for_byte_noop(tmp_path):
    project = tmp_path / "proj"
    _write(project / "phase1/generated_docs/L10_TEST_CASES.json",
           {"test_cases": [{"name": "vector_1", "kind": "functional_vector"}]})
    before = sorted(p.relative_to(project).as_posix()
                    for p in project.rglob("*") if p.is_file())

    rep = {}
    assert A.emit_acceptance_checks(project, rep) == -1
    assert A.run_acceptance_checks(project, rep) == -1
    assert rep["applicable"] is False and "no L22" in rep["reason"]

    after = sorted(p.relative_to(project).as_posix()
                   for p in project.rglob("*") if p.is_file())
    # MEMBERSHIP, not a count: a substitution cannot disturb a count.
    assert before == after, f"producer wrote {set(after) - set(before)}"
    assert not A.check_dir(project).exists()
    assert not A.result_dir(project).exists()


def test_an_analog_plan_with_no_intent_row_is_also_a_noop(tmp_path):
    project = tmp_path / "proj"
    _l10(project, [])
    _l22(project, block_a_specs=[_BOUNDED_VOUT])
    rep = {}
    assert A.emit_acceptance_checks(project, rep) == -1
    assert "nothing for this producer to author" in rep["reason"]


# --------------------------------------------------------------------------
# 2. The value-bound clause, in BOTH directions.
# --------------------------------------------------------------------------
def test_bounded_quantity_inside_its_range_passes_at_every_corner(tmp_path):
    project = _value_project(tmp_path)
    rep = {}
    assert A.emit_acceptance_checks(project, rep) == 1
    clause = rep["clauses"][0]
    assert clause["kind"] == "value_bound" and clause["quantity"] == "vout"
    assert clause["bound"]["min"] == 1.1 and clause["bound"]["max"] == 1.3
    verdict, detail = A.evaluate_clause(project, clause)
    assert verdict == A.PASS, detail
    # The verdict must NAME the corners it read, not just assert a pass.
    assert "9 executed corner(s)" in detail and "mos_ss_125c" in detail


def test_a_value_outside_the_declared_bound_fails(tmp_path):
    """NEGATIVE CONTROL, byte-adjacent to the green fixture: one corner moved
    out of the declared range and nothing else."""
    bad = [("mos_tt", -40, 1.192), ("mos_tt", 27, 1.191),
           ("mos_tt", 125, 1.190), ("mos_ss", -40, 1.192),
           ("mos_ss", 27, 1.191), ("mos_ss", 125, 1.401),   # <- the only edit
           ("mos_ff", -40, 1.193), ("mos_ff", 27, 1.192),
           ("mos_ff", 125, 1.191)]
    project = _value_project(tmp_path, values=bad)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    verdict, detail = A.evaluate_clause(project, rep["clauses"][0])
    assert verdict == A.FAIL, detail
    assert "mos_ss_125c" in detail and "1.401" in detail


def test_a_value_only_at_an_unexecuted_corner_is_not_measured(tmp_path):
    """`simulator_run: false` is not a measurement. Crediting it would make a
    corner nobody ran read exactly like one that passed."""
    project = _value_project(tmp_path, executed=False)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    verdict, detail = A.evaluate_clause(project, rep["clauses"][0])
    # The record still carries a `spec_results` value, so the clause degrades
    # to that single measurement rather than inventing corner coverage.
    assert verdict in (A.PASS, A.NOT_MEASURED)
    assert "corner" in detail


def test_absent_a4_record_is_not_measured_and_never_a_pass(tmp_path):
    project = _value_project(tmp_path, record=False)
    rep = {}
    assert A.emit_acceptance_checks(project, rep) == 1
    # The clause is an INPUT artefact and carries no record path: where the
    # measurement lives is resolved when the check RUNS. See
    # `test_a_check_emitted_before_the_analog_track_reads_the_later_record`.
    assert "record" not in rep["clauses"][0]
    verdict, detail = A.evaluate_clause(project, rep["clauses"][0])
    assert verdict == A.NOT_MEASURED
    assert "A4" in detail and "not a pass" in detail


# --------------------------------------------------------------------------
# 3. The corner-coverage clause, in BOTH directions.
# --------------------------------------------------------------------------
def _corner_project(tmp_path: Path, **kw) -> Path:
    project = tmp_path / "proj"
    method = "Multi-corner: TT/SS/FF x -40/27/125 C."
    _l10(project, [(_ROW_CORNERS, method)])
    _l22(project, block_a_specs=[_BOUNDED_VOUT],
         unscoped_intent=[{"phase": _ROW_CORNERS, "method": method,
                           "evidence": "input/docs/spec.md"}])
    _a4(project, "block_a", **kw)
    return project


def test_a_declared_pvt_matrix_that_really_ran_passes(tmp_path):
    project = _corner_project(tmp_path)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    clause = [c for c in rep["clauses"] if c["kind"] == "corner_coverage"][0]
    assert clause["corner_matrix"]["process"] == ["TT", "SS", "FF"]
    assert clause["corner_matrix"]["temperature_c"] == [-40, 27, 125]
    verdict, detail = A.evaluate_clause(project, clause)
    assert verdict == A.PASS, detail
    assert "all 9 declared corner(s)" in detail


def test_a_missing_corner_of_the_declared_matrix_fails(tmp_path):
    short = [("mos_tt", -40, 1.19), ("mos_tt", 27, 1.19), ("mos_tt", 125, 1.19),
             ("mos_ss", -40, 1.19), ("mos_ss", 27, 1.19), ("mos_ss", 125, 1.19),
             ("mos_ff", -40, 1.19), ("mos_ff", 27, 1.19)]  # ff@125 removed
    project = _corner_project(tmp_path, values=short)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    clause = [c for c in rep["clauses"] if c["kind"] == "corner_coverage"][0]
    verdict, detail = A.evaluate_clause(project, clause)
    assert verdict == A.FAIL, detail
    assert "FF@125C" in detail


def test_a_derived_but_unexecuted_corner_is_not_credited(tmp_path):
    """The A4 record distinguishes a corner a simulator RAN from one it
    derived. Ignoring `simulator_run` would credit the derivation."""
    project = _corner_project(tmp_path, executed=False)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    clause = [c for c in rep["clauses"] if c["kind"] == "corner_coverage"][0]
    verdict, detail = A.evaluate_clause(project, clause)
    assert verdict == A.NOT_MEASURED, detail
    assert "simulator_run=true" in detail


# --------------------------------------------------------------------------
# 4. Refusals, each NAMED. A refusal is never a pass and never silent.
# --------------------------------------------------------------------------
def test_a_named_quantity_the_input_does_not_bound_is_refused_by_name(tmp_path):
    project = tmp_path / "proj"
    method = "Check the load reg of the block"
    _l10(project, [(_ROW_VALUE, method)])
    _l22(project, block_a_specs=[_UNBOUNDED_REG],
         scoped_intent=[{"phase": _ROW_VALUE, "method": method,
                         "evidence": "input/docs/spec.md"}])
    _a4(project, "block_a")
    rep = {}
    A.emit_acceptance_checks(project, rep)
    refusals = {r["id"]: r for r in rep["refusals"]}
    hit = [r for r in refusals.values()
           if r["reason_class"] == "NO_DECLARED_BOUND"]
    assert hit, rep["refusals"]
    assert "Load reg" in hit[0]["detail"] and "best-effort" in hit[0]["detail"]
    assert rep["rows"][0]["authorable"] is False


def test_a_target_without_a_tolerance_is_not_a_bound(tmp_path):
    """A target alone cannot decide pass from fail. Inventing a tolerance
    would be inventing the acceptance."""
    assert A._bound_of(_TARGET_ONLY) is None
    assert A._bound_of(_BOUNDED_VOUT) is not None


def test_the_golden_cross_check_row_is_refused_under_4_05(tmp_path):
    project = tmp_path / "proj"
    method = ("Golden cross-check (verify stage only): the fabricated part's "
              "extracted netlist")
    _l10(project, [(_ROW_GOLDEN, method)])
    _l22(project, block_a_specs=[_BOUNDED_VOUT],
         unscoped_intent=[{"phase": _ROW_GOLDEN, "method": method,
                           "evidence": "input/docs/spec.md"}])
    _a4(project, "block_a")
    rep = {}
    A.emit_acceptance_checks(project, rep)
    assert rep["clauses"] == []
    assert rep["refusals"][0]["reason_class"] == "SECTION_4_05_GOLDEN"
    assert "4.05" in rep["refusals"][0]["detail"]
    assert rep["rows"][0]["authorable"] is False


def test_a_row_that_states_no_acceptance_is_refused_by_name(tmp_path):
    project = tmp_path / "proj"
    method = "Tool disclosure: the kit ships sectioned corner libraries."
    _l10(project, [(_ROW_PROSE, method)])
    _l22(project, block_a_specs=[_BOUNDED_VOUT],
         unscoped_intent=[{"phase": _ROW_PROSE, "method": method,
                           "evidence": "input/docs/spec.md"}])
    _a4(project, "block_a")
    rep = {}
    A.emit_acceptance_checks(project, rep)
    assert rep["clauses"] == []
    assert rep["refusals"][0]["reason_class"] == "NO_ACCEPTANCE_DERIVABLE"


# --------------------------------------------------------------------------
# 5. The emitted check is really EXECUTABLE, and its exit code is the verdict.
# --------------------------------------------------------------------------
def test_the_emitted_check_is_an_executable_program(tmp_path):
    project = _value_project(tmp_path)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    script = A.check_dir(project) / f"{rep['clauses'][0]['id']}.py"
    assert script.is_file()
    # The AUTHORED ACCEPTANCE must be readable in the file itself, not hidden
    # behind a library call: a reviewer has to see which bound is asserted.
    text = script.read_text()
    assert '"min": 1.1' in text and '"max": 1.3' in text
    proc = subprocess.run([sys.executable, str(script)],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == A._EXIT[A.PASS], proc.stdout + proc.stderr
    assert "ANALOG_ACCEPTANCE" in proc.stdout and " PASS" in proc.stdout


def test_the_emitted_check_exits_non_zero_on_a_real_failure(tmp_path):
    bad = [("mos_tt", 27, 9.99)]
    project = _value_project(tmp_path, values=bad)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    script = A.check_dir(project) / f"{rep['clauses'][0]['id']}.py"
    proc = subprocess.run([sys.executable, str(script)],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == A._EXIT[A.FAIL], proc.stdout + proc.stderr


def test_a_re_emission_removes_the_stale_checks(tmp_path):
    project = _value_project(tmp_path)
    A.emit_acceptance_checks(project, {})
    stale = A.check_dir(project) / "yesterdays_clause.py"
    stale.write_text("#\n")
    A.emit_acceptance_checks(project, {})
    assert not stale.exists(), (
        "a narrower derivation left yesterday's check behind, where the "
        "executor would run and count it again")


# --------------------------------------------------------------------------
# 6. The Step-4 JUnit. An acceptance nobody could run must NOT read as a
#    suite with nothing wrong in it.
# --------------------------------------------------------------------------
def test_unrunnable_acceptances_are_errors_never_skips(tmp_path):
    project = tmp_path / "proj"
    method_v = "DC operating point (Vout)"
    method_g = "Golden cross-check against the fabricated part"
    _l10(project, [(_ROW_VALUE, method_v), (_ROW_GOLDEN, method_g)])
    _l22(project, block_a_specs=[_BOUNDED_VOUT],
         scoped_intent=[{"phase": _ROW_VALUE, "method": method_v,
                         "evidence": "input/docs/spec.md"}],
         unscoped_intent=[{"phase": _ROW_GOLDEN, "method": method_g,
                           "evidence": "input/docs/spec.md"}])
    # No A4 record at all: the derivable acceptance is UNMEASURED.
    rep = {}
    A.emit_acceptance_checks(project, rep)
    A.run_acceptance_checks(project, rep)
    xml = (A.result_dir(project) / "results.xml").read_text()
    assert 'skipped="0"' in xml and "<skipped" not in xml
    summary = SRB.parse_junit(A.result_dir(project) / "results.xml")
    assert summary["errors"] == 2 and summary["passed"] == 0
    # ... and therefore the Step-4 professional-pass reader cannot credit it.
    assert SRB.find_professional_tb_pass(project) is None


def test_a_fully_green_acceptance_is_a_real_functional_pass(tmp_path):
    project = _value_project(tmp_path)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    A.run_acceptance_checks(project, rep)
    assert rep["passed"] == 1 and rep["failed"] == 0
    assert rep["not_measured"] == 0 and rep["refused"] == 0
    found = SRB.find_professional_tb_pass(project)
    assert found is not None and found["tests"] == 1
    assert A.RESULT_DIR_NAME in found["rel_path"]


def test_the_record_names_every_row_and_its_verdict(tmp_path):
    project = _value_project(tmp_path)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    A.run_acceptance_checks(project, rep)
    record = json.loads((project / A.RECORD_REL).read_text())
    assert record["rows_total"] == 1 and record["rows_authorable"] == 1
    assert [r["name"] for r in record["rows"]] == [_ROW_VALUE]
    assert record["cases"][0]["verdict"] == A.PASS


# --------------------------------------------------------------------------
# 7. The Step-4 DENOMINATOR accessor — the scope table two readers share.
# --------------------------------------------------------------------------
def test_flow_authorable_counts_the_union_not_one_producer_scope(tmp_path):
    project = _value_project(tmp_path)
    rows = T.load_l10_cases(project)
    flow = T.flow_authorable(project, rows)
    assert flow["total"] == 1
    assert flow["scaffold"] == 0, (
        "the verification_intent row must NOT be inside the scaffold scope — "
        "widening SCAFFOLD_KINDS is the empty-denominator pass the #2064 "
        "ruling refused")
    assert flow["analog_acceptance"] == 1 and flow["authorable"] == 1


def test_without_the_producer_the_count_is_absent_not_zero(tmp_path, monkeypatch):
    """MUTATION: remove the producer. `authorable` must fall back to the
    scaffold count and the analog key must be ABSENT — never reported as 0,
    which would read as "the producer looked and found none"."""
    project = _value_project(tmp_path)
    rows = T.load_l10_cases(project)
    monkeypatch.setattr(T, "acceptance_authorable_rows", lambda p: None)
    flow = T.flow_authorable(project, rows)
    assert "analog_acceptance" not in flow
    assert flow["authorable"] == 0 and flow["total"] == 1
    assert flow["unauthorable_kinds"] == {"verification_intent": 1}


def test_a_refused_row_is_not_authorable(tmp_path):
    project = tmp_path / "proj"
    method = "Tool disclosure: the kit ships sectioned corner libraries."
    _l10(project, [(_ROW_PROSE, method)])
    _l22(project, block_a_specs=[_BOUNDED_VOUT],
         unscoped_intent=[{"phase": _ROW_PROSE, "method": method,
                           "evidence": "input/docs/spec.md"}])
    assert A.authorable_row_names(project) == set()
    rows = T.load_l10_cases(project)
    assert T.flow_authorable(project, rows)["authorable"] == 0


# --------------------------------------------------------------------------
# 8. Wiring: the producer is CALLED, and the two jobs stay apart.
# --------------------------------------------------------------------------
def test_the_runner_declares_and_appends_both_steps():
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    for name in ("step_analog_acceptance_tb_gen",
                 "step_analog_acceptance_tb_run"):
        assert f"def {name}(" in src, f"{name} is not defined"
        assert f"plan.append({name}(project))" in src, (
            f"{name} is defined and never appended to the plan — the #797 "
            f"dormant-producer shape, refused again")


def test_the_front_door_re_evaluates_after_the_analog_track():
    """Step 4 runs BEFORE the A-track, so on a cold project every clause is
    honestly NOT_MEASURED. The front door must refresh the JUnit once A4 has
    written its records, or the whole-flow audit reads a stale verdict."""
    src = (PROGRAMS / "vibe_ic_one_shot_runner.py").read_text()
    assert "analog_acceptance_tb_gen.py" in src
    assert src.index("ANALOG A1..A8") < src.index(
        "ANALOG ACCEPTANCE (re-evaluated after A4)")


def test_verification_intent_stays_out_of_the_non_executable_kinds():
    """The refused shortcut, pinned. Passing Step 4 by declaring the rows
    non-executable is a pass over an EMPTY denominator."""
    import cpu_functional_oracle_waiver_check as W
    assert "verification_intent" not in W._NON_EXECUTABLE_TEST_KINDS


# --------------------------------------------------------------------------
# 9. chip-AGNOSTIC source guard.
# --------------------------------------------------------------------------
def test_no_design_literal_in_the_logic():
    """The producer DECLARES `CHIP_AGNOSTIC: strict-logic` (the convention
    `source_chip_agnostic_check.declared_strictness_site` reads), so the module
    docstring may name the design it was measured on — that is the provenance
    of its claims — and the LOGIC may not. This test is the lane that refuses;
    the gate only discloses the declaration."""
    import ast as _ast
    path = PROGRAMS / "analog_acceptance_tb_gen.py"
    text = path.read_text()
    assert "CHIP_AGNOSTIC: strict-logic" in text, (
        "the producer must declare its own strictness where an author editing "
        "it will see it")
    tree = _ast.parse(text)
    # Strip the MODULE docstring only; every nested docstring and comment
    # stays in scope, because that is where a literal would really hide.
    body = tree.body[1:] if (tree.body and isinstance(tree.body[0], _ast.Expr)
                             and isinstance(tree.body[0].value, _ast.Constant)
                             and isinstance(tree.body[0].value.value, str)
                             ) else tree.body
    logic = "\n".join(
        _ast.get_source_segment(text, node) or "" for node in body).lower()
    for literal in ("hawaii", "sg13g2", "sky130", "gf180", "ihp", "ee628",
                    "delta_sigma", "opentitan"):
        assert literal not in logic, (
            f"{literal!r} appears in the producer's logic — it must key on "
            f"the design's own declared structures, never a chip/vendor/SKU "
            f"literal")


# --------------------------------------------------------------------------
# 10. The clause SET is a property of the INPUT, not of the measurement.
#     Regression: an earlier revision derived a clause only for the quantities
#     the A4 record already measured. The producer then derived a DIFFERENT
#     number of clauses before and after the analog track had run, and every
#     declared bound nobody measured was named nowhere at all — which is the
#     one fact this producer exists to surface.
# --------------------------------------------------------------------------
def _two_bound_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    method = "DC operating point for the block"
    _l10(project, [(_ROW_VALUE, method)])
    _l22(project,
         block_a_specs=[_BOUNDED_VOUT,
                        {"name": "Rejection", "target_raw": ">= 40",
                         "range_raw": ">= 40", "unit": "dB", "min": 40.0}],
         scoped_intent=[{"phase": _ROW_VALUE, "method": method,
                         "evidence": "input/docs/spec.md"}])
    return project


def test_the_clause_set_does_not_move_when_the_record_appears(tmp_path):
    project = _two_bound_project(tmp_path)
    cold = {}
    A.emit_acceptance_checks(project, cold)
    cold_ids = sorted(c["id"] for c in cold["clauses"])

    _a4(project, "block_a")           # the analog track runs
    warm = {}
    A.emit_acceptance_checks(project, warm)
    warm_ids = sorted(c["id"] for c in warm["clauses"])

    # MEMBERSHIP, not a count.
    assert cold_ids == warm_ids, (
        f"the derivation moved with the measurement: "
        f"{set(warm_ids) ^ set(cold_ids)}")
    assert len(cold_ids) == 2, cold_ids


def test_a_declared_bound_the_record_never_measures_is_not_measured(tmp_path):
    """A bound the input states and the sweep never measured must get its own
    verdict, by name — never a silent omission and never a pass."""
    project = _two_bound_project(tmp_path)
    _a4(project, "block_a")           # measures `vout` only
    rep = {}
    A.emit_acceptance_checks(project, rep)
    A.run_acceptance_checks(project, rep)
    by_name = {c["name"]: c for c in rep["cases"]}
    hit = [c for n, c in by_name.items() if n.endswith("__rejection")]
    assert hit and hit[0]["verdict"] == A.NOT_MEASURED, by_name
    assert "Rejection" in hit[0]["detail"] and ">= 40.0 dB" in hit[0]["detail"]
    assert rep["passed"] == 1 and rep["not_measured"] == 1


# --------------------------------------------------------------------------
# 11. The emission happens BEFORE the analog track. A check emitted then must
#     read the record A4 writes AFTERWARDS.
#
#     MEASURED on the front door: an earlier revision froze the record PATH
#     into the emitted check at emission time. Step 4 runs before the A-track,
#     so every check was emitted pointing at nothing, and the post-A4
#     re-evaluation re-ran nine of them and reported nine NOT_MEASURED over a
#     record that was sitting right there.
# --------------------------------------------------------------------------
def test_a_check_emitted_before_the_analog_track_reads_the_later_record(tmp_path):
    project = _value_project(tmp_path, record=False)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    A.run_acceptance_checks(project, rep)
    assert rep["not_measured"] == 1 and rep["passed"] == 0

    _a4(project, "block_a")            # the A-track runs, LATER

    again = {}
    A.run_acceptance_checks(project, again)   # NO re-emission
    assert again["passed"] == 1 and again["not_measured"] == 0, (
        "the check emitted before A4 did not read the record A4 wrote")
    assert again["cases"][0]["record"] == (
        "phase3/analog/block_a/corner_results.json")
