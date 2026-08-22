"""#1079 merge — the boundary #1093 missed, and the liveness it could not claim.

#1093 shipped the MECHANISM (wired at `_watchdog.run_supervised`, the one place
a supervised step becomes a process) with the WRONG boundary: it asked
`blindness_audit._classify_rel`, which answers "is this a benchmark scoring
oracle", not `_reference_flow_boundary`, which answers "where does §4.05 run".
Measured on that branch before this merge:

    oracle_reason('golden/x.v')                   -> None
    oracle_reason('oracle/y.json')                -> None
    oracle_reason('ground_truth/z.txt')           -> None
    oracle_reason('reference_flow/qor_rules.tcl') -> None

— a §4.05 "mechanism" under which a step may read `golden/`.

#1105 had the right boundary and nothing invoked it. This file tests the two
things the merge adds; #1093's own 13 tests are untouched and still pass, which
is the point: the boundary got stronger without an assertion getting weaker.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import step_input_scope as S  # noqa: E402
import _reference_flow_boundary as RFB  # noqa: E402


# --------------------------------------------------------------------------- #
# The boundary
# --------------------------------------------------------------------------- #
def test_every_canonical_off_limits_segment_is_denied():
    """The gap. All twelve, from the repo's own single definition — not a list
    retyped here, so a segment added there is covered here for free."""
    missed = [seg for seg in sorted(RFB.OFF_LIMITS_TREE_SEGMENTS)
              if S.oracle_reason(f"{seg}/thing.v") is None]
    assert missed == [], f"segments a step could still read: {missed}"


def test_the_benchmark_scoring_channels_are_still_denied():
    """The other authority is UNIONED in, not replaced. #1093 was right that
    `score/` and `canonical_samples/` are off limits; it was only incomplete."""
    assert S.oracle_reason("score/x.json")
    assert S.oracle_reason("canonical_samples/y.v")
    assert S.oracle_reason("verified_netlist.v")


def test_a_legitimate_design_path_is_NOT_denied():
    """The false-positive control. A deny-list that denies the design is not a
    boundary, it is an outage."""
    for ok in ("phase2/stage1/rtl/top.v",
               "phase3/stage3/pnr/routed.def",
               "input/docs/L1_DATASHEET.md",
               "reports/phase3/drc.rpt"):
        assert S.oracle_reason(ok) is None, ok


def test_deny_segments_covers_both_authorities():
    d = set(S.deny_segments())
    assert set(RFB.OFF_LIMITS_TREE_SEGMENTS) <= d
    assert {"score", "canonical_samples"} <= d


# --------------------------------------------------------------------------- #
# The shim re-implements nothing
# --------------------------------------------------------------------------- #
def test_the_shim_carries_NO_classifier_of_its_own(tmp_path):
    """#1093's shim held its own `_ORACLE_DIRS` and its own regex, duplicated
    on the sound reasoning that a guard which fails to import is a guard that
    silently does not run. The consequence was two definitions with nothing
    pinning them together. The parent now resolves the list and hands it down,
    which keeps the no-import property AND removes the second definition."""
    src = (_PROGRAMS / "step_input_scope.py").read_text(encoding="utf-8")
    shim = src.split("_SITECUSTOMIZE = '''")[1].split("'''")[0]
    assert "_ORACLE_DIRS" not in shim, "the shim re-grew a hardcoded deny list"
    # No SEGMENT is named in the shim. Checked against the real list rather
    # than a retyped one, so a segment added upstream is covered here for free.
    # (`golden` appears once inside a MESSAGE string —
    # "hidden oracle file (test/ref/golden)" — which is prose, not a decision;
    # the first draft of this test asserted on the bare substring and caught
    # that instead of what it meant to.)
    decisions = "\n".join(l for l in shim.splitlines()
                          if "hidden oracle file" not in l)
    for seg in sorted(RFB.OFF_LIMITS_TREE_SEGMENTS) + ["canonical_samples"]:
        assert f'"{seg}"' not in decisions and f"'{seg}'" not in decisions, seg
    # It reads the list it was handed, and nothing else.
    assert "VIBEIC_STEP_SCOPE_DENY" in shim


def test_the_deny_list_actually_reaches_the_child(tmp_path):
    env, meta = S.child_env({S.ENV_SWITCH: "1"}, project=tmp_path,
                            step_id="23", guard_dir=tmp_path / "g")
    assert meta["enforced"] is True, meta
    handed = json.loads(env[S.ENV_DENY])
    assert set(RFB.OFF_LIMITS_TREE_SEGMENTS) <= set(handed), handed
    assert env[S.ENV_DENY_FILE_RE] == S.DENY_FILENAME_RE


# --------------------------------------------------------------------------- #
# Liveness — an enforcement whose failure mode is a green tick is not one
# --------------------------------------------------------------------------- #
def test_a_guard_that_never_loaded_is_NOT_reported_as_enforced(tmp_path):
    env, meta = S.child_env({S.ENV_SWITCH: "1"}, project=tmp_path,
                            step_id="23", guard_dir=tmp_path / "g")
    assert meta["enforced"] is True          # we asked for it …
    out = S.liveness(dict(meta))             # … the child never wrote the marker
    assert out["enforced"] is False, out
    assert "REFUSED" in out["liveness"], out


def test_a_guard_that_DID_load_is_confirmed(tmp_path):
    env, meta = S.child_env({S.ENV_SWITCH: "1"}, project=tmp_path,
                            step_id="23", guard_dir=tmp_path / "g")
    Path(meta["marker"]).write_text("loaded")
    out = S.liveness(dict(meta))
    assert out["enforced"] is True, out
    assert out["liveness"] == "confirmed", out


def test_env_scrub_only_says_so_rather_than_claiming_the_hook(tmp_path):
    """No guard dir requested -> the env half ran and the in-child half did
    not. Saying which is the difference between a record and a claim."""
    env, meta = S.child_env({S.ENV_SWITCH: "1"}, project=tmp_path,
                            step_id="23", guard_dir=None)
    out = S.liveness(dict(meta))
    assert out["enforced"] is True
    assert "env scrub only" in out["liveness"], out


def test_off_by_default_is_untouched(tmp_path):
    """The merge must not switch anything on. `VIBEIC_STEP_SCOPE` unset ->
    the environment comes back byte-for-byte, including None."""
    assert S.child_env(None, project=tmp_path, step_id="23") == (None,
                                                                 {"enforced": False})


# --------------------------------------------------------------------------- #
# PAIRED GUARD
# --------------------------------------------------------------------------- #
def test_a_boundary_that_denies_EVERYTHING_is_not_a_boundary():
    """The always-fires guard.

    An `oracle_reason` that returns a reason unconditionally passes every
    positive test above. It dies here: the design's own paths must come back
    None, and `deny_segments()` must not have swallowed the whole tree.
    """
    assert S.oracle_reason("phase2/stage1/rtl/top.v") is None
    assert S.oracle_reason("") is None
    assert "phase2" not in S.deny_segments()
    assert "reports" not in S.deny_segments()
