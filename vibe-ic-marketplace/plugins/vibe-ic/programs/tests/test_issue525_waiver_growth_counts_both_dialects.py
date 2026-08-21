"""#525 — the growth gate counts the waivers it could not previously see, and
it counts each one exactly once.

`waiver_growth_check` exists to stop deferred work accumulating release over
release. It read `waived_steps` only, behind a `{"waived_steps": []}` default,
so on a project carrying the OTHER sanctioned dialect it reported 0 current
waivers, compared them against a baseline of 0, and passed — a verdict that
reads identically whether or not anything was examined. Across the tracked
corpus that hid 8 of 19 entries in 6 of 11 projects.

Measured a second, independent instance of the same failure while fixing the
first: the STALE_EVIDENCE check read `evidence` only when it was a `str`, and
every one of the 19 corpus entries carries the LIST form. That check had
therefore examined zero pointers and had never fired, in either dialect.

Growth is a set difference across runs, so the fix turns on the KEY. The tests
below pin, by EXECUTION, both directions of that key:

  * two genuinely different obligations must not collide — including the case
    where their step names resolve to the SAME canonical flow step, which is
    the shape the runner emits and which a resolve-then-compare key would fuse;
  * one obligation must not look like two across runs — including when the
    emitting runner's version string, the prose and the verdict tier all move
    around it, which a whole-entry key would report as a close plus an open.

and that the gate never makes itself green: it does not write, create or
rewrite a baseline, and it says out loud when it compared against an absent one
rather than a recorded zero.

Tests marked REGRESSION GUARD do NOT discriminate against the unfixed gate —
they pin behaviour the fix must not break, and each says so.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PROG = PROGRAMS / "waiver_growth_check.py"
sys.path.insert(0, str(PROGRAMS))

STATE_DIR = ".vibe-ic-state"
BASELINE_NAME = "waivers_baseline.json"


# ----------------------------------------------------------------------
# harness
# ----------------------------------------------------------------------
def _run(project: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project), *extra],
                          capture_output=True, text=True)


def _run_json(project: Path, *extra: str):
    """``(rc, parsed_json)``. Parsing is asserted rather than assumed so a gate
    that dies before emitting cannot be mistaken for a gate that passed."""
    proc = _run(project, "--json", *extra)
    assert proc.stdout.strip(), (
        f"gate produced no JSON; rc={proc.returncode} stderr={proc.stderr!r}")
    return proc.returncode, json.loads(proc.stdout)


def _project(tmp_path: Path, doc, baseline=None) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    (proj / "waivers.json").write_text(json.dumps(doc))
    if baseline is not None:
        state = proj / STATE_DIR
        state.mkdir(exist_ok=True)
        (state / BASELINE_NAME).write_text(json.dumps(baseline))
    return proj


def _categories(result) -> set:
    return {f["category"] for f in result["findings"]}


def _attestation(step, ticket, **over):
    """One entry in the dialect the runner emits — no `id`, identified by its
    step role plus phase plus ticket."""
    entry = {
        "step": step,
        "phase": "3",
        "verdict_tier": "WAIVED",
        "rationale": "deferred to a dedicated flow",
        "evidence": ["reports/orchestrator/run.json"],
        "ticket": ticket,
        "review_required": True,
        "reviewer_action": "Sign-off engineer must re-run offline.",
    }
    entry.update(over)
    return entry


# ----------------------------------------------------------------------
# the reported defect
# ----------------------------------------------------------------------
def test_attestation_dialect_is_counted_at_all(tmp_path):
    """The reproduction. One entry in the runner's dialect must be seen."""
    proj = _project(tmp_path, {"waivers": [_attestation("lvs", "T-1")]})
    rc, result = _run_json(proj)
    assert result["summary"]["current_root_waivers"] == 1, (
        "the gate reported %d waivers on a project carrying one"
        % result["summary"]["current_root_waivers"])
    assert rc == 1
    assert "UNJUSTIFIED_WAIVER_GROWTH" in _categories(result)


def test_both_dialects_in_one_document_are_both_counted(tmp_path):
    """A document carrying BOTH keys must total both, and must not die doing
    it. A naive union over the historical `entry["id"]` accessor raises
    KeyError here, because the attestation dialect carries no `id`."""
    proj = _project(tmp_path, {
        "waived_steps": [{"id": 39, "reason": "board"}],
        "waivers": [_attestation("lvs", "T-1")],
    })
    rc, result = _run_json(proj)
    assert result["summary"]["current_root_waivers"] == 2
    assert result["summary"]["current_waivers_by_key"] == {
        "waived_steps": 1, "waivers": 1}
    assert rc == 1


# ----------------------------------------------------------------------
# identity — two different waivers must not collide
# ----------------------------------------------------------------------
def test_roles_sharing_one_canonical_step_do_not_collide(tmp_path):
    """The corpus shape, and the hardest collision to avoid.

    A project separately defers two physical-verification roles that resolve to
    the SAME canonical flow step, under ONE ticket, in one phase — so the two
    entries differ in exactly one field, the step name as written. Two things
    would fuse them into a single counted waiver and hide half the deferred
    work: resolving the step name through the many-to-one step map before
    comparing, or keying on the ticket, which is the field that most looks like
    an identifier."""
    import _waiver_entries as _we
    assert _we.resolve_step_name("drc") == _we.resolve_step_name("lvs"), (
        "premise moved: these role names no longer share a canonical step, so "
        "this test no longer exercises the collision it was written for")

    proj = _project(tmp_path, {"waivers": [
        _attestation("drc", "T-SHARED"),
        _attestation("lvs", "T-SHARED"),
    ]})
    _rc, result = _run_json(proj)
    assert result["summary"]["current_root_waivers"] == 2
    assert len(set(result["summary"]["new_waivers"])) == 2


def test_same_step_different_ticket_do_not_collide(tmp_path):
    """One step deferred under two tickets is two obligations. Keying on the
    step alone would fuse them."""
    proj = _project(tmp_path, {"waivers": [
        _attestation("drc", "T-CELL-LIBRARY"),
        _attestation("drc", "T-DENSITY"),
    ]})
    _rc, result = _run_json(proj)
    assert result["summary"]["current_root_waivers"] == 2


def test_same_step_and_ticket_in_different_phases_do_not_collide(tmp_path):
    """A step deferred at two different points in the flow is two obligations,
    so `phase` earns its place in the key rather than riding along."""
    proj = _project(tmp_path, {"waivers": [
        _attestation("fpga_compile", "T-BOARD", phase="2"),
        _attestation("fpga_compile", "T-BOARD", phase="3"),
    ]})
    _rc, result = _run_json(proj)
    assert result["summary"]["current_root_waivers"] == 2


# ----------------------------------------------------------------------
# identity — one waiver must not look like two across runs
# ----------------------------------------------------------------------
def test_identity_survives_runner_version_and_prose_churn(tmp_path):
    """The SAME obligation, re-emitted by a newer runner: the version string
    inside `reviewer_action` moves, the prose moves, the evidence list grows and
    the tier is re-graded. None of that is a close plus an open, and a gate that
    reported it as one would cry growth on every release."""
    before = _attestation(
        "lvs", "T-1",
        rationale="deferred; extraction flow not yet landed",
        reviewer_action="Re-run offline. Auto-generated by the runner v1.0.0.",
        evidence=["reports/orchestrator/run.json"],
        verdict_tier="WAIVED")
    after = _attestation(
        "lvs", "T-1",
        rationale="still deferred; extraction flow landed but unqualified",
        reviewer_action="Re-run offline. Auto-generated by the runner v9.9.9.",
        evidence=["reports/orchestrator/run.json", "reports/extraction.log"],
        verdict_tier="PASS_STRUCTURAL")

    proj = _project(tmp_path, {"waivers": [after]}, baseline={"waivers": [before]})
    rc, result = _run_json(proj)
    summary = result["summary"]
    # Asserted explicitly: a gate that sees NOTHING also reports net 0, so the
    # verdict alone would pass this test for the wrong reason.
    assert summary["current_root_waivers"] == 1
    assert summary["baseline_root_waivers"] == 1
    assert summary["new_waivers"] == []
    assert summary["removed_waivers"] == []
    assert summary["net_growth"] == 0
    assert rc == 0


def test_reading_the_same_document_twice_does_not_double_count(tmp_path):
    """The identity is a pure function of the entry: the same document as both
    current and baseline is flat, not doubled."""
    doc = {"waivers": [_attestation("drc", "T-A"), _attestation("lvs", "T-B")]}
    proj = _project(tmp_path, doc, baseline=doc)
    rc, result = _run_json(proj)
    assert result["summary"]["current_root_waivers"] == 2
    assert result["summary"]["net_growth"] == 0
    assert rc == 0


def test_a_genuinely_closed_attestation_is_reported_removed(tmp_path):
    """The set difference works in the shrink direction too — otherwise
    "net 0" could just mean "both sides invisible"."""
    proj = _project(
        tmp_path,
        {"waivers": [_attestation("lvs", "T-1")]},
        baseline={"waivers": [_attestation("lvs", "T-1"),
                              _attestation("drc", "T-2")]})
    rc, result = _run_json(proj)
    assert result["summary"]["removed_waivers"] and \
        "drc" in result["summary"]["removed_waivers"][0]
    assert result["summary"]["net_growth"] == -1
    assert rc == 0


def test_cascades_to_does_not_suppress_by_step_role(tmp_path):
    """A step ROLE is not a unique name — the same role is legitimately
    deferred twice under two tickets. Reading a `cascades_to` target as a role
    name suppresses EVERY entry carrying it: one declaration hides two distinct
    obligations, and a growth gate that loses waivers to a guess is a false
    PASS. Derivation in this dialect comes only from `cascade_source`."""
    doc = {"waivers": [
        _attestation("drc", "T-ROOT", cascades_to=["lvs"]),
        _attestation("lvs", "T-EXTRACTION"),
        _attestation("lvs", "T-DEVICE-LEVEL"),
    ]}
    _rc, result = _run_json(_project(tmp_path, doc))
    assert result["summary"]["current_root_waivers"] == 3, (
        "a cascades_to target suppressed obligations it does not name: %r"
        % (result["summary"]["new_waivers"],))


def test_attestation_cascade_child_is_not_a_root(tmp_path):
    """`cascade_source` marks bookkeeping, not new deferred work — and that
    rule applies in both dialects, not only the one with ids."""
    proj = _project(tmp_path, {"waivers": [
        _attestation("drc", "T-ROOT"),
        _attestation("lvs", "T-ROOT", cascade_source="drc"),
    ]})
    _rc, result = _run_json(proj)
    assert result["summary"]["current_waivers_by_key"] == {"waivers": 2}
    assert result["summary"]["current_root_waivers"] == 1


# ----------------------------------------------------------------------
# the baseline is never rewritten by the gate
# ----------------------------------------------------------------------
def test_gate_never_writes_a_baseline(tmp_path):
    """REGRESSION GUARD (does not discriminate against the unfixed gate).
    Making the second dialect visible must not be paid for by the gate
    freezing its own reference — a gate that edits what it compares against
    is certifying itself."""
    proj = _project(tmp_path, {"waivers": [_attestation("lvs", "T-1")]})
    rc, _result = _run_json(proj)
    assert rc == 1
    assert not (proj / STATE_DIR).exists(), (
        "the gate created its own baseline directory")
    assert json.loads((proj / "waivers.json").read_text())["waivers"], (
        "the gate rewrote the project's waivers.json")


def test_absent_baseline_is_disclosed_not_shown_as_a_recorded_zero(tmp_path):
    """"No baseline was ever frozen" and "the frozen baseline held zero" print
    the same number and mean different things."""
    proj = _project(tmp_path, {"waivers": [_attestation("lvs", "T-1")]})
    _rc, result = _run_json(proj)
    assert result["baseline_present"] is False
    assert result["summary"]["baseline_present"] is False
    text = _run(proj).stdout
    assert "ABSENT" in text
    assert "empty document" in text


def test_present_baseline_is_reported_as_present(tmp_path):
    proj = _project(tmp_path, {"waivers": [_attestation("lvs", "T-1")]},
                    baseline={"waivers": [_attestation("lvs", "T-1")]})
    rc, result = _run_json(proj)
    assert result["baseline_present"] is True
    assert "ABSENT" not in _run(proj).stdout
    assert rc == 0


def test_growth_rationale_is_the_operator_escape_hatch(tmp_path):
    """Growth in the newly-visible dialect is justified the same documented
    way as growth in the other — by a human writing it down in the data, not
    by the gate lowering its own bar.

    vibe-ic#922 added the second half of what "writing it down" means: the
    rationale also records the waiver population it was written against
    (``growth_rationale_covers``), because a bare string authorised unlimited
    growth forever. This test's SUBJECT is unchanged and so are its assertions
    — the escape hatch still opens, on the same dialect, with the same
    ``growth_justified is True`` and rc 0. Only the fixture moved to the
    current contract."""
    proj = _project(tmp_path, {
        "waivers": [_attestation("lvs", "T-1")],
        "growth_rationale": ("Device-level extraction is scheduled for the "
                             "next release; deferral accepted by sign-off."),
        "growth_rationale_covers": 1,
    })
    rc, result = _run_json(proj)
    assert result["summary"]["current_root_waivers"] == 1
    assert result["summary"]["growth_justified"] is True
    assert rc == 0


# ----------------------------------------------------------------------
# unreadable shapes are reported, never counted as zero
# ----------------------------------------------------------------------
def test_entry_list_that_is_not_a_list_is_reported(tmp_path):
    """A present-but-unreadable entry list must not read as "no waivers"."""
    proj = _project(tmp_path, {"waivers": {"step": "lvs"}})
    rc, result = _run_json(proj)
    assert "WAIVER_LIST_UNREADABLE" in _categories(result)
    assert rc == 1


@pytest.mark.parametrize("doc", [[1, 2, 3], None, "text", 7])
def test_top_level_that_is_not_an_object_is_reported_not_passed(tmp_path, doc):
    """A document whose top level is not a JSON object carries no readable
    entry list. The shared reader fail-softs it to "no entries" — right for a
    caller asking whether one step is waived, and a silent PASS for a gate
    counting them. Reported instead."""
    proj = _project(tmp_path, doc)
    rc, result = _run_json(proj)
    assert "WAIVER_DOCUMENT_UNREADABLE" in _categories(result)
    assert rc == 1


def test_unhashable_identifier_does_not_crash_the_gate(tmp_path):
    """A traceback is not a verdict: the gate must still produce a report."""
    proj = _project(tmp_path, {"waived_steps": [{"id": {"nested": 1}}],
                               "waivers": [_attestation("lvs", "T-1")]})
    rc, result = _run_json(proj)
    assert result["summary"]["current_root_waivers"] == 2
    assert rc == 1


def test_unhashable_cascade_target_does_not_crash_the_gate(tmp_path):
    """A `cascades_to` list holding something unhashable names no entry; it
    must not take the report down with it."""
    proj = _project(tmp_path, {"waived_steps": [
        {"id": 1, "cascades_to": [{"nested": 1}]}]})
    rc, result = _run_json(proj)
    assert result["summary"]["current_root_waivers"] == 1
    assert rc == 1


def test_unreadable_baseline_is_reported_too(tmp_path):
    """A growth number measured against a baseline the gate could not read is
    not a measurement."""
    proj = _project(tmp_path, {"waivers": [_attestation("lvs", "T-1")]},
                    baseline=[1, 2, 3])
    _rc, result = _run_json(proj)
    unreadable = [f for f in result["findings"]
                  if f["category"] == "WAIVER_DOCUMENT_UNREADABLE"]
    assert len(unreadable) == 1
    assert "baseline" in unreadable[0]["message"]


def test_corrupt_waivers_json_still_refuses(tmp_path):
    """REGRESSION GUARD (does not discriminate against the unfixed gate).
    The shared reader fail-softs an unparseable document to "no entries"; this
    gate must keep exiting 2 instead, or a corrupt waiver list becomes a PASS."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "waivers.json").write_text("{not json")
    assert _run(proj).returncode == 2


def test_absent_waivers_json_is_still_a_clean_pass(tmp_path):
    """REGRESSION GUARD (does not discriminate against the unfixed gate).
    A project with no waivers.json at all is legitimately flat."""
    proj = tmp_path / "proj"
    proj.mkdir()
    rc, result = _run_json(proj)
    assert result["summary"]["current_root_waivers"] == 0
    assert rc == 0


# ----------------------------------------------------------------------
# the second instance: evidence pointers
# ----------------------------------------------------------------------
def test_list_shaped_evidence_is_checked(tmp_path):
    """Every entry in the tracked corpus carries the list form, and the check
    read only the string form — so it had examined nothing, in either dialect."""
    proj = _project(tmp_path, {"waived_steps": [
        {"id": 31, "evidence": ["reports/does_not_exist.rpt"]}]})
    _rc, result = _run_json(proj)
    stale = [f for f in result["findings"] if f["category"] == "STALE_EVIDENCE"]
    assert len(stale) == 1
    assert "reports/does_not_exist.rpt" in stale[0]["message"]


def test_evidence_that_resolves_is_not_reported_stale(tmp_path):
    """The check must DISCRIMINATE, not warn on everything it can now read —
    and silence about the live pointer must not be the silence of a check that
    read nothing, so a genuinely missing pointer sits beside it and must be
    reported."""
    proj = _project(tmp_path, {"waived_steps": [
        {"id": 31, "evidence": ["reports/real.rpt"]},
        {"id": 32, "evidence": ["reports/gone.rpt"]},
    ]})
    (proj / "reports").mkdir()
    (proj / "reports" / "real.rpt").write_text("clean\n")
    _rc, result = _run_json(proj)
    stale = [f for f in result["findings"] if f["category"] == "STALE_EVIDENCE"]
    assert len(stale) == 1, [f["message"] for f in stale]
    assert "reports/gone.rpt" in stale[0]["message"]
    assert "reports/real.rpt" not in stale[0]["message"]


def test_prose_in_a_pointer_list_is_not_mined_for_paths(tmp_path):
    """A list is a sequence of pointer slots. Token-mining a prose element
    yields sentence fragments reported as missing files, which trains readers
    to ignore the finding — while a REAL missing pointer in the same list must
    still be reported."""
    proj = _project(tmp_path, {"waived_steps": [{"id": 31, "evidence": [
        "violations land on library-internal layer rules a/b and c/d, see "
        "the deck under input/vendor/deck/ for the full list",
        "reports/missing.rpt",
    ]}]})
    _rc, result = _run_json(proj)
    stale = [f for f in result["findings"] if f["category"] == "STALE_EVIDENCE"]
    assert len(stale) == 1, [f["message"] for f in stale]
    assert "reports/missing.rpt" in stale[0]["message"]


def test_fragment_locator_does_not_make_a_live_pointer_stale(tmp_path):
    """A `#fragment` locates a position INSIDE the file. Leaving it attached
    reports every precise pointer as missing."""
    proj = _project(tmp_path, {"waived_steps": [
        {"id": 31, "evidence": "reports/run.json#steps[name=lvs]"}]})
    (proj / "reports").mkdir()
    (proj / "reports" / "run.json").write_text("{}")
    _rc, result = _run_json(proj)
    assert "STALE_EVIDENCE" not in _categories(result)


def test_stale_evidence_names_the_waiver_it_came_from(tmp_path):
    """An attestation entry has no `id`; the finding must name it by the
    identity it does have, not by `id=None`."""
    proj = _project(tmp_path, {"waivers": [
        _attestation("lvs", "T-1", evidence=["reports/missing.rpt"])]})
    _rc, result = _run_json(proj)
    stale = [f for f in result["findings"] if f["category"] == "STALE_EVIDENCE"]
    assert len(stale) == 1
    assert "id=None" not in stale[0]["message"]
    assert "T-1" in stale[0]["message"]


def test_non_string_approved_at_is_reported_not_crashed(tmp_path):
    """Widening the age ladder to every dialect must not widen a crash."""
    proj = _project(tmp_path, {"waivers": [
        _attestation("lvs", "T-1", approved_at=20260101)]})
    rc, result = _run_json(proj)
    assert "APPROVED_AT_INVALID" in _categories(result)
    assert rc == 1  # from the growth finding, not from a traceback


# ----------------------------------------------------------------------
# the control: the dialect that already worked must not move
# ----------------------------------------------------------------------
def test_id_dialect_identity_is_byte_for_byte_unchanged(tmp_path):
    """REGRESSION GUARD (does not discriminate against the unfixed gate).
    Adopting the shared reader must not restate an identity the id dialect
    already had — these keys are what this gate has always printed."""
    proj = _project(tmp_path, {"waived_steps": [
        {"id": 39, "reason": "board"}, {"id": 6, "reason": "board"}]})
    rc, result = _run_json(proj)
    assert sorted(result["summary"]["new_waivers"]) == ["39", "6"], (
        "the id dialect's printed identity moved: %r"
        % (result["summary"]["new_waivers"],))
    assert result["summary"]["current_root_waivers"] == 2
    assert rc == 1


def test_id_dialect_cascade_target_still_counts_once(tmp_path):
    """REGRESSION GUARD (does not discriminate against the unfixed gate)."""
    proj = _project(tmp_path, {"waived_steps": [
        {"id": 31, "cascades_to": [32]},
        {"id": 32},
    ]})
    _rc, result = _run_json(proj)
    assert result["summary"]["current_root_waivers"] == 1


@pytest.mark.parametrize("tolerance,expected_rc", [(0, 1), (5, 0)])
def test_tolerance_applies_to_the_newly_visible_dialect(tmp_path, tolerance,
                                                        expected_rc):
    """The existing operator controls reach the entries that were invisible."""
    proj = _project(tmp_path, {"waivers": [
        _attestation("drc", "T-A"), _attestation("lvs", "T-B")]})
    rc, result = _run_json(proj, "--tolerance", str(tolerance))
    assert result["summary"]["current_root_waivers"] == 2
    assert rc == expected_rc
