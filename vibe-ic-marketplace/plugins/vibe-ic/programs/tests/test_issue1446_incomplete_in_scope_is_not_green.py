#!/usr/bin/env python3
"""vibe-ic#1446 — a P0 that measured NOTHING over a chain that never ran.

THE INPUT, on `--phase 2 --strict-structural` — the mode that narrows the
verdict scope to the P0 umbrella alone:

    [INCOMPLETE] Step P0: Structural-RTL gates
                 (P0 umbrella, 0 of 246 checkers returned a verdict)
    ✗ [P0] … = INCOMPLETE marked done while dependency [D1] … = MISSING
    Overall: PASS   rc=0

Zero of 246 checkers answered, the Phase-1 chain under them never ran, and the
only step inside the verdict scope published green.

WHY IT TOOK A CONJUNCTION TO FIX. Each half is already settled, in the other
direction, by a landed decision this file must not reopen:

  * INCOMPLETE ALONE MUST STAY GREEN. `test_p0_umbrella_verdict_coverage`
    asserts "INCOMPLETE is a disclosure tier, not a failure — it must not turn a
    run red on its own"; `test_issue497_step2_consumers_read_records` asserts
    "gates that never ran must not force the verdict". Both run over a SATISFIED
    `blocks_on` chain.
  * A BROKEN ANCESTRY ALONE MUST STAY GREEN, which is vibe-ic#1429: a terminal
    that RAN, AUDITED and PASSED, then had its PASS voided by an out-of-scope
    dependency (`PASS_VOIDED_BY_DEPENDENCY`), is informational in this mode. The
    void is about CERTIFICATION; the gates did look and saw clean.

So neither "INCOMPLETE gates" nor "the ordering guard reads the terminal" is
correct on its own — each was measured here and each breaks three landed tests.
What gates is the pair: nothing was measured, AND the inputs that would have
been measured were never produced. This file pins the conjunction and BOTH
single-condition controls, so a future repair of one half cannot silently take
the other with it.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "flow_compliance_check.py"

_L_DOCS = (
    "L1_DATASHEET", "L2_FRS", "L3_CMD_PROTOCOL", "L4_REGMAP", "L5_ADI_SPEC",
    "L6_CONTROL_LOGIC", "L7_TEST_DEBUG", "L8_TIMING_WAVEFORM",
    "L8_RTL_CONSTANTS", "L9_INTEGRATION_SPEC", "L10_TEST_CASES",
    "L11_OTP_CONTENT", "L12_BEHAVIORAL_SEQUENCES", "L13_BRINGUP",
)


def _import_fcc():
    """A fresh module object per test, so a monkeypatched gate runner cannot
    leak between cases."""
    spec = importlib.util.spec_from_file_location("fcc_issue1446", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fcc_issue1446"] = mod
    spec.loader.exec_module(mod)
    return mod


def _bare_project(tmp_path: Path) -> Path:
    """RTL and nothing else — P0's declared ancestry never ran."""
    project = tmp_path / "proj"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "core.sv").write_text("module core; endmodule\n")
    return project


def _close_ancestry(project: Path) -> Path:
    """Stage every artefact step D1 declares, so the chain under P0 is closed.

    D1 holds ALL of its `required_outputs` ("satisfied: N/20 — the gate passed,
    but every declared output must be produced"), so this has to stage the
    L-docs, the coverage report, the expert-track report AND the extraction
    pattern catalogue. If D1 gains a 21st,
    `test_the_ancestry_control_really_closes_the_chain` below goes red and names
    it, rather than this helper quietly ceasing to close anything.

    That is not hypothetical: #1348 added the 19th
    (`phase1/extraction_patterns.json`) and the control went red naming it
    (vibe-ic#1351), which is the mechanism this docstring promises, working.
    """
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    for name in _L_DOCS:
        (gd / f"{name}.json").write_text(
            json.dumps({"schema": name, "generated_by": "test fixture"}))
    # The 20th D1 output, added after this closed-ancestry control was written.
    # Presence is the contract under test here; physical floorplan semantics
    # remain owned by l9_floorplan_contract_check's own fixtures.
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({
        "schema": "L19_CONSTRAINTS_PDK", "generated_by": "test fixture"}))
    (gd / "L21_POWER_INTENT.json").write_text(json.dumps(
        {"schema": "L21_POWER_INTENT", "generated_by": "test fixture",
         "supply_pins": [], "external_supplies": [], "pads": []}))
    rp = project / "reports" / "phase1"
    rp.mkdir(parents=True, exist_ok=True)
    (rp / "extraction_coverage_report.md").write_text("# coverage\n\n100%\n")
    (rp / "extraction_coverage_report.json").write_text(
        json.dumps({"coverage_pct": 100}))
    ra = project / "reports" / "audit" / "phase1"
    ra.mkdir(parents=True, exist_ok=True)
    (ra / "expert_parse_track.json").write_text(json.dumps({
        "program": "phase1_expert_parse_track.py", "verdict": "PASS",
        "findings": [], "ai_subtrack": {"status": "SKIPPED-CONDITION"},
        "generated_by": "test fixture"}))
    # AND THE ANSWER THE SECOND PASS CONSUMES. Staging the REPORT alone does
    # not close this chain, and MEASURED on live main 7903c1972305 (2026-09-03,
    # pinned image sha256:66c33ff2..., host load 5.5) that is why both arms of
    # this file were red:
    #
    #   flow_compliance_check --phase 2 --strict-structural  ->  [FAIL] Step D1
    #   of D1's five blocking clauses:
    #     phase1_all_l_docs_present_check      rc 0
    #     analog_a0_skip_forbidden_check       rc 0
    #     l_doc_todo_stub_count_check          rc 0
    #     phase1_coverage_report_present_check rc 2
    #     phase1_expert_parse_track .          rc 1   <-- this
    #
    # `phase1_expert_parse_track` is a TWO-PASS protocol: a program cannot
    # spawn a subagent, so pass 1 writes the hand-off pack, reports
    # HANDOFF_EMITTED, and exits 1 by design — AND OVERWRITES the report this
    # fixture staged. Every headless invocation is pass 1, so D1 could not
    # pass on any tree, fixture or real. `1aa24ef268` (#2014) fixed exactly
    # this shape in `phase1_one_shot_runner`'s disposition layer and did not
    # reach this gate clause, which calls the program directly.
    #
    # A "closed ancestry" means a Phase 1 that really RAN, and a Phase 1 that
    # really ran has been through both passes. So the fixture stages the
    # SECOND pass's input: the agent answer the consumer reads back. Measured
    # end state — CONSUMED, 1 expectation, agreed 1, verdict PASS, rc 0.
    #
    # NOT DONE HERE, deliberately: downgrading D1's
    # `program_exit_zero: phase1_expert_parse_track .` to advisory. That is a
    # relabel, and it would change the verdict of every REAL run, not just
    # this fixture's. Nor is `CONSUMED_EMPTY` used — measured, it is also rc 1,
    # and #312 separated it from CONSUMED on purpose: an empty reading and a
    # full one produce the same zero findings and only one is coverage.
    pack = ra / "expert_parse_track_pack"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "l_doc_expectations.json").write_text(json.dumps({
        "expectations": [{
            "id": "ancestry-fixture-l1-schema",
            "layer": "L1",
            "field_path": "schema",
            "requirement": "L1 names its own schema",
            # `expected_tokens` is what makes an expectation DECIDABLE:
            # `converge_ai_expectation` refuses a prose-only one rather than
            # counting it as agreed. The token is satisfied by the L-doc stubs
            # staged above, so this answer is met by THIS fixture's tree and
            # not by assertion.
            "expected_tokens": ["L1_"],
            "evidence": ["staged by _close_ancestry: this fixture models a "
                         "Phase 1 that completed BOTH passes of the expert "
                         "track, not one that emitted a hand-off and stopped"],
            "expert_source": "test fixture"}]}))
    # The 19th (#1348). `phase1_doc_one_shot_runner._seed_canonical_from_
    # backfilled_subset` returns WITHOUT writing when nothing was backfilled,
    # and on a tree with no `input/docs` nothing can be — so a hand-staged
    # Phase 1 stages it. An object holding only the provenance key is that
    # seeder's own empty shape and parses as a catalogue with no entries, not as
    # MALFORMED (`extraction_coverage_check._load_explicit_patterns` wants a
    # top-level object and skips non-list values).
    (project / "phase1").mkdir(parents=True, exist_ok=True)
    (project / "phase1" / "extraction_patterns.json").write_text(json.dumps({
        "_comment": ("Canonical extraction patterns. No auto-discovered "
                     "literal was backfilled into a typed L doc on this tree, "
                     "so the catalogue is empty; staged by test fixture.")}))
    return project


def _stub_p0(monkeypatch, mod, *, passing: int):
    """P0 publishes `passing` records, all PASS, no FAIL.

    `passing=0` is NOT "the gates passed" — no record at all is what the
    empty-denominator guard reads as INCOMPLETE. That is the single variable
    separating each red case below from its control.
    """
    records = [mod._p0_gate_record(f"synthetic_gate_{i}", "PASS", "",
                                   {"exit_code": 0})
               for i in range(passing)]

    def _stub(_project, **kwargs):
        out = kwargs.get("records_out")
        if out is not None:
            out.extend(records)
        return (True, [], [], [])

    monkeypatch.setattr(mod, "_run_structural_rtl_gates", _stub)


def _status(out: str, step_id: str) -> str:
    m = re.search(rf"^\s*\S*\s*\[([\w-]+)\s*\] Step\s+{re.escape(step_id)}:",
                  out, re.M)
    assert m, f"PRECONDITION: step {step_id} must appear in the report:\n{out}"
    return m.group(1)


def _audit(mod, project, *flags):
    return mod.main([str(project), "--phase", "2", "--strict-structural",
                     *flags])


# ══ 1. THE DEFECT — both conditions present ═══════════════════════════════

def test_a_no_verdict_p0_over_a_broken_chain_is_not_green(
        tmp_path, monkeypatch, capsys):
    project = _bare_project(tmp_path)
    mod = _import_fcc()
    _stub_p0(monkeypatch, mod, passing=0)

    rc = _audit(mod, project)
    out = capsys.readouterr().out

    # PRECONDITIONS: both halves must actually be present, or this case is
    # passing for a reason it does not name.
    assert _status(out, "P0") == "INCOMPLETE", out
    assert re.search(r"\[P0\].*marked done while dependency", out), out

    assert rc == 1, out
    assert "Overall: FAIL" in out, out


def test_the_violation_that_gates_is_named_as_gating(
        tmp_path, monkeypatch, capsys):
    """SCOPED, NOT SUPPRESSED, in the other direction too: when the P0
    violation DOES reach the verdict it must not be filed under the
    "reported, NOT gating" tail, or the report contradicts its own verdict."""
    project = _bare_project(tmp_path)
    mod = _import_fcc()
    _stub_p0(monkeypatch, mod, passing=0)

    rep = tmp_path / "gating.json"
    mod.main([str(project), "--phase", "2", "--strict-structural",
              "--json", str(rep)])
    capsys.readouterr()

    doc = json.loads(rep.read_text())
    gating = doc["ordering_violations_gating"]
    assert [ln for ln in gating if "[P0]" in ln], (
        f"the P0 violation must reach the verdict; gating={gating!r}")


# ══ 2. CONTROL A — INCOMPLETE alone must stay green ═══════════════════════
#
# The half owned by #599 / #497: "gates that never ran must not force the
# verdict". Same no-record P0, chain CLOSED.

def test_an_incomplete_p0_over_a_closed_chain_stays_green(
        tmp_path, monkeypatch, capsys):
    project = _close_ancestry(_bare_project(tmp_path))
    mod = _import_fcc()
    _stub_p0(monkeypatch, mod, passing=0)

    rc = _audit(mod, project)
    out = capsys.readouterr().out

    assert _status(out, "P0") == "INCOMPLETE", (
        "PRECONDITION: this control is only meaningful while P0 is still "
        "INCOMPLETE — it is the OTHER condition that is supposed to have "
        "changed:\n" + out)
    assert rc == 0, (
        "INCOMPLETE alone must not turn a run red — #599's tier is a "
        "disclosure, not a failure:\n" + out)


def test_the_ancestry_control_really_closes_the_chain(
        tmp_path, monkeypatch, capsys):
    """`_close_ancestry` is a CLAIM, and a stale fixture does not fail — it
    just stops testing anything. vibe-ic#1446 was masked for exactly this
    reason: D1 gained an 18th `required_outputs` entry 25 seconds after the
    helper that stages them landed, so the "closed chain" fixture silently
    stopped closing the chain. Checked here so the next entry reddens a test
    that NAMES the missing artefact."""
    project = _close_ancestry(_bare_project(tmp_path))
    mod = _import_fcc()
    _stub_p0(monkeypatch, mod, passing=0)

    _audit(mod, project)
    out = capsys.readouterr().out

    assert _status(out, "D1") != "MISSING", (
        "`_close_ancestry` no longer closes P0's ancestry — D1 gained a "
        "`required_outputs` entry the helper does not stage. The report names "
        "it on D1's `required_outputs missing:` line:\n" + out)
    assert not re.search(r"\[P0\].*marked done while dependency", out), out


# ══ 3. CONTROL B — a broken chain alone must stay green (vibe-ic#1429) ═════

def test_a_voided_but_measured_p0_over_a_broken_chain_stays_green(
        tmp_path, monkeypatch, capsys):
    """THE #1429 CASE, and the reason this fix is a conjunction rather than
    "the ordering guard reads the terminal".

    Same broken chain, same violation naming P0 as the terminal — but P0's
    gates RAN and PASSED, so the step is PASS_VOIDED_BY_DEPENDENCY, not
    INCOMPLETE. A void is a statement about certification; #1429 settled that
    it is informational in the mode that declares step-level state
    informational, and this must stay green."""
    project = _bare_project(tmp_path)
    mod = _import_fcc()
    _stub_p0(monkeypatch, mod, passing=2)

    rc = _audit(mod, project)
    out = capsys.readouterr().out

    # PRECONDITION: the violation is still there — only P0's own tier differs.
    assert re.search(r"\[P0\].*marked done while dependency", out), (
        "PRECONDITION: this control needs the SAME violation as the defect "
        "case, so that P0's tier is the only variable:\n" + out)
    assert _status(out, "P0") != "INCOMPLETE", out
    assert rc == 0, (
        "a P0 whose gates measured and passed must stay informational when "
        "its dependency is out of verdict scope (vibe-ic#1429):\n" + out)


def test_the_step_level_violation_never_gates_either_way(
        tmp_path, monkeypatch, capsys):
    """`[1] Spec-to-RTL = PASS marked done while [D1] = MISSING` is #1429's own
    worked example. Its terminal is step-level, so it is outside the scope in
    BOTH arms and must never appear in the gating subset."""
    for passing in (0, 2):
        project = _bare_project(tmp_path / f"arm{passing}")
        mod = _import_fcc()
        _stub_p0(monkeypatch, mod, passing=passing)
        rep = tmp_path / f"arm{passing}.json"
        mod.main([str(project), "--phase", "2", "--strict-structural",
                  "--json", str(rep)])
        capsys.readouterr()
        doc = json.loads(rep.read_text())
        assert any("[1]" in ln for ln in doc["ordering_violations"]), (
            f"PRECONDITION (passing={passing}): the step-1 violation must be "
            f"REPORTED:\n{doc['ordering_violations']}")
        assert not [ln for ln in doc["ordering_violations_gating"]
                    if ln.startswith("[1]")], (
            f"passing={passing}: a step-level terminal must not gate "
            f"--strict-structural; gating={doc['ordering_violations_gating']!r}")


# ══ 4. THE SUBSET INVARIANT — gating is never wider than reported ═════════

def test_the_gating_subset_is_never_larger_than_what_was_reported(
        tmp_path, monkeypatch, capsys):
    """Adding a second way in must not let the gating list outgrow the
    disclosure list — every gating line has to be a line the reader saw."""
    for passing in (0, 2):
        project = _bare_project(tmp_path / f"sub{passing}")
        mod = _import_fcc()
        _stub_p0(monkeypatch, mod, passing=passing)
        rep = tmp_path / f"sub{passing}.json"
        mod.main([str(project), "--phase", "2", "--strict-structural",
                  "--json", str(rep)])
        capsys.readouterr()
        doc = json.loads(rep.read_text())
        reported = doc["ordering_violations"]
        gating = doc["ordering_violations_gating"]
        assert len(gating) <= len(reported), (passing, gating, reported)
        for line in gating:
            assert line in reported, (passing, line, reported)


def test_default_strict_mode_still_gates_on_every_violation(
        tmp_path, monkeypatch, capsys):
    """The complement: outside `--phase 2 --strict-structural` the scope is the
    whole run, so both readings admit everything and nothing here changes."""
    project = _bare_project(tmp_path)
    mod = _import_fcc()
    _stub_p0(monkeypatch, mod, passing=2)

    rc = mod.main([str(project), "--strict"])
    out = capsys.readouterr().out

    assert "Step-execution ordering violations" in out, out
    assert "NOT gating" not in out, (
        "in full-scope mode every violation gates, so the degrade-loudly line "
        "must not appear:\n" + out)
    assert rc == 1, out
