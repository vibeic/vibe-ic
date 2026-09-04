"""`check_step` must judge a step's declared outputs by THIS step's own folder.

BIDIRECTIONAL CONTROL for the "step-attributed output resolution" change.

WHY EVERY ASSERTION HERE IS ON `check_step`
===========================================
This file imports exactly one symbol — `flow_compliance_check.check_step` —
which exists on BOTH sides of the change. Nothing here asserts that a helper,
a module or a field was ADDED; every assertion is on the VERDICT and on the
EVIDENCE LIST, both of which the pre-change program already produced. A
control that fails pre-change only because a new name does not resolve is a
control on "did somebody add a file", not on behaviour.

WHAT PRE-CHANGE DOES, MEASURED
==============================
`check_step` resolved every `required_outputs` entry with
`_glob_first(project, pattern)` — "does a file matching this glob exist
SOMEWHERE under the project". A 0-byte file matches. `_evidence_integrity_scan`
(#433) catches some of those, but only when the step's final verdict is
exactly `PASS`; a step whose gate returns the rc=2 VACUOUS_PASS convention
skips that scan entirely, so its 0-byte declared output was credited in full.
Both of the real-run steps this change reddens (D1 and step 5 of
$HOME/_sky130A_r3_run under a named single-file mutation) are exactly
that shape.

The reverse cases are as load-bearing as the forward one. A run with no
`steps/` tree — every published cell, every phase-driven run — must get the
pre-change verdict UNCHANGED, and a step folder that CLAIMS an artefact which
is not on disk must not be able to manufacture a green. That second one is not
hypothetical: on the converged run $HOME/_car15_evidence the step
folders record 90 outputs and 7 of them (steps 15, 17, 19, 20, 21, 22, 34 —
every one of those folders carrying `"status": "pass"`) name a path that does
not exist in the run directory at all.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flow_compliance_check import check_step  # noqa: E402


# `mixed_signal_merge_check <project>` exits 2 on a project with no
# mixed-signal content. rc=2 is the flow's "input-missing skip" convention and
# `check_step` promotes it to the VACUOUS_PASS tier — a DONE-CLAIM that
# `_evidence_integrity_scan` does not scan, which is what makes the 0-byte
# credit visible instead of being caught by the pre-existing net.
_VACUOUS_GATE = {"program_exit_zero": "mixed_signal_merge_check ."}

_DONE_CLAIMS = {"PASS", "VACUOUS_PASS", "STRUCTURE-ONLY", "INCOMPLETE"}


def _step(sid, outputs, gate=None):
    s = {"id": sid, "name": f"synthetic step {sid}", "stage": "stage2",
         "required_outputs": list(outputs)}
    if gate is not None:
        s["gate"] = gate
    return s


def _write_step_record(project: Path, sid, folder: str, produced, not_produced):
    """Write the two files a run leaves behind per step.

    `written.json` is `step_write_ledger`'s per-step slice — the OBSERVATION.
    `outputs.json` is `step_output_collector`'s view — a RESTATEMENT of the
    declaration. Both are written here on purpose: several tests need them to
    DISAGREE, because that is the state a real converged run was found in.
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
    (sdir / "outputs.json").write_text(json.dumps({
        "id": str(sid), "status": "pass", "folder": folder,
        "outputs": [{"rel": rel, "abs": str(project / rel), "size": 1}
                    for _spec, rel in produced],
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
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "good.json").write_text('{"ok": true}\n')
    return tmp_path


# ── FORWARD: fails pre-change, passes after ─────────────────────────────────

def test_a_zero_byte_declared_output_is_not_credited_as_produced(project):
    """The load-bearing one.

    Two declared outputs; one is real, one is a 0-byte file. The step's own
    folder records the second as `zero_byte`. Pre-change the project-wide glob
    matched it and the step kept its done-claim; a 0-byte report is equally
    consistent with "clean" and with "the tool never wrote anything", so a
    verdict resting on it has measured nothing.
    """
    (project / "out" / "empty.json").write_text("")
    _write_step_record(
        project, 99, "phase2/stage2/99_synthetic",
        produced=[("out/good.json", "out/good.json")],
        not_produced=[("out/empty.json", "zero_byte")])

    r = check_step(project, _step(99, ["out/good.json", "out/empty.json"],
                                  _VACUOUS_GATE), {})
    assert r.status not in _DONE_CLAIMS, (
        f"a declared output this step's own write record calls zero_byte was "
        f"credited: status={r.status} evidence={r.evidence}")
    assert "out/empty.json" not in r.evidence, (
        "a 0-byte file must not appear as evidence that the step produced it")
    # and the real one still counts — the rejection is targeted, not blanket
    assert "out/good.json" in r.evidence


def test_the_report_says_which_question_the_output_verdict_answered(project):
    """A step-attributed PASS and a project-wide PASS must be tellable apart.

    Pre-change both printed the same thing, so a reader of the 63xN matrix
    could not know whether "outputs present" meant "this step produced them"
    or "something under the project matched the pattern". Asserted on
    `reasons`, a field the pre-change program already had.
    """
    _write_step_record(
        project, 99, "phase2/stage2/99_synthetic",
        produced=[("out/good.json", "out/good.json")], not_produced=[])
    r = check_step(project, _step(99, ["out/good.json"], _VACUOUS_GATE), {})
    attribution = [x for x in r.reasons if x.startswith("OUTPUT ATTRIBUTION:")]
    assert len(attribution) == 1, r.reasons
    assert "step-attributed" in attribution[0]

    # and the degraded case says so too — never silence, in either direction
    for stale in (project / "steps").rglob("*"):
        if stale.is_file():
            stale.unlink()
    r2 = check_step(project, _step(99, ["out/good.json"], _VACUOUS_GATE), {})
    attribution2 = [x for x in r2.reasons if x.startswith("OUTPUT ATTRIBUTION:")]
    assert len(attribution2) == 1, r2.reasons
    assert "PROJECT-WIDE" in attribution2[0]
    assert "no_steps_tree" in attribution2[0]


# ── REVERSE CASES: must pass on BOTH sides ─────────────────────────────────

def test_a_dangling_symlink_the_step_records_is_not_credited(project):
    """MEASURED TO BE A REVERSE CASE, and kept as one.

    Written expecting it to fail pre-change; it does not. `Path.glob`'s precise
    selector existence-checks a LITERAL pattern before yielding it, and
    `_resolves_to_real_artefact` already covers the wildcard spelling, so a
    link to nothing was ALREADY rejected. Kept as a pin: the new resolver must
    not regress it, and the honest count of what this change moves is two
    forward cases, not three.
    """
    (project / "out" / "gone.json").symlink_to(project / "out" / "nowhere.json")
    _write_step_record(
        project, 99, "phase2/stage2/99_synthetic",
        produced=[("out/good.json", "out/good.json")],
        not_produced=[("out/gone.json", "dangling_symlink")])
    r = check_step(project, _step(99, ["out/good.json", "out/gone.json"],
                                  _VACUOUS_GATE), {})
    assert r.status not in _DONE_CLAIMS, (r.status, r.evidence)
    assert "out/gone.json" not in r.evidence


def test_a_real_output_still_reads_as_produced(project):
    """Anti-"flag everything". A step whose declared outputs are all real,
    non-empty files keeps its done-claim, with both of them as evidence."""
    (project / "out" / "second.json").write_text('{"ok": true}\n')
    _write_step_record(
        project, 99, "phase2/stage2/99_synthetic",
        produced=[("out/good.json", "out/good.json"),
                  ("out/second.json", "out/second.json")],
        not_produced=[])
    r = check_step(project, _step(99, ["out/good.json", "out/second.json"],
                                  _VACUOUS_GATE), {})
    assert r.status in _DONE_CLAIMS, (r.status, r.reasons)
    assert sorted(r.evidence) == ["out/good.json", "out/second.json"]


def test_a_run_with_no_steps_tree_keeps_the_pre_change_verdict(project):
    """BACKWARD COMPATIBILITY, and it is not optional.

    Published cells carry no `steps/` (benchmark_evidence_publish excludes it
    by name as per-step scratch) and any run driven straight at a phase runner
    never built one. The same 0-byte output that reddens the step above must
    NOT redden it here: with no per-step write record there is no evidence
    that this step failed to produce anything, only the absence of a record,
    and failing a cell on the absence of a record is failing it for the
    auditor's benefit.
    """
    (project / "out" / "empty.json").write_text("")
    assert not (project / "steps").exists()
    r = check_step(project, _step(99, ["out/good.json", "out/empty.json"],
                                  _VACUOUS_GATE), {})
    assert r.status in _DONE_CLAIMS, (r.status, r.reasons)
    assert "out/empty.json" in r.evidence


def test_no_binding_blocks_only_in_explicit_strict_mode(project):
    """The producer-migration flag tightens `no_binding`, not the default."""
    (project / "out" / "empty.json").write_text("")
    assert not (project / "steps").exists()
    # The explicit migration mode grades the producer gap rather than silently
    # changing the default for every pre-ledger published run.
    strict = check_step(
        project,
        _step(99, ["out/good.json", "out/empty.json"], _VACUOUS_GATE),
        {}, strict_step_binding=True)
    assert strict.status == "FAIL", (strict.status, strict.reasons)
    assert any("UNATTRIBUTED OUTPUT" in reason
               and "no_binding" in reason for reason in strict.reasons)


def test_a_run_ledger_that_omits_this_step_can_never_certify_it(project):
    """`no_step_record` blocks even when strict migration mode is disabled.

    The run has a valid ledger row for another step and a live file matching
    this step's declaration.  Therefore the run had the means to attribute
    the file and positively did not attribute it to this step.  A
    project-wide match must not turn that evidence into a done claim.
    """
    _write_step_record(
        project, 42, "phase2/stage2/42_other",
        produced=[("out/good.json", "out/good.json")],
        not_produced=[])

    step = _step(99, ["out/good.json"], _VACUOUS_GATE)

    # This assertion executes before either new keyword spelling, so the
    # pre-fix control fails on the old program's wrong DONE value rather than
    # on the mere absence of a newly-added API parameter.
    result = check_step(project, step, {})
    assert result.status == "FAIL", (result.status, result.reasons)
    assert any("UNATTRIBUTED OUTPUT" in reason
               and "no_step_record" in reason
               for reason in result.reasons), result.reasons
    assert result.output_binding["codes"] == ["no_step_record"]

    # Neither explicit spelling may provide an escape hatch for the stronger
    # `no_step_record` fact.
    for strict in (False, True):
        result = check_step(project, step, {}, strict_step_binding=strict)
        assert result.status == "FAIL", (
            strict, result.status, result.reasons)
        assert any("UNATTRIBUTED OUTPUT" in reason
                   and "no_step_record" in reason
                   for reason in result.reasons), result.reasons
        assert result.output_binding["codes"] == ["no_step_record"]


def test_a_step_folder_claiming_an_absent_artefact_cannot_make_it_green(project):
    """ANTI-WEAKENING, taken from a real converged run.

    `$HOME/_car15_evidence` has 7 step folders whose `outputs.json`
    records a produced artefact — with a byte size — for a path that does not
    exist in the run directory, every one of them under `"status": "pass"`.
    Had this change read the collector's VIEW instead of the write LEDGER, or
    let a record override the disk, those 7 currently-MISSING steps would have
    turned green. The resolver is monotone: it can only take away.
    """
    _write_step_record(
        project, 99, "phase2/stage2/99_synthetic",
        produced=[("out/good.json", "out/good.json"),
                  ("out/never_written.json", "out/never_written.json")],
        not_produced=[])
    assert not (project / "out" / "never_written.json").exists()
    r = check_step(project, _step(99, ["out/good.json",
                                       "out/never_written.json"],
                                  _VACUOUS_GATE), {})
    assert r.status not in _DONE_CLAIMS, (
        f"a step folder that CLAIMS an artefact which is not on disk was "
        f"allowed to certify it: status={r.status} evidence={r.evidence}")
    assert "out/never_written.json" not in r.evidence


def test_an_artefact_declared_by_two_steps_is_green_for_both(project):
    """SHARED ARTEFACTS ARE NOT A FAILURE.

    Some outputs are legitimately written once and read by many. The shipped
    flow has two such paths (`phase2/stage2/synth/netlist.v` — steps 9 and 14;
    `phase3/mixed_signal/cosim/mixed_signal_results.json` — A9 and M3). Because
    the unit of attribution is the step's DECLARATION and not a single
    producer, both declaring steps resolve it independently and both stay
    green. A design that bound this to "exactly one step may claim this write"
    would have reddened one of each pair for doing nothing wrong.
    """
    _write_step_record(project, 9, "phase2/stage2/9_a",
                       produced=[("out/good.json", "out/good.json")],
                       not_produced=[])
    _write_step_record(project, 14, "phase2/stage2/14_b",
                       produced=[("out/good.json", "out/good.json")],
                       not_produced=[])
    for sid in (9, 14):
        r = check_step(project, _step(sid, ["out/good.json"], _VACUOUS_GATE), {})
        assert r.status in _DONE_CLAIMS, (sid, r.status, r.reasons)
        assert r.evidence == ["out/good.json"], (sid, r.evidence)


def test_a_step_with_no_declared_outputs_is_untouched(project):
    """Nothing to attribute is a third state, not a degraded one. A step that
    declares no `required_outputs` must not acquire an attribution line."""
    r = check_step(project, _step(99, [], _VACUOUS_GATE), {})
    assert not [x for x in r.reasons if x.startswith("OUTPUT ATTRIBUTION:")]


def test_an_unreadable_step_record_degrades_instead_of_failing(project):
    """A corrupt record loses an ATTRIBUTION, never a verdict. `steps/` exists,
    `index.json` is garbage: the step must resolve exactly as it did before the
    change, and say that it did."""
    (project / "steps").mkdir()
    (project / "steps" / "index.json").write_text("{not json")
    r = check_step(project, _step(99, ["out/good.json"], _VACUOUS_GATE), {})
    assert r.status in _DONE_CLAIMS, (r.status, r.reasons)
    assert r.evidence == ["out/good.json"]
