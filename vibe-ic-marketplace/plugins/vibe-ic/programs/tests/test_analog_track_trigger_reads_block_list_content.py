#!/usr/bin/env python3
"""The A1..A9 / M1..M4 trigger must read the analog block list's CONTENT.

BUG (pre-fix). Every analog and mixed-signal step carries the same flow
condition:

    condition: { files_exist: ["phase1/analog/analog_block_list.json"] }

`_check_condition` satisfied that pattern on the file merely EXISTING. That
asks "did anything write a block list", which is ADJACENT to the question the
condition exists to answer, "does this design have analog blocks to process".

The two answers diverge on precisely the input the flow most wants to reward: a
Phase-1 extraction that looked for analog content, found none, and SAID SO by
writing

    {"blocks": [], "no_analog": true}

Existence-only read that as "the analog track applies". All thirteen analog /
mixed-signal steps were then expected of a design with no analog block, none
could ever produce an artefact, and each landed as MISSING — scored as work
that should have happened and did not. A digital project whose Phase 1 wrote
NOTHING got SKIPPED-CONDITION for the very same steps. The honest disclosure
was therefore scored strictly worse than silence, which inverts the incentive
the disclosure exists to create.

The module ALREADY carried a content-aware predicate
(`_has_canonical_analog_blocks`, which requires a non-empty
`blocks`/`analog_blocks`). It sat two lines below as a FALLBACK consulted only
when the file was ABSENT — never in the case it was written for. The fix makes
the primary path agree with the fallback that was already there.

DIRECTION: this NARROWS the trigger (existence -> existence AND declares >=1
block). It cannot open an analog step that used to run.

BIDIRECTIONAL NEGATIVE CONTROL — the forward cases below FAIL against the
byte-identical pre-fix file; the REVERSE cases must STILL pass after the fix,
and they are what stops this from being "tighten the filter until the count
hits zero":

  FORWARD (broken before, correct after)
    F1  empty `blocks` + `no_analog: true`      -> track stands down
    F2  empty `blocks`, no flag                 -> track stands down
    F3  end-to-end: a real digital project tree -> condition False

  REVERSE (must STILL be True after the fix — the anti-over-tighten control)
    R1  a block list naming one real block               -> still triggers
    R2  block list only at the CANONICAL dir             -> still triggers
    R3  L9 `analog_modules` with NO block list at all    -> still triggers
    R4  L5_ADI_SPEC `analog_blocks` fallback             -> still triggers
    R5  `analog_blocks` spelling instead of `blocks`     -> still triggers
    R6  blocks named AND a contradicting `no_analog:true` -> still triggers
        (a self-contradictory list must not silently delete the track)
    R7  UNREADABLE / malformed list                      -> still triggers
        (unreadable is not evidence of absence — fail LOUD)
    R8  a NON-analog condition pattern                   -> byte-unchanged
        existence semantics, both present and absent

chip-AGNOSTIC: synthetic generic fixtures, JSON structure only. No chip,
vendor, PDK, SKU or part-number literal anywhere in this file.
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


_COND = {"files_exist": ["phase1/analog/analog_block_list.json"]}

_ONE_BLOCK = [{"name": "blk_a", "type": "ldo", "spec": None}]


def _write(p: Path, payload) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(payload if isinstance(payload, str)
                 else json.dumps(payload))


def _fresh(tmp_path: Path, name: str) -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True, exist_ok=True)
    # `_project_is_pure_analog` and friends memoize on the resolved path;
    # a per-case directory keeps the cases independent.
    F._PURE_ANALOG_CACHE.pop(str(proj.resolve()), None)
    return proj


# ───────────────────────────── FORWARD (the bug) ───────────────────────────

def test_F1_empty_blocks_with_no_analog_flag_stands_the_track_down(tmp_path):
    """The exact honest Phase-1 disclosure. Pre-fix this returned True."""
    proj = _fresh(tmp_path, "f1")
    _write(proj / "phase3/analog/analog_block_list.json",
           {"blocks": [], "no_analog": True})
    assert F._check_condition(proj, _COND) is False


def test_F2_empty_blocks_without_a_flag_stands_the_track_down(tmp_path):
    proj = _fresh(tmp_path, "f2")
    _write(proj / "phase3/analog/analog_block_list.json", {"blocks": []})
    assert F._check_condition(proj, _COND) is False


def test_F3_digital_project_tree_end_to_end(tmp_path):
    """A digital project that ALSO carries L-docs positively recording no
    analog. Every signal in the tree says 'no analog'; pre-fix the condition
    still said the analog track applies."""
    proj = _fresh(tmp_path, "f3")
    _write(proj / "phase2/stage1/rtl/top.v", "module top(); endmodule\n")
    _write(proj / "phase3/analog/analog_block_list.json",
           {"blocks": [], "no_analog": True})
    _write(proj / "phase1/generated_docs/L5_ADI_SPEC.json",
           {"applicability": "NOT_APPLICABLE", "analog_blocks": [],
            "no_analog": True, "analog_blocks_detected": False})
    _write(proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
           {"analog_modules": []})
    assert F._check_condition(proj, _COND) is False


# ─────────── REVERSE (must STILL pass — the anti-over-tighten control) ──────

def test_R1_a_named_block_still_triggers_the_track(tmp_path):
    proj = _fresh(tmp_path, "r1")
    _write(proj / "phase3/analog/analog_block_list.json",
           {"blocks": _ONE_BLOCK})
    assert F._check_condition(proj, _COND) is True


def test_R2_block_list_at_the_literal_declared_path_still_triggers(tmp_path):
    """The condition pins `phase1/analog/`; a list actually written THERE with
    real blocks must still trigger. This is the case a naive content check
    keyed only on the canonical dir would have silently dropped."""
    proj = _fresh(tmp_path, "r2")
    _write(proj / "phase1/analog/analog_block_list.json",
           {"blocks": _ONE_BLOCK})
    assert F._check_condition(proj, _COND) is True


def test_R3_l9_analog_modules_with_no_block_list_still_triggers(tmp_path):
    proj = _fresh(tmp_path, "r3")
    _write(proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
           {"analog_modules": [{"name": "blk_a"}]})
    assert F._check_condition(proj, _COND) is True


def test_R4_l5_adi_spec_fallback_still_triggers(tmp_path):
    proj = _fresh(tmp_path, "r4")
    _write(proj / "phase1/generated_docs/L5_ADI_SPEC.json",
           {"analog_blocks": [{"name": "blk_a"}]})
    assert F._check_condition(proj, _COND) is True


def test_R5_analog_blocks_spelling_still_triggers(tmp_path):
    proj = _fresh(tmp_path, "r5")
    _write(proj / "phase3/analog/analog_block_list.json",
           {"analog_blocks": _ONE_BLOCK})
    assert F._check_condition(proj, _COND) is True


def test_R6_named_block_beats_a_contradicting_no_analog_flag(tmp_path):
    """Self-contradictory input is a Phase-1 defect. The non-suppressive
    reading keeps the track running so somebody has to look at it."""
    proj = _fresh(tmp_path, "r6")
    _write(proj / "phase3/analog/analog_block_list.json",
           {"blocks": _ONE_BLOCK, "no_analog": True})
    assert F._check_condition(proj, _COND) is True


@pytest.mark.parametrize("payload", [
    "{ this is not json",                 # unparseable
    "[]",                                 # parses, but not an object
    '{"note": "no blocks key at all"}',   # object, but not the judged shape
])
def test_R7_unreadable_or_unjudgeable_list_still_triggers(tmp_path, payload):
    """Unreadable is NOT evidence of absence. A corrupt or truncated block
    list must never silently delete thirteen steps."""
    proj = _fresh(tmp_path, "r7" + str(abs(hash(payload)) % 9973))
    _write(proj / "phase3/analog/analog_block_list.json", payload)
    assert F._check_condition(proj, _COND) is True


def test_R8_non_analog_condition_keeps_pure_existence_semantics(tmp_path):
    """Every other `files_exist` condition in the flow must be byte-unchanged:
    present -> True, absent -> False, decided on existence alone."""
    proj = _fresh(tmp_path, "r8")
    cond = {"files_exist": ["phase2/stage2/dft/cut_netlist.v"]}
    assert F._check_condition(proj, cond) is False
    _write(proj / "phase2/stage2/dft/cut_netlist.v", "module m(); endmodule\n")
    assert F._check_condition(proj, cond) is True


def test_R8b_any_of_condition_keeps_pure_existence_semantics(tmp_path):
    """The `any_of` form (used by the at-speed ATPG steps, whose triggers
    include their own *_not_run.json self-report) must be unchanged too."""
    proj = _fresh(tmp_path, "r8b")
    cond = {"any_of": True, "files_exist": [
        "phase2/stage2/dft/cut_netlist.v",
        "phase2/stage2/dft/transition_atpg_not_run.json",
    ]}
    assert F._check_condition(proj, cond) is False
    _write(proj / "phase2/stage2/dft/transition_atpg_not_run.json",
           {"verdict": "SKIPPED-CONDITION"})
    assert F._check_condition(proj, cond) is True


def test_R9_empty_condition_is_unchanged(tmp_path):
    proj = _fresh(tmp_path, "r9")
    assert F._check_condition(proj, {}) is True
    assert F._check_condition(proj, None) is True
