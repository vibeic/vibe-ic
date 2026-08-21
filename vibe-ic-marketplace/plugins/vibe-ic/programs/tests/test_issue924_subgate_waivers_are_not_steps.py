#!/usr/bin/env python3
"""P0 SUB-GATE waivers were subtracted from the STEP denominator. vibe-ic#924.

THE DEFECT
==========
`counts` is a tally of STEPS. It is built by one statement::

    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

so every unit in it is one canonical step. Immediately after that statement the
producer added a SUB-GATE population into it::

    counts["WAIVED"] += len(structural_waivers)

`structural_waivers` is one entry per P0 structural sub-gate whose FAIL was
converted to a deferred waiver — all of them INSIDE the single step `P0`. And
`WAIVED` is in `_flow_verdict_tiers.EXCUSED`, which is precisely what the
denominator subtracts::

    total_required = (len(steps)
                      - sum(_n for _k, _n in counts.items() if _T.is_excused(_k))
                      + len(oss_blocked_skipped))

So N waived SUB-GATES removed N STEPS from a 63-step denominator while exactly
one step was involved — and the direction is unfavourable, because a smaller
denominator under an unchanged numerator RAISES the published ratio, by more the
more you waive.

MEASURED on the shipped CLI before the fix, same project, only the P0 records
varying (`Steps: 25 total (X/Y executed PASS, W DEFERRED via waiver)`)::

    N=0  Y=8  X/Y=12.5%     steps carrying a WAIVED status: 0
    N=1  Y=7  X/Y=14.3%     steps carrying a WAIVED status: 0
    N=2  Y=6  X/Y=16.7%     steps carrying a WAIVED status: 0
    N=3  Y=5  X/Y=20.0%     steps carrying a WAIVED status: 0
    N=4  Y=4  X/Y=25.0%     steps carrying a WAIVED status: 0

Nothing was waived at step level in ANY of those runs. It is also visible in
committed data: one published audit log reads

    Steps: 21 total (4/3 executed PASS, 3 DEFERRED via waiver)
      PASS=4  FAIL=0  MISSING=0  WAIVED-DEFERRED=3  SKIPPED=15

— a numerator LARGER than its denominator, over a per-verdict tally summing 22
across 21 steps. That is the same unit mismatch surfacing as arithmetic that
cannot be true of any run.

WHY THE FIX IS "EXCUSES NOTHING AT STEP LEVEL" AND NOT "EXCUSES ITS OWN STEP"
============================================================================
The intermediate reading — a sub-gate waiver excuses at most the one step it
lives in, i.e. contribute ``min(1, N)`` — assumes a waived sub-gate leaves P0
itself excused. It does not. ``_p0_umbrella_status`` is the sole owner of P0's
step verdict and its whole range is {SKIPPED-CONDITION, FAIL, INCOMPLETE, PASS};
it cannot return WAIVED, and with a WAIVED record present the reachable set is
{PASS, FAIL} — neither of which is EXCUSED. ``min(1, N)`` would therefore remove
from the denominator a step that is simultaneously counted in the NUMERATOR.
That is the same unit error at magnitude 1, so it is not an option this file
leaves open: :func:`test_p0_is_never_excused_at_step_level` pins the premise
by asking the shipped function, not by asserting a remembered fact.

WHAT MUST NOT CHANGE, AND WHY HALF THIS FILE IS THAT
====================================================
The addend had a purpose (v1.6.97 / issue #29): keep `Overall` at
PASS_WITH_WAIVERS rather than a bare PASS whenever a `--allow-thin-input`
waiver fired. A "fix" that simply stopped counting waivers would satisfy every
falsifying test above while deleting that, and would also make a real deferral
invisible — which is laundering, not repair. So each falsifying test is paired
with a guard that must hold IDENTICALLY before and after:

  * a STEP-level waiver must still remove exactly one step from the denominator,
    each (the mechanism a "stop counting waivers" fix would break);
  * a sub-gate waiver must still drive Overall to PASS_WITH_WAIVERS;
  * every sub-gate waiver must still be published, per gate, in the report;
  * a run with ZERO sub-gate waivers must be untouched in every field.

DISCOVERED, NOT ENUMERATED. No verdict word, bucket name or tally label is typed
in this file. The verdict vocabulary comes from `_flow_verdict_tiers` (the
producer's own classifier), the tally labels are scraped out of the line the
program itself printed, and the waivable gate names come from the producer's own
`_THIN_INPUT_WAIVER_GATES`. A bucket added tomorrow is compared by these tests
without anyone editing them.

TESTS THE PROGRAM, NOT A LOCAL COPY OF ITS RULE. Every number asserted on is
read back out of `main()`'s own stdout or its own `--json` report. This file
never recomputes `total_required`.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _flow_verdict_tiers as _T  # noqa: E402
import flow_compliance_check as F  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _p0_umbrella_probe_flow as _probe  # noqa: E402

#: The producer's own headline. Group order is the producer's own field order.
_HEADLINE = re.compile(
    r"^Steps:\s+(?P<total>\d+)\s+total\s+"
    r"\((?P<x>\d+)/(?P<y>\d+)\s+executed PASS,\s+"
    r"(?P<waived>\d+)\s+DEFERRED via waiver")
#: Any `LABEL=n` token. The label VOCABULARY is deliberately not written down —
#: whatever the producer printed is what gets summed.
_TALLY_TOKEN = re.compile(r"([A-Za-z][A-Za-z0-9_-]*)=(\d+)")


# ---------------------------------------------------------------------------
# fixtures — records in the producer's own shape, via its own constructors
# ---------------------------------------------------------------------------
def _pass(name):
    return F._p0_gate_record(name, "PASS", "", {"exit_code": 0})


def _subgate_waiver(name):
    """A P0 sub-gate whose FAIL was converted to a deferred waiver.

    Built through `_p0_waiver_record`, the producer's own constructor and the
    only thing either waiver-producing branch calls, so this fixture cannot
    carry a shape the program does not emit.
    """
    return F._p0_waiver_record({
        "gate": name,
        "review_required": True,
        "ticket": F._THIN_INPUT_WAIVER_TICKET,
        "evidence": "synthetic thin-input coverage-shape gap (test fixture)",
        "reason": "synthetic (test fixture)",
        "first_line": "FAIL — synthetic sub-gate failure (test fixture)",
    })


def _waivable_gate_names(n):
    """`n` gate names from the producer's OWN waivable-gate tuple.

    Not a hand-typed list: if that tuple is re-spelled, these fixtures follow
    it. The names are only labels here, but a fixture naming a gate the
    producer would never waive is a fixture testing a shape nothing emits.
    """
    names = list(F._THIN_INPUT_WAIVER_GATES)
    assert n <= len(names), (
        f"fixture wants {n} waivable gate names, the producer registers "
        f"{len(names)}")
    return names[:n]


#: Monotonic run counter, so every `_run` gets its own project tree.
_RUN_SEQ = [0]


def _run(tmp_path, monkeypatch, *, n_subgate_waivers=0, waived_steps=(),
         argv=("--lenient",), probe_flow=True):
    """Drive the SHIPPED `main()` and hand back exactly what it published.

    The gate RUNNER is stubbed (the established shape in this tree — see
    `test_p0_umbrella_verdict_coverage._run_main`) so the P0 sub-gate
    population is the independent variable. Everything under test —
    the `counts` tally, `total_required`, the headline, the tally line and the
    Overall verdict — is `main()`'s own code and is untouched by the stub.
    """
    # A FRESH tree per invocation. Two arms of one test can be identically
    # parameterised (in the N=0 case the base arm IS the arm), and a shared
    # directory would have made them one measurement wearing two names.
    _RUN_SEQ[0] += 1
    proj = tmp_path / (f"proj_{_RUN_SEQ[0]:02d}_sub{n_subgate_waivers}"
                       f"_steps{len(waived_steps)}")
    (proj / "rtl").mkdir(parents=True)
    (proj / "rtl" / "top.v").write_text(
        "module top(input a, output b); assign b = a; endmodule\n")
    if waived_steps:
        (proj / "waivers.json").write_text(json.dumps({"waived_steps": [
            {"id": sid,
             "reason": ("The bench this step measures on is not reachable "
                        "from this container, so the measurement it needs "
                        "cannot be taken here (test fixture)."),
             "approver": "issue924-test-harness",
             "ticket": "TEST-924",
             "review_required": True,
             "date": "2026-08-10"}
            for sid in waived_steps]}, indent=2))

    records = [_subgate_waiver(g)
               for g in _waivable_gate_names(n_subgate_waivers)]
    records.append(_pass("issue924_clean_sub_gate"))

    def _stub(_project, **kw):
        out = kw.get("records_out")
        if out is not None:
            out.extend(records)
        return (not any(r["verdict"] == "FAIL" for r in records),
                *F._p0_buckets_from_records(records))

    monkeypatch.setattr(F, "_run_structural_rtl_gates", _stub)
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES",
                        tuple(r["name"] for r in records))

    report = proj / "report.json"
    # THE SAME P0 ORDERING EDGE AS #1066, third file (found by a full sweep of
    # a38902d16, not by the matrix — it does not import this file).
    #
    # P0 declares blocks_on:[1] and step 1 declares blocks_on:[D1]; a tmp_path
    # project has run neither, so the ordering rule voids P0's PASS and reds the
    # run before this file's subject — whether a waived SUB-GATE moves the STEP
    # denominator — can decide anything:
    #
    #     [P0] ... = PASS marked done while dependency [1] Spec-to-RTL = MISSING
    #     PASS-VOIDED=1
    #
    # This file DETECTS that itself rather than asserting past it: four of its
    # five failures are its own guard, "fixture drifted: the zero-waiver arm is
    # FAIL, so the assertion below could not distinguish anything". It was
    # right; the flow's health had swallowed the independent variable.
    #
    # ONLY when this run does not waive real STEPS. A blanket probe was my
    # first attempt and it MEASURED WORSE: it fixed the five sub-gate tests and
    # broke all five `test_a_step_level_waiver_still_removes_exactly_one_step_
    # each` — a step-level waiver names step ids the 3-step probe flow does not
    # carry, so the waiver matches nothing. Net zero, different names.
    #
    # It is a PER-TEST parameter, not derived from `waived_steps`. Deriving it
    # was my second attempt and it measured worse again: the step-level test
    # pairs a base arm with NO waived steps against an arm WITH them, so a
    # per-call rule gave the two arms DIFFERENT flows and compared a 3-step
    # denominator against a 63-step one. Both arms of a comparison must stand
    # on the same flow, so the choice belongs to the test, not the call.
    argv_extra = []
    if probe_flow:
        flow_def = proj.parent / f"{proj.name}_p0_probe_flow.yaml"
        _probe.write_flow(flow_def)
        _probe.write_seed(proj)
        argv_extra = ["--flow-def", str(flow_def)]
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        rc = F.main([str(proj), "--json", str(report), *argv_extra, *argv])
    stdout = buf.getvalue()

    head = None
    for ln in stdout.splitlines():
        m = _HEADLINE.match(ln.strip())
        if m:
            head = {k: int(v) for k, v in m.groupdict().items()}
            head["line"] = ln
            break
    assert head is not None, (
        "the producer printed no headline — nothing downstream of this can "
        f"mean anything. stdout was:\n{stdout}")

    tally = None
    for ln in stdout.splitlines():
        toks = _TALLY_TOKEN.findall(ln)
        if toks and any(k.upper() == "PASS" for k, _ in toks):
            tally = {k: int(v) for k, v in toks}
            tally["_line"] = ln
            break
    assert tally is not None, (
        f"the producer printed no per-verdict tally line. stdout was:\n{stdout}")

    overall = next((ln.split(":", 1)[1].split("(")[0].strip()
                    for ln in stdout.splitlines()
                    if ln.startswith("Overall:")), None)
    assert overall is not None, f"no Overall line. stdout was:\n{stdout}"

    return {
        "rc": rc,
        "stdout": stdout,
        "head": head,
        "tally": tally,
        "overall": overall,
        "report": json.loads(report.read_text()),
    }


def _step_status_tally(report):
    """A Counter over the statuses the program itself gave its own steps."""
    return Counter(s["status"] for s in report["steps"])


#: 0 and every N the producer can actually reach. `N>1` is what the issue's
#: acceptance requires, and the multiplier is only visible above 1.
_ARMS = list(range(0, len(F._THIN_INPUT_WAIVER_GATES) + 1))


# ===========================================================================
# THE PREMISE — asked of the shipped function, not remembered
# ===========================================================================
def test_p0_is_never_excused_at_step_level():
    """`min(1, N)` is ruled out here, by measurement, not by argument.

    If `_p0_umbrella_status` could return an EXCUSED word, the step tally would
    already subtract P0 and "excuse at most its own step" would be the right
    reading. It cannot: WAIVED is not in its range at all, and with a WAIVED
    record present it returns only non-excused words. So a sub-gate waiver
    leaves a step that is still owed AND still in the numerator, and removing
    it from the denominator is wrong at any magnitude.
    """
    waived = [_subgate_waiver(g) for g in _waivable_gate_names(2)]
    reachable = set()
    for executed in (None, True, False):
        for records in ([], [_pass("a")], list(waived), waived + [_pass("a")],
                        waived + [F._p0_gate_record(
                            "a", "NOT_INVOCABLE", "argparse rejected argv",
                            {"exit_code": 2})]):
            reachable.add(F._p0_umbrella_status(executed, records))
    assert "WAIVED" not in reachable, (
        f"P0's own verdict CAN be WAIVED now ({sorted(reachable)}) — the "
        f"reasoning that a sub-gate waiver must not excuse a step needs "
        f"re-deriving before this file is trusted")

    with_waiver = {
        F._p0_umbrella_status(not any(r["verdict"] == "FAIL" for r in recs),
                              recs)
        for recs in (list(waived), waived + [_pass("a")])}
    excused = {s for s in with_waiver if _T.is_excused(s)}
    assert not excused, (
        f"with a sub-gate waiver present P0 can now be excused at step level "
        f"({sorted(excused)}); the denominator treatment must be re-decided")


# ===========================================================================
# FALSIFYING — these fail against the unfixed program
# ===========================================================================
@pytest.mark.parametrize("n", _ARMS)
def test_the_published_counts_are_a_tally_of_steps_and_nothing_else(
        tmp_path, monkeypatch, n):
    """Every bucket in the program's own `counts` must equal the number of
    steps in the program's own `steps` array carrying that status.

    This is the defect at its root and it is stated over the WHOLE vocabulary,
    not over `WAIVED`: nothing here names a bucket, so a future addend into any
    other counter is caught by the same assertion.
    """
    r = _run(tmp_path, monkeypatch, n_subgate_waivers=n)
    published = r["report"]["counts"]
    from_steps = _step_status_tally(r["report"])
    mismatched = {k: (v, from_steps.get(k, 0))
                  for k, v in published.items() if v != from_steps.get(k, 0)}
    assert not mismatched, (
        f"with {n} P0 SUB-GATE waiver(s), the published step tally disagrees "
        f"with the program's own per-step statuses in {mismatched} "
        f"(bucket: published vs steps-actually-carrying-it). A sub-gate "
        f"population is being counted in a counter whose unit is steps.")


@pytest.mark.parametrize("n", _ARMS)
def test_the_step_denominator_is_invariant_to_the_subgate_waiver_count(
        tmp_path, monkeypatch, n):
    """`total_required` counts STEPS, so waiving a SUB-GATE cannot move it.

    Compared against the same fixture with zero sub-gate waivers — same
    project, same flow, same everything else — so the only thing that could
    have moved the denominator is the independent variable.
    """
    base = _run(tmp_path, monkeypatch, n_subgate_waivers=0)
    arm = _run(tmp_path, monkeypatch, n_subgate_waivers=n)
    assert arm["head"]["y"] == base["head"]["y"], (
        f"{n} P0 SUB-GATE waiver(s) moved the STEP denominator from "
        f"{base['head']['y']} to {arm['head']['y']} (delta "
        f"{base['head']['y'] - arm['head']['y']}), raising the published "
        f"ratio from {base['head']['x']}/{base['head']['y']} to "
        f"{arm['head']['x']}/{arm['head']['y']}. Sub-gates are not steps.\n"
        f"  base headline: {base['head']['line']}\n"
        f"  arm  headline: {arm['head']['line']}")


@pytest.mark.parametrize("n", _ARMS)
def test_the_per_verdict_tally_line_sums_to_the_step_total(
        tmp_path, monkeypatch, n):
    """The parts of the tally line must sum to the number of steps.

    The producer's own note beside that line — "ON THE LINE, or the parts stop
    summing to the total" — is the contract. The labels are scraped from the
    line the program printed, so this holds over a vocabulary this test has
    never heard of. It is the same arithmetic that shows the defect in
    committed data (`PASS=4 FAIL=0 MISSING=0 WAIVED-DEFERRED=3 SKIPPED=15`
    summing 22 across 21 steps).
    """
    r = _run(tmp_path, monkeypatch, n_subgate_waivers=n)
    parts = {k: v for k, v in r["tally"].items() if not k.startswith("_")}
    assert sum(parts.values()) == r["head"]["total"], (
        f"with {n} P0 SUB-GATE waiver(s) the tally sums to "
        f"{sum(parts.values())} over {r['head']['total']} steps "
        f"(excess {sum(parts.values()) - r['head']['total']}): {parts}\n"
        f"  tally line: {r['tally']['_line'].strip()}")


@pytest.mark.parametrize("n", _ARMS)
def test_the_numerator_never_exceeds_the_denominator(
        tmp_path, monkeypatch, n):
    """A FLOOR, and stated as one: it does NOT discriminate on this fixture.

    `X/Y executed PASS` with X > Y is not a ratio, and the deflated denominator
    is how a committed audit log came to publish `4/3`. But reaching X > Y needs
    a numerator large enough to overtake the shrunken denominator, and this
    fixture's project passes exactly one step, so this assertion holds against
    the UNFIXED program too. It is recorded here as a permanent floor on the
    published pair — not as evidence that the fix works. The tests above are
    that evidence.
    """
    r = _run(tmp_path, monkeypatch, n_subgate_waivers=n,
             waived_steps=(33, 34))
    assert r["head"]["x"] <= r["head"]["y"], (
        f"with {n} P0 SUB-GATE waiver(s) the producer published "
        f"{r['head']['x']}/{r['head']['y']} executed PASS — more steps passed "
        f"than were required.\n  headline: {r['head']['line']}")


# ===========================================================================
# PAIRED GUARDS — these must hold IDENTICALLY before and after the fix.
# Without them, "stop counting waivers at all" satisfies everything above.
# Each was RUN against `origin/main` and passed there, which is what makes it
# a guard rather than a second copy of the tests above.
# ===========================================================================
@pytest.mark.parametrize("n", _ARMS)
def test_a_step_level_waiver_still_removes_exactly_one_step_each(
        tmp_path, monkeypatch, n):
    """THE GUARD THE ISSUE'S ACCEPTANCE ASKS FOR.

    Waiving a STEP is a step-level exemption and must still subtract, once per
    step, whatever the P0 sub-gate population is doing. A fix that deleted the
    waiver subtraction wholesale passes every falsifying test above and fails
    here.

    The waived steps come from the project's own `waivers.json`, read by the
    program's own loader and schema check, and the count subtracted is compared
    against the steps the PROGRAM says it waived — not against the number this
    test wrote into the file.
    """
    base = _run(tmp_path, monkeypatch, n_subgate_waivers=n, probe_flow=False)
    arm = _run(tmp_path, monkeypatch, n_subgate_waivers=n, probe_flow=False,
               waived_steps=(33, 34))
    waived_steps_seen = _step_status_tally(arm["report"])["WAIVED"]
    assert waived_steps_seen > 0, (
        "the fixture produced no step-level WAIVED step, so this guard would "
        "pass vacuously; the waivers.json path must be repaired before this "
        "file is trusted")
    assert arm["head"]["y"] == base["head"]["y"] - waived_steps_seen, (
        f"{waived_steps_seen} step-level waiver(s) moved the denominator by "
        f"{base['head']['y'] - arm['head']['y']}, not by "
        f"{waived_steps_seen}. A step-level waiver is a step-level exemption "
        f"and must still be subtracted exactly once each.")


@pytest.mark.parametrize("n", [a for a in _ARMS if a > 0])
def test_a_subgate_waiver_still_forces_PASS_WITH_WAIVERS(
        tmp_path, monkeypatch, n):
    """The whole point of the addend (v1.6.97 / issue #29), preserved.

    A deferred sub-gate is open work; the run must not report a bare PASS.
    This is what makes "just delete the line" the wrong fix.
    """
    base = _run(tmp_path, monkeypatch, n_subgate_waivers=0)
    arm = _run(tmp_path, monkeypatch, n_subgate_waivers=n)
    assert base["overall"] == "PASS", (
        f"fixture drifted: the zero-waiver arm is {base['overall']}, so the "
        f"assertion below could not distinguish anything")
    assert arm["overall"] == "PASS_WITH_WAIVERS", (
        f"{n} deferred P0 sub-gate(s) and the run reports "
        f"{arm['overall']} — a deferred sub-gate must never read as a bare "
        f"PASS")


@pytest.mark.parametrize("n", [a for a in _ARMS if a > 0])
def test_every_subgate_waiver_is_still_published_per_gate(
        tmp_path, monkeypatch, n):
    """ANTI-LAUNDERING. Making the finding disappear is not fixing it.

    Each waiver must still be in the report by gate name, still
    review_required, still ticketed — and its COUNT must still be somewhere on
    the operator-facing output, so the fix cannot pay for a correct denominator
    with a silent deferral.
    """
    r = _run(tmp_path, monkeypatch, n_subgate_waivers=n)
    published = r["report"]["thin_input_waivers"]
    assert len(published) == n, (
        f"{n} sub-gate waiver(s) fired, {len(published)} were published")
    assert {w["gate"] for w in published} == set(_waivable_gate_names(n))
    assert all(w["review_required"] is True for w in published)
    assert all(w["ticket"] for w in published)
    p0 = next(s for s in r["report"]["steps"] if s["id"] == "P0")
    reasons = "\n".join(p0["reasons"])
    for gate in _waivable_gate_names(n):
        assert gate in reasons, (
            f"P0's own reasons no longer name the deferred sub-gate {gate!r} "
            f"— the waiver stopped being auditable at the place an operator "
            f"reads it:\n{reasons}")


@pytest.mark.parametrize("n", [a for a in _ARMS if a > 0])
def test_the_subgate_deferral_count_is_disclosed_in_its_own_unit(
        tmp_path, monkeypatch, n):
    """FALSIFYING, and the other half of not-laundering.

    Taking the sub-gate population out of a step counter is only half a fix: if
    the count then appears nowhere, a correct denominator has been bought with
    a silent deferral, which is the failure the producer's own "ON THE LINE"
    note forbids. The unfixed program did disclose the number — as STEPS, which
    is the defect — so this asserts the number is present AND that the words
    around it name the unit it is actually in.
    """
    r = _run(tmp_path, monkeypatch, n_subgate_waivers=n)
    assert re.search(rf"\b{n}\b[^\n]*sub-gate", r["stdout"]), (
        f"the count {n} of deferred sub-gates never appears beside the word "
        f"'sub-gate' on the operator-facing output, so a reader cannot tell "
        f"what unit it is in:\n{r['stdout']}")


def test_a_run_with_zero_subgate_waivers_is_untouched(tmp_path, monkeypatch):
    """THE OTHER ARM THE ISSUE'S ACCEPTANCE REQUIRES.

    With no P0 sub-gate waiver there was never anything to mis-unit, so every
    published field must read exactly as it did: the verdict word, the exit
    code, a tally that is the step tally, a denominator that is the steps the
    producer's own classifier does not excuse, and a headline carrying no
    sub-gate clause at all.
    """
    r = _run(tmp_path, monkeypatch, n_subgate_waivers=0)
    assert r["overall"] == "PASS"
    assert r["rc"] == 0
    assert r["report"]["thin_input_waivers"] == []
    assert "sub-gate" not in r["head"]["line"], (
        f"a run with no sub-gate waiver grew a sub-gate clause: "
        f"{r['head']['line']}")
    assert r["report"]["counts"] == {
        k: _step_status_tally(r["report"]).get(k, 0)
        for k in r["report"]["counts"]}
    not_excused = sum(1 for s in r["report"]["steps"]
                      if not _T.is_excused(s["status"]))
    assert r["head"]["y"] == not_excused, (
        f"total_required is {r['head']['y']} over {not_excused} steps the "
        f"producer's own classifier does not excuse")
