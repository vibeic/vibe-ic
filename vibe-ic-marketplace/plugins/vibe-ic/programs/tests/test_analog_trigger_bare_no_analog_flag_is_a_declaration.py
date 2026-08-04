#!/usr/bin/env python3
"""Regression — a BARE ``{"no_analog": true}`` block list is a DECLARATION of
no analog, not an unjudgeable shape.

WHAT THIS FILE IS, AFTER THE REBASE
-----------------------------------
This started life as the whole of PR #808 ("decide the analog-track trigger on
block-list CONTENT, not file existence"). While it was open, #845 landed the
SAME subject — `f4ad9c5a` moved the trigger from existence to content via
`_condition_pattern_satisfied` / `_analog_block_list_declares_blocks`, and
`e3b1ae49` added the two-root undecidable probe and the one-way ceiling. Main
now covers, parametrised over BOTH reachable roots and with a 4096-tree payload
grid, everything the original file asserted EXCEPT one payload — so all of it
was deleted rather than carried as a duplicate. Measured, not assumed: the
original file's 17 cases were re-run against the landed main and every
`_check_condition`-level assertion passed at both roots. Its 8 failures were
all `TypeError` from calling `_analog_block_list_declares_blocks(project, pat)`
against main's `(path)` signature — a signature artefact, not a behaviour gap,
so re-asserting them here would have proved nothing.

THE ONE PAYLOAD MAIN STILL GETS WRONG
-------------------------------------
`_analog_block_list_declares_blocks` decided everything on the block ARRAY:

    blocks = d.get("blocks") or d.get("analog_blocks")
    if not isinstance(blocks, list):
        return None          # "not the shape we can judge" -> track RUNS

so a list carrying the flag and no array —

    {"no_analog": true}

— fell into the undecidable bucket and TRIGGERED all thirteen A1..A9 / M1..M4
steps. But that is not an unknown shape; it is the most explicit affirmative
declaration of "this design has no analog blocks" the schema has. The
emitters' own A-step gates already stand down on it —
`_analog_a_check_common.load_block_list` yields `[]` for a list with no
`blocks` key, and every `analog_a1..a9_*_check` then VACUOUS_PASSes with "no
analog blocks declared". So for the flag-only form the flow held thirteen
steps applicable that every gate certifies as INAPPLICABLE, and each landed
MISSING — the exact gate-vs-flow disagreement, and the exact
disclosure-scored-worse-than-silence inversion, that #845 was written to end.
The array form `{"blocks": [], "no_analog": true}` was fixed; the flag-only
form was not.

FIX, AND ITS SCOPE
------------------
The flag decides ONLY when NEITHER block key is present. A block array that is
present but MALFORMED (`{"blocks": "oops", "no_analog": true}`) CONTRADICTS the
flag, and a self-contradictory list stays undecidable so somebody has to look
at it — the same polarity as main's existing named-block-beats-the-flag rule.
Direction is still strictly NARROWING, and `_condition_pattern_satisfied`'s
one-way ceiling (`pre_fix_satisfied` computed first) is untouched, so this can
stand a track down and can never open one.

CASES
-----
FORWARD (fails on the rebased base, passes after — all assert an OBSERVED
boolean; no case turns on a symbol this change introduces, because it
introduces none):
  F1  bare `{"no_analog": true}`, at each reachable root  -> stands down
  F2  the same at the predicate, at each reachable root   -> False, not None
  F3  bare flag at one reachable root + a parseably-empty list at the other,
      in BOTH root orders                                 -> stands down

FAIL-LOUD GUARDS (green in BOTH directions — the fix is a scoped refinement,
not a filter tightened until the count reached zero):
  G1  an object with no block key AND no flag             -> still triggers
  G2  `no_analog: false`                                  -> still triggers
  G3  unparseable / non-object                            -> still triggers
  G4  a MALFORMED block array contradicting the flag      -> still triggers
  G5  a NAMED block contradicting the flag                -> still triggers
  G6  bare flag at one root, UNJUDGEABLE at the other, in BOTH root orders
      -> still triggers (e3b1ae49's fail-loud restoration must survive)
  G7  no list at all                                      -> unchanged
  G8  a non-analog `files_exist` condition                -> unchanged

chip-AGNOSTIC: synthetic generic fixtures, JSON structure only. No chip,
vendor, PDK, SKU, node or part-number literal anywhere in this file.
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
_COND = {"files_exist": ["phase1/analog/analog_block_list.json"]}

_LIST = "analog_block_list.json"

# The roots `_glob_first` can resolve that pattern at: the one the flow-def
# literally pins, and the canonical analog root it remaps to. Every one-root
# case below is parametrised over BOTH — a fixture that only ever writes to
# one of them cannot see a defect living in the hand-off between them.
_REACHABLE = ["phase1/analog", "phase3/analog"]

# The bare flag: the affirmative declaration with no block array beside it.
_BARE_FLAG = {"no_analog": True}

# Present but genuinely impossible to judge — these must keep the track
# running, before and after.
_UNJUDGEABLE = [
    "{ this is not json",                # unparseable
    "[]",                                # parses, but not an object
    '{"note": "no block key at all"}',   # object, not the judged shape
]


def _fresh(tmp_path: Path, name: str) -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True, exist_ok=True)
    # `_project_is_pure_analog` and friends memoize on the resolved path; a
    # per-case directory keeps the cases independent.
    F._PURE_ANALOG_CACHE.pop(str(proj.resolve()), None)
    return proj


def _write(p: Path, payload) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload))


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s)[:40]


# ─────────────────────────── FORWARD (the defect) ──────────────────────────

@pytest.mark.parametrize("root", _REACHABLE)
def test_F1_bare_no_analog_flag_stands_the_track_down(tmp_path, root):
    """A block list whose entire content is `{"no_analog": true}` declares
    that the design has no analog blocks. The analog track must not trigger.

    Pre-fix this returns True: with no block ARRAY the payload fell into the
    undecidable bucket, so thirteen A/M steps were held applicable on the very
    artefact declaring there is nothing to do, and each landed MISSING.
    """
    proj = _fresh(tmp_path, f"f1_{_slug(root)}")
    _write(proj / root / _LIST, _BARE_FLAG)
    assert F._check_condition(proj, _COND) is False, (
        f"a bare no_analog:true block list at {root}/ triggered the analog "
        f"track; an affirmative declaration of none was read as an "
        f"unjudgeable shape"
    )


@pytest.mark.parametrize("root", _REACHABLE)
def test_F2_predicate_reads_the_bare_flag_as_a_declaration(tmp_path, root):
    """The predicate itself must answer False (parseably declares none), not
    None (undecidable). Stated separately from F1 so a future caller-side
    change cannot make the polarity look right for the wrong reason."""
    proj = _fresh(tmp_path, f"f2_{_slug(root)}")
    path = proj / root / _LIST
    _write(path, _BARE_FLAG)
    assert F._analog_block_list_declares_blocks(path) is False


@pytest.mark.parametrize("flag_root,empty_root", [
    (_REACHABLE[0], _REACHABLE[1]),
    (_REACHABLE[1], _REACHABLE[0]),
])
def test_F3_bare_flag_beside_an_empty_list_stands_down(
        tmp_path, flag_root, empty_root):
    """Both reachable roots parseably declare none — one by the flag, one by
    an empty array. `_glob_first` short-circuits at whichever root it resolves
    first, and the undecidable probe then opens the sibling, so BOTH orders
    have to be driven. Pre-fix the flag-only sibling reads as undecidable and
    keeps the track running in either order."""
    proj = _fresh(tmp_path, f"f3_{_slug(flag_root)}")
    _write(proj / flag_root / _LIST, _BARE_FLAG)
    _write(proj / empty_root / _LIST, {"blocks": []})
    assert F._check_condition(proj, _COND) is False


# ───────── FAIL-LOUD GUARDS — green in BOTH directions, by design ──────────

@pytest.mark.parametrize("root", _REACHABLE)
def test_G1_no_block_key_and_no_flag_still_triggers(tmp_path, root):
    """The boundary of the change: without the flag, an object that is not
    the judged shape stays UNDECIDABLE and keeps the track running."""
    proj = _fresh(tmp_path, f"g1_{_slug(root)}")
    _write(proj / root / _LIST, {"note": "no block key at all"})
    assert F._check_condition(proj, _COND) is True


@pytest.mark.parametrize("root", _REACHABLE)
def test_G2_no_analog_false_still_triggers(tmp_path, root):
    """Only `is True` stands the track down. `no_analog: false` is a
    declaration that the design DOES have analog, and any other value is not
    a declaration at all."""
    proj = _fresh(tmp_path, f"g2_{_slug(root)}")
    _write(proj / root / _LIST, {"no_analog": False})
    assert F._check_condition(proj, _COND) is True


@pytest.mark.parametrize("root", _REACHABLE)
@pytest.mark.parametrize("payload", _UNJUDGEABLE)
def test_G3_unjudgeable_still_triggers(tmp_path, root, payload):
    """A list nobody could read is not a declaration of no analog."""
    proj = _fresh(tmp_path, f"g3_{_slug(root)}_{_slug(payload)}")
    _write(proj / root / _LIST, payload)
    assert F._check_condition(proj, _COND) is True


@pytest.mark.parametrize("root", _REACHABLE)
@pytest.mark.parametrize("blocks", ["oops", 7, {"a": 1}])
def test_G4_malformed_block_array_beats_the_flag(tmp_path, root, blocks):
    """The flag decides ONLY when neither block key is present. A block key
    that IS present but malformed contradicts the flag; a self-contradictory
    list stays undecidable so somebody has to look at it."""
    proj = _fresh(tmp_path, f"g4_{_slug(root)}_{_slug(str(blocks))}")
    _write(proj / root / _LIST, {"blocks": blocks, "no_analog": True})
    assert F._check_condition(proj, _COND) is True


@pytest.mark.parametrize("root", _REACHABLE)
def test_G5_named_block_beats_the_flag(tmp_path, root):
    """main's existing polarity, re-pinned here because the new branch sits
    on the same code path: a named block wins over a contradicting flag."""
    proj = _fresh(tmp_path, f"g5_{_slug(root)}")
    _write(proj / root / _LIST,
           {"blocks": [{"name": "blk_a"}], "no_analog": True})
    assert F._check_condition(proj, _COND) is True


@pytest.mark.parametrize("flag_root,bad_root", [
    (_REACHABLE[0], _REACHABLE[1]),
    (_REACHABLE[1], _REACHABLE[0]),
])
@pytest.mark.parametrize("payload", _UNJUDGEABLE)
def test_G6_flag_beside_an_unjudgeable_sibling_still_triggers(
        tmp_path, flag_root, bad_root, payload):
    """e3b1ae49's fail-loud restoration must survive the new branch: one root
    declaring none must not stand thirteen steps down while the sibling
    reachable root holds a list nobody could open."""
    proj = _fresh(tmp_path, f"g6_{_slug(flag_root)}_{_slug(payload)}")
    _write(proj / flag_root / _LIST, _BARE_FLAG)
    _write(proj / bad_root / _LIST, payload)
    assert F._check_condition(proj, _COND) is True


def test_G7_absent_block_list_unchanged(tmp_path):
    """No list and no L5/L9 analog evidence: the track does not trigger,
    exactly as before."""
    proj = _fresh(tmp_path, "g7")
    (proj / "phase3" / "analog").mkdir(parents=True)
    assert F._check_condition(proj, _COND) is False


def test_G8_non_analog_condition_is_unchanged(tmp_path):
    """The branch is reached only for an `analog_block_list` pattern; an
    ordinary `files_exist` condition keeps pure existence semantics, content
    irrelevant, in both directions."""
    proj = _fresh(tmp_path, "g8")
    cond = {"files_exist": ["sub/marker.json"]}
    assert F._check_condition(proj, cond) is False       # absent -> no run
    _write(proj / "sub" / "marker.json", {})
    assert F._check_condition(proj, cond) is True        # present -> run
    _write(proj / "sub" / "marker.json", _BARE_FLAG)
    assert F._check_condition(proj, cond) is True        # content irrelevant
