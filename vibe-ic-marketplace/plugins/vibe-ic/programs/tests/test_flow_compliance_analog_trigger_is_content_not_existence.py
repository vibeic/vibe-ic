#!/usr/bin/env python3
"""Regression — the analog-track trigger must be decided on the block list's
CONTENT, not on the block list FILE's existence.

Bug
---
The analog stage and every A1..A9 / M1..M4 step declare the same trigger:

    condition:
      files_exist: ["phase1/analog/analog_block_list.json"]

`_check_condition` satisfied that trigger with a bare `_glob_first` existence
probe. But every producer emits a block list UNCONDITIONALLY, and on a
digital-only project the emitted list reads:

    {"blocks": [], "no_analog": true}

— an explicit statement that the design has NO analog blocks. Existence is
ADJACENT to the question the condition asks ("does this design have analog
blocks?"), not an answer to it, so the trigger fired on the very artefact that
declares it must not. Every analog step was then held applicable and reported
MISSING — "analog work NOT DONE" — on a project with no analog work TO do.

Two further details made it unreachable rather than merely wrong:

  * `_glob_first` itself remaps `phase{1,2}/analog/<tail>` onto the canonical
    analog dir. The condition pins `phase1/analog/...`, the runners write
    `phase3/analog/...`, so the pinned path HIT via the remap.
  * A content-aware predicate (`_has_canonical_analog_blocks`, which requires
    `len(blocks) > 0`) already existed — but only in the fallback branch taken
    when the existence probe MISSES. Because the remap made it hit, the
    content-aware predicate was never consulted.

The A-step gates already used the content contract: `analog_a1..a9_*_check`
each VACUOUS_PASS when the block list is "missing OR EMPTY (digital-only
project)". So the gates and the flow disagreed about the same project.

Fix
---
Decide an `analog_block_list` trigger with `_analog_block_list_declares_blocks`
BEFORE the existence probe. Skip the track only on an AFFIRMATIVE declaration
of none (`no_analog: true`, or a present-and-empty `blocks`/`analog_blocks`).

NEG cases (load-bearing — the fix must not be a tightened filter)
-----------------------------------------------------------------
  * NEG-1  a list with one block STILL triggers the track.
  * NEG-2  the alternate `analog_blocks` key STILL triggers the track.
  * NEG-3  a list carrying neither array STILL triggers (fail-OPEN).
  * NEG-4  an UNPARSEABLE list STILL triggers (fail-OPEN) — a corrupt trigger
           must surface as a real verdict, never as a silent skip.
  * NEG-5  no list at all is unchanged: the track does not trigger.
  * NEG-6  a non-analog `files_exist` condition is byte-unchanged in both
           directions (the new branch is scoped to analog triggers only).

chip-AGNOSTIC: synthetic generic fixtures only; the predicate reads only the
structural `blocks` / `analog_blocks` arrays and the `no_analog` flag — never
a chip, vendor, SKU, process-node or PDK literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as F  # noqa: E402


# The trigger exactly as phase1_phase2_phase3.yaml declares it for
# stage_analog, stage_mixed_signal and every A1..A9 / M1..M4 step.
_ANALOG_COND = {"files_exist": ["phase1/analog/analog_block_list.json"]}


def _project(tmp_path: Path, payload) -> Path:
    """A project whose ONLY analog evidence is `payload`, written at the
    canonical analog dir the runners actually use."""
    root = tmp_path / "proj"
    (root / "phase3" / "analog").mkdir(parents=True)
    if payload is not None:
        f = root / "phase3" / "analog" / "analog_block_list.json"
        f.write_text(payload if isinstance(payload, str)
                     else json.dumps(payload))
    return root


# ───────────────────────────── the defect ──────────────────────────────────

@pytest.mark.parametrize("payload", [
    {"blocks": [], "no_analog": True},   # what the digital-only emitters write
    {"blocks": []},                      # empty array, no flag
    {"analog_blocks": [], "no_analog": True},
])
def test_digital_only_block_list_does_not_trigger_analog_track(
        tmp_path, payload):
    """A block list that AFFIRMATIVELY declares no analog blocks must not
    trigger the analog track.

    Pre-fix this returns True — the existence probe fires on the very file
    that says there is nothing to do — and every A/M step lands MISSING.
    """
    root = _project(tmp_path, payload)
    assert F._check_condition(root, _ANALOG_COND) is False, (
        "a block list declaring NO analog blocks triggered the analog track; "
        "the trigger read the file's existence, not its content"
    )


# ───────────────────── NEG — the track must still fire ─────────────────────

@pytest.mark.parametrize("payload", [
    pytest.param({"blocks": [{"name": "blk_a"}]}, id="NEG-1-one-block"),
    pytest.param({"analog_blocks": [{"name": "blk_a"}]}, id="NEG-2-alt-key"),
    pytest.param({"note": "no array here"}, id="NEG-3-no-array-fail-open"),
    pytest.param("{ not json at all", id="NEG-4-unparseable-fail-open"),
])
def test_analog_track_still_triggers(tmp_path, payload):
    """The fix must not be a filter tightened until the count hit zero: a real
    analog project, and every ambiguous payload, must STILL run the track."""
    root = _project(tmp_path, payload)
    assert F._check_condition(root, _ANALOG_COND) is True, (
        "the analog track stopped triggering for a project that needs it"
    )


def test_absent_block_list_unchanged(tmp_path):
    """NEG-5 — with no block list and no L5/L9 analog evidence the track does
    not trigger. Byte-identical to pre-fix behaviour."""
    root = _project(tmp_path, None)
    assert F._check_condition(root, _ANALOG_COND) is False


# ───────────── NEG-6 — non-analog conditions must not be touched ───────────

def test_non_analog_condition_is_unchanged(tmp_path):
    """The new branch is scoped to analog triggers; an ordinary `files_exist`
    condition keeps pure existence semantics in both directions."""
    root = tmp_path / "p2"
    (root / "sub").mkdir(parents=True)
    cond = {"files_exist": ["sub/marker.json"]}

    assert F._check_condition(root, cond) is False      # absent -> no run
    (root / "sub" / "marker.json").write_text("{}")
    assert F._check_condition(root, cond) is True       # present -> run
    # content is irrelevant for a non-analog trigger, exactly as before
    (root / "sub" / "marker.json").write_text('{"blocks": []}')
    assert F._check_condition(root, cond) is True


# ─────────────── the predicate itself, stated independently ────────────────

@pytest.mark.parametrize("payload,expected", [
    ({"blocks": [{"name": "a"}]}, True),
    ({"analog_blocks": [{"name": "a"}]}, True),
    ({"blocks": [], "no_analog": True}, False),
    ({"blocks": []}, False),
    ({"no_analog": True}, False),
    ({"unrelated": 1}, True),          # fail-open
    ("not json", True),                # fail-open
    ([1, 2, 3], True),                 # non-object payload -> fail-open
])
def test_predicate_polarity(tmp_path, payload, expected):
    root = _project(tmp_path, payload)
    got = F._analog_block_list_declares_blocks(
        root, "phase1/analog/analog_block_list.json")
    assert got is expected
