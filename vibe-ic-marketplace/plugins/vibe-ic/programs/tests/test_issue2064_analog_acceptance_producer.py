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
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import analog_acceptance_tb_gen as A      # noqa: E402


def _check_env() -> dict:
    """The environment the EXECUTOR hands an emitted check: the producer's own
    directory. The check carries no absolute path of its own (see
    `test_the_emitted_check_carries_no_absolute_home_path`)."""
    env = dict(os.environ)
    env[A.PROGRAMS_DIR_ENV] = str(PROGRAMS)
    return env
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
#: The SAME quantity in the two states the J1 ruling separates. `_UNBOUNDED_REG`
#: above is the design SPEAKING ("best-effort"); this one is the input saying
#: nothing at all about the bound, in the spellings a spec table uses for an
#: empty cell.
_ABSENT_BOUND_REG = {"name": "Load reg", "target_raw": "—",
                     "range_raw": "", "unit": "-"}
_TBD_BOUND_REG = {"name": "Load reg", "target_raw": "TBD",
                  "range_raw": "—", "unit": "-"}


def _one_quantity_project(tmp_path: Path, spec: dict) -> Path:
    project = tmp_path / "proj"
    method = "Check the load reg of the block"
    _l10(project, [(_ROW_VALUE, method)])
    _l22(project, block_a_specs=[spec],
         scoped_intent=[{"phase": _ROW_VALUE, "method": method,
                         "evidence": "input/docs/spec.md"}])
    _a4(project, "block_a")
    return project


def test_a_quantity_the_input_declares_unbounded_is_disclosed_not_refused(
        tmp_path):
    """J1 RULING (2026-09-07). `best-effort` is the DESIGN'S OWN statement that
    no acceptance bound exists. The first revision refused it and emitted a
    JUnit `<error>`, which made an honest declaration a permanent red: nothing
    anyone could do to the design or the sweep would ever clear it."""
    project = _one_quantity_project(tmp_path, _UNBOUNDED_REG)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    assert rep["refusals"] == [], rep["refusals"]
    disc = rep["disclosures"]
    assert len(disc) == 1, disc
    assert disc[0]["verdict"] == A.DISCLOSED
    assert disc[0]["reason_class"] == "NO_BOUND_DECLARED"
    # The input's OWN WORDS are carried, not paraphrased.
    assert disc[0]["declared_value"] == "best-effort"
    assert "Load reg" in disc[0]["detail"] and "best-effort" in disc[0]["detail"]


def test_a_quantity_whose_bound_is_absent_is_still_refused(tmp_path):
    """The other half of the ruling, and the reason the two must not collapse:
    a bound the input never declared EITHER WAY is a bound withheld, and it
    still blocks."""
    project = _one_quantity_project(tmp_path, _ABSENT_BOUND_REG)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    assert rep["disclosures"] == [], rep["disclosures"]
    assert len(rep["refusals"]) == 1, rep["refusals"]
    assert rep["refusals"][0]["reason_class"] == "NO_DECLARED_BOUND"
    assert rep["refusals"][0]["verdict"] == A.REFUSED
    assert "declares NOTHING" in rep["refusals"][0]["detail"]
    assert rep["rows"][0]["authorable"] is False


def test_a_bound_still_to_be_determined_is_absent_not_declared(tmp_path):
    """`TBD` is a bound that has not been determined — the ABSENT case. Reading
    it as a declaration that no bound applies would let a placeholder buy the
    non-blocking treatment the ruling reserves for a real statement."""
    project = _one_quantity_project(tmp_path, _TBD_BOUND_REG)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    assert rep["disclosures"] == []
    assert [r["reason_class"] for r in rep["refusals"]] == ["NO_DECLARED_BOUND"]


def test_a_disclosed_non_acceptance_blocks_nothing(tmp_path):
    """VISIBLE and NON-BLOCKING, measured on all four consumers at once: the
    JUnit element, the suite counters, the run report, and the predicate the
    runner step's status is computed from."""
    project = tmp_path / "proj"
    method = "DC operating point (Vout) and the load reg of the block"
    _l10(project, [(_ROW_VALUE, method)])
    _l22(project, block_a_specs=[_BOUNDED_VOUT, _UNBOUNDED_REG],
         scoped_intent=[{"phase": _ROW_VALUE, "method": method,
                         "evidence": "input/docs/spec.md"}])
    _a4(project, "block_a")
    rep = {}
    A.emit_acceptance_checks(project, rep)
    A.run_acceptance_checks(project, rep)

    assert rep["failed"] == 0 and rep["not_measured"] == 0
    assert rep["refused"] == 0 and rep["disclosed"] == 1
    assert rep["passed"] == 1
    # THE STEP'S OWN PREDICATE. `disclosed` is deliberately not in it.
    blocking = (rep["failed"] or rep["not_measured"] or rep["refused"])
    assert not blocking and rep["passed"] > 0, rep["cases"]

    xml = (A.result_dir(project) / "results.xml").read_text()
    assert '<skipped type="DISCLOSED"' in xml and 'skipped="1"' in xml
    assert 'errors="0"' in xml and 'failures="0"' in xml
    # ... and it is VISIBLE: a testcase, by name, carrying the input's words.
    assert "__loadreg" in xml and "best-effort" in xml

    ledger = json.loads((project / A.RECORD_REL).read_text())
    assert [d["declared_value"] for d in ledger["disclosures"]] == ["best-effort"]
    assert ledger["rows"][0]["disclosures"], ledger["rows"][0]


def test_a_disclosure_never_credits_a_suite_either(tmp_path):
    """It blocks nothing AND it passes nothing. A suite whose only content is a
    disclosure must not read as a functional PASS — `passed` is 0, so the
    Step-4 professional-pass reader still returns None."""
    project = _one_quantity_project(tmp_path, _UNBOUNDED_REG)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    A.run_acceptance_checks(project, rep)
    summary = SRB.parse_junit(A.result_dir(project) / "results.xml")
    assert summary["tests"] == 1 and summary["skipped"] == 1
    assert summary["passed"] == 0 and summary["errors"] == 0
    assert SRB.find_professional_tb_pass(project) is None


def test_a_row_whose_only_outcome_is_a_disclosure_is_not_re_refused(tmp_path):
    """The `NO_ACCEPTANCE_DERIVABLE` fallback must not fire on a row the input
    DID speak about — that would re-erect the wall the ruling removed."""
    project = _one_quantity_project(tmp_path, _UNBOUNDED_REG)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    assert rep["refusals"] == []
    assert rep["rows"][0]["disclosures"] and not rep["rows"][0]["clauses"]


def test_the_runner_status_predicate_excludes_the_disclosure(tmp_path):
    """Read off the SOURCE, so a future edit that folds `disclosed` back into
    the blocking predicate is refused here and not only on a live run."""
    import ast as _ast
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    fn = [n for n in _ast.walk(_ast.parse(src))
          if isinstance(n, _ast.FunctionDef)
          and n.name == "step_analog_acceptance_tb_run"]
    assert fn, "the runner step is gone"
    status = [n for n in _ast.walk(fn[0]) if isinstance(n, _ast.Assign)
              and any(isinstance(t, _ast.Name) and t.id == "status"
                      for t in n.targets)]
    assert status, "no `status = ...` in the step"
    text = _ast.get_source_segment(src, status[0]) or ""
    for key in ("failed", "not_measured", "refused", "passed"):
        assert f'"{key}"' in text, (key, text)
    assert '"disclosed"' not in text, (
        "a disclosed non-acceptance is back in the blocking predicate; the "
        "input's own words say no bound exists, so nothing could ever clear it")


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
    proc = subprocess.run([sys.executable, str(script)], env=_check_env(),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == A._EXIT[A.PASS], proc.stdout + proc.stderr
    assert "ANALOG_ACCEPTANCE" in proc.stdout and " PASS" in proc.stdout


def test_the_emitted_check_exits_non_zero_on_a_real_failure(tmp_path):
    bad = [("mos_tt", 27, 9.99)]
    project = _value_project(tmp_path, values=bad)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    script = A.check_dir(project) / f"{rep['clauses'][0]['id']}.py"
    proc = subprocess.run([sys.executable, str(script)], env=_check_env(),
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
    import ast as _ast
    src = (PROGRAMS / "vibe_ic_one_shot_runner.py").read_text()
    assert "analog_acceptance_tb_gen.py" in src
    # ORDER IS READ OFF THE AST, NOT OFF `src.index`. A `str.index` anchor
    # moves the moment anyone writes a COMMENT containing the same words, and
    # then a green code order reads red (or the reverse) for a reason that has
    # nothing to do with the order.
    dispatch = {}
    for node in _ast.walk(_ast.parse(src)):
        if (isinstance(node, _ast.Call)
                and isinstance(node.func, _ast.Name)
                and node.func.id == "_run_phase"
                and node.args
                and isinstance(node.args[0], _ast.Constant)
                and isinstance(node.args[0].value, str)):
            dispatch.setdefault(node.args[0].value, node.lineno)
    a_track = [v for k, v in dispatch.items() if k.startswith("ANALOG A1")]
    accept = [v for k, v in dispatch.items() if "ACCEPTANCE" in k]
    assert a_track and accept, sorted(dispatch)
    assert min(a_track) < min(accept), (
        "the acceptance re-evaluation is dispatched BEFORE the A-track, so it "
        "would re-read the same absent records Step 4 already read")


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


# --------------------------------------------------------------------------
# 12. Step 4's own blocking SENTENCE counts this producer.
#
#     `cpu_functional_oracle_waiver_check._row_kind_disclosure` (#2055) ends
#     "the rest carry no stimulus ANY PRODUCER IN THE FLOW is scoped to drive"
#     and used to compute that claim by summing over `testbench_gen.
#     SCAFFOLD_KINDS` alone. MEASURED on the real design with this producer on
#     the tree: it printed "0 of 4" while the flow could author 2 of the 4.
# --------------------------------------------------------------------------
def test_step4_sentence_counts_the_analog_acceptance_producer(tmp_path):
    import cpu_functional_oracle_waiver_check as W
    project = _value_project(tmp_path)
    text = W._row_kind_disclosure(project)
    assert "1 of 1 row(s) are authorable" in text, text
    assert "by analog_acceptance_tb_gen" in text, text
    assert "0 of 1" not in text, (
        "the sentence still reports one producer's scope as the whole flow's")
    denom = W._row_kind_denominator(project)
    assert denom["rows_authorable_by_any_producer"] == 1
    assert denom["rows_authorable_by_analog_acceptance"] == 1
    # The scaffold key keeps meaning exactly what its name says.
    assert denom["rows_inside_tb_producer_scaffold_scope"] == 0


def test_step4_sentence_says_unmeasured_not_zero_when_the_producer_is_absent(
        tmp_path, monkeypatch):
    """MUTATION of the environment, not of the code: with the analog producer
    unreachable the sentence must NOT print a 0 nobody measured."""
    import cpu_functional_oracle_waiver_check as W
    project = _value_project(tmp_path)
    monkeypatch.setattr(T, "acceptance_authorable_rows", lambda p: None)
    text = W._row_kind_disclosure(project)
    assert "could NOT be asked" in text and "not zero" in text, text
    assert "by analog_acceptance_tb_gen" not in text
    denom = W._row_kind_denominator(project)
    assert "rows_authorable_by_analog_acceptance" not in denom


# --------------------------------------------------------------------------
# 13. Every artefact this producer writes appears under its FINAL name only
#     when it is complete.
#
#     CAUGHT BY A DIFF OF FAILURE CONTENT, not by a diff of failing test ids:
#     `atomic_artifact_write_check` was ALREADY red on the branch base for a
#     different program, so the test id was identical on both arms and only the
#     message differed — "1 program(s) newly write ..." became "2 program(s)",
#     with this one named. An already-red test absorbs a new defect silently.
# --------------------------------------------------------------------------
def test_every_artefact_is_written_atomically():
    import ast as _ast
    text = (PROGRAMS / "analog_acceptance_tb_gen.py").read_text()
    assert "_atomic_artefact" in text, (
        "the JUnit is the Step-4 functional denominator: a writer that dies "
        "mid-document must not leave a truncated file under the final name")
    bare = [n.lineno for n in _ast.walk(_ast.parse(text))
            if isinstance(n, _ast.Call)
            and isinstance(n.func, _ast.Attribute)
            and n.func.attr in ("write_text", "write_bytes")
            and not (isinstance(n.func.value, _ast.Name)
                     and n.func.value.id.startswith("_atomic"))]
    assert not bare, (
        f"non-atomic write(s) at line(s) {bare} — route them through "
        f"_atomic_artefact.write_text / write_json")


def test_the_junit_and_the_record_survive_a_re_run(tmp_path):
    """Idempotence, byte for byte: the producer is invoked twice by the flow
    (at Step 4, and again after the A-track)."""
    project = _value_project(tmp_path)
    A.emit_acceptance_checks(project, {})
    A.run_acceptance_checks(project, {})
    first = (A.result_dir(project) / "results.xml").read_text()
    A.run_acceptance_checks(project, {})
    assert (A.result_dir(project) / "results.xml").read_text().count(
        "<testcase") == first.count("<testcase")


# --------------------------------------------------------------------------
# 14. The emitted check lives in the PROJECT tree, which travels. It must
#     carry no personal absolute path, and it must refuse — NOT_MEASURED, not
#     FAIL — when it cannot find the producer.
# --------------------------------------------------------------------------
def test_the_emitted_check_carries_no_absolute_home_path(tmp_path):
    project = _value_project(tmp_path)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    A.run_acceptance_checks(project, rep)
    for artefact in list(A.check_dir(project).glob("*.py")) + [
            project / A.RECORD_REL]:
        text = artefact.read_text()
        assert "/home/" not in text and "/Users/" not in text, (
            f"{artefact.name} freezes a personal absolute path into a design "
            f"artefact; it would break anywhere but the machine that wrote it")
    record = json.loads((project / A.RECORD_REL).read_text())
    assert not record["results_xml"].startswith("/")
    assert not record["check_dir"].startswith("/")


def test_a_check_that_cannot_find_its_producer_is_not_measured(tmp_path):
    """Exiting 1 would report a design FAILURE the check never looked for."""
    project = _value_project(tmp_path)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    script = A.check_dir(project) / f"{rep['clauses'][0]['id']}.py"
    env = {k: v for k, v in os.environ.items()
           if k not in (A.PROGRAMS_DIR_ENV, "PYTHONPATH")}
    proc = subprocess.run([sys.executable, str(script)], env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == A._EXIT[A.NOT_MEASURED], (
        proc.returncode, proc.stdout, proc.stderr)
    assert "NOT_MEASURED" in proc.stdout and A.PROGRAMS_DIR_ENV in proc.stdout


def test_the_executor_hands_the_producer_directory_to_the_check(tmp_path):
    project = _value_project(tmp_path)
    rep = {}
    A.emit_acceptance_checks(project, rep)
    A.run_acceptance_checks(project, rep)
    assert rep["passed"] == 1 and rep["not_measured"] == 0, rep["cases"]
