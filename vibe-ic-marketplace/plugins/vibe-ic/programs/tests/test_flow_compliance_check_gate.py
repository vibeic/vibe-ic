#!/usr/bin/env python3
"""Tests for flow_compliance_check.py — the sole Phase 2+3 acceptance gate."""
from __future__ import annotations
import json, re, shutil, subprocess, sys, tempfile
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "flow_compliance_check.py"

def _run(*args):
    return subprocess.run([sys.executable, str(PROG)] + list(args),
                          capture_output=True, text=True)

def test_help():
    r = _run("--help")
    assert r.returncode == 0

def test_error_missing_dir(tmp_path):
    r = _run(str(tmp_path / "nope"))
    assert r.returncode == 2

def test_runs_on_empty_project(tmp_path):
    r = _run(str(tmp_path))
    # Empty project likely fails (no flow artifacts) but should not crash
    assert r.returncode in (1, 2)


def test_list_structural_gates(tmp_path):
    """v0.119.24: discoverability flag — fresh agents can enumerate the
    full Step -1 gate set before designing, so they don't miss real-bug
    catchers like fpga_pad_fanout_check that earlier weren't in any
    auto-discoverable list."""
    r = _run("--list-structural-gates")
    assert r.returncode == 0
    # Spot-check a handful of expected gates across the lifetime of
    # the plugin
    for gate in ("fpga_pad_fanout_check",
                 "fpga_top_pin_completeness_check",
                 "tx_bit_width_min_resolution_check",
                 "fpga_clock_divider_antipattern_check",
                 "half_duplex_wrapper_open_drain_check",
                 "self_rx_mask_check"):
        assert gate in r.stdout, f"{gate} missing from --list output"


def test_list_structural_gates_no_project_dir_required():
    """The flag must work without project_dir argument."""
    r = _run("--list-structural-gates")
    assert r.returncode == 0
    assert "structural-RTL gates" in r.stdout


def test_no_project_dir_without_list_flag_errors():
    """Without --list-structural-gates, project_dir is still required."""
    r = _run()
    assert r.returncode == 2


def test_v029_phase_flag_present():
    """v0.119.29: --phase flag exposed in --help so fresh agents
    know they can scope a Phase-2-only audit."""
    r = _run("--help")
    assert "--phase" in r.stdout
    assert "Phase-2-only" in r.stdout or "Phase 2" in r.stdout


def test_v029_phase_2_limits_step_set(tmp_path):
    """A real audit on an empty project SHOULD still run; Phase 2 scope
    means only steps 1-6 are considered, so the report shouldn't
    mention Phase-3-only steps like `Final STA` or `Tapeout signoff`.
    Empty project still FAILs (no docs, no RTL), but the failure
    must be scoped to phase 2."""
    r = _run(str(tmp_path), "--phase", "2")
    # Empty project always FAILs Step 1 etc; what we test is that
    # Phase-3 step names are NOT in the report.
    # THE STEP, not the substring. A bare `"tapeout" not in stdout.lower()` was a
    # proxy for "no Phase-3-only step appears", and it stopped measuring that the
    # moment a PHASE-AGNOSTIC step acquired an artefact whose NAME contains the
    # word: step 0.5ic (in scope for both phases, as this command's own NOTE says)
    # declares `input/submission_template/tapeout_declaration.json` and gates on
    # `tapeout_declaration_check`, so the proxy fired on a report that contained
    # no Phase-3-only step at all. The phase-3-only step it was really guarding is
    # 36, `Tapeout checklist`; asserting that name keeps the property and drops
    # the false positive. Its sibling below already asserts on a step NAME
    # (`Spec-to-RTL`) for the symmetric direction — this is the same rule.
    assert "Tapeout checklist" not in r.stdout, \
        f"--phase 2 must not include the Phase-3-only step 36: {r.stdout}"
    assert "phase 2" in r.stdout.lower() or "phase=2" in r.stdout.lower() \
        or r.returncode in (1, 2), r.stdout


def test_v029_phase_3_excludes_phase_2_steps(tmp_path):
    """Symmetric: --phase 3 must not include Phase-2 step names like
    `Spec-to-RTL` (step 1)."""
    r = _run(str(tmp_path), "--phase", "3")
    assert "Spec-to-RTL" not in r.stdout, \
        f"--phase 3 must not include Phase-2 step 1: {r.stdout}"


def test_v029_phase_invalid_value_rejected():
    """Argparse choice validation: only 2 / 3 / all accepted."""
    r = _run("/tmp", "--phase", "99")
    assert r.returncode == 2  # argparse error


# ====================================================================
# Wave 9 (v0.119.41) — Step -1 aggregator surfaces individual gate
# names + first-line messages when ≥2 structural gates FAIL.
# Motivated by 1st_benchmark_benchmark_a/phase2_v0119.40-vendor/RESULT.md:
# 10 distinct structural FAILs collapsed into one composite FAIL line
# without per-gate detail, making triage hard.
# ====================================================================

def test_wave9_step_minus1_lists_failing_gates_by_name(tmp_path,
                                                        monkeypatch):
    """Project with ≥3 known-failing structural gates must surface
    each gate name in the verdict's `Failed gates (N):` block.

    We import flow_compliance_check, monkey-patch the registry to
    point at three stub gate scripts that always FAIL, and verify
    the aggregator output names each one. Stable against future
    changes to the real gate registry.
    """
    import importlib.util as _ilu
    import sys as _sys

    progs_dir = tmp_path / "stub_programs"
    progs_dir.mkdir(parents=True, exist_ok=True)
    stub_names = (
        "stub_alpha_check", "stub_bravo_check", "stub_charlie_check",
    )
    for n in stub_names:
        (progs_dir / f"{n}.py").write_text(
            f"#!/usr/bin/env python3\n"
            f"import sys; print('first-line msg from {n}'); sys.exit(1)\n"
        )

    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "core.sv").write_text(
        "module core; endmodule\n")

    spec = _ilu.spec_from_file_location(
        "flow_compliance_check_under_test", PROG)
    mod = _ilu.module_from_spec(spec)
    _sys.modules["flow_compliance_check_under_test"] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "PROGRAMS_DIR", progs_dir)
    monkeypatch.setattr(mod, "_STRUCTURAL_RTL_GATES", stub_names)

    # v1.6.97 — _run_structural_rtl_gates returns 4-tuple (added
    # waiver list for the --allow-thin-input scaffold).
    s_passed, s_fails, s_skips, _waivers = mod._run_structural_rtl_gates(tmp_path)
    assert s_passed is False
    assert len(s_fails) == 3, s_fails

    # Reproduce the aggregator's Wave-9 header logic.
    failed_gate_lines = []
    if len(s_fails) >= 2:
        failed_gate_lines.append(f"Failed gates ({len(s_fails)}):")
        for f_line in s_fails:
            failed_gate_lines.append(
                f"  - {f_line[len('FAIL: '):]}"
                if f_line.startswith("FAIL: ")
                else f"  - {f_line}")
    rendered = "\n".join(failed_gate_lines)
    assert "Failed gates (3):" in rendered, rendered
    for n in stub_names:
        assert n in rendered, f"{n} not surfaced in:\n{rendered}"
        assert f"first-line msg from {n}" in rendered, rendered


# ====================================================================
# Wave 11 (v0.119.43) — `--phase 2 --strict-structural` forces Overall:
# FAIL whenever ANY structural-RTL gate FAILs, with each gate listed.
# Closes the v0.119.42 single-pass abandonment pattern: the agent saw
# 4 structural FAILs collapsed into Step -1 and didn't RTL-repair/retry.
# ====================================================================

def _make_phase2_project(tmp_path,
                         stub_names: tuple[str, ...],
                         exit_codes: tuple[int, ...] | None = None) -> Path:
    """Build a fake project with rtl/ + waivers.json, and produce a stub
    program directory whose gates exit with the chosen codes.

    Returns (project_path, programs_dir).
    """
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    (project / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (project / "phase2" / "stage1" / "rtl" / "core.sv").write_text("module core; endmodule\n")
    return project


# The 13 L-doc prefixes `phase1_all_l_docs_present_check` requires, under the
# canonical filenames step D1 declares as its `required_outputs`. Written out
# rather than derived from the flow so that a fixture this test OWNS cannot
# silently change shape when the flow's output list is edited.
_L_DOCS = (
    "L1_DATASHEET", "L2_FRS", "L3_CMD_PROTOCOL", "L4_REGMAP", "L5_ADI_SPEC",
    "L6_CONTROL_LOGIC", "L7_TEST_DEBUG", "L8_TIMING_WAVEFORM",
    "L8_RTL_CONSTANTS", "L9_INTEGRATION_SPEC", "L10_TEST_CASES",
    "L11_OTP_CONTENT", "L12_BEHAVIORAL_SEQUENCES", "L13_BRINGUP",
)


def _satisfy_p0_ancestry(project: Path) -> Path:
    """Give the fixture the Phase-1 chain P0 declares it depends on.

    P0 (the structural-RTL pre-flight) declares `blocks_on: [1]`, and step 1
    declares `blocks_on: [D1]`. That edge is not incidental — vibe-ic#923
    (332b9985) wrote it down deliberately, because without it "a FAILED Phase 1
    would not have redded" the pre-flight, and it is pinned by
    `test_flow_blocks_on_declares_phase1_dependency`.

    So a project carrying ONE .sv file and nothing else is a project whose P0
    verdict rests on a chain that never ran, and the step-execution ordering
    guard is right to void it. Verdict-SCOPE claims about `--strict-structural`
    cannot be made on such a tree: whatever the scoping code does, the run
    fails, and a test asserting otherwise is asserting the pre-#923 flow.

    This adds the minimum that makes D1 and step 1 stop being MISSING, so the
    scope claim is exercised against the thing it is actually about — steps 2-6,
    which stay MISSING because nothing here writes lint / CDC / sim / formal /
    FPGA artefacts.

    THE SENTENCE ABOVE IS A CLAIM, AND vibe-ic#1446 CAUGHT IT BEING FALSE.
    D1 declares 19 `required_outputs` and the gate holds ALL of them ("satisfied:
    18/19 — the gate passed, but every declared output must be produced, not just
    one"), so ONE artefact added to that list downgrades D1 to MISSING and this
    helper stops closing the chain — silently, because a stale fixture does not
    fail, it just stops testing anything. That is what happened: #1159 added
    `L21_POWER_INTENT.json` to D1's `required_outputs` 25 seconds after this
    helper landed, and the resulting ordering violation was then masked by the
    #1429 guard filter that landed 2 minutes after THAT. Hence
    `assert_p0_ancestry_closed` below — the claim is now checked at the point of
    use rather than asserted in prose, so the next output added to D1 reddens a
    test that NAMES the missing artefact instead of quietly hollowing this one.

    AND IT CAUGHT IT A SECOND TIME (vibe-ic#1351). #1348 added
    `phase1/extraction_patterns.json` to D1's `required_outputs`, so the helper
    closed 18 of 19 and `assert_p0_ancestry_closed` went red NAMING the missing
    entry — which is the guard working, not a defect in it. The 19th is staged
    below. Both times the addition was correct and both times the fixture was
    the stale side; that is why the precondition is checked rather than trusted.
    """
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    for name in _L_DOCS:
        (gd / f"{name}.json").write_text(
            json.dumps({"schema": name, "generated_by": "test fixture"}))
    # NOT one of `_L_DOCS`: that tuple is the set `phase1_all_l_docs_present_
    # check` requires, and this is not one of them — it is a D1 `required_
    # outputs` entry (#1159), which is a different contract enforced by a
    # different rule. Kept separate so neither comment has to lie.
    (gd / "L21_POWER_INTENT.json").write_text(
        json.dumps({"schema": "L21_POWER_INTENT", "generated_by": "test fixture",
                    "supply_pins": [], "external_supplies": [], "pads": []}))
    # The 20th declared output, and the FOURTH time this helper has gone stale
    # the same way (#1159 staged the 18th, #1348 the 19th, both recorded above).
    # v1.17.18 (340998c69) added `phase1/generated_docs/L19_CONSTRAINTS_PDK.json`
    # to D1's `required_outputs`, so the helper closed 19 of 20 and
    # `assert_p0_ancestry_closed` reddened NAMING the missing entry. That is the
    # guard doing its job — the whole reason it was written instead of trusting
    # the docstring — so the fixture is the side that moves. Like L21 above this
    # is NOT one of `_L_DOCS`: it is a D1 `required_outputs` entry, a different
    # contract enforced by a different rule, and the two must not be merged.
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"schema": "L19_CONSTRAINTS_PDK",
                    "generated_by": "test fixture", "notes": []}))
    rp = project / "reports" / "phase1"
    rp.mkdir(parents=True, exist_ok=True)
    (rp / "extraction_coverage_report.md").write_text(
        "# extraction coverage\n\n100%\n")
    # A report that carries a MEASUREMENT, not just a number-shaped key.
    # `phase1_coverage_report_present_check` reads `overall.pct` together with
    # the (hit, total) pair that pct was computed from, and returns rc=2
    # "VACUOUS_PASS: report present but coverage NOT measured (hit=None,
    # total=None)" for anything else — a `{"coverage_pct": 100}` body reaches
    # that branch, because the gate refuses to certify a percentage it cannot
    # see a denominator for.
    #
    # That branch is why this helper stopped closing the chain at v1.17.18
    # (340998c69), which added the vacuity classification to
    # `flow_compliance_check` — a gate that examined nothing is now reported as
    # INCOMPLETE ("its input was applicable and was NOT examined") instead of
    # counting as a quiet pass, so D1 goes MISSING and every P0 ancestry claim
    # built on this fixture is voided. The gate and the classification are both
    # right; the fixture was the stale side, exactly as it was for #1159 and
    # #1348 above. Same lesson, third time: staged evidence has to be evidence.
    (rp / "extraction_coverage_report.json").write_text(
        json.dumps({"overall": {"pct": 100.0, "hit": 1, "total": 1},
                    "per_doc": [{"doc": "L1_DATASHEET", "hit": 1,
                                 "total": 1, "pct": 100.0}],
                    "generated_by": "test fixture"}))
    # The 18th declared output. `phase1_expert_parse_track` writes this itself
    # when it runs for real. Issue #1973 requires a non-empty expert answer
    # before that execution is credited, so this closed-chain fixture stages
    # both the answer consumed by the live gate and the matching report shape.
    # `phase1_expert_track_evidence_check` anticipates exactly that ("the flat
    # path is accepted too so a hand-staged project is not mistaken for a track
    # that never ran"). The one expectation agrees with the synthetic L1 layer,
    # so `findings: []` is a real RAN_EMPTY rather than an unanswered handoff.
    ra = project / "reports" / "audit" / "phase1"
    ra.mkdir(parents=True, exist_ok=True)
    pack = ra / "expert_parse_track_pack"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "l_doc_expectations.json").write_text(json.dumps({
        "expectations": [{
            "id": "fixture::l1_schema",
            "layer": "L1_DATASHEET",
            "field_path": "schema",
            "requirement": "the staged L1 schema identity",
            "evidence": ["synthetic fixture stages L1_DATASHEET"],
            "expected_tokens": ["L1_DATASHEET"],
        }],
    }))
    (ra / "expert_parse_track.json").write_text(json.dumps({
        "program": "phase1_expert_parse_track.py",
        "verdict": "PASS",
        "findings": [],
        "ai_subtrack": {"status": "CONSUMED"},
        "ai_convergence": {"consumed": 1},
        "denominator": {"deterministic": 0, "ai": 1, "total": 1},
        "generated_by": "test fixture",
    }))
    # The 19th declared output (#1348). Same reason as the 18th above: the
    # canonical catalogue is seeded by `phase1_doc_one_shot_runner.py`
    # (`_seed_canonical_from_backfilled_subset`), which RETURNS WITHOUT WRITING
    # when no auto-discovered literal was backfilled into a typed L doc — and on
    # a tree with no `input/docs` nothing can be. So a hand-staged Phase 1 has to
    # stage it like the other 18.
    #
    # An object carrying only the provenance key is the seeder's own empty
    # shape: `canonical_payload` starts as `{"_comment": ...}` and is then
    # `update()`d with the promoted patterns, so zero promoted patterns is
    # exactly this file. `extraction_coverage_check._load_explicit_patterns`
    # requires a top-level object (anything else is WARN + ignored) and skips
    # non-list values, so this parses as a catalogue with no entries rather than
    # as MALFORMED — the same distinction the expert-track entry above turns on.
    (project / "phase1" / "extraction_patterns.json").write_text(json.dumps({
        "_comment": ("Canonical extraction patterns. No auto-discovered "
                     "literal was backfilled into a typed L doc on this tree, "
                     "so the catalogue is empty; staged by test fixture."),
    }))
    return project


#: The step listing abbreviates exactly two of the producer's own status words;
#: every other label is the word itself. Kept as a rendering map, NOT as a
#: judgement about done-ness — the judgement below stays derived from
#: `_flow_verdict_tiers`, the one place a verdict word is classified (#634). A
#: label that is neither an alias here nor a `PRODUCER_STATUSES` member makes
#: the precondition REFUSE rather than guess, so a renamed rendering reddens
#: this file instead of quietly widening what counts as "closed".
_LABEL_TO_PRODUCER_STATUS = {
    "WAIVED-DEFERRED": "WAIVED",
    "PASS-VOIDED": "PASS-VOIDED-BY-DEPENDENCY",
}


def assert_p0_ancestry_closed(out: str) -> None:
    """Fail if `_satisfy_p0_ancestry`'s tree did not actually close the chain.

    A PRECONDITION, not an assertion about the code under test. Every caller of
    `_satisfy_p0_ancestry` is making a claim about what happens once P0's
    ancestry is SATISFIED; on a tree where D1 has not completed that claim is
    being made about the opposite input, and the test passes or fails for
    reasons unrelated to what it is named after.

    Checks the step listing rather than the ordering-violation block on purpose:
    the violation block is what the guard consumes, so reading it here would
    make the precondition and the assertion share a failure mode.

    WHAT IT MEASURES vs WHAT IT CLAIMED (vibe-ic#1351). Until now the test was
    `!= "MISSING"`, i.e. it measured one spelling of one way to break the chain
    while claiming the chain was CLOSED. Measured on this fixture's own tree,
    removing one artefact each and running the real gate:

        remove phase1/extraction_patterns.json    D1=MISSING  P0=PASS-VOIDED  REJECTED
        remove reports/phase1/…_report.json       D1=FAIL     P0=PASS-VOIDED  ACCEPTED  <-
        remove generated_docs/L4_REGMAP.json      D1=FAIL     P0=PASS-VOIDED  ACCEPTED  <-
        remove reports/audit/phase1/expert_…json  D1=MISSING  P0=PASS-VOIDED  REJECTED

    A D1 that FAILS breaks P0's ancestry exactly as a D1 that is MISSING does —
    same voided P0, same two ordering violations — and the precondition waved it
    through. Under `--strict-structural` the run still exits 0 (the violation
    names D1, which #1429 scopes out), so nothing else in the caller could have
    noticed: the precondition is the only thing standing between that test and
    vacuity.

    So the question asked here is now the ordering guard's own: for an ORDINARY
    PROCESS step, which D1 is, `analyze()` raises no violation unless the
    ancestor's word is non-green — EXCUSED ancestors and qualified done-claims
    (VACUOUS-PASS, STRUCTURE-ONLY, INCOMPLETE) both close the chain under one,
    and only a sign-off / terminal hand-off / stage-5 attestation ancestor is
    held to full PASS (`_blocks_when_vacuous`). D1 is none of those and cannot
    become one without a flow change far larger than this file. The predicate is
    imported from `_flow_verdict_tiers`, which exists precisely so this
    classification is not re-enumerated per consumer and so a tier invented
    tomorrow is adjudicated without anyone remembering to come here.
    """
    # Function-local: `programs/` is on `sys.path` via conftest, and a helper
    # this file's other 30-odd tests do not use should not be able to error the
    # whole module at collection time if that ever stops being true.
    import _flow_verdict_tiers as _T

    m = re.search(r"^\s*\S*\s*\[([\w-]+)\s*\] Step\s+D1:", out, re.M)
    assert m, f"precondition: step D1 must appear in the report:\n{out}"
    label = m.group(1)
    status = _LABEL_TO_PRODUCER_STATUS.get(label, label)
    assert _T.normalize(status) in _T.PRODUCER_STATUSES, (
        f"precondition NOT DETERMINED: the step listing rendered D1 as "
        f"{label!r}, which is neither one of `_flow_verdict_tiers."
        f"PRODUCER_STATUSES` nor a rendering this file knows how to translate. "
        f"A precondition that cannot classify the word cannot say the chain is "
        f"closed, so it refuses instead of guessing. Add the rendering to "
        f"`_LABEL_TO_PRODUCER_STATUS` (or the word to PRODUCER_STATUSES, where "
        f"its done-ness is decided):\n" + out)
    assert not _T.is_non_green(status), (
        f"precondition: `_satisfy_p0_ancestry` no longer closes P0's ancestry "
        f"— D1 is {label} on the tree it builds, so any claim this test makes "
        f"about a SATISFIED ancestry is being made about the wrong input. "
        f"Either D1 gained a `required_outputs` entry the fixture does not "
        f"write (the report names it on D1's `required_outputs missing:` "
        f"line), or one of D1's gate clauses now FAILs on what the fixture "
        f"stages:\n" + out)


def _patch_run(monkeypatch, mod, stub_results: dict[str, tuple[int, str]],
               *, passing: int = 0):
    """Monkey-patch _run_structural_rtl_gates to report the chosen per-gate
    exit codes directly, bypassing subprocess invocation.

    #497 step 2 — the stub now publishes the STRUCTURED per-gate records as
    well as the prose buckets, because that is what the umbrella publishes and
    what the strict-structural consumer reads. Before the cut-over a stub could
    state a gate's outcome ONLY in prose and every consumer believed it; that
    is the same coupling this issue removes from production, and a stub that
    kept it would be testing a contract the shipped code no longer has.

    `passing` (vibe-ic#1446) — SYNTHETIC GATES THAT ACTUALLY PASSED, for the
    callers whose premise is "every structural gate PASSED". `_patch_run(mod,
    {})` publishes NO record, and no record is not a pass: the umbrella's
    empty-denominator guard (#599/#901/#947) reports INCOMPLETE, which says
    nobody looked. The two are opposite claims and the tests here need BOTH —
    `test_strict_structural_does_not_excuse_a_broken_p0_ancestry` is about a P0
    that answered nothing, `test_strict_structural_only_structural_gates` is
    about a P0 that answered PASS — so the distinction is a parameter rather
    than a default. Deliberately mirrors `_stub_structural_gates(passing=…)` in
    `test_issue1429_ordering_guard_is_scoped_not_disabled.py`, whose docstring
    made this same point first; the DEFAULT stays 0 so no existing caller
    silently changes the claim it is making.
    """
    fails = []
    skips = []
    records = [mod._p0_gate_record(f"synthetic_pass_gate_{i}", "PASS", "",
                                   {"exit_code": 0})
               for i in range(passing)]
    for name, (code, msg) in stub_results.items():
        if code == 1:
            fails.append(f"FAIL: {name} — {msg}")
            records.append(mod._p0_gate_record(name, "FAIL", msg,
                                               {"exit_code": 1}))
        elif code == 2:
            skips.append(name)
            records.append(mod._p0_gate_record(
                name, "SKIP", "", {"exit_code": 2,
                                   "skip_kind": "input-missing"}))
        else:
            records.append(mod._p0_gate_record(name, "PASS", "",
                                               {"exit_code": 0}))

    def _stub(_project, **_kwargs):
        # v1.6.32: signature accepts strict_timing kwarg from umbrella
        # v1.6.97: now also accepts allow_thin_input kwarg + returns
        # 4-tuple (waivers list appended).
        # #497: records_out is the umbrella's structured channel.
        out = _kwargs.get("records_out")
        if out is not None:
            out.extend(records)
        return (len(fails) == 0, fails, skips, [])
    monkeypatch.setattr(mod, "_run_structural_rtl_gates", _stub)


def _patch_unrelated_advisory_outcomes_as_pass(monkeypatch, mod):
    """Keep the P0-scope fixtures about P0, not D1 advisory findings.

    Issue #1980 correctly makes a live advisory-slot refusal block its step.
    The fixtures that call this helper deliberately exercise structural-only
    verdict scoping and D1 ancestry bookkeeping, not the dozens of independent
    D1 program findings.  Preserve each real execution, but replace its typed
    advisory disposition with a synthetic clean result so a newly actionable
    D1 checker cannot silently hollow out those unrelated tests.

    Blocking (non-advisory) D1 predicates are untouched.  That is load-bearing
    for the two ancestry-break arms below: removing a declared output can still
    make D1 MISSING, while removing an L document can still make D1 FAIL.
    """
    original = getattr(mod, "_advisory_execution_record", None)
    if original is None:
        # Pre-#1980 baseline: the advisory slot itself is nonblocking, so no
        # isolation shim is needed.  Keeping this arm executable prevents the
        # differential control from reddening on a helper-only AttributeError.
        return

    def _clean_record(*args, **kwargs):
        record = original(*args, **kwargs)
        return {
            **record,
            "exit_code": 0,
            "verdict": "PASS",
            "structured_verdict": None,
            "reason_class": None,
            "enforcement": "PASSED",
        }

    monkeypatch.setattr(mod, "_advisory_execution_record", _clean_record)


def _import_fcc(monkeypatch=None):
    import importlib.util as _ilu
    import sys as _sys
    spec = _ilu.spec_from_file_location("fcc_under_test_w11", PROG)
    mod = _ilu.module_from_spec(spec)
    _sys.modules["fcc_under_test_w11"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_phase2_strict_structural_fail_aggregates(tmp_path,
                                                   monkeypatch, capsys):
    """Two known-failing structural gates → Overall: FAIL with both names
    surfaced under the `Phase 2 strict-structural mode` header."""
    project = _make_phase2_project(tmp_path, ("alpha_check", "bravo_check"))

    mod = _import_fcc()
    _patch_run(monkeypatch, mod, {
        "alpha_check": (1, "alpha root cause line"),
        "bravo_check": (1, "bravo root cause line"),
    })
    rc = mod.main([str(project), "--phase", "2", "--strict-structural"])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "Overall: FAIL" in out, out
    assert "Phase 2 strict-structural mode" in out, out
    assert "structural gates FAILed" in out, out
    assert "alpha_check" in out, out
    assert "bravo_check" in out, out
    assert "alpha root cause line" in out, out
    assert "bravo root cause line" in out, out


def test_phase2_strict_with_waivers(tmp_path, monkeypatch, capsys):
    """Per-gate waivers (already implemented at the individual gate
    level) absorb the FAIL → the structural runner sees exit 0 from
    those gates → Wave-11 strict-structural emits NO failed-gate block.
    We simulate this by returning an empty fails list."""
    project = _make_phase2_project(tmp_path, ("alpha_check",))

    mod = _import_fcc()
    # Each gate honors its own waiver internally; when waivers absorb
    # the failure, the gate exits 0 and the runner sees no FAIL.
    _patch_run(monkeypatch, mod, {})  # no FAILs after per-gate waivers
    rc = mod.main([str(project), "--phase", "2", "--strict-structural"])
    out = capsys.readouterr().out
    assert "Phase 2 strict-structural mode" not in out, (
        "When per-gate waivers absorb structural FAILs, no Wave-11 "
        "override block should be emitted: " + out)


def test_phase2_no_structural_failures(tmp_path, monkeypatch, capsys):
    """Clean structural runner → no Phase-2 strict-structural block,
    verdict is NOT forced to FAIL by Wave-11 logic. (Other MISSING
    steps may still cause FAIL — we assert only that the strict-
    structural override does not contribute.)"""
    project = _make_phase2_project(tmp_path, ())

    mod = _import_fcc()
    _patch_run(monkeypatch, mod, {})  # no fails
    rc = mod.main([str(project), "--phase", "2", "--strict-structural"])
    out = capsys.readouterr().out
    assert "Phase 2 strict-structural mode" not in out, out
    # rc may still be 1 because the empty project has no docs/RTL
    # for actual phase-2 steps — but it must not be due to the Wave-11
    # override.


def test_existing_strict_unchanged_no_phase(tmp_path, monkeypatch, capsys):
    """Regression: --strict (no --phase) and no --strict-structural → no
    Wave-11 block emitted, verdict path identical to pre-Wave-11."""
    project = _make_phase2_project(tmp_path, ())
    mod = _import_fcc()
    _patch_run(monkeypatch, mod, {
        "alpha_check": (1, "would have triggered Wave-11 if --phase 2"),
    })
    rc = mod.main([str(project), "--strict"])
    out = capsys.readouterr().out
    assert "Phase 2 strict-structural mode" not in out, out


def test_strict_structural_flag_in_help():
    """--strict-structural exposed in --help."""
    r = _run("--help")
    assert "--strict-structural" in r.stdout
    assert "structural" in r.stdout.lower()


# ====================================================================
# Wave 21 (v0.119.53) — `--strict-structural` semantic fix.
# `--strict-structural` MUST scope verdict to structural-RTL gates only.
# `--strict-step-artifacts` is the broader flag for real EDA artefacts.
# ====================================================================


def test_strict_step_artifacts_flag_in_help():
    """Wave 21: --strict-step-artifacts exposed in --help."""
    r = _run("--help")
    assert "--strict-step-artifacts" in r.stdout
    assert "real EDA tool" in r.stdout or "step-artifacts" in r.stdout.lower()


def test_strict_structural_only_structural_gates(tmp_path,
                                                  monkeypatch, capsys):
    """Wave 21: a project whose structural-RTL gates ALL PASS but
    step-level gates are MISSING/FAIL → with --phase 2 --strict-
    structural, Overall must NOT be FAIL because step-level gates are
    informational only. Step-level FAIL/MISSING is reported in the
    step listing, but verdict scope is structural-RTL only.

    THE FIXTURE NOW SATISFIES P0's DECLARED ANCESTRY, and that is the repair.
    This test used to run on a tree holding one `.sv` file, which was enough
    only while P0 declared no dependencies. vibe-ic#923 gave P0
    `blocks_on: [1]` on purpose, step 1 already declared `blocks_on: [D1]`, and
    the ordering guard then — correctly — voided P0's own claim because the
    chain under it had never run. The run failed for a reason that has nothing
    to do with verdict SCOPE, so the scope claim was no longer being tested at
    all. `_satisfy_p0_ancestry` closes the chain; steps 2-6 stay MISSING, which
    is the population this test is about, and the negative arm below pins the
    #923 behaviour so nobody "repairs" this by scoping the ordering guard out.
    """
    project = _satisfy_p0_ancestry(_make_phase2_project(tmp_path, ()))

    mod = _import_fcc()
    # No structural FAILs — and, per vibe-ic#1446, that is NOT the same as no
    # structural gates. This test's first sentence says "a project whose
    # structural-RTL gates ALL PASS"; publishing zero records made P0
    # INCOMPLETE (0 of 246 checkers returned a verdict), which is the OPPOSITE
    # claim and the input the negative arm below owns. `passing=2` makes the
    # premise true, so the scope question this test asks is asked of a P0 that
    # actually answered.
    _patch_run(monkeypatch, mod, {}, passing=2)
    _patch_unrelated_advisory_outcomes_as_pass(monkeypatch, mod)
    rc = mod.main([str(project), "--phase", "2", "--strict-structural"])
    out = capsys.readouterr().out
    # PRECONDITION #1 (vibe-ic#1446): the fixture's own promise. Without it this
    # test ran on a tree whose D1 was MISSING — i.e. on the BARE-ancestry input
    # the test two functions down owns — and was green only because the guard
    # filter it was paired with looked at the dependency instead of the step
    # that claimed done.
    assert_p0_ancestry_closed(out)
    # PRECONDITION #2, not decoration: if steps 2-6 were not MISSING this test
    # would be asserting that a clean run is clean.
    for sid in (2, 3, 4, 5, 6):
        assert re.search(rf"^\s*\S*\s*\[MISSING\s*\] Step\s+{sid}:",
                         out, re.M), (
            f"precondition: step {sid} must be MISSING for the scope claim "
            f"to mean anything:\n{out}")
    assert "Phase 2 strict-structural mode" not in out, out
    # Overall verdict could be PASS or PASS_WITH_WAIVERS (but never
    # FAIL purely due to step-level MISSING when structural gates
    # all PASS).
    assert "Overall: FAIL" not in out, (
        "structural-only mode should NOT FAIL on step-level "
        "MISSING/FAIL alone:\n" + out)
    assert rc == 0, out


# ── vibe-ic#1351 — the precondition's own falsifiability ─────────────────
#
# `assert_p0_ancestry_closed` is the ONLY thing keeping the test above from
# testing nothing: under `--strict-structural` a broken P0 ancestry still exits
# 0 (the violation names D1, which #1429 scopes out of the verdict), so a
# hollowed fixture is green and silent. A guard in that position has to be shown
# capable of failing, or "it passed" and "it could not tell" are the same
# reading — which is the defect the guard exists to prevent, one level up.
#
# Each arm below breaks the chain a DIFFERENT way and the arm asserts which,
# because that is the part that decayed: the pre-#1351 form of the precondition
# tested `!= "MISSING"` and therefore accepted the FAIL arm outright.

_ANCESTRY_BREAKS = (
    # (artefact removed from the closed tree, the word D1 then reports)
    # ABSENT — a `required_outputs` entry the fixture stops writing. This is the
    # break #1159 and #1348 both produced.
    ("phase1/extraction_patterns.json", "MISSING"),
    # FAILED — an artefact D1's own gate clause reads and rejects the absence
    # of. Same voided P0, same two ordering violations, DIFFERENT word; accepted
    # by the pre-#1351 precondition.
    ("phase1/generated_docs/L4_REGMAP.json", "FAIL"),
)


def _p0_ancestry_report(tmp_path, monkeypatch, capsys, *, remove=None) -> str:
    """The real gate's printed report for `_satisfy_p0_ancestry`'s tree, with at
    most one declared artefact removed first."""
    project = _satisfy_p0_ancestry(_make_phase2_project(tmp_path, ()))
    if remove is not None:
        victim = project / remove
        assert victim.is_file(), (
            f"precondition: `_satisfy_p0_ancestry` must stage {remove!r} for "
            f"removing it to break anything — if it no longer does, this arm "
            f"is testing an empty operation")
        victim.unlink()
    mod = _import_fcc()
    _patch_run(monkeypatch, mod, {}, passing=2)
    _patch_unrelated_advisory_outcomes_as_pass(monkeypatch, mod)
    mod.main([str(project), "--phase", "2", "--strict-structural"])
    return capsys.readouterr().out


def test_the_p0_ancestry_precondition_passes_on_the_intact_tree(
        tmp_path, monkeypatch, capsys):
    """Direction 1 of 2: the guard must accept the input it is written for, or
    the arms below prove only that it rejects everything."""
    out = _p0_ancestry_report(tmp_path, monkeypatch, capsys)
    assert_p0_ancestry_closed(out)


@pytest.mark.parametrize("removed,expected_word", _ANCESTRY_BREAKS)
def test_the_p0_ancestry_precondition_catches_a_chain_broken_either_way(
        tmp_path, monkeypatch, capsys, removed, expected_word):
    """Direction 2 of 2, once per way the chain breaks."""
    out = _p0_ancestry_report(tmp_path, monkeypatch, capsys, remove=removed)

    # This arm's premise: removing THIS artefact produces THIS word. Asserted so
    # that an arm which stops exercising its break mode says so, instead of
    # passing on a duplicate of the other arm's.
    m = re.search(r"^\s*\S*\s*\[([\w-]+)\s*\] Step\s+D1:", out, re.M)
    assert m and m.group(1) == expected_word, (
        f"precondition: removing {removed!r} was chosen because it makes D1 "
        f"{expected_word}; it now reports "
        f"{(m.group(1) if m else 'NO D1 LINE')!r}, so this arm no longer covers "
        f"that break mode:\n{out}")

    with pytest.raises(AssertionError) as exc:
        assert_p0_ancestry_closed(out)
    assert "no longer closes P0's ancestry" in str(exc.value), str(exc.value)
    assert expected_word in str(exc.value), str(exc.value)


def test_the_p0_ancestry_precondition_refuses_a_word_it_cannot_classify():
    """A precondition that cannot classify the verdict word has NOT looked, so
    it must refuse rather than fall through to "not MISSING, therefore closed".
    Planted word, no gate run — the point is the classification, and
    `_flow_verdict_tiers` is where a real new word gets its home."""
    planted = "  ? [MOSTLY-FINE      ] Step D1: Phase 1 Doc Extraction  (stage_phase1)\n"
    with pytest.raises(AssertionError) as exc:
        assert_p0_ancestry_closed(planted)
    assert "NOT DETERMINED" in str(exc.value), str(exc.value)
    assert "MOSTLY-FINE" in str(exc.value), str(exc.value)


def test_strict_structural_does_not_excuse_a_broken_p0_ancestry(
        tmp_path, monkeypatch, capsys):
    """The other half of the scope, and the reason the fixture above grew.

    `--strict-structural` narrows the verdict to P0 — it does not make P0's own
    claim unfalsifiable. On the tree the test above used to run on (RTL only, no
    Phase 1), P0 depends on a chain that never ran, so the step-execution
    ordering guard voids it and the run FAILs. vibe-ic#923 wrote that edge down
    for exactly this outcome.

    Pinned here so the paired repair is visible: the run above is green because
    its chain is closed, NOT because step-level state stopped counting.
    """
    project = _make_phase2_project(tmp_path, ())   # deliberately bare

    mod = _import_fcc()
    _patch_run(monkeypatch, mod, {})
    rc = mod.main([str(project), "--phase", "2", "--strict-structural"])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "Overall: FAIL" in out, out
    assert "Step-execution ordering violations" in out, out
    assert re.search(r"\[P0\].*marked done while dependency", out), out


def test_strict_step_artifacts_includes_step_gates(tmp_path,
                                                    monkeypatch, capsys):
    """Wave 21: same project but --strict-step-artifacts → Overall
    FAIL when step-level gates MISSING/FAIL."""
    project = _make_phase2_project(tmp_path, ())

    mod = _import_fcc()
    # No structural FAILs.
    _patch_run(monkeypatch, mod, {})
    rc = mod.main([str(project), "--phase", "2",
                   "--strict-step-artifacts"])
    out = capsys.readouterr().out
    # With strict-step-artifacts, step-level MISSING/FAIL forces FAIL.
    # Empty project always has missing L*.json etc.
    if "MISSING" in out or "FAIL" in out:
        # Verdict scope includes step-level → expect FAIL.
        assert ("Overall: FAIL" in out
                or "strict-step-artifacts mode" in out
                or rc == 1), out


def test_strict_structural_with_failing_structural_gate(tmp_path,
                                                         monkeypatch,
                                                         capsys):
    """Wave 21 regression: a structural-gate FAIL still propagates to
    Overall: FAIL even in scoped --strict-structural mode."""
    project = _make_phase2_project(tmp_path, ("alpha_check",))
    mod = _import_fcc()
    _patch_run(monkeypatch, mod, {
        "alpha_check": (1, "alpha root cause line"),
    })
    rc = mod.main([str(project), "--phase", "2", "--strict-structural"])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "Overall: FAIL" in out, out
    assert "Phase 2 strict-structural mode" in out, out
    assert "alpha_check" in out, out


def test_strict_structural_step_level_info_block(tmp_path,
                                                  monkeypatch, capsys):
    """Wave 21: when structural gates pass but step-level gates
    FAIL/MISSING, the output should contain an informational block
    naming step-level gates without forcing FAIL."""
    project = _make_phase2_project(tmp_path, ())
    mod = _import_fcc()
    _patch_run(monkeypatch, mod, {})  # no structural FAILs
    rc = mod.main([str(project), "--phase", "2", "--strict-structural"])
    out = capsys.readouterr().out
    # If step-level gates have MISSING entries (which the empty-project
    # fixture should produce), an info block should appear. We accept
    # either presence of the info block OR no step-level fails (if the
    # fixture happens to have no step entries) — we only need to be
    # sure rc is 0 (verdict not gated on step-level).
    assert rc == 0 or rc == 1, out  # rc may legitimately be either
    # The key invariant: the "Phase 2 strict-structural mode" line
    # only appears when ≥1 structural gate FAILs.
    assert "Phase 2 strict-structural mode" not in out


# ──────────────────────────────────────────────────────────────────────
# Wave 93 / v1.6.17 — VACUOUS_PASS verdict tier formalisation
# ──────────────────────────────────────────────────────────────────────
def test_issue1980_step14_nested_nonverdict_is_classed_not_skipped(tmp_path):
    """The nested missing report is classed, never flattened to a skip.

    The fixture has a synth netlist but no ``.ys`` recipe, so the two Yosys
    classifiers report NOT_CHECKED, and it has no analog track, so the
    nested stage-analog on-pass review finds nothing to review. #1978
    classifies those non-verdicts as EXECUTION_ERROR; #1980 preserves their
    real rc and disposition, while the landed dependency policy keeps the
    step MISSING behind Step 9 rather than calling it a skip.
    """
    proj = tmp_path / "vac"
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl" / "top.v").write_text(
        "module top(input clk, output reg q);"
        "always @(posedge clk) q <= ~q; endmodule\n"
    )
    (proj / "phase2" / "stage2" / "synth" / "netlist.v").write_text("module top(); endmodule\n")
    r = _run(str(proj), "--strict")
    assert re.search(r"\[MISSING\s*\] Step\s+14:.*blocked-by-upstream\(9\)",
                     r.stdout), r.stdout
    # This line used to read `flow_compliance_check rc=1 verdict=CRASHED`, and
    # the crash it pinned was a DEFECT rather than a property of the fixture:
    # the nested stage-analog compliance gate died with FileNotFoundError
    # writing `reports/analog/stage_analog_compliance.json`, because nothing
    # creates `reports/analog/` on a project with no analog track. MEASURED on
    # sha256 x sky130A (v1.15.58): that same crash turned a clean stage verdict
    # into a phase-2 FAIL and halted a whole acceptance run. With the report
    # writer creating its own parent, the nested gate RUNS and is RECORDED.
    assert "GATE EVIDENCE: flow_compliance_check rc=0 verdict=PASS" in r.stdout
    # The SUBJECT of this test is unchanged and is now pinned per gate rather
    # than by a bare substring anywhere in stdout: an applicable input that was
    # NOT examined is CLASSED with its real rc, its reason class and its
    # enforcement tier — never flattened to a skip or a vacuous pass.
    assert ("GATE EVIDENCE: stage_on_pass_review rc=2 verdict=INCOMPLETE "
            "reason_class=EXECUTION_ERROR enforcement=DISCLOSED_INCOMPLETE"
            ) in r.stdout, r.stdout
    assert ("GATE EVIDENCE: yosys_tiecell_recipe_order_check rc=2 "
            "verdict=NOT_CHECKED reason_class=EXECUTION_ERROR "
            "enforcement=DISCLOSED_INCOMPLETE") in r.stdout, r.stdout
    assert not re.search(r"\[VACUOUS-PASS\s*\] Step\s+14:", r.stdout)


#: The steps that ARE vacuous on the `vac2` fixture below, re-measured for
#: issue #1980 on 2026-09-01:
#:   * FS1 — the fixture's RTL declares no ECC/parity/lockstep mechanism, so
#:     the FMEDA pair measures no diagnostic coverage.
#:
#: Step 14 deliberately stays outside this set. #1978 classifies its unsafe
#: non-verdicts as INCOMPLETE, and the delivery/dependency policy leaves the
#: canonical full-run row MISSING behind Step 9. Neither is a skip-eligible
#: non-verdict.
#: Pinned as a SET so that a step JOINING or LEAVING the vacuous tier is a
#: named, deliberate edit here rather than an invisible drift.
_VAC2_EXPECTED_VACUOUS_STEPS = {"FS1"}


def _labelled_step_ids(stdout: str, label: str) -> set:
    """Step ids carrying `label` in the per-step listing.

    Lines look like `  ○ [VACUOUS-PASS     ] Step 14: … (stage2)`.
    """
    out = set()
    for ln in stdout.splitlines():
        if f"[{label}" not in ln:
            continue
        m = re.search(r"\]\s*Step\s+(\S+?):", ln)
        if m:
            out.add(m.group(1))
    return out


def test_wave93_vacuous_pass_counter_accurate(tmp_path):
    """The summary counter must equal the number of steps LABELLED
    `[VACUOUS-PASS]` in the per-step listing — AND those steps must be the
    ones this fixture is built to make vacuous.

    Two properties, deliberately both:

    * ACCURACY. The counter and the listing must agree in either direction,
      for any number of vacuous steps. This replaces a literal
      `VACUOUS-PASS=1`, which was a fixture census wearing the name of an
      accuracy check and went stale the moment a second gate started
      disclosing its skip honestly.
    * CENSUS. Accuracy alone is a consistency check between two values
      computed from `r.status` in the same loop: it no longer pins WHICH or
      HOW MANY steps land on the vacuous tier, which is precisely the class of
      drift the original assertion existed to catch. So the SET is pinned too,
      by step id, with the reason each member is vacuous written down above.
    """
    proj = tmp_path / "vac2"
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl" / "top.v").write_text(
        "module top(input clk); endmodule\n"
    )
    (proj / "phase2" / "stage2" / "synth" / "netlist.v").write_text("module top(); endmodule\n")
    r = _run(str(proj), "--strict")
    # Find the summary line
    counter_lines = [ln for ln in r.stdout.splitlines()
                     if "VACUOUS-PASS=" in ln and "PASS=" in ln]
    assert counter_lines, r.stdout
    labelled = [ln for ln in r.stdout.splitlines() if "[VACUOUS-PASS" in ln]
    assert labelled, (
        "no step is LABELLED [VACUOUS-PASS] on a fixture that must produce at "
        f"least Step 14's no-.ys vacuous pass:\n{r.stdout}")
    m = re.search(r"VACUOUS-PASS=(\d+)", counter_lines[0])
    assert m, counter_lines[0]
    assert int(m.group(1)) == len(labelled), (
        f"summary says VACUOUS-PASS={m.group(1)} but the per-step listing "
        f"labels {len(labelled)} step(s) [VACUOUS-PASS]: "
        f"{[ln.strip()[:80] for ln in labelled]}\n{counter_lines[0]}")
    seen = _labelled_step_ids(r.stdout, "VACUOUS-PASS")
    assert seen == _VAC2_EXPECTED_VACUOUS_STEPS, (
        f"the set of steps on the VACUOUS-PASS tier changed: expected "
        f"{sorted(_VAC2_EXPECTED_VACUOUS_STEPS)}, got {sorted(seen)}. A step "
        f"joining the vacuous tier means a gate stopped measuring; a step "
        f"leaving it means a gate started, or stopped disclosing. Either is a "
        f"deliberate edit — update _VAC2_EXPECTED_VACUOUS_STEPS and say why."
        f"\n{r.stdout}")


# ─── _expand_globs basics (kept after v1.6.21 legacy-fallback removal) ──

def test_expand_globs_non_path_literal_passes_through(tmp_path):
    """Args that don't look like paths (`magic,openroad`, `60`,
    `--severity ERROR`) pass through unchanged."""
    from programs.flow_compliance_check import _expand_globs
    out = _expand_globs(
        ["magic,openroad", "60", "--severity", "ERROR"],
        tmp_path,
    )
    assert out == ["magic,openroad", "60", "--severity", "ERROR"], out


def test_expand_globs_glob_with_match(tmp_path):
    """Glob pattern with at least one match expands to the relative
    paths (canonical Phase/Stage/Step layout — runners always emit
    here as of v1.6.21)."""
    from programs.flow_compliance_check import _expand_globs
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "foo.sv").write_text("module foo(); endmodule\n")
    out = _expand_globs(["phase2/stage1/rtl/*.sv"], tmp_path)
    assert out == ["phase2/stage1/rtl/foo.sv"], out


def test_expand_globs_glob_zero_matches_dropped(tmp_path):
    """nullglob: pattern with zero matches is dropped from output."""
    from programs.flow_compliance_check import _expand_globs
    out = _expand_globs(
        ["phase2/stage1/rtl/*.sv", "--json", "reports/x.json"], tmp_path,
    )
    # The glob is dropped; the literal `--json` flag and value pass through.
    assert out == ["--json", "reports/x.json"], out


# ─── _check_program_exit_zero rc=2 → VACUOUS_PASS ────────────────
# v10619 Step M1 (mixed_signal_merge_check) and Step 35
# (foundry_handoff_package_check) print `verdict: SKIP` and exit 2
# when their inputs aren't there yet. This is the same convention
# `_run_structural_rtl_gates` already honours; before this fix,
# `_check_program_exit_zero` treated rc=2 as FAIL, causing
# pre-tapeout / digital-only projects to FAIL the canonical-flow
# audit on those steps despite having legitimate skip-conditions.

def test_unclassified_rc2_is_incomplete(tmp_path):
    """An rc-2 token without a typed absence basis is not a free N/A."""
    from programs.flow_compliance_check import (
        _check_program_exit_zero,
        _VACUOUS_HINT_PREFIX,
        PROGRAMS_DIR,
    )
    # Plant a one-off helper program that exits 2.
    helper = PROGRAMS_DIR / "_pytest_rc2_helper.py"
    helper.write_text(
        "import sys; print('verdict: SKIP'); sys.exit(2)\n"
    )
    try:
        passed, snippet = _check_program_exit_zero(tmp_path, "_pytest_rc2_helper")
        assert passed is True, "INCOMPLETE is not a manufactured design FAIL"
        assert snippet.startswith("INCOMPLETE:"), snippet
        assert not snippet.startswith(_VACUOUS_HINT_PREFIX)
    finally:
        helper.unlink(missing_ok=True)


def test_check_program_exit_zero_rc1_still_fails(tmp_path):
    """rc=1 must still register as FAIL — the rc=2 carve-out doesn't
    affect rc=1 semantics."""
    from programs.flow_compliance_check import (
        _check_program_exit_zero, PROGRAMS_DIR,
    )
    helper = PROGRAMS_DIR / "_pytest_rc1_helper.py"
    helper.write_text("import sys; print('FAIL: bad'); sys.exit(1)\n")
    try:
        passed, snippet = _check_program_exit_zero(tmp_path, "_pytest_rc1_helper")
        assert passed is False
        assert "FAIL: bad" in snippet
    finally:
        helper.unlink(missing_ok=True)


# ─── CRASH vs VERDICT: the distinction must not depend on the path ────
# `_check_program_exit_zero` returns `passed=False` for BOTH "the gate found
# a defect" and "the gate blew up", so every consumer that needs to tell them
# apart used to re-derive the answer from the evidence snippet — a fixed-width
# tail of each stream. A traceback's frame lines carry the program's absolute
# path and its exception message routinely carries the project's, so how much
# of the traceback survived that cut was a function of how deep the checkout
# lived. MEASURED on this tree, one crashing gate, path length the only
# variable: 107 characters graded CRASH, 108 graded FAIL — and the dimension-2
# falsifiability matrix counts FAIL as proof that a gate can fail, so past 108
# characters a crash was issuing that certificate.
#
# The consumer now decides it against the UNTRUNCATED streams and says so with
# `_CRASH_HINT_PREFIX`, which is the first thing in the string and therefore
# survives every downstream cut. These tests pin both directions and, above
# all, the invariant: same gate, same project contents, two path lengths that
# straddle the evidence window — one answer.

_CRASH_HELPER_SRC = (
    "import sys\n"
    "from pathlib import Path\n"
    "def _f4(p): return {'only': 1}[str(p)]\n"
    "def _f3(p): return _f4(p)\n"
    "def _f2(p): return _f3(p)\n"
    "def _f1(p): return _f2(p)\n"
    "print('helper: audited 0 files')\n"
    # The KeyError message is the project's ABSOLUTE path — the shape most
    # gates in this tree produce, because they open with
    # `project = Path(args.project_dir).resolve()`.
    "_f1(Path(sys.argv[1]).resolve() / 'reports' / 'phase2' / 'gates' / 'x.json')\n"
)

#: A real FAIL whose finding NAMES a Python exception type and quotes absolute
#: paths — the adversarial input for any crash detector.
_VERDICT_HELPER_SRC = (
    "import sys\n"
    "from pathlib import Path\n"
    "project = Path(sys.argv[1]).resolve()\n"
    "print('verdict: FAIL')\n"
    "print('  [ERROR] corner set incomplete under %s' % project)\n"
    "print(\"  ValueError: corner name 'ss' is not in the PVT matrix\")\n"
    "print('  offending file: %s/constraints/pvt_matrix.json' % project)\n"
    "sys.exit(1)\n"
)

#: A real FAIL that QUOTES a sub-tool's traceback inside its report and then
#: keeps writing. The process did not die of it, so it is a verdict.
_QUOTED_TRACEBACK_HELPER_SRC = (
    "import sys\n"
    "print('verdict: FAIL')\n"
    "print('  the netlist reader rejected the input:')\n"
    "print('  Traceback (most recent call last):')\n"
    "print('    File \"/opt/eda/reader.py\", line 42, in parse')\n"
    "print(\"  SyntaxError: unexpected token at line 12\")\n"
    "print('  [ERROR] 1 unreadable netlist -> signoff cannot proceed')\n"
    "sys.exit(1)\n"
)


def _deep_project(tmp_path):
    """A project dir whose absolute path is far longer than the snippet."""
    deep = tmp_path.joinpath(*(["d" * 40] * 10))
    deep.mkdir(parents=True, exist_ok=True)
    return deep


def _run_helper(name, src, project):
    from programs.flow_compliance_check import (
        _check_program_exit_zero, PROGRAMS_DIR,
    )
    helper = PROGRAMS_DIR / f"{name}.py"
    helper.write_text(src)
    try:
        return _check_program_exit_zero(project, f"{name} .")
    finally:
        helper.unlink(missing_ok=True)


def test_crash_is_flagged_as_a_crash_at_any_checkout_depth(tmp_path):
    """An unhandled exception is disclosed as one, short path or deep."""
    from programs.flow_compliance_check import (
        _CRASH_HINT_PREFIX, _OUTPUT_SNIPPET_CHARS, looks_like_python_traceback,
    )
    shallow = tmp_path / "p"
    shallow.mkdir()
    deep = _deep_project(tmp_path)
    assert len(str(deep)) > _OUTPUT_SNIPPET_CHARS, (
        f"the deep fixture is {len(str(deep))} chars, which does not exceed "
        f"the {_OUTPUT_SNIPPET_CHARS}-char evidence window it exists to "
        f"overflow — this test would prove nothing")

    results = {}
    for label, project in (("shallow", shallow), ("deep", deep)):
        passed, snippet = _run_helper("_pytest_crash_helper",
                                      _CRASH_HELPER_SRC, project)
        assert passed is False, f"{label}: a crash must not be a PASS"
        assert snippet.startswith(_CRASH_HINT_PREFIX), (
            f"{label} (path {len(str(project))} chars): the crash carries no "
            f"{_CRASH_HINT_PREFIX!r} sentinel, so every consumer downstream "
            f"must guess from prose again. Snippet:\n{snippet}")
        # `_evaluate_gate` records `out[:200]`; the exception type has to be
        # inside that, or the disclosure dies one hop later.
        assert "KeyError" in snippet[:200], (
            f"{label}: exception type outside the first 200 chars: "
            f"{snippet[:200]!r}")
        results[label] = snippet

    # The point of the sentinel, stated as a measurement: on the deep path the
    # PROSE channel alone no longer carries the crash. If this ever stops
    # holding the test still passes above, but it stops proving that the
    # sentinel — rather than a lucky truncation — is what did the work.
    body = results["deep"].split("\n", 1)[1]
    assert not looks_like_python_traceback(body), (
        "the deep fixture no longer overflows the evidence window, so this "
        f"test no longer isolates the sentinel. Body:\n{body}")


#: A real FAIL whose indented stdout tail lands immediately above a column-0
#: exception-NAMED summary on stderr, once `output_snippet` glues the two
#: together. 2026-07-28, adversarial finding (HIGH): for one revision this
#: shape was graded CRASH at EVERY checkout depth — origin/main graded it
#: FAIL — because a bare exception tail was allowed to be corroborated by any
#: 4-space-indented line above it. A working, genuinely falsifiable gate
#: reported as having blown up, and its demonstration deleted from the
#: dimension-2 count.
_INDENTED_THEN_COL0_ERROR_SRC = (
    "import sys\n"
    "from pathlib import Path\n"
    "project = Path(sys.argv[1]).resolve()\n"
    "print('verdict: FAIL')\n"
    "print('  [ERROR] 3 corners missing under %s' % project)\n"
    "print('    ss_125c, ff_m40c, tt_25c')\n"
    "sys.stderr.write("
    "'ConstraintError: 3 of 5 PVT corners are undeclared\\n')\n"
    "sys.exit(1)\n"
)


def test_a_real_verdict_is_not_mistaken_for_a_crash(tmp_path):
    """rc 1 with a substantive finding is never DISCLOSED as a crash.

    Three helpers, each built to trip a careless crash detector: one prints an
    exception type as its finding, one quotes a sub-tool traceback inside its
    report, one puts an indented finding immediately above a column-0
    exception-named summary.

    WHAT THIS ASSERTS, exactly: no `_CRASH_HINT_PREFIX`. That is the
    authoritative channel, and it is the one this test owns. It is NOT the
    same as "dimension 2 grades it RED": for the quoted-traceback helper the
    consumer stays silent (correctly — it did not die) and D2's prose fallback
    still calls it a crash, because a verbatim-echoed sub-tool traceback and a
    corpse are indistinguishable from the text alone. That is origin/main
    behaviour, unchanged here, and it is stated rather than implied away —
    an earlier revision of this docstring claimed "both stay FAIL", which was
    measurably false.
    """
    from programs.flow_compliance_check import (
        _CRASH_HINT_PREFIX, _OUTPUT_SNIPPET_CHARS,
    )
    # THE SHALLOW ARM'S PREMISE IS CONSTRUCTED AND ASSERTED, like the deep
    # arm's at `test_crash_is_flagged_as_a_crash_at_any_checkout_depth`.
    #
    # `tmp_path / "p"` is not shallow. pytest builds it as
    # <TMPDIR>/pytest-of-<user>/pytest-<n>/<the test's own name, truncated to
    # 30>/p, which is 63 characters BEFORE the temp root. The helper prints the
    # project path TWICE, so the marker survives the fixed
    # `_OUTPUT_SNIPPET_CHARS`-character TAIL only while
    # 2 * len(project) + 156 <= 300, i.e. len(project) <= 72 -- and 63 plus any
    # temp root of 10 characters or more is already over. MEASURED on
    # ae5cc4dbfc, both arms failing on the same assertion:
    #
    #     TMPDIR=/var/tmp/t1                    project 74 chars   FAIL
    #     TMPDIR=/var/tmp/reyer_lane_code/tmpfix project 94 chars   FAIL
    #
    # and the reported snippet begins mid-word, which is the fixed tail eating
    # `verdict: FAIL` off the front. That is a statement about the host's temp
    # root, not about the crash detector this test owns, so the arm named
    # "shallow" is built short here instead of being hoped short, and the
    # premise is asserted so it cannot rot back into a confusing red.
    shallow = Path(tempfile.mkdtemp(prefix="fcc", dir=tempfile.gettempdir()))
    assert len(str(shallow)) <= _OUTPUT_SNIPPET_CHARS // 4, (
        f"the shallow fixture is {len(str(shallow))} chars against a "
        f"{_OUTPUT_SNIPPET_CHARS}-char evidence window; the helper prints the "
        f"project path twice, so no finding can survive the tail and this arm "
        f"would fail for the host's temp root rather than for the detector")
    deep = _deep_project(tmp_path)
    try:
        _assert_a_real_verdict_is_not_a_crash(shallow, deep, _CRASH_HINT_PREFIX)
    finally:
        shutil.rmtree(shallow, ignore_errors=True)


def _assert_a_real_verdict_is_not_a_crash(shallow, deep, _CRASH_HINT_PREFIX):

    for name, src, marker in (
        ("_pytest_verdict_helper", _VERDICT_HELPER_SRC, "verdict: FAIL"),
        ("_pytest_quoted_tb_helper", _QUOTED_TRACEBACK_HELPER_SRC,
         "unreadable netlist"),
        ("_pytest_indented_err_helper", _INDENTED_THEN_COL0_ERROR_SRC,
         "verdict: FAIL"),
    ):
        for label, project in (("shallow", shallow), ("deep", deep)):
            passed, snippet = _run_helper(name, src, project)
            assert passed is False, f"{name}/{label}: rc 1 must stay a FAIL"
            assert not snippet.startswith(_CRASH_HINT_PREFIX), (
                f"{name}/{label}: a real verdict was disclosed as a CRASH, "
                f"which would delete it from every falsifiability count. "
                f"Snippet:\n{snippet}")
            # ASSERTED ON BOTH ARMS NOW. It used to be asserted on the
            # shallow arm only, and that concession was the defect: with a
            # contiguous TAIL the verdict helper's stdout is
            # `155 + 2 * len(project)` characters against a 300-char window,
            # so the assertion sat exactly on a boundary
            #
            #     len(project) = 72 -> stdout 299 -> `verdict: FAIL` kept
            #     len(project) = 73 -> stdout 301 -> `verdict: FAIL` gone
            #
            # and which lane read a RED here was decided by $TMPDIR. The
            # bounded `shallow` fixture above is a workaround for that window;
            # `output_snippet` now keeps `_OUTPUT_SNIPPET_HEAD_CHARS` of stdout
            # HEAD as well as the tail, so the headline survives at ANY depth
            # and the deep arm — 425 characters, far past any lottery — is the
            # arm that proves it. See
            # `test_the_report_headline_survives_at_any_path_depth` for the
            # property stated on its own, with no helper in the way.
            assert marker in snippet, (
                f"{name}/{label}: the finding itself is missing from the "
                f"evidence snippet:\n{snippet}")
            # NOT asserted on the deep path, and the omission is the finding.
            # MEASURED while writing this test: with a 425-character project
            # path, `_pytest_verdict_helper`'s snippet is the tail of one
            # absolute path and nothing else — `verdict: FAIL` and the
            # `[ERROR]` line are both gone. The CLASSIFICATION is still right
            # (that is what the assertions above pin, and it is right because
            # it no longer reads this string), but the human-readable EVIDENCE
            # for a legitimate failure is still destroyed by the same
            # fixed-width window. Fixing that means changing the snippet's
            # SHAPE — head+tail instead of one contiguous tail — which is a
            # separate change with its own blast radius:
            # `test_matrix_d6_skip_discipline._consumer_snippet` hard-codes a
            # copy of the current shape. Left open deliberately; asserting a
            # marker this code does not preserve would be asserting a wish.


@pytest.mark.parametrize("pad", [0, 1, 40, 400, 4000])
def test_the_report_headline_survives_at_any_path_depth(pad):
    """The FIRST line of a gate's report reaches the consumer, always.

    Stated directly on `output_snippet` rather than through a subprocess, so
    the property is pinned by one call with one variable — the length of the
    absolute paths the report quotes, which is what used to decide it.

    `pad` sweeps the old boundary from both sides: at `pad` small the report
    fits the window whole, at `pad` large it does not and the head is the only
    reason `verdict: FAIL` is still there.
    """
    # IMPORTED AS A MODULE, and the head width read with getattr, so that a
    # tree without the head window FAILS this test rather than ERRORING on the
    # import. An ImportError says the question could not be put; the question
    # here is answerable against any `output_snippet`, and the answer on a
    # pure-tail one is "no".
    from programs import flow_compliance_check as _fcc
    output_snippet = _fcc.output_snippet
    _OUTPUT_SNIPPET_HEAD_CHARS = getattr(
        _fcc, "_OUTPUT_SNIPPET_HEAD_CHARS", None)
    project = "/" + "d" * pad if pad else "/p"
    stdout = (f"verdict: FAIL\n"
              f"  [ERROR] corner set incomplete under {project}\n"
              f"  offending file: {project}/constraints/pvt_matrix.json\n")
    snippet = output_snippet(stdout, "")

    assert snippet.startswith("verdict: FAIL"), (
        f"stdout is {len(stdout)} chars; the headline did not survive the "
        f"{_OUTPUT_SNIPPET_HEAD_CHARS}-char head window:\n{snippet}")
    assert "pvt_matrix.json" in snippet, (
        "the TAIL must still survive — the head is ADDITIVE, and a head that "
        f"cost the tail would be a different defect:\n{snippet}")


def test_the_snippet_is_additive_and_names_what_it_dropped():
    """Everything the pure-tail shape delivered is still delivered.

    The head can only be a repair if it takes nothing away, so the old shape
    is recomputed here and asserted to be a SUBSET of the new one. And when
    anything IS dropped the snippet says so at column 0, so a reader is never
    handed a splice that reads as one contiguous report.
    """
    # Module import + getattr for the same reason as above: a pure-tail
    # `output_snippet` must make this test go RED, not make it unrunnable.
    from programs import flow_compliance_check as _fcc
    output_snippet = _fcc.output_snippet
    n = _fcc._OUTPUT_SNIPPET_CHARS
    elision = getattr(_fcc, "_OUTPUT_SNIPPET_ELISION", None)
    assert elision is not None, (
        "the snippet declares no elision marker, so it cannot be keeping a "
        "head and a tail — it is a contiguous window again")
    stdout = "HEADLINE\n" + "".join(f"line {i}\n" for i in range(400))
    stderr = "".join(f"err {i}\n" for i in range(400))

    snippet = output_snippet(stdout, stderr)
    assert stdout[-n:].strip() in snippet, "the old stdout tail was lost"
    assert stderr[-n:].strip() in snippet, "the stderr window changed"
    marker = elision.split("{n}")[0]
    assert any(ln.startswith(marker) for ln in snippet.splitlines()), (
        f"an elided snippet must NAME the gap:\n{snippet}")

    short = output_snippet("one line\n", "")
    assert marker not in short, (
        f"nothing was elided, so nothing may claim it was: {short!r}")


def test_rc0_and_rc2_are_not_misread_as_crashes(tmp_path):
    """The crash branch sits AFTER the PASS / vacuous / waiver arms.

    A gate that exits 0 or 2 has reached a verdict; printing traceback-shaped
    text on the way must not reclassify it.
    """
    from programs.flow_compliance_check import (
        _CRASH_HINT_PREFIX, _VACUOUS_HINT_PREFIX,
    )
    noisy_pass = (
        "import sys\n"
        "print('Traceback (most recent call last):')\n"
        "print('  File \"/opt/eda/x.py\", line 9, in run')\n"
        "print('RuntimeError: sub-tool warning, recovered')\n"
        "print('[PASS] 12/12 checks clean')\n"
        "sys.exit(0)\n"
    )
    passed, snippet = _run_helper("_pytest_noisy_pass_helper", noisy_pass,
                                  tmp_path)
    assert passed is True, "rc 0 must stay a PASS"
    assert not snippet.startswith(_CRASH_HINT_PREFIX)

    noisy_skip = (
        "import sys\n"
        "print('RuntimeError: probe unavailable')\n"
        "print('verdict: SKIP')\n"
        "sys.exit(2)\n"
    )
    passed, snippet = _run_helper("_pytest_noisy_skip_helper", noisy_skip,
                                  tmp_path)
    assert passed is True, "rc 2 must not become a manufactured design FAIL"
    assert snippet.startswith("INCOMPLETE:")
    assert not snippet.startswith(_CRASH_HINT_PREFIX)
