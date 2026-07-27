#!/usr/bin/env python3
"""`required_outputs` is ALL-of-N — every declared output must be produced.

`flow_compliance_check.check_step()` accumulated evidence across the whole
`required_outputs` list and raised MISSING only when the COMBINED evidence was
empty. A step declaring five outputs therefore passed the artefact check on the
strength of one, which is any-of-N — while the module's own docstring has always
said "verifies every step has: (a) all required_outputs present".

MEASURED on the real spm x ihp-sg13g2 converge run, before the fix:
  * Step 21 declared drc.rpt (absent) and routed.def (present) -> PASS
  * Step 9  declared netlist.v (present) and area.rpt OR stats.json (both
            absent) -> PASS

Second-order effect, which is the reason this is more than a bookkeeping fix:
`flow_step_execution_coverage_check` enforces the declared `blocks_on` edges by
flagging any step marked done whose ancestry has not truly passed — but its
ancestor states are the very statuses this function produces. With any-of-N,
upstream steps essentially never reached MISSING, so the dependency guard was
starved of the ancestor states it fires on. It was never broken.

HOW BIG that effect is depends on the ENGINE VERSION, not only on this branch,
because every other gate also feeds the same ancestor states. Stating one bare
number without its tree is what made the first version of this docstring wrong:
it claimed "89 ordering violations", a figure that reproduces in no
configuration anyone has been able to run — the PR body said 62, a re-derivation
at v1.7.53 measured 68, and the count below is 84. Only the DELTA, measured on
one tree, means anything.

RE-MEASURED at plugin v1.7.58, same run, same command:

    flow_compliance_check.py <run> --flow phase1_phase2_phase3 \\
        --skip-analog --skip-hardware

                       any-of-N     ALL-of-N (this branch)
    PASS                     31     27
    MISSING                   0      4   (steps 9, 10, 23, 38)
    ordering violations      36     84

The 36 already present under any-of-N come from gates that landed AFTER the run
was produced (steps 8, 27, 37 FAIL on today's engine). The net +48 is
+54 -6: steps 9/10/23 turning MISSING adds 54 lines against their dependants
(24 + 24 + 6), and steps 9/10/23/38 losing their own PASS removes the 6 lines
where THEY were the step "marked done". At the merge-base the same measurement
was 0 -> 62, which is why the PR body says 62.

Step 38 is MISSING rather than SKIPPED-CONDITION in that column because this
completed run predates the disclosure marker its generator now writes; a re-run
resolves it to a disclosed SKIPPED-CONDITION. See
`test_step38_scribe_frame_absence_is_disclosed_not_certified.py`.

The " OR " INSIDE one entry stays any-of — that spelling is how the flow yaml
declares a single artefact with two accepted names/locations.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as FCC  # noqa: E402
import flow_step_execution_coverage_check as COV  # noqa: E402


def _touch(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"real": true}\n')
    return p


def _check(project: Path, step: dict):
    return FCC.check_step(project, step, {}, None)


# ── the property ─────────────────────────────────────────────────────────────

def test_one_present_one_absent_is_missing_not_pass(tmp_path):
    """THE defect, in its smallest form. Before the fix this returned a
    non-MISSING status because `netlist.v` alone populated the evidence list."""
    _touch(tmp_path, "phase2/stage2/synth/netlist.v")
    r = _check(tmp_path, {
        "id": 9, "name": "Synthesis",
        "required_outputs": ["phase2/stage2/synth/netlist.v",
                             "phase2/stage2/synth/area.rpt"]})
    assert r.status == "MISSING", r.reasons
    assert any("area.rpt" in x for x in r.reasons), r.reasons


def test_all_present_is_not_missing(tmp_path):
    """DIRECTION 1: the fix must not turn a genuinely complete step red."""
    _touch(tmp_path, "phase2/stage2/synth/netlist.v")
    _touch(tmp_path, "phase2/stage2/synth/area.rpt")
    r = _check(tmp_path, {
        "id": 9, "name": "Synthesis",
        "required_outputs": ["phase2/stage2/synth/netlist.v",
                             "phase2/stage2/synth/area.rpt"]})
    assert r.status != "MISSING", r.reasons


def test_none_present_still_missing_with_the_original_wording(tmp_path):
    """DIRECTION 1: the pre-existing all-absent path is untouched, including
    its message — an operator's grep for it must keep working."""
    r = _check(tmp_path, {
        "id": 9, "name": "Synthesis",
        "required_outputs": ["phase2/stage2/synth/netlist.v",
                             "phase2/stage2/synth/area.rpt"]})
    assert r.status == "MISSING"
    assert any("no required_outputs found" in x for x in r.reasons), r.reasons


def test_empty_required_outputs_does_not_enter_the_all_of_n_path(tmp_path):
    """DIRECTION 1. A step declaring no outputs and carrying no gate is MISSING
    with NO reasons — the default status, untouched by this change (verified
    identical on origin/main). What matters here is that the ALL-of-N branch
    does not claim it: an empty list has nothing to be missing, so it must not
    acquire a required_outputs reason."""
    r = _check(tmp_path, {"id": 99, "name": "x", "required_outputs": []})
    assert not any("required_outputs" in x for x in r.reasons), r.reasons


# ── " OR " within one entry stays any-of ─────────────────────────────────────

@pytest.mark.parametrize("present", ["a/area.rpt", "a/stats.json"])
def test_or_inside_one_entry_is_satisfied_by_either_side(tmp_path, present):
    _touch(tmp_path, "a/netlist.v")
    _touch(tmp_path, present)
    r = _check(tmp_path, {
        "id": 9, "name": "Synthesis",
        "required_outputs": ["a/netlist.v", "a/area.rpt OR a/stats.json"]})
    assert r.status != "MISSING", (present, r.reasons)


def test_or_entry_with_neither_side_present_is_missing(tmp_path):
    _touch(tmp_path, "a/netlist.v")
    r = _check(tmp_path, {
        "id": 9, "name": "Synthesis",
        "required_outputs": ["a/netlist.v", "a/area.rpt OR a/stats.json"]})
    assert r.status == "MISSING", r.reasons


# ── the reported counts must be about ENTRIES, not evidence hits ─────────────

def test_satisfied_count_counts_entries_not_evidence_hits(tmp_path):
    """An entry spelled "A OR B" contributes two evidence hits when both names
    exist. Counting hits produced the self-contradicting "present: 3/3" on a
    step that was simultaneously reported as missing one of its three."""
    _touch(tmp_path, "a/area.rpt")
    _touch(tmp_path, "a/stats.json")   # both sides of the OR exist -> 2 hits
    r = _check(tmp_path, {
        "id": 9, "name": "Synthesis",
        "required_outputs": ["a/area.rpt OR a/stats.json", "a/missing.log"]})
    assert r.status == "MISSING"
    joined = " ".join(r.reasons)
    assert "satisfied: 1/2" in joined, joined


# ── the starved-dependency-guard coupling ────────────────────────────────────

def test_dependency_guard_fires_once_an_upstream_can_reach_missing():
    """The audit that prompted this fix reported `blocks_on` as unenforced,
    having tested `check_step()` alone — which is per-step and legitimately does
    not consult dependencies. The whole-run pass does. This pins the real
    behaviour so the claim is not re-derived wrongly: given an upstream MISSING,
    a downstream PASS IS an ordering violation."""
    report = {"steps": [
        {"id": "43", "name": "Final Test", "status": "MISSING"},
        {"id": "44", "name": "Reliability qualification", "status": "PASS"},
    ]}
    res = COV.analyze(report, {"44": ["43"]})
    assert res["verdict"] == "FAIL"
    v = res["ordering_violations"]
    assert len(v) == 1 and v[0]["terminal_id"] == "44" and v[0]["signoff_id"] == "43"


def test_dependency_guard_stays_quiet_when_upstream_really_passed():
    """DIRECTION 1: the guard must not fire on a healthy chain."""
    report = {"steps": [
        {"id": "43", "name": "Final Test", "status": "PASS"},
        {"id": "44", "name": "Reliability qualification", "status": "PASS"},
    ]}
    assert COV.analyze(report, {"44": ["43"]})["verdict"] == "PASS"


# ── the flow yaml must not declare enforcement nobody performs ───────────────

_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"


def test_flow_declares_no_gate_at_end():
    """Every stage used to carry `gate_at_end: <name>` — and no program in the
    tree ever read the key. FOUR of the eight names did not correspond to any
    file at all (`phase1_compliance`, `analog_compliance`,
    `mixed_signal_compliance`, `manufacturing_compliance`); the other four exist
    as `programs/stage[1-4]_compliance.py` and are catalogued in
    `programs/INDEX.md`, but nothing dispatched them either. An earlier version
    of this docstring said "one of the eight", which understated it — verify
    with `find <tree> -name '<name>.py'` for all eight before editing this line.
    A stage-end gate that exists only in the declaration is a claim of
    enforcement that never runs.

    If stage-end gating is wanted, WIRE it and delete this test in the same
    change. Re-adding the key alone must fail here."""
    assert "gate_at_end" not in _FLOW.read_text(), (
        "flow yaml re-declares `gate_at_end`, which no program reads — "
        "wire it or drop it, do not declare it")


def test_every_program_the_flow_names_exists():
    """The general form of the `gate_at_end` lesson: four of those eight names
    pointed at no file at all, and nothing noticed because nothing checked that
    a name the flow DECLARES resolves to something. `steps[].programs` is the
    live surface of that same class — 84 names today — so check it as a whole
    rather than pinning the four dead strings that were deleted."""
    import yaml
    doc = yaml.safe_load(_FLOW.read_text())
    named = {str(p) for st in doc.get("steps", [])
             for p in (st.get("programs") or [])}
    assert named, "flow declares no programs — the scan found nothing to check"
    dangling = sorted(n for n in named if not (_PROGRAMS / f"{n}.py").is_file())
    assert not dangling, (
        f"flow yaml names {len(dangling)} program(s) with no "
        f"programs/<name>.py: {dangling}")


def test_every_required_output_entry_is_a_plain_relative_glob():
    """Guards the ALL-of-N semantics against a declaration that can never be
    satisfied: an absolute path or a parent escape would now hard-MISS the step
    rather than being quietly absorbed by a sibling entry."""
    import yaml
    doc = yaml.safe_load(_FLOW.read_text())
    bad = []
    for st in doc.get("steps", []):
        for entry in (st.get("required_outputs") or []):
            for alt in (p.strip() for p in entry.split(" OR ")):
                if alt.startswith("/") or ".." in alt.split("/"):
                    bad.append((st.get("id"), alt))
    assert not bad, f"non-relative required_outputs: {bad}"
