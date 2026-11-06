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

from _published_corpus import corpus_root, needs_corpus  # noqa: E402


GOOD_REASON = ("LVS deck requires a SPICE-extracted netlist that this "
               "environment cannot produce; deferred to foundry sign-off.")


def _write(project: Path, doc) -> Path:
    p = project / "waivers.json"
    p.write_text(json.dumps(doc))
    return p




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
    assert analog_netlist_pdk_check._pdk_mismatch_waived(tmp_path) is False

    monkeypatch.setattr(
        _we, "entries",
        lambda data: [crc_waiver, pdk_waiver, step_waiver])

    # Every consumer's verdict now follows the shared reader.
    assert analog_netlist_pdk_check._pdk_mismatch_waived(tmp_path) is True


def test_schema_check_and_flow_compliance_share_one_step_name_map():
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




# ----------------------------------------------------------------------
# The legitimate early return SURVIVES, narrowed
# ----------------------------------------------------------------------







# ----------------------------------------------------------------------
# Role names are many-to-one onto flow steps
# ----------------------------------------------------------------------







# ----------------------------------------------------------------------
# approved_at — a human signature, whose absence is SAID, never fabricated
# ----------------------------------------------------------------------











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

    # the sanctioned approver and the open review survive — the entry is a
    # deferral awaiting a human, which is the whole point of withholding the date

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
