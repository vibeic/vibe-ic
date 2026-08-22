"""#519 — the waiver entry list has ONE reader, and it reads BOTH keys.

`waivers_schema_check` exists to stop rubber-stamp waivers passing through. It
read `waived_steps` and returned OK the moment that key was absent, so a
waivers.json written by `phase3_one_shot_runner` — which emits `waivers` — was
reported as "Waiver count: 0", exit 0, with its entries never examined. Six of
eleven tracked waiver files and 8 of 19 entries were invisible.

Those 8 turned out NOT to be rubber stamps. They are written in a second,
sanctioned dialect whose approval model is an evidence-gated attestation
(`step` + `rationale` + `ticket` + `review_required` + `evidence`) rather than
a named human, and `flow_compliance_check` both re-checks that contract before
honouring such an entry and SUPPLIES the tier approver when one is absent. So
the fix is to validate each entry against the dialect it is written in — and
the severities differ, because `waived_steps` entries are applied with no other
gate while `waivers` entries pass a stricter, fail-safe one at the point of use.

The tests below pin, by EXECUTION:
  * the shared reader is genuinely shared — each consumer's behaviour follows
    `_waiver_entries`, rather than each holding a private copy that happens to
    agree today;
  * the legitimate early return SURVIVES, narrowed to "neither key holds
    entries" (a project may carry a waivers.json of only per-gate scalar keys);
  * each dialect is held to its own approval contract, and neither dialect's
    findings can take down the other's report;
  * `drc` and `lvs` both resolving to Step 31 is not a false duplicate;
  * `approved_at`'s absence is reported rather than silently un-aged, and is
    never fabricated by a writer.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _waiver_entries as _we  # noqa: E402
import waivers_schema_check as wsc  # noqa: E402
import waiver_staleness_check as wsl  # noqa: E402

from _published_corpus import corpus_root, needs_corpus  # noqa: E402

SCRIPT = PROGRAMS / "waivers_schema_check.py"

GOOD_REASON = ("LVS deck requires a SPICE-extracted netlist that this "
               "environment cannot produce; deferred to foundry sign-off.")


def _write(project: Path, doc) -> Path:
    p = project / "waivers.json"
    p.write_text(json.dumps(doc))
    return p


def _run(project: Path):
    return subprocess.run([sys.executable, str(SCRIPT), str(project)],
                          capture_output=True, text=True)


# ----------------------------------------------------------------------
# The shared reader is ONE reader
# ----------------------------------------------------------------------

def test_both_canonical_keys_are_read_as_a_union():
    doc = {"waived_steps": [{"id": 1}], "waivers": [{"step": "lvs"}]}
    assert _we.entries(doc) == [{"id": 1}, {"step": "lvs"}]
    assert _we.has_entries(doc)
    # order is documented and load-bearing: waived_steps first, so a consumer
    # that stops at the first match keeps the precedence it already had.
    assert list(_we.entries_by_key(doc)) == ["waived_steps", "waivers"]


def test_consumers_follow_the_shared_reader_not_a_private_copy(
        tmp_path, monkeypatch):
    """Identity by EXECUTION: bend the shared reader, and every consumer's
    ANSWER bends with it.

    This must drive each consumer's real entry point and read its observable
    result. Asserting that the monkeypatch took effect on `_we` would measure
    nothing about the consumers — a gate holding a private copy of the union
    would sail through such an assertion, which is exactly how the original
    copies drifted apart unnoticed.
    """
    import clock_plan_check
    import crc_engine_isolation_check
    import analog_netlist_pdk_check

    # An empty file on disk: every answer below must come from the reader,
    # never from the bytes, so a private read cannot supply it.
    _write(tmp_path, {})

    crc_waiver = {"name": "crc_byte_intentionally_constant",
                  "reason": "held constant by design; " + "x" * 40}
    pdk_waiver = {"rule": "PDK_MISMATCH", "reason": GOOD_REASON}
    step_waiver = {"id": "clock_plan", "reason": GOOD_REASON,
                   "ticket": "OPS-1"}

    # Baseline: with the real reader, the empty document grants nothing.
    assert crc_engine_isolation_check._load_waiver(tmp_path) is False
    assert analog_netlist_pdk_check._pdk_mismatch_waived(tmp_path) is False
    assert clock_plan_check._step_waived(tmp_path, "clock_plan") is None

    monkeypatch.setattr(
        _we, "entries",
        lambda data: [crc_waiver, pdk_waiver, step_waiver])

    # Every consumer's verdict now follows the shared reader.
    assert crc_engine_isolation_check._load_waiver(tmp_path) is True
    assert analog_netlist_pdk_check._pdk_mismatch_waived(tmp_path) is True
    assert clock_plan_check._step_waived(tmp_path, "clock_plan") == step_waiver


def test_schema_check_and_flow_compliance_share_one_step_name_map():
    import flow_compliance_check as fcc
    assert fcc._ENV_UNAVAILABLE_STEP_NAME_TO_ID is _we.STEP_NAME_TO_ID
    assert _we.resolve_step_name("lvs") == 31
    assert _we.resolve_step_name("LVS  ") == 31
    assert _we.resolve_step_name("not_a_real_step") is None


# ----------------------------------------------------------------------
# The defect: entries under `waivers` were never examined
# ----------------------------------------------------------------------

_ATTESTED = {
    "step": "lvs", "phase": "3", "verdict_tier": "ENV_UNAVAILABLE",
    "rationale": GOOD_REASON, "ticket": "TAPEOUT-AUTOGEN-LVS",
    "review_required": True,
    "evidence": ["reports/orchestrator/phase3_one_shot.json#steps[name=lvs]"],
    "_autogen": True,
}


def test_waivers_key_entry_is_counted_and_examined(tmp_path):
    """The defect proper: an entry under `waivers` used to be invisible, and
    the file reported `Waiver count: 0`."""
    _write(tmp_path, {"_schema_version": "1", "waivers": [dict(_ATTESTED)]})
    findings, summary = wsc.validate(tmp_path)
    assert summary["waiver_count"] == 1
    assert summary["waiver_count_by_key"] == {"waivers": 1}
    # a COMPLETE attestation is valid: this dialect substitutes an
    # evidence gate for a human signature, and this entry passes it.
    assert [f for f in findings if f.severity == "error"] == []


def test_missing_approver_is_not_an_error_in_the_attestation_dialect(tmp_path):
    """`flow_compliance_check` supplies the tier approver for these entries
    (`w.get("approver", "field-agent-attest (ENV_UNAVAILABLE tier)")`), so the
    absence of `approver` is the dialect's design. Demanding one here would
    fail every waiver the runner has ever emitted."""
    _write(tmp_path, {"waivers": [dict(_ATTESTED)]})
    findings, _ = wsc.validate(tmp_path)
    assert "approver-missing" not in {f.rule for f in findings}


def test_waived_steps_dialect_still_requires_a_human_approver(tmp_path):
    """The asymmetry is the point: nothing else gates this dialect."""
    _write(tmp_path, {"waived_steps": [{
        "id": 31, "reason": GOOD_REASON, "ticket": "OPS-1",
        "review_required": True,
    }]})
    findings, _ = wsc.validate(tmp_path)
    assert "approver-missing" in {
        f.rule for f in findings if f.severity == "error"}
    assert _run(tmp_path).returncode == 1


@pytest.mark.parametrize("drop,rule", [
    ("ticket", "attestation-ticket-missing"),
    ("evidence", "attestation-evidence-missing"),
    ("review_required", "attestation-review-not-required"),
])
def test_incomplete_attestation_is_reported(tmp_path, drop, rule):
    entry = dict(_ATTESTED)
    entry.pop(drop)
    _write(tmp_path, {"waivers": [entry]})
    findings, _ = wsc.validate(tmp_path)
    assert rule in {f.rule for f in findings}


def test_attestation_findings_do_not_kill_the_compliance_report(tmp_path):
    """Severity is load-bearing. `flow_compliance_check` turns any schema ERROR
    into SystemExit(1); an incomplete attestation must stay a WARNING so that
    caller can keep its #216 behaviour — refuse the waiver, name the missing
    field, let the step fail on its own merits, and still emit a report."""
    entry = dict(_ATTESTED)
    entry.pop("evidence")
    entry["rationale"] = "env gap"          # also too short
    _write(tmp_path, {"waivers": [entry]})
    findings, _ = wsc.validate(tmp_path)
    assert [f for f in findings if f.severity == "error"] == []
    assert {"attestation-evidence-missing", "reason-too-short"} <= {
        f.rule for f in findings}
    assert _run(tmp_path).returncode == 0


def test_a_self_approver_is_an_error_in_BOTH_dialects(tmp_path):
    """`approver` is OPTIONAL in the attestation dialect but is APPLIED when
    present, so nothing else guards it and it stays an error."""
    entry = dict(_ATTESTED)
    entry["approver"] = "claude"
    _write(tmp_path, {"waivers": [entry]})
    findings, _ = wsc.validate(tmp_path)
    assert "approver-self" in {
        f.rule for f in findings if f.severity == "error"}


def test_role_resolved_id_is_not_range_checked_against_max_step():
    """A role name resolving PAST `max_step` must still be accepted.

    The canonical map is the source of truth for which step a role names, and
    it legitimately reaches beyond this program's default `max_step` of 40 —
    `htol` binds to Step 44. Range-checking a resolved id rejected that correct
    waiver as out-of-range, and because `flow_compliance_check` turns any schema
    error into SystemExit(1), it killed the whole compliance run for any project
    deferring that step. Caught by test_matrix_d6_skip_discipline[step44].
    """
    over = {name: sid for name, sid in _we.STEP_NAME_TO_ID.items()
            if isinstance(sid, int) and sid > 40}
    assert over, ("no role in the map exceeds max_step=40 any more — this "
                  "regression can no longer be expressed; re-pin it against "
                  "whatever the new out-of-range role is, or drop the test "
                  "deliberately rather than letting it pass vacuously")
    for name in over:
        entry = {**_ATTESTED, "step": name}
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            _write(proj, {"waivers": [entry]})
            findings, summary = wsc.validate(proj)
            assert summary["waiver_count"] == 1
            assert [f for f in findings if f.severity == "error"] == [], (
                f"role {name!r} -> step {over[name]} was rejected")


def test_unknown_role_name_is_reported_not_silently_passed(tmp_path):
    entry = dict(_ATTESTED)
    entry["step"] = "no_such_step"
    _write(tmp_path, {"waivers": [entry]})
    findings, _ = wsc.validate(tmp_path)
    assert "step-name-unknown" in {f.rule for f in findings}


# ----------------------------------------------------------------------
# The legitimate early return SURVIVES, narrowed
# ----------------------------------------------------------------------

def test_file_with_only_per_gate_keys_still_passes(tmp_path):
    """The v0.119.21 behaviour this fix must NOT break: a project may carry a
    waivers.json holding only per-gate scalar waivers and no flow-step waivers
    at all, and must not be rejected for lacking an empty array."""
    _write(tmp_path, {"frame_end_idle_reset_alternative": "documented in L8",
                      "otp_field_map_unresolved": ["FIELD_A"]})
    findings, summary = wsc.validate(tmp_path)
    assert findings == []
    assert summary["waiver_count"] == 0
    assert _run(tmp_path).returncode == 0


@pytest.mark.parametrize("doc", [
    {"waivers": [], "waived_steps": []},
    {"waived_steps": []},
    {"waivers": []},
    {"_schema_version": "1"},
])
def test_no_entries_under_either_key_is_a_pass(tmp_path, doc):
    _write(tmp_path, doc)
    findings, summary = wsc.validate(tmp_path)
    assert findings == []
    assert summary["waiver_count"] == 0


@pytest.mark.parametrize("key", ["waived_steps", "waivers"])
def test_present_but_non_list_key_is_still_rejected(tmp_path, key):
    """A malformed key must not fall through the no-entries early return."""
    _write(tmp_path, {key: "not-a-list"})
    findings, _ = wsc.validate(tmp_path)
    assert {f.rule for f in findings if f.severity == "error"} == {
        "waived-steps-type"}


# ----------------------------------------------------------------------
# Role names are many-to-one onto flow steps
# ----------------------------------------------------------------------

def test_drc_and_lvs_are_not_a_false_duplicate(tmp_path):
    """Step 31 is "Physical Verification (DRC + LVS + ERC + Density)", so both
    role names resolve to 31. Deduplicating on the resolved id would call the
    shape the runner actually emits a double-waive."""
    _write(tmp_path, {"waivers": [
        {**_ATTESTED, "step": "drc"}, {**_ATTESTED, "step": "lvs"},
    ]})
    findings, _ = wsc.validate(tmp_path)
    assert [f for f in findings if f.severity == "error"] == []


def test_the_same_role_twice_is_still_a_duplicate(tmp_path):
    _write(tmp_path, {"waivers": [
        {**_ATTESTED, "step": "lvs"}, {**_ATTESTED, "step": "LVS"},
    ]})
    findings, _ = wsc.validate(tmp_path)
    assert {f.rule for f in findings if f.severity == "error"} == {
        "id-duplicate"}


def test_numeric_id_duplicate_detection_is_unchanged(tmp_path):
    _write(tmp_path, {"waived_steps": [
        {"id": 39, "reason": GOOD_REASON, "approver": "a-human",
         "review_required": True, "approved_at": "2026-07-01"},
        {"id": "step_39_fpga", "reason": GOOD_REASON, "approver": "a-human",
         "review_required": True, "approved_at": "2026-07-01"},
    ]})
    findings, _ = wsc.validate(tmp_path)
    assert {f.rule for f in findings if f.severity == "error"} == {
        "id-duplicate"}


# ----------------------------------------------------------------------
# approved_at — a human signature, whose absence is SAID, never fabricated
# ----------------------------------------------------------------------

def test_missing_approved_at_warns_but_does_not_fail(tmp_path):
    _write(tmp_path, {"waived_steps": [{
        "id": 6, "reason": GOOD_REASON, "approver": "a-human",
        "ticket": "OPS-1", "review_required": True,
    }]})
    findings, _ = wsc.validate(tmp_path)
    warns = {f.rule for f in findings if f.severity == "warning"}
    assert "approved-at-missing" in warns
    assert [f for f in findings if f.severity == "error"] == []
    assert _run(tmp_path).returncode == 0


def test_present_approved_at_produces_no_warning(tmp_path):
    _write(tmp_path, {"waived_steps": [{
        "id": 6, "reason": GOOD_REASON, "approver": "a-human",
        "ticket": "OPS-1", "review_required": True,
        "approved_at": "2026-07-01",
    }]})
    findings, _ = wsc.validate(tmp_path)
    assert "approved-at-missing" not in {f.rule for f in findings}


def test_staleness_names_the_population_it_could_not_age(tmp_path):
    """The skip is correct — an autogen waiver legitimately has no human
    signature — but it must SAY so rather than reporting nothing."""
    _write(tmp_path, {"waivers": [
        {**_ATTESTED, "step": "lvs"}, {**_ATTESTED, "step": "drc"},
    ]})
    findings, summary = wsl.inspect(tmp_path)
    assert findings == []
    assert summary["entries_total"] == 2
    assert summary["entries_unageable"] == 2
    assert summary["entries_examined"] == 0
    assert "could be aged" in summary["skipped_reason"]
    assert "2 of 2" in summary["skipped_reason"]


def test_staleness_reads_entries_under_both_keys(tmp_path):
    """First-list-wins dropped whichever key it did not reach first."""
    _write(tmp_path, {
        "waived_steps": [{"id": 1, "approved_at": "2000-01-01",
                          "reason": GOOD_REASON}],
        "waivers": [{"step": "lvs", "approved_at": "2000-01-01",
                     "rationale": GOOD_REASON}],
    })
    findings, summary = wsl.inspect(tmp_path)
    assert summary["entries_total"] == 2
    assert summary["entries_examined"] == 2
    assert len(summary["stale_err"]) == 2


def test_generated_waivers_carry_no_fabricated_approved_at(tmp_path):
    """#519 decided `approved_at` is a HUMAN signature.

    A machine-written approval date would readmit through the time field
    exactly the self-approval the `approver` field bars, and would start an
    aging clock on an approval nobody gave — converting an unreviewed waiver
    into one that merely looks young. Driven by EXECUTION: build a real
    materialized entry and a real runner-autogen entry and inspect the
    products, because a source-text search for `"approved_at":` misses every
    other spelling a writer could use to introduce one.
    """
    import waivers_materialize

    entry = waivers_materialize._to_entry(
        {"id": 6, "reason": GOOD_REASON, "approver": "field-agent-attest"},
        tmp_path)
    assert "approved_at" not in entry, (
        "waivers_materialize stamped an approval date nobody gave")
    # the sanctioned approver and the open review survive — the entry is a
    # deferral awaiting a human, which is the whole point of withholding the date
    assert entry["review_required"] is True

    # ...and no waiver file the flow has ever produced carries one either.
    for path, doc in _tracked_waiver_docs():
        for e in _we.dict_entries(doc):
            assert "approved_at" not in e, (
                f"{path} carries a machine-written approved_at")


def _tracked_waiver_docs():
    """Every waivers.json in the published corpus, as (path, parsed) pairs.

    Empty when there is no corpus to read. Locating it is `_published_corpus`'s
    job, not a private walk up the tree: the walk answered "is there a
    `benchmark-data/` directory?", which this checkout still satisfies with the
    design INPUTS after the result cells moved to vibeic/benchmark-data — so it
    returned a root holding no waiver at all, and the sweep below then read as a
    defect rather than as "I could not look".
    """
    root = corpus_root()
    if root is None:
        return []
    out = []
    for p in sorted(root.glob("**/waivers.json")):
        try:
            out.append((p, json.loads(p.read_text())))
        except (OSError, ValueError):
            continue
    return out


@needs_corpus
def test_every_tracked_waiver_file_is_actually_examined():
    """The corpus-level statement of the defect: no tracked waiver file may
    report a waiver_count of 0 while holding entries.

    The `assert docs` below stays exactly as strict: with a corpus present, a
    sweep that examined nothing is still a defect. It is only when there is no
    corpus at all that this reports SKIP instead of FAIL.
    """
    docs = _tracked_waiver_docs()
    assert docs, "corpus root exists but holds no waivers.json — probe is vacuous"
    for path, doc in docs:
        held = len(_we.entries(doc))
        _, summary = wsc.validate(path.parent)
        assert summary["waiver_count"] == held, (
            f"{path}: holds {held} entr(ies) but the validator counted "
            f"{summary['waiver_count']}")
