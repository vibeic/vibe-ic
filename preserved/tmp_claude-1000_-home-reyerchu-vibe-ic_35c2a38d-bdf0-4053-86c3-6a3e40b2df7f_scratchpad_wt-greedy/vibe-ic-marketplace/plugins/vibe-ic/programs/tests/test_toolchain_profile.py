"""A baseline that does not carry its toolchain cannot be compared (vibe-ic#1327).

Every test here is PAIRED. The module's whole value is that it REFUSES, so the
controls that matter are the ones proving it still says SAME when the profiles
genuinely match — a refuser that refuses everything is as useless as one that
refuses nothing, and it is the easier of the two to write by accident.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import toolchain_profile as T  # noqa: E402


def _prof(**keyed):
    """A profile literal with a fingerprint derived the same way the tool does."""
    full = {t: bool(keyed.get(t, False)) for t in T.KEYED_TOOLS}
    return {"keyed": full, "recorded": {}, "fingerprint": T.fingerprint(full)}


# ---------------------------------------------------------------------------
# The fingerprint is over the KEYED tools only, and is order-independent.
# ---------------------------------------------------------------------------
def test_same_keyed_tools_fingerprint_identically():
    a = _prof(iverilog=True, yosys=False, verilator=False)
    b = _prof(iverilog=True, yosys=False, verilator=False)
    assert a["fingerprint"] == b["fingerprint"]


def test_one_keyed_tool_moving_changes_the_fingerprint():
    """PAIRED with the test above — the digest must not be constant."""
    a = _prof(iverilog=True, yosys=False, verilator=False)
    b = _prof(iverilog=False, yosys=False, verilator=False)
    assert a["fingerprint"] != b["fingerprint"], (
        "the fingerprint ignored a keyed tool, so every host looks comparable")


def test_a_RECORDED_tool_does_not_affect_comparability():
    """klayout differing must NOT refuse a comparison.

    No red in the measured 122/147 sets is attributable to the recorded tools.
    Refusing on them would block sound comparisons — the failure mode opposite
    to the one this module exists to prevent, and just as wrong.
    """
    a = _prof(iverilog=True)
    b = _prof(iverilog=True)
    a["recorded"] = {"klayout": True}
    b["recorded"] = {"klayout": False}
    verdict, _ = T.compare(a, b)
    assert verdict == T.SAME


# ---------------------------------------------------------------------------
# compare(): the three verdicts, and the exit code contract.
# ---------------------------------------------------------------------------
def test_matching_profiles_are_comparable():
    verdict, sentence = T.compare(_prof(iverilog=True), _prof(iverilog=True))
    assert verdict == T.SAME, sentence
    assert T.verdict_code(verdict) == 0


def test_the_REAL_two_host_divergence_is_refused():
    """The exact pair measured on 2026-08-13: host A vs 8HD-8.

    This is the case the module was written for — the profiles differ by
    `iverilog` alone, and that one tool moved main's red set by 25 failures.
    """
    host_a = _prof(iverilog=False, yosys=False, verilator=False)
    hd8 = _prof(iverilog=True, yosys=False, verilator=False)
    verdict, sentence = T.compare(host_a, hd8)
    assert verdict == T.DIFFERENT
    assert T.verdict_code(verdict) == 2
    assert "iverilog" in sentence
    assert "baseline=ABSENT" in sentence and "current=PRESENT" in sentence, sentence


def test_a_mismatch_is_never_exit_code_1():
    """rc=1 would let a caller blame the BRANCH for the HOST.

    Non-zero-means-bad is the common convention, so a profile mismatch reported
    as 1 gets read as "this branch failed". Nothing failed; we could not look.
    """
    assert T.verdict_code(T.DIFFERENT) == 2
    assert T.verdict_code(T.UNREADABLE) == 2
    assert 1 not in {T.verdict_code(v)
                     for v in (T.SAME, T.DIFFERENT, T.UNREADABLE)}


# ---------------------------------------------------------------------------
# "Could not look" is its own verdict — the VACUOUS_PASS discipline.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("baseline", [None, {}, {"keyed": {"iverilog": True}}],
                         ids=["unreadable", "empty", "no-fingerprint"])
def test_an_unusable_baseline_refuses_rather_than_agreeing(baseline):
    verdict, sentence = T.compare(baseline, _prof(iverilog=True))
    assert verdict == T.UNREADABLE, sentence
    assert T.verdict_code(verdict) == 2


def test_UNREADABLE_is_not_folded_into_DIFFERENT():
    """They call for different remedies, so they must stay distinguishable.

    DIFFERENT means somebody must re-measure on a matching host. UNREADABLE
    means the baseline predates the profile and nobody is at fault. Collapsing
    them sends the reader to the wrong fix.
    """
    unreadable, _ = T.compare(None, _prof(iverilog=True))
    different, _ = T.compare(_prof(iverilog=False), _prof(iverilog=True))
    assert unreadable != different


def test_a_baseline_with_no_fingerprint_does_not_read_as_matching():
    """The pre-#1327 baseline case, stated explicitly.

    Every baseline recorded before this module existed has no fingerprint. The
    tempting default is to treat it as compatible so nothing breaks; that is the
    silent wrong answer, and it would apply to EVERY existing baseline at once.
    """
    verdict, sentence = T.compare({"keyed": {"iverilog": True}},
                                  _prof(iverilog=True))
    assert verdict == T.UNREADABLE
    assert "re-measure" in sentence.lower()


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------
def test_emit_then_compare_against_this_host_is_SAME(tmp_path, capsys):
    """Round-trip: what the tool writes, the tool accepts."""
    out = tmp_path / "profile.json"
    assert T.main(["--emit", str(out)]) == 0
    capsys.readouterr()
    assert T.main(["--compare", str(out)]) == 0
    assert "OK" in capsys.readouterr().out


def test_compare_against_a_foreign_profile_exits_2(tmp_path, capsys):
    """PAIRED with the round-trip above — emit/compare is not trivially 0."""
    cur = T.probe(T.KEYED_TOOLS)
    flipped = {t: (not v if t == "iverilog" else v) for t, v in cur.items()}
    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps(
        {"keyed": flipped, "recorded": {}, "fingerprint": T.fingerprint(flipped)}))
    assert T.main(["--compare", str(foreign)]) == 2
    assert "REFUSE" in capsys.readouterr().out


def test_a_missing_baseline_file_exits_2_not_0(tmp_path, capsys):
    assert T.main(["--compare", str(tmp_path / "nope.json")]) == 2
    assert "REFUSE" in capsys.readouterr().out


def test_the_probe_reports_this_host_and_is_not_hardcoded():
    """`probe` must read PATH, not a constant.

    Asserted by probing a name that cannot exist rather than by asserting any
    real tool's state — this suite has to pass on hosts with and without the
    EDA container, which is the very variability #1327 is about.
    """
    assert T.probe(("definitely-not-a-real-binary-xyzzy",)) == {
        "definitely-not-a-real-binary-xyzzy": False}
    assert set(T.probe()) == set(T.KEYED_TOOLS)
