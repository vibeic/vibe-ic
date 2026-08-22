"""A wildcard `required_outputs` entry must bind to what the step RECORDED.

BIDIRECTIONAL CONTROL for the "wildcard output resolution" change.

THE DEFECT, MEASURED
====================
Step 1 declares `phase2/stage1/rtl/*.sv OR phase2/stage1/rtl/*.v`. On the real
run $HOME/_sky130A_r3_run (ledger generated with
`step_write_ledger.emit`), rename the recorded `phase2/stage1/rtl/spm.v` to
`spm_copy.v` and the audit still returned:

    step 1 Spec-to-RTL  PASS
    output_binding.mode = "mixed"
    note: "step record names phase2/stage1/rtl/spm.v (absent); credited
           instead to phase2/stage1/rtl/spm_copy.v, matched project-wide"

The run had shipped no RTL this step is on record as having written, and the
only thing that changed was a word in a JSON field and a sentence a human was
asked to read. A note is not a verdict.

WHAT A WILDCARD MEANS, AND WHY THIS RULE AND NOT ANOTHER
========================================================
`rtl/*.sv` does NOT mean "exactly the files the ledger recorded" — a design
legitimately gains an RTL file between runs, and set equality would red a step
for someone adding a module (`test_a_new_file_matching_the_wildcard_is_not_a_
regression`). It does NOT mean "any file at all matching the glob" — that is
the defect above, and a file another step wrote satisfies it. It means "the
recorded output set still EXISTS, in part or in whole": satisfied when at
least one recorded path is still an artefact, with M-of-N reported as two
NUMBERS because "recorded 5, resolves 4" and "recorded 5, resolves 0" are
different facts and only the second is an absence.

A LITERAL " OR " alternative keeps its any-of credit — that spelling exists
for one artefact with two accepted names, and a spec that NAMES `parasitic.spef`
by path is satisfied by finding it (`test_a_literal_or_alternative_still_
counts_when_the_recorded_path_is_gone`). Only WILDCARD alternatives lose the
right to be discharged by a file the step never recorded writing.

WHY EVERY ASSERTION IS ON `check_step`
======================================
This file imports one symbol — `flow_compliance_check.check_step` — which
exists on BOTH sides of the change, and asserts on `status`, `evidence` and
`reasons`, all of which the pre-change program already produced. Nothing here
asserts that a field or a helper was ADDED; a control that fails pre-change
only because a new name does not resolve is a control on "did somebody add a
file".

BIDIRECTIONAL, MEASURED BOTH WAYS
=================================
Against the byte-identical pre-change `flow_compliance_check.py` (checked out
detached at 855504f5): 5 failed, 4 passed. Against the change: 9 passed. The
four that pass on BOTH sides are the ones under REVERSE CASES, and they are
the point — the rule has to leave a legitimate wildcard, a literal `OR`
alternative, a literal spec and a ledger-less published cell exactly where it
found them.

BLAST RADIUS, MEASURED BEFORE WRITING THE RULE
==============================================
Three real ledger-bearing runs ($HOME/_sky130A_r3_run,
campaign_v1544/spm/converge_1.5.44_gf180mcuD,
campaign_v1574/spm/converge_1.5.74_sky130A): 24 wildcard specs each, 6-7
carrying a write record, ZERO in the M-of-N state and ZERO credited to an
unrecorded match. All 61 step verdicts identical before and after on all
three. The three published spm cells and benchmark-data/ic/u_hawaii_adc carry
no ledger at all, degrade to the pre-change resolver, and are likewise
verdict-identical.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flow_compliance_check import check_step  # noqa: E402


# `mixed_signal_merge_check <project>` exits 2 on a project with no
# mixed-signal content; rc=2 is the flow's "input-missing skip" convention and
# `check_step` promotes it to VACUOUS_PASS — a DONE-CLAIM. Using it keeps
# these tests about the OUTPUT resolution and not about a gate's opinion.
_VACUOUS_GATE = {"program_exit_zero": "mixed_signal_merge_check ."}

_DONE_CLAIMS = {"PASS", "VACUOUS_PASS", "STRUCTURE-ONLY", "INCOMPLETE"}

_RTL_SPEC = "rtl/*.sv OR rtl/*.v"


def _step(sid, outputs, gate=None):
    s = {"id": sid, "name": f"synthetic step {sid}", "stage": "stage2",
         "required_outputs": list(outputs)}
    if gate is not None:
        s["gate"] = gate
    return s


def _write_step_record(project: Path, sid, folder: str, produced,
                       not_produced=()):
    """Write `step_write_ledger`'s per-step slice — the OBSERVATION half.

    `produced` is [(spec, rel), ...] exactly as the ledger emits it: one entry
    per RESOLVED PATH, so a wildcard spec that matched three files appears
    three times under the same `spec` string.
    """
    sdir = project / "steps" / folder
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "written.json").write_text(json.dumps({
        "id": str(sid),
        "name": f"synthetic step {sid}",
        "n_required_outputs": len(produced) + len(not_produced),
        "n_produced": len(produced),
        "produced": [
            {"rel": rel, "size": 1, "mtime": 1.0, "kind": "file", "spec": spec,
             "producer": None, "producer_confidence": "unwitnessed"}
            for spec, rel in produced],
        "findings": [
            {"dimension": "D3", "kind": "finding",
             "rule": "declared_output_not_produced", "step": str(sid),
             "spec": spec, "reason": reason, "detail": "synthetic"}
            for spec, reason in not_produced],
    }, indent=2) + "\n")
    idx_path = project / "steps" / "index.json"
    try:
        idx = json.loads(idx_path.read_text())
    except (OSError, ValueError):
        idx = {"steps": []}
    idx["steps"] = [s for s in idx["steps"] if str(s.get("id")) != str(sid)]
    idx["steps"].append({"id": str(sid), "name": f"synthetic step {sid}",
                         "status": "pass", "folder": folder,
                         "n_outputs": len(produced)})
    idx_path.write_text(json.dumps(idx, indent=2) + "\n")


@pytest.fixture()
def project(tmp_path):
    """A project whose step 99 recorded writing ONE RTL file under a wildcard."""
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "spm.v").write_text("module spm; endmodule\n")
    _write_step_record(tmp_path, 99, "phase2/stage1/99_synthetic",
                       produced=[(_RTL_SPEC, "rtl/spm.v")])
    return tmp_path


# ── FORWARD: fails against the byte-identical pre-change file ──────────────

def test_a_renamed_recorded_output_does_not_keep_the_wildcard_green(project):
    """THE LOAD-BEARING ONE.

    The step's whole recorded output set for this pattern is gone. A file of
    the same shape is present, and the pre-change resolver credited it —
    `spm_copy.v` proves that A file matching `rtl/*.v` exists under the
    project, which is exactly what a file some OTHER step wrote also proves.
    Reproduced verbatim on the real run $HOME/_sky130A_r3_run:
    PASS before, and the only trace was `mode: "mixed"` plus a sentence.
    """
    (project / "rtl" / "spm.v").rename(project / "rtl" / "spm_copy.v")
    r = check_step(project, _step(99, [_RTL_SPEC], _VACUOUS_GATE), {})
    assert r.status not in _DONE_CLAIMS, (
        f"a wildcard whose entire recorded output set is gone was discharged "
        f"by an unrecorded file that happens to match it: status={r.status} "
        f"evidence={r.evidence}")
    assert "rtl/spm_copy.v" not in r.evidence, (
        "a file this step is on no record of having written must not appear "
        "as evidence that it produced one")


def test_the_step_says_the_wildcard_did_not_bind(project):
    """The verdict must be readable as WHY, not just as a status.

    Asserted on `reasons` — a field the pre-change program already had, which
    on that side carried the word 'credited' and a done-claim.
    """
    (project / "rtl" / "spm.v").rename(project / "rtl" / "spm_copy.v")
    r = check_step(project, _step(99, [_RTL_SPEC], _VACUOUS_GATE), {})
    blob = " ".join(r.reasons)
    assert "wildcard did not bind" in blob, r.reasons
    assert "rtl/spm_copy.v" in blob, (
        "the file that was NOT credited must still be named — an unexplained "
        "absence next to a file that looks like the artefact is the report "
        "that gets overridden by hand")


def test_a_second_step_cannot_discharge_this_ones_wildcard(project):
    """The defect stated as what it actually permits.

    Step 98 writes `rtl/other.v`; step 99 recorded `rtl/spm.v` and it is gone.
    Pre-change, step 99 was green on step 98's file. The two steps are
    independent and the ledger's unit of attribution is the DECLARATION, so
    step 98 stays green on its own record — the rejection is targeted.
    """
    (project / "rtl" / "spm.v").unlink()
    (project / "rtl" / "other.v").write_text("module other; endmodule\n")
    _write_step_record(project, 98, "phase2/stage1/98_other",
                       produced=[(_RTL_SPEC, "rtl/other.v")])

    r99 = check_step(project, _step(99, [_RTL_SPEC], _VACUOUS_GATE), {})
    assert r99.status not in _DONE_CLAIMS, (r99.status, r99.evidence)
    r98 = check_step(project, _step(98, [_RTL_SPEC], _VACUOUS_GATE), {})
    assert r98.status in _DONE_CLAIMS, (r98.status, r98.reasons)
    assert "rtl/other.v" in r98.evidence


def test_a_partial_recorded_set_is_a_different_fact_from_an_absence(project):
    """M OF N IS NOT ZERO OF N — and pre-change it read as neither.

    The step recorded three files under one wildcard; one is gone. The verdict
    is the same on both sides (a residual is not a failure to produce), but
    pre-change the report said NOTHING about it: the step-attributed branch of
    the disclosure printed no notes at all, so "recorded 3, resolves 2" and
    "recorded 3, resolves 3" were the same line. A consumer that cannot tell
    them apart is back to reading prose. Forward on the REPORT, pinned on the
    verdict.
    """
    for name in ("a.v", "b.v", "c.v"):
        (project / "rtl" / name).write_text(f"module {name[0]}; endmodule\n")
    _write_step_record(project, 99, "phase2/stage1/99_synthetic",
                       produced=[(_RTL_SPEC, "rtl/a.v"),
                                 (_RTL_SPEC, "rtl/b.v"),
                                 (_RTL_SPEC, "rtl/c.v")])
    (project / "rtl" / "b.v").unlink()

    r = check_step(project, _step(99, [_RTL_SPEC], _VACUOUS_GATE), {})
    assert r.status in _DONE_CLAIMS, (
        f"two of three recorded outputs are still on disk; that is a "
        f"residual, not an absence: {r.status} {r.reasons}")
    blob = " ".join(r.reasons)
    assert "2 of 3" in blob, (
        f"the residual must be reported as numbers: {r.reasons}")
    assert "rtl/b.v" in blob, r.reasons


def test_a_dangling_link_matching_the_wildcard_cannot_stand_in(project):
    """The tidier way of shipping nothing, one level up.

    `_glob_first` already refuses a link to nothing — that is the "leaving a
    link to nothing scored strictly BETTER than deleting the file" finding in
    its docstring. Pre-change that refusal was undone one layer above it: the
    recorded `spm.v` is a dangling link, so the record's path is not live, and
    the unrecorded `spm_copy.v` was credited in its place. The step shipped no
    RTL it is on record for and kept its done-claim.
    """
    (project / "rtl" / "spm.v").rename(project / "rtl" / "spm_copy.v")
    (project / "rtl" / "spm.v").symlink_to(project / "rtl" / "nowhere.v")
    r = check_step(project, _step(99, [_RTL_SPEC], _VACUOUS_GATE), {})
    assert r.status not in _DONE_CLAIMS, (r.status, r.evidence)
    assert "rtl/spm.v" not in r.evidence


# ── REVERSE CASES: must pass on BOTH sides of the change ───────────────────

def test_a_new_file_matching_the_wildcard_is_not_a_regression(project):
    """WHAT WILDCARDS ARE LEGITIMATELY FOR, and the reason the rule is not
    set equality. A design gains an RTL file between runs; the recorded one is
    still there. This must stay green, and the new file must still be scanned
    as evidence — `_evidence_integrity_scan` reads the evidence list, so
    dropping the addition from it would make the check WEAKER on the exact
    file nobody has looked at yet."""
    (project / "rtl" / "extra.sv").write_text("module extra; endmodule\n")
    r = check_step(project, _step(99, [_RTL_SPEC], _VACUOUS_GATE), {})
    assert r.status in _DONE_CLAIMS, (r.status, r.reasons)
    assert "rtl/spm.v" in r.evidence
    assert "rtl/extra.sv" in r.evidence, (
        f"a file the wildcard matches must stay in the evidence the integrity "
        f"scan reads: {r.evidence}")


def test_a_literal_or_alternative_still_counts_when_the_recorded_path_is_gone(
        project):
    """THE ANY-OF THE " OR " SPELLING EXISTS FOR, and it is not a wildcard.

    Taken from the shipped flow's step 22:
    `phase3/stage3/extracted/parasitic.spef OR phase3/stage3/extracted/*.spef`
    — the run wrote `spm.spef`, the record names it, and renaming it to the
    CANONICAL name the spec itself declares is a normalisation, not a loss.
    Measured on $HOME/_sky130A_r3_run: step 22 stays green on both
    sides of this change. Only the wildcard alternative loses the right to be
    discharged by an unrecorded file.
    """
    spec = "extracted/parasitic.spef OR extracted/*.spef"
    (project / "extracted").mkdir()
    (project / "extracted" / "spm.spef").write_text("*SPEF\n")
    _write_step_record(project, 97, "phase3/stage3/97_spef",
                       produced=[(spec, "extracted/spm.spef")])
    (project / "extracted" / "spm.spef").rename(
        project / "extracted" / "parasitic.spef")

    r = check_step(project, _step(97, [spec], _VACUOUS_GATE), {})
    assert r.status in _DONE_CLAIMS, (
        f"a literal alternative the spec NAMES by path was refused: "
        f"{r.status} {r.reasons}")
    assert "extracted/parasitic.spef" in r.evidence


def test_a_run_with_no_write_record_keeps_the_pre_change_verdict(project):
    """BACKWARD COMPATIBILITY, and it is not optional.

    The three published spm cells and benchmark-data/ic/u_hawaii_adc carry no
    `steps/` tree (benchmark_evidence_publish excludes it by name as per-step
    scratch). With no record there is no evidence that this step failed to
    produce anything — only the absence of a record — and the same renamed
    file that reddens the step above must NOT redden it here.
    """
    for stale in sorted((project / "steps").rglob("*"), reverse=True):
        stale.unlink() if stale.is_file() else stale.rmdir()
    (project / "steps").rmdir()
    (project / "rtl" / "spm.v").rename(project / "rtl" / "spm_copy.v")

    r = check_step(project, _step(99, [_RTL_SPEC], _VACUOUS_GATE), {})
    assert r.status in _DONE_CLAIMS, (r.status, r.reasons)
    assert "rtl/spm_copy.v" in r.evidence
    attribution = [x for x in r.reasons if x.startswith("OUTPUT ATTRIBUTION:")]
    assert len(attribution) == 1 and "PROJECT-WIDE" in attribution[0], (
        "the degradation must be RECORDED, never silent")
    assert "no_steps_tree" in attribution[0]


def test_a_literal_spec_is_judged_exactly_as_before(project):
    """SCOPE. The rule is about patterns that name a SET. A spec that names a
    path resolves the same way it always did — the recorded path is the
    declared path, so there is no third file for the question to be about."""
    (project / "reports").mkdir()
    (project / "reports" / "r.json").write_text("{}\n")
    _write_step_record(project, 96, "phase2/stage1/96_lit",
                       produced=[("reports/r.json", "reports/r.json")])
    r = check_step(project, _step(96, ["reports/r.json"], _VACUOUS_GATE), {})
    assert r.status in _DONE_CLAIMS, (r.status, r.reasons)
    assert r.evidence == ["reports/r.json"]

    (project / "reports" / "r.json").unlink()
    r2 = check_step(project, _step(96, ["reports/r.json"], _VACUOUS_GATE), {})
    assert r2.status not in _DONE_CLAIMS, (r2.status, r2.evidence)
