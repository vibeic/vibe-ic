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

THE TWO-ROOT SHAPE (U-cases below). Everything above judges a tree with a block
list at ONE root, and at one root the fix is right. `_glob_first` resolves an
analog pattern at TWO roots — the pinned `phase1/analog/` and the canonical
`phase3/analog/` it remaps to — and it SHORT-CIRCUITS: the pinned root having a
file means the canonical root is never opened. So a tree carrying a clean
`{"blocks": []}` at one reachable root and a CORRUPT or DANGLING list at the
other read, through the resolved hit alone, as a positive declaration of no
analog. Thirteen steps stood down on the strength of a file nobody could read —
the exact opposite of the fail-LOUD property this change claims. The U-cases
are that shape; no single-root fixture can see it.

  U1  clean-empty at one root, UNJUDGEABLE at the other -> still triggers
  U2  clean-empty at one root, DANGLING SYMLINK at other -> still triggers
      (`lexists`, not `is_file` — a dangling symlink is a list somebody put
       there AND is unreadable, which is the definition of undecidable)
  U3  the OVER-CORRECTION canary: an undecidable list ALONE, at a root where
      the pre-fix read already stood the track down, must STILL stand it down.
      Restoring fail-loud is not a licence to WIDEN. An unscoped `lexists`
      probe passes every U1/U2 case and fails only this one.
  U4  clean-empty at BOTH roots -> still stands down (the intended fix must
      survive the fail-loud restoration)

REACHABILITY PIN (K-cases). `phase2/analog/` and a bare `analog/` are remap
SOURCES, never remap TARGETS, so a list at either is invisible to this
condition at EVERY payload. That deferral is safe — it can only leave the track
running — but it is only honest while it is PINNED, so K1 measures reachability
and K2 asserts the measurement matches what the module documents.

chip-AGNOSTIC: synthetic generic fixtures, JSON structure only. No chip,
vendor, PDK, SKU or part-number literal anywhere in this file.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as F  # noqa: E402


_COND = {"files_exist": ["phase1/analog/analog_block_list.json"]}

_ONE_BLOCK = [{"name": "blk_a", "type": "ldo", "spec": None}]

_LIST = "analog_block_list.json"

# The roots `_glob_first` can resolve this condition's pattern at: the one the
# flow-def literally pins, and the canonical analog root it remaps to when the
# pinned path misses. EVERY block-list case below is parametrised over BOTH —
# a fixture set that only ever writes to one of them cannot see a defect that
# lives in the hand-off between them.
_REACHABLE = ["phase1/analog", "phase3/analog"]

# Remap SOURCES, never remap TARGETS — see K1/K2.
_DEFERRED = ["phase2/analog", "analog"]

# Payloads that are PRESENT but cannot be judged. Each must be read as
# "unknown", never as "no analog".
_UNJUDGEABLE = [
    "{ this is not json",                 # unparseable
    "[]",                                 # parses, but not an object
    '{"note": "no blocks key at all"}',   # object, but not the judged shape
]

_SENTINEL_DANGLING = "@@dangling-symlink@@"


def _write(p: Path, payload) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if payload == _SENTINEL_DANGLING:
        # A list somebody put there that cannot be read. `is_file()` calls it
        # absent; `lexists` calls it present-and-unreadable, which it is.
        os.symlink("/nonexistent/no/such/block/list.json", p)
        return
    p.write_text(payload if isinstance(payload, str)
                 else json.dumps(payload))


def _fresh(tmp_path: Path, name: str) -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True, exist_ok=True)
    # `_project_is_pure_analog` and friends memoize on the resolved path;
    # a per-case directory keeps the cases independent.
    F._PURE_ANALOG_CACHE.pop(str(proj.resolve()), None)
    return proj


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s)[:40]


# ───────────────────────────── FORWARD (the bug) ───────────────────────────

@pytest.mark.parametrize("root", _REACHABLE)
def test_F1_empty_blocks_with_no_analog_flag_stands_the_track_down(
        tmp_path, root):
    """The exact honest Phase-1 disclosure. Pre-fix this returned True."""
    proj = _fresh(tmp_path, "f1_" + _slug(root))
    _write(proj / root / _LIST, {"blocks": [], "no_analog": True})
    assert F._check_condition(proj, _COND) is False


@pytest.mark.parametrize("root", _REACHABLE)
def test_F2_empty_blocks_without_a_flag_stands_the_track_down(tmp_path, root):
    proj = _fresh(tmp_path, "f2_" + _slug(root))
    _write(proj / root / _LIST, {"blocks": []})
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

@pytest.mark.parametrize("root", _REACHABLE)
def test_R1_a_named_block_still_triggers_the_track(tmp_path, root):
    """At EITHER reachable root — the condition pins `phase1/analog/` and
    remaps to the canonical `phase3/analog/`, and a list naming real blocks
    must still trigger at both. A content check keyed to only one of them
    would silently drop the other."""
    proj = _fresh(tmp_path, "r1_" + _slug(root))
    _write(proj / root / _LIST, {"blocks": _ONE_BLOCK})
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


@pytest.mark.parametrize("root", _REACHABLE)
def test_R5_analog_blocks_spelling_still_triggers(tmp_path, root):
    proj = _fresh(tmp_path, "r5_" + _slug(root))
    _write(proj / root / _LIST, {"analog_blocks": _ONE_BLOCK})
    assert F._check_condition(proj, _COND) is True


@pytest.mark.parametrize("root", _REACHABLE)
def test_R6_named_block_beats_a_contradicting_no_analog_flag(tmp_path, root):
    """Self-contradictory input is a Phase-1 defect. The non-suppressive
    reading keeps the track running so somebody has to look at it."""
    proj = _fresh(tmp_path, "r6_" + _slug(root))
    _write(proj / root / _LIST, {"blocks": _ONE_BLOCK, "no_analog": True})
    assert F._check_condition(proj, _COND) is True


@pytest.mark.parametrize("payload", _UNJUDGEABLE)
@pytest.mark.parametrize("root", _REACHABLE)
def test_R7_unreadable_or_unjudgeable_list_still_triggers(
        tmp_path, root, payload):
    """Unreadable is NOT evidence of absence. A corrupt or truncated block
    list must never silently delete thirteen steps — at EITHER reachable
    root, since either may be the one the pattern resolves to."""
    proj = _fresh(tmp_path, f"r7_{_slug(root)}_{_slug(payload)}")
    _write(proj / root / _LIST, payload)
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


# ───────── TWO-ROOT: the shape no single-root fixture can see ──────────────
#
# `_glob_first` SHORT-CIRCUITS at the first root that has a file. A clean
# `{"blocks": []}` at that root is a positive "no analog"; a corrupt or
# dangling list at the OTHER reachable root is never opened at all. Judging on
# the resolved hit alone therefore stands thirteen steps down on the strength
# of a file nobody could read — the negation of the fail-LOUD property.

@pytest.mark.parametrize("clean_payload", [
    {"blocks": []}, {"blocks": [], "no_analog": True},
])
@pytest.mark.parametrize("bad_payload", _UNJUDGEABLE)
@pytest.mark.parametrize("clean_root,bad_root", [
    ("phase1/analog", "phase3/analog"),
    ("phase3/analog", "phase1/analog"),
])
def test_U1_unjudgeable_at_the_sibling_root_keeps_the_track_running(
        tmp_path, clean_root, bad_root, bad_payload, clean_payload):
    """One reachable root parseably declares zero blocks; the other carries a
    list that CANNOT be judged. Unreadable is not evidence of absence, so the
    track must stay up — in BOTH root orders, because which one the pattern
    resolves to decides which one is silently skipped."""
    proj = _fresh(tmp_path, f"u1_{_slug(clean_root)}_{_slug(bad_payload)}"
                            f"_{_slug(json.dumps(clean_payload))}")
    _write(proj / clean_root / _LIST, clean_payload)
    _write(proj / bad_root / _LIST, bad_payload)
    assert F._check_condition(proj, _COND) is True


@pytest.mark.parametrize("clean_root,bad_root", [
    ("phase1/analog", "phase3/analog"),
    ("phase3/analog", "phase1/analog"),
])
def test_U2_dangling_symlink_at_the_sibling_root_keeps_the_track_running(
        tmp_path, clean_root, bad_root):
    """The `is_file()`-vs-`lexists` case, stated on its own. A dangling
    symlink is a block list somebody put there AND cannot be read — exactly
    undecidable. `is_file()` reports it ABSENT, which is the one answer that
    is affirmatively wrong."""
    proj = _fresh(tmp_path, "u2_" + _slug(clean_root))
    _write(proj / clean_root / _LIST, {"blocks": [], "no_analog": True})
    _write(proj / bad_root / _LIST, _SENTINEL_DANGLING)
    assert F._check_condition(proj, _COND) is True


@pytest.mark.parametrize("root", _REACHABLE)
def test_U3_over_correction_canary_undecidable_alone_must_not_widen(
        tmp_path, root):
    """THE OVER-CORRECTION. Every U1/U2 case above is also passed by an
    UNSCOPED `lexists` probe — one that triggers whenever any block-list path
    exists and cannot be judged, regardless of whether the pre-fix read saw it
    at all. This is the single case that separates the two.

    A dangling symlink is the one payload the pre-fix read ALSO stood the
    track down on: `glob` does not match it, so the pattern resolved to
    nothing and the step was SKIPPED-CONDITION. `lexists` DOES see it. An
    unscoped probe therefore newly OPENS thirteen steps on a project that
    never ran them — a WIDENING, and this change's whole stated direction is
    that it can only narrow. Restoring fail-loud is not a licence to trigger.

    Measured against the byte-identical pre-fix file, both roots: False."""
    proj = _fresh(tmp_path, "u3_" + _slug(root))
    _write(proj / root / _LIST, _SENTINEL_DANGLING)
    assert F._check_condition(proj, _COND) is False


@pytest.mark.parametrize("p1_payload", [
    {"blocks": []}, {"blocks": [], "no_analog": True},
])
@pytest.mark.parametrize("p3_payload", [
    {"blocks": []}, {"blocks": [], "no_analog": True},
])
def test_U4_clean_empty_at_both_roots_still_stands_the_track_down(
        tmp_path, p1_payload, p3_payload):
    """The intended fix must SURVIVE the fail-loud restoration. When every
    reachable root parseably and positively declares zero blocks, the track
    still stands down — otherwise U1/U2 would have been 'fixed' by simply
    reverting to existence semantics."""
    proj = _fresh(tmp_path, f"u4_{_slug(json.dumps(p1_payload))}"
                            f"_{_slug(json.dumps(p3_payload))}")
    _write(proj / "phase1/analog" / _LIST, p1_payload)
    _write(proj / "phase3/analog" / _LIST, p3_payload)
    assert F._check_condition(proj, _COND) is False


# ─────────────────── REACHABILITY PIN (the disclosed deferral) ─────────────

@pytest.mark.parametrize("payload", [
    {"blocks": _ONE_BLOCK},               # even a NAMED block
    {"blocks": []},
    {"blocks": [], "no_analog": True},
    "{ this is not json",
    "[]",
    '{"note": "no blocks key at all"}',
    _SENTINEL_DANGLING,
])
@pytest.mark.parametrize("root", _DEFERRED)
def test_K1_deferred_roots_are_invisible_at_every_payload(
        tmp_path, root, payload):
    """CHARACTERIZATION, not an aspiration. `_glob_first` remaps `phase2/
    analog/` and a bare `analog/` INTO the canonical root; it never remaps
    OUT to them. A block list at either is therefore invisible to this
    condition whatever it says — including a list naming real blocks.

    This is measured pre-fix behaviour and this change does not touch it:
    widening the remap would move every `phase{1,2,3}/analog/*` condition in
    the flow, and the real owner of the drift is the analog runner's own
    candidate list. What is NOT acceptable is leaving it disclosed only in
    prose. This test is the pin: if a future `_glob_first` change opens or
    re-closes one of these roots, it fails here instead of drifting silently
    under the undecidable probe."""
    proj = _fresh(tmp_path, f"k1_{_slug(root)}_{_slug(str(payload))}")
    _write(proj / root / _LIST, payload)
    assert F._check_condition(proj, _COND) is False


def test_K2_module_documents_exactly_the_measured_reachable_set(tmp_path):
    """The measured reachable set must equal what the module declares. A
    constant that drifts from behaviour is worse than no constant."""
    measured_reachable = []
    for root in _REACHABLE + _DEFERRED:
        proj = _fresh(tmp_path, "k2_" + _slug(root))
        _write(proj / root / _LIST, {"blocks": _ONE_BLOCK})
        if F._check_condition(proj, _COND) is True:
            measured_reachable.append(root)

    assert measured_reachable == _REACHABLE
    assert list(F._ANALOG_BLOCK_LIST_ROOTS_DEFERRED) == _DEFERRED
    # Two reachable roots, and the probe covers both of them.
    probes = F._analog_block_list_probe_paths(
        tmp_path / "k2_probe", "phase1/analog/analog_block_list.json")
    assert [str(p).split("k2_probe/")[-1] for p in probes] == [
        f"{r}/{_LIST}" for r in _REACHABLE]


def test_K3_a_glob_pattern_degrades_to_pre_fix_resolution(tmp_path):
    """No analog condition in the flow-def is a glob. If one ever is, the
    literal probe has no single path to look at and returns nothing — the
    honest degradation is to `_glob_first`'s own resolution, i.e. pre-fix
    behaviour, never past it."""
    assert F._analog_block_list_probe_paths(
        tmp_path, "phase*/analog/analog_block_list.json") == []
