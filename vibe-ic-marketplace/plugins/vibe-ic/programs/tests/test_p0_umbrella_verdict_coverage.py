#!/usr/bin/env python3
"""The P0 umbrella certified a population it had not audited.

THE DEFECT
==========
`_run_structural_rtl_gates` returns `len(fails) == 0` and `main()` published it
as the P0 step's verdict. `fails` is drawn from the gates that RETURNED a
verdict; the step's name, its `gates` array and the pre-burn guard that reads
them are all about the gates that are REGISTERED. Those are different
populations, and the difference is not small.

MEASURED at v1.9.78 by running the real CLI end to end over 49 tracked
benchmark projects (every project root under `benchmark-data` /
`benchmark_external` carrying RTL, minus the 58-project
`run_v1333_knowledge_converge` cvdp sub-corpus of near-duplicates). The same
three numbers on ALL 49:

    registered         246
    returned a verdict  210
    NOT_INVOCABLE        36   (argparse rejected the umbrella's argv, or the
                               gate hand-rolled a required-argument check for
                               an option the umbrella does not pass)

Identical on every project, which is the proof that the un-invocable set is a
property of the CALL and not of any project's content. So on a project whose
210 answering gates all come back clean, the umbrella printed `PASS` — over 246
checkers, 36 of which had never been validly invoked. What those 36 audit was
UNAUDITED, and the word `PASS` said the opposite.

#492 made the silence visible (`NOT_INVOCABLE` became a first-class verdict,
disclosed by name under its own heading). #559 put both numbers into the step's
name. Neither reached the VERDICT, and neither reached the machine-readable
artifact: `phase23_completion_audit.json` published `passed_gate_count` and
`failed_gate_count` — two numerators — over a denominator that appeared nowhere
in the file.

THE RULE
========
1. The umbrella emits invoked-count and registered-count as TWO NUMBERS, in the
   artifact and not only inside an English sentence.
2. It does not report an aggregate PASS while any registered gate was never
   validly invoked.

A gate that cannot be invoked is a REGISTRATION DEFECT, not an absence — which
is why the third branch is `INCOMPLETE` (#599: "the input WAS applicable and was
NOT examined... a vacuous step is one nobody needs to come back to; this is one
somebody does") and not `FAIL`. A gate that never ran said nothing about the
design; calling the run a failure would be a second false claim in the opposite
direction.

THE REVERSE CASE IS HALF OF THIS FILE, deliberately. A rule that refuses to say
PASS is trivially satisfiable by never saying PASS, and a filter tuned until a
count reaches zero swallows the defect underneath it. Every assertion that the
umbrella must NOT say PASS is paired with one where the property legitimately
holds and it must STILL say PASS — same fixture shape, one record changed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _flow_verdict_tiers as _T  # noqa: E402
import _p0_umbrella_probe_flow as _probe  # noqa: E402
import flow_compliance_check as F  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures — records in the umbrella's own shape, built by its own constructor
# ---------------------------------------------------------------------------
def _pass(name):
    return F._p0_gate_record(name, "PASS", "", {"exit_code": 0})


def _fail(name, msg="[FAIL] synthetic"):
    return F._p0_gate_record(name, "FAIL", msg, {"exit_code": 1})


def _skip(name):
    return F._p0_gate_record(
        name, "SKIP", "design declared no command protocol",
        {"exit_code": 2, "skip_kind": "class-not-applicable"})


def _not_invocable(name):
    """A gate the umbrella dispatched and that never got past argument parsing.

    The message is the classifier's own sentence, not a re-typed literal: the
    disclosure text and every downstream recogniser live in `_gate_invocation`,
    and a fixture that invents its own wording tests a shape nothing emits.
    """
    why = ("argparse rejected the umbrella's argv: the following arguments "
           "are required: --l9-file")
    return F._p0_gate_record(name, "NOT_INVOCABLE", why, {"exit_code": 2})


def _run_main(tmp_path, monkeypatch, records, extra_args=("--phase", "2",
                                                          "--strict-structural")):
    """Drive `main()` with the gate runner replaced by a fixed set of RECORDS.

    The established stub shape (`test_p0_failed_gate_names_preserved`,
    `test_p0_umbrella_registry_and_reporting`): the stub publishes the records
    and derives its 4-tuple from them exactly as the real umbrella does, so the
    assertions land on the shipped composer rather than on a fixture's idea of
    it.

    The REGISTRY is monkeypatched to the fixture's own gate names. Without it
    `registered_gate_count` is 246 while the stub published a handful of
    records, and the two numbers this file is about would be a fixture artefact
    instead of a statement. One test below deliberately does NOT do this — that
    is the case where the subtraction `registered - invoked` is wrong, which is
    why `not_invocable_gate_count` is its own field.

    THE FLOW IS THE FIXTURE'S TOO, carrying the shipped P0 verbatim over a
    SATISFIED `blocks_on` chain — see `_p0_umbrella_probe_flow`. On the shipped
    63-step flow a `tmp_path` project leaves P0's ancestry MISSING, and the
    step-execution ordering rule rewrites `PASS` to `PASS_VOIDED_BY_DEPENDENCY`
    and reds the run — deciding this file's verdicts before the umbrella's own
    word could be read, which is a statement about the empty project and not
    about the composer this file is for.
    """
    proj = tmp_path / "proj"
    (proj / "rtl").mkdir(parents=True)
    (proj / "rtl" / "top.v").write_text(
        "module top(input a, output b); assign b = a; endmodule\n")
    _probe.write_seed(proj)
    flow_def = tmp_path / "p0_probe_flow.yaml"
    _probe.write_flow(flow_def)

    def _stub(_project, **kw):
        out = kw.get("records_out")
        if out is not None:
            out.extend(records)
        return (not any(r["verdict"] == "FAIL" for r in records),
                *F._p0_buckets_from_records(records))

    monkeypatch.setattr(F, "_run_structural_rtl_gates", _stub)
    report = tmp_path / "report.json"
    rc = F.main([str(proj), "--json", str(report),
                 "--flow-def", str(flow_def), *extra_args])
    audit = json.loads(
        (proj / "reports" / "audit" /
         "phase23_completion_audit.json").read_text())
    step = next((s for s in json.loads(report.read_text())["steps"]
                 if s["id"] == "P0"), None)
    return rc, step, audit


def _registry(monkeypatch, records):
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES",
                        tuple(r["name"] for r in records))


# ===========================================================================
# RULE PART 2 — no aggregate PASS over a never-validly-invoked gate
# ===========================================================================
def test_a_clean_sweep_with_one_uninvoked_gate_is_not_a_PASS(
        tmp_path, monkeypatch, capsys):
    """THE DEFECT, end to end, on the artifact `main()` actually writes.

    Every gate that answered, answered PASS. One registered gate never got past
    argument parsing. The step used to publish `PASS`, i.e. a verdict about 4
    checkers stated as a verdict about 5.
    """
    records = [_pass("gate_a_check"), _pass("gate_b_check"),
               _pass("gate_c_check"), _pass("gate_d_check"),
               _not_invocable("gate_e_check")]
    _registry(monkeypatch, records)
    rc, step, audit = _run_main(tmp_path, monkeypatch, records)
    capsys.readouterr()
    assert step is not None, "P0 must be in the report in every outcome"
    assert step["status"] != "PASS", (
        "the umbrella certified 5 registered checkers on the strength of the 4 "
        f"that answered; status={step['status']!r}")
    assert step["status"] == "INCOMPLETE"
    assert rc == 0, (
        "INCOMPLETE is a disclosure tier, not a failure — it must not turn a "
        "run red on its own")


def test_a_clean_sweep_with_every_gate_invoked_IS_a_PASS(
        tmp_path, monkeypatch, capsys):
    """THE REVERSE CASE. Identical fixture, the fifth record answers.

    Without this, "never say PASS" satisfies the rule above, and so does any
    filter tuned until the count reaches zero. This is the assertion that says
    the rule fires on the property and not on the shape.
    """
    records = [_pass("gate_a_check"), _pass("gate_b_check"),
               _pass("gate_c_check"), _pass("gate_d_check"),
               _pass("gate_e_check")]
    _registry(monkeypatch, records)
    rc, step, audit = _run_main(tmp_path, monkeypatch, records)
    capsys.readouterr()
    assert step is not None and step["status"] == "PASS", (
        f"a fully-invoked clean sweep must still be a PASS; "
        f"status={step and step['status']!r}")
    assert rc == 0


def test_SKIP_and_WAIVED_do_not_cost_the_PASS(tmp_path, monkeypatch, capsys):
    """The other reverse case, and the one a careless predicate breaks.

    A declaration-derived `SKIP` and `WAIVED` are statements about what was
    audited.  They remain compatible with PASS; execution failures and empty
    denominators do not.  A rule keyed on "did every gate PASS", or on
    `invoked < registered`, would demote this legitimate reverse case too.
    """
    records = [_pass("gate_a_check"), _skip("gate_b_check"),
               _skip("gate_c_check"),
               F._p0_waiver_record({"gate": "gate_d_check", "ticket": "T-1",
                                    "review_required": True, "reason": "thin",
                                    "evidence": "e", "first_line": "boom"})]
    _registry(monkeypatch, records)
    rc, step, audit = _run_main(tmp_path, monkeypatch, records)
    capsys.readouterr()
    assert step["status"] == "PASS", (
        f"a declaration-derived SKIP and WAIVED remain compatible with PASS; "
        f"status={step['status']!r}")
    assert audit["not_invocable_gate_count"] == 0
    assert audit["invoked_gate_count"] == audit["registered_gate_count"] == 4


def test_a_real_FAIL_still_outranks_the_disclosure(
        tmp_path, monkeypatch, capsys):
    """A never-invoked gate must not soften a failure into a disclosure.

    `INCOMPLETE` is in none of `failing` / `missing` / `setup_required_skipped`,
    so a FAIL that reached it would leave the run green. The branch order is the
    guard, and this is the test that pins it.
    """
    records = [_fail("gate_a_check"), _not_invocable("gate_b_check")]
    _registry(monkeypatch, records)
    rc, step, audit = _run_main(tmp_path, monkeypatch, records)
    capsys.readouterr()
    assert step["status"] == "FAIL"
    assert rc != 0
    assert audit["failed_gates"] == ["gate_a_check"]
    # ...and the disclosure is still published beside it, not swallowed.
    assert audit["not_invocable_gate_count"] == 1


def test_no_RTL_is_still_SKIPPED_CONDITION(tmp_path, monkeypatch, capsys):
    """#447's tri-state survives. The umbrella that dispatched NOTHING is not
    INCOMPLETE — it has no population at all, and saying `INCOMPLETE` there
    would claim it tried."""
    def _stub(_project, **kw):
        out = kw.get("records_out")
        if out is not None:
            out.extend([])
        return (None, [], [F._P0_NO_RTL_NOTE], [])

    proj = tmp_path / "proj"
    (proj / "rtl").mkdir(parents=True)
    (proj / "rtl" / "top.v").write_text("module top; endmodule\n")
    monkeypatch.setattr(F, "_run_structural_rtl_gates", _stub)
    report = tmp_path / "report.json"
    F.main([str(proj), "--json", str(report), "--lenient"])
    capsys.readouterr()
    step = next(s for s in json.loads(report.read_text())["steps"]
                if s["id"] == "P0")
    assert step["status"] == "SKIPPED-CONDITION"


# ===========================================================================
# RULE PART 1 — invoked-count and registered-count, as TWO NUMBERS
# ===========================================================================
def test_the_artifact_publishes_the_denominator(
        tmp_path, monkeypatch, capsys):
    """`passed_gate_count` and `failed_gate_count` are numerators. Until this
    change the artifact carried no field a consumer could divide them by, and
    the number it would have guessed — the registry size — is the wrong one."""
    records = [_pass("gate_a_check"), _pass("gate_b_check"),
               _not_invocable("gate_c_check")]
    _registry(monkeypatch, records)
    _rc, step, audit = _run_main(tmp_path, monkeypatch, records)
    capsys.readouterr()
    for key in ("registered_gate_count", "invoked_gate_count",
                "not_invocable_gate_count"):
        assert key in audit, f"the artifact does not state {key}"
    assert audit["registered_gate_count"] == 3
    assert audit["invoked_gate_count"] == 2
    assert audit["not_invocable_gate_count"] == 1
    assert audit["passed_gate_count"] == 2


def test_the_headline_and_the_artifact_state_the_same_two_numbers(
        tmp_path, monkeypatch, capsys):
    """One fact, two renderings. #559 put the pair in the step NAME; a second
    pair computed at the artifact site is a second place to be wrong, and this
    repo has shipped that shape more than once."""
    records = [_pass("gate_a_check"), _not_invocable("gate_b_check"),
               _skip("gate_c_check")]
    _registry(monkeypatch, records)
    _rc, step, audit = _run_main(tmp_path, monkeypatch, records)
    capsys.readouterr()
    assert (f"{audit['invoked_gate_count']} of "
            f"{audit['registered_gate_count']} checkers returned a verdict"
            ) in step["name"], (step["name"], audit["invoked_gate_count"],
                                audit["registered_gate_count"])


def test_not_invocable_count_is_not_left_to_subtraction(
        tmp_path, monkeypatch, capsys):
    """`registered - invoked` equals the un-invoked count only while every
    registered gate has exactly one record — an invariant of the dispatch loop,
    not of this artifact. Here the registry is NOT patched to the fixture, so
    the subtraction says 245 and the truth is 1."""
    records = [_pass("gate_a_check"), _not_invocable("gate_b_check")]
    _rc, _step, audit = _run_main(tmp_path, monkeypatch, records)
    capsys.readouterr()
    assert audit["registered_gate_count"] == len(F._STRUCTURAL_RTL_GATES)
    assert audit["invoked_gate_count"] == 1
    assert audit["not_invocable_gate_count"] == 1
    assert (audit["registered_gate_count"] - audit["invoked_gate_count"]
            != audit["not_invocable_gate_count"]), (
        "the fixture no longer separates the field from the subtraction")


def test_the_counts_are_null_when_the_umbrella_did_not_run(
        tmp_path, monkeypatch, capsys):
    """Stage 3/4: there is no P0 step. `0 registered` would read as "the
    registry is empty" and `246 registered / 0 invoked` as "246 checkers were
    supposed to run and none did". Neither is true; `null` says so."""
    proj = tmp_path / "proj"
    (proj / "rtl").mkdir(parents=True)
    (proj / "rtl" / "top.v").write_text("module top; endmodule\n")
    report = tmp_path / "report.json"
    F.main([str(proj), "--json", str(report), "--stage", "3", "--lenient"])
    capsys.readouterr()
    audit = json.loads(
        (proj / "reports" / "audit" /
         "phase23_completion_audit.json").read_text())
    assert audit["registered_gate_count"] is None
    assert audit["invoked_gate_count"] is None
    assert audit["not_invocable_gate_count"] is None


# ===========================================================================
# THE REAL UMBRELLA, NO STUB — real subprocesses, real argv, real classifier
#
# Everything above replaces `_run_structural_rtl_gates` with a fixture, which
# is the established shape here and the only way to reach `main()` cheaply. It
# also means every record above was written by this file. The two tests below
# take the records from a REAL dispatch of the REAL registry over real RTL, and
# scope the registry to a population with no FAIL in it — which is the shape the
# corpus does not currently contain (every tracked project has failing
# structural gates, so the clean-sweep branch is never reached there and the
# sweep cannot exercise it).
# ===========================================================================
@pytest.fixture(scope="module")
def real_umbrella(tmp_path_factory):
    """One real run of the real umbrella over trivial synthetic RTL.

    chip-AGNOSTIC: an 8-bit counter, no PDK, no protocol, no design literal.
    """
    proj = tmp_path_factory.mktemp("p0_real")
    rtl = proj / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "top.v").write_text(
        "module top (input wire clk, input wire rst_n, output reg [7:0] q);\n"
        "  always @(posedge clk or negedge rst_n) begin\n"
        "    if (!rst_n) q <= 8'd0;\n"
        "    else        q <= q + 8'd1;\n"
        "  end\n"
        "endmodule\n")
    records: list = []
    passed, _f, _s, _w = F._run_structural_rtl_gates(proj, records_out=records)
    by = {v: [r["name"] for r in records if r["verdict"] == v]
          for v in F.P0_GATE_VERDICTS}
    if not by["NOT_INVOCABLE"] or not by["PASS"]:
        pytest.skip("the live registry yields no un-invocable gate and/or no "
                    "passing gate on trivial RTL — nothing to scope")
    return {"proj": proj, "passed": passed, "records": records, "by": by}


def test_real_gates_a_clean_registry_with_one_uninvoked_gate_is_INCOMPLETE(
        real_umbrella, monkeypatch):
    """The defect on real dispatch: no gate failed, one was never invoked."""
    by = real_umbrella["by"]
    scoped = tuple(by["PASS"] + by["NOT_INVOCABLE"][:1])
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES", scoped)
    records: list = []
    passed, fails, _s, _w = F._run_structural_rtl_gates(
        real_umbrella["proj"], records_out=records)
    assert fails == [], "the scoped registry must contain no failing gate"
    assert F._p0_not_invocable_count(records) >= 1
    assert F._p0_umbrella_status(passed, records) == "INCOMPLETE"


def test_real_gates_a_fully_invoked_clean_registry_is_PASS(
        real_umbrella, monkeypatch):
    """The reverse case on the same real dispatch: drop the one un-invoked gate
    and the same registry, the same project and the same code say PASS."""
    scoped = tuple(real_umbrella["by"]["PASS"])
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES", scoped)
    records: list = []
    passed, fails, _s, _w = F._run_structural_rtl_gates(
        real_umbrella["proj"], records_out=records)
    assert fails == []
    assert F._p0_not_invocable_count(records) == 0
    assert F._p0_umbrella_status(passed, records) == "PASS"


# ===========================================================================
# the decision function, as a truth table
# ===========================================================================
@pytest.mark.parametrize("executed,records,expected", [
    (None, [], "SKIPPED-CONDITION"),
    (None, [_not_invocable("g")], "SKIPPED-CONDITION"),
    (False, [_fail("g")], "FAIL"),
    (False, [_fail("g"), _not_invocable("h")], "FAIL"),
    # `len(fails) == 0` over a population of ZERO. Not reachable from the one
    # production call site today — `_run_structural_rtl_gates` appends one
    # record per registered gate, so `executed is not None` implies a full
    # records list — but this row is the PIN, and a pinned PASS outlives the
    # invariant that makes it unreachable. Pinned as INCOMPLETE so a future
    # caller that holds its own records list cannot inherit a certification
    # over nothing.
    #
    # RB2-03 (#2063) moved the two ZERO-population rows from `INCOMPLETE` to
    # `NOT-MEASURED`: both are adjudicated identically (a qualified done-claim,
    # in neither EXCUSED nor NON_GREEN — see `_flow_verdict_tiers`), so no run's
    # greenness moves, and the word now distinguishes "nothing answered" from
    # "some did not". The MIXED row below keeps `INCOMPLETE` and is what proves
    # the two cases have not been collapsed the other way.
    (True, [], "NOT-MEASURED"),
    (True, [_pass("g")], "PASS"),
    (True, [_pass("g"), _skip("h")], "PASS"),
    (True, [_not_invocable("g")], "NOT-MEASURED"),
    (True, [_not_invocable("g"), _not_invocable("h")], "NOT-MEASURED"),
    (True, [_pass("g"), _not_invocable("h")], "INCOMPLETE"),
])
def test_umbrella_status_truth_table(executed, records, expected):
    assert F._p0_umbrella_status(executed, records) == expected


def test_not_invocable_count_counts_only_that_verdict():
    recs = [_pass("a"), _fail("b"), _skip("c"), _not_invocable("d"),
            {"name": "e"}]          # an unfamiliar record shape
    assert F._p0_not_invocable_count(recs) == 1
    # the two numbers are complements over the SAME list
    assert (F._p0_verdict_count(recs) + F._p0_not_invocable_count(recs)
            == len(recs))


# ===========================================================================
# where INCOMPLETE lands in the roll-up — asserted against the tier module,
# not against a belief about it
# ===========================================================================
def test_incomplete_is_a_registered_producer_status():
    """`_flow_verdict_tiers` derives done-claim membership BY SUBTRACTION, so an
    unregistered word silently becomes a done-claim. INCOMPLETE was registered
    by #599; the umbrella is a new PRODUCER of it and that must stay true."""
    assert "INCOMPLETE" in _T.PRODUCER_STATUSES


def test_incomplete_cannot_turn_a_green_run_red():
    """The whole reason this is not `FAIL`. A gate that blocks every landing
    gets deleted, not fixed — so the tier discloses and does not block."""
    assert not _T.is_non_green("INCOMPLETE")


def test_incomplete_is_not_a_full_pass():
    """...and the whole reason it is not `PASS`. It is a QUALIFIED done-claim:
    it ran and did not fail, but it certified less than its population."""
    assert _T.is_done_claim("INCOMPLETE")
    assert not _T.is_full_pass("INCOMPLETE")
    assert _T.is_qualified_done("INCOMPLETE")


def test_incomplete_is_not_excused_from_the_denominator():
    """`EXCUSED` is what `total_required` subtracts. A P0 that certified 210 of
    246 is still a step that was required; removing it from the denominator
    would make the coverage gap improve the published ratio."""
    assert not _T.is_excused("INCOMPLETE")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
