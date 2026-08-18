#!/usr/bin/env python3
"""vibe-ic#559 (round 7) — the ratchet must use the umbrella's OWN predicate.

THE DEFECT. `flow_compliance_check._eval_gate_worker` decides a gate is
`NOT_INVOCABLE` with `_gate_invocation.classify_not_invocable`, which has TWO
rules:

  Rule A  argparse rejected the command line — `usage:` block on stderr, rc 2.
  Rule B  the gate hand-rolled its own required-argument check and printed an
          `error:` line naming a long option the caller never supplied. argparse
          never runs, so there is NO `usage:` block anywhere.

`p0_gate_invocability_drift_check` — the ratchet whose entire job is to stop the
silent-gate population growing — RE-TYPED that predicate as

    return r.returncode == 2 and "usage:" in (r.stderr or "")

which is Rule A alone. Measured at v1.9.74 over the 246 registered gates, both
arms driven from `_structural_gate_argv` against the same empty probe directory:

    the umbrella (Rule A + Rule B)   36 NOT_INVOCABLE
    the ratchet  (Rule A only)       32

The four in the gap have been named in `_gate_invocation`'s own docstring since
#492. They were not stale entries — they were a whole RULE the ratchet could not
express, so a NEW gate of that shape goes permanently silent under P0 while this
check prints `[PASS] ... No new silent gate`. That is the "silence reads as
benign" defect of #492/#559 relocated into the guard against it.

Every test here is a NEGATIVE CONTROL: each one passes on the fix and FAILS on
`origin/main`, and none of them names a real gate, so none can be satisfied by
editing a list.
"""
from __future__ import annotations

import importlib.util
import pathlib
import stat
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load("flow_compliance_check", "flow_compliance_check.py")
D = _load("p0_gate_invocability_drift_check",
          "p0_gate_invocability_drift_check.py")

import _private_tree as _T  # noqa: E402

#: Reached THROUGH the module under test, never re-imported. A fresh `_load`
#: would hand back a second module object, and patching that one would prove
#: nothing about what the ratchet actually calls. `getattr` rather than
#: attribute access so this file COLLECTS against a tree where the ratchet
#: re-types the predicate and imports nothing — a collection error would hide
#: which assertions fail.
GI = getattr(D, "_gate_invocation", None)


# A gate that hand-rolls its required-argument check. This is not a contrivance:
# it is a byte-for-byte reproduction of the shape four registered gates already
# have (`error: top module not resolved (give --top or --qsf)`).
_HAND_ROLLED = (
    "import argparse, sys\n"
    "p = argparse.ArgumentParser()\n"
    "p.add_argument('rtl')\n"
    "p.add_argument('--widget', default=None)\n"
    "a = p.parse_args()\n"
    "if not a.widget:\n"
    "    print('error: no widget supplied (--widget)', file=sys.stderr)\n"
    "    sys.exit(2)\n"
)


def _gate(tmp_path: pathlib.Path, name: str, body: str) -> pathlib.Path:
    p = tmp_path / f"{name}.py"
    p.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def _planted_in_a_private_farm(tmp_path, monkeypatch, name: str, body: str):
    """Register *name* as a structural gate whose file lives OUTSIDE the tree.

    THE GATE USED TO BE WRITTEN INTO THE LIVE `programs/` DIR, because the
    umbrella's own argv builder resolves a gate as
    `flow_compliance_check.PROGRAMS_DIR / f"{gate}.py"` and the whole point of
    #492 is that this test must drive the SAME builder. Planting there put an
    extra, deliberately-broken `.py` beside the shipped programs for the length
    of the test; the landing gate's per-file parallel path runs many pytest
    sessions over ONE checkout, so every neighbour enumerating `programs/`
    counted it as this branch's. The `finally` that removed it also removed the
    evidence, so `git status --porcelain` came back clean over a manufactured
    red.

    Pointing `PROGRAMS_DIR` at a HARDLINK FARM of the shipped programs keeps
    every real gate byte-identical (same inode) and the builder unchanged,
    while the plant lands in a directory this test owns.
    """
    plugin = _T.private_plugin(tmp_path)
    farm = plugin / "programs"
    _gate(farm, name, body)
    monkeypatch.setitem(sys.modules, "flow_compliance_check", F)
    monkeypatch.setattr(F, "PROGRAMS_DIR", farm)
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES",
                        tuple(F._STRUCTURAL_RTL_GATES) + (name,))
    return farm


# ---------------------------------------------------------------------------
# 1. the predicate itself
# ---------------------------------------------------------------------------

def test_a_hand_rolled_required_argument_is_a_rejection(tmp_path):
    """NEGATIVE CONTROL for the whole round. On origin/main this asserts False:
    the gate exits 2, prints no `usage:` line, and the ratchet calls it
    invocable."""
    argv = [sys.executable, str(_gate(tmp_path, "hand_rolled", _HAND_ROLLED)),
            str(tmp_path)]
    assert D._rejects_the_umbrella_argv(argv) is True, (
        "a gate that hand-rolls its required-argument check exits 2 with no "
        "argparse usage block; a Rule-A-only predicate reports it as invocable "
        "and P0 then passes over a gate that never ran")


def test_the_ratchet_and_the_umbrella_agree_by_construction(tmp_path):
    """The #492 lesson applied to the classifier instead of the argv.

    The ratchet must not merely happen to agree with the umbrella — it must call
    the same function. Monkeypatching `classify_not_invocable` to a constant
    ``None`` has to silence the ratchet too; if it does not, the ratchet owns a
    second copy of the rule and the two can drift, which is how they drifted.
    """
    assert GI is not None and GI is F._gate_invocation, (
        "the ratchet does not hold the umbrella's `_gate_invocation` module at "
        "all, so it cannot be calling the umbrella's classifier — it owns a "
        "second copy of the rule")
    argv = [sys.executable, str(_gate(tmp_path, "hand_rolled2", _HAND_ROLLED)),
            str(tmp_path)]
    assert D._rejects_the_umbrella_argv(argv) is True
    real = GI.classify_not_invocable
    try:
        GI.classify_not_invocable = lambda *a, **k: None
        assert D._rejects_the_umbrella_argv(argv) is False, (
            "the ratchet still classified after the umbrella's classifier was "
            "neutralised, so it is not calling it")
    finally:
        GI.classify_not_invocable = real


def test_a_gates_own_input_error_is_still_not_a_rejection(tmp_path):
    """THE OPPOSITE FALSE DIRECTION, kept nailed down. 181 of 243 gates exit 2
    for their own missing input; widening the predicate must not swallow them.
    Rule B fires only on an error line NAMING a long option."""
    argv = [sys.executable, str(_gate(tmp_path, "own_exit2", (
        "import sys\n"
        "print('error: not a directory: /nope', file=sys.stderr)\n"
        "sys.exit(2)\n"))), str(tmp_path)]
    assert D._rejects_the_umbrella_argv(argv) is False


def test_a_flag_the_caller_did_supply_is_the_gates_verdict_not_a_defect(tmp_path):
    """Rule B is scoped by the flags actually passed. A gate complaining about
    `--rtl-dir` when the caller DID pass `--rtl-dir` is judging the VALUE, and
    calling that an invocation defect would manufacture silences."""
    argv = [sys.executable, str(_gate(tmp_path, "value_verdict", (
        "import sys\n"
        "print('error: --rtl-dir is empty', file=sys.stderr)\n"
        "sys.exit(2)\n"))), "--rtl-dir", str(tmp_path)]
    assert D._rejects_the_umbrella_argv(argv) is False


def test_rule_b_scoping_is_unchanged_for_a_mixed_error_line(tmp_path):
    """BEHAVIOUR-PRESERVATION CONTROL for the umbrella, not for the ratchet.

    Rule B's shipped predicate is `named and not (named & supplied)` — a line
    mentioning ANY flag the caller passed is skipped. Factoring the rule into a
    shared helper is a refactor only if that stays exact; relaxing it to
    `named - supplied` would fire on a line naming one supplied and one
    unsupplied flag, and manufacture a NOT_INVOCABLE verdict inside
    `flow_compliance_check`. This pins the conservative reading.
    """
    GI = F._gate_invocation
    line = "error: give --rtl-dir together with --top"
    assert GI.classify_not_invocable(
        "", line, supplied_flags=["--rtl-dir"]) is None
    assert GI.rule_b_named_options(
        "", line, supplied_flags=["--rtl-dir"]) == []
    # ...and with neither supplied it is still a rejection, both ways round.
    assert GI.classify_not_invocable("", line, supplied_flags=[]) is not None
    assert GI.rule_b_named_options("", line, supplied_flags=[]) == [
        "--rtl-dir", "--top"]


def test_a_nonzero_exit_that_is_not_2_is_never_a_rejection(tmp_path):
    """`classify_not_invocable` is documented as valid for rc 2 ONLY. A gate
    that FAILS (rc 1) may print anything at all, including an error line naming
    a flag; reading that as an invocation defect would erase a real finding."""
    argv = [sys.executable, str(_gate(tmp_path, "real_fail", (
        "import sys\n"
        "print('error: --max-depth exceeded at foo.v:12', file=sys.stderr)\n"
        "sys.exit(1)\n"))), str(tmp_path)]
    assert D._rejects_the_umbrella_argv(argv) is False


# ---------------------------------------------------------------------------
# 2. the growth hole — what the ratchet exists to prevent
# ---------------------------------------------------------------------------

def test_a_newly_registered_hand_rolled_gate_fails_the_ratchet(
        tmp_path, monkeypatch, capsys):
    """THE POINT OF THE FILE. Register a brand-new gate of the Rule-B shape and
    the ratchet must go red. On origin/main it prints `[PASS] ... No new silent
    gate` while P0 reports PASS over a check that never ran."""
    name = "brand_new_hand_rolled_check"
    # `measure()` does its own `import flow_compliance_check`, and sibling test
    # modules in the same session load their own copy into `sys.modules` —
    # patching only our `F` would patch an object the measurement never reads,
    # and the test would pass or fail on file ordering.
    _planted_in_a_private_farm(tmp_path, monkeypatch, name, _HAND_ROLLED)
    res = D.measure(jobs=4)
    assert name in res["measured"], (
        "a newly registered gate that hand-rolls its required-argument "
        "check was measured as INVOCABLE; it returns no verdict, P0 still "
        "says PASS, and the ratchet built to notice says nothing")
    assert D.main([]) == D.RC_DRIFT
    assert name in capsys.readouterr().err
    _T.assert_live_tree_unplanted("brand_new_*_check.py")


# ---------------------------------------------------------------------------
# 3. the second site — the undecided pile was split with the same blind rule
# ---------------------------------------------------------------------------

def test_a_rule_b_gates_needs_are_read_from_its_own_error_line(tmp_path):
    """`_required_flags` read ONLY argparse's `the following arguments are
    required:` line. A Rule-B gate never produces one, so it fell through to
    POSITIONAL_MARKER — a member of UMBRELLA_SUPPLIABLE — and every Rule-B gate
    was filed under `wiring_gap`, the pile labelled "mechanical work". Three of
    the four measured at v1.9.74 need a fact about the DESIGN."""
    argv = [sys.executable, str(_gate(tmp_path, "hand_rolled3", _HAND_ROLLED)),
            str(tmp_path)]
    assert D._required_flags(argv) == ["--widget"]
    assert D.POSITIONAL_MARKER not in D._required_flags(argv)


def test_a_rule_b_gate_is_not_filed_as_mechanical_wiring(tmp_path, monkeypatch):
    """The split, end to end: a design-specific value must land in
    `needs_design_value`. Filing it as a wiring gap tells the next reader that
    an adapter row would fix it, and it would not."""
    name = "brand_new_semantic_check"
    _planted_in_a_private_farm(tmp_path, monkeypatch, name, _HAND_ROLLED)
    out = D._split_undecided([name])
    assert out["needs_design_value"] == [name], out
    assert out["wiring_gap"] == [], out
    _T.assert_live_tree_unplanted("brand_new_*_check.py")


# ---------------------------------------------------------------------------
# 4. the recorded size of the problem must be the umbrella's own number
# ---------------------------------------------------------------------------

def test_the_recorded_set_matches_what_the_umbrella_classifies():
    """P0's true coverage, re-derived rather than quoted. The ratchet's pinned
    list must be the set the UMBRELLA calls NOT_INVOCABLE — not a subset of it
    produced by a different rule. At v1.9.74 those were 32 and 36."""
    res = D.measure(jobs=8)
    if "error" in res:
        pytest.skip(f"cannot measure here: {res['error']}")
    measured = set(res["measured"])
    assert measured <= set(D.KNOWN_NOT_INVOCABLE), (
        f"un-recorded silent gates: {sorted(measured - set(D.KNOWN_NOT_INVOCABLE))}")
    assert len(measured) == 36 and res["registered"] == 246, (
        f"P0 coverage moved: {res['registered'] - len(measured)} of "
        f"{res['registered']} gates return a verdict. Update this anchor "
        f"deliberately and say which direction it moved.")


def test_every_measured_silence_carries_a_machine_readable_decision():
    """A decision written as a comment is invisible to every program, which is
    how these four stayed both unlicensed and unflagged. `undecided_silence`
    reaching 0 is only meaningful if the measurement can see the whole set."""
    res = D.check(jobs=8)
    if "error" in res:
        pytest.skip(f"cannot measure here: {res['error']}")
    assert res["undecided_silence"] == [], res["undecided_silence"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
