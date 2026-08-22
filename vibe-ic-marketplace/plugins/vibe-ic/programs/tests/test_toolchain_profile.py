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


# ---------------------------------------------------------------------------
# VERSION, not only PRESENCE (vibe-ic#1353 review)
# ---------------------------------------------------------------------------
# The gap these close, measured across two hosts of this fleet:
#
#   iverilog 11.0  binding an absent parameter -> WARNING, rc=0  -> 2 tests FAIL
#   iverilog 14.0  the same case               -> ERROR,   rc=2  -> the same 2 PASS
#
# Both hosts report `iverilog PRESENT`, so under a presence-only payload both
# produced the IDENTICAL fingerprint while legitimately disagreeing about two
# tests — and a subset judgement across them would have charged the branch for a
# version-caused red. That is the substitution this module exists to refuse,
# one field narrower than the one it already refuses.
def _vprof(keyed, vers):
    full = {t: bool(keyed.get(t, False)) for t in T.KEYED_TOOLS}
    v = {t: vers.get(t) for t in T.KEYED_TOOLS}
    return {"keyed": full, "versions": v, "recorded": {},
            "fingerprint": T.fingerprint(full, v)}


def test_the_SAME_tools_at_DIFFERENT_versions_do_not_fingerprint_alike():
    """The counterexample, as a rule."""
    present = {t: True for t in T.KEYED_TOOLS}
    old = T.fingerprint(present, {"iverilog": "11.0", "yosys": "0.33",
                                  "verilator": "5.020"})
    new = T.fingerprint(present, {"iverilog": "14.0", "yosys": "0.33",
                                  "verilator": "5.020"})
    assert old != new, (
        "iverilog 11.0 and 14.0 produced the same fingerprint, so a baseline "
        "taken on one is still readable as comparable to the other — the exact "
        "pair measured to disagree about two tests")


def test_the_same_tools_at_the_same_versions_DO_fingerprint_alike():
    """The other half. Without it the test above passes on a `fingerprint`
    that simply returns a fresh value every call, which would refuse every
    comparison and be useless in the opposite direction."""
    present = {t: True for t in T.KEYED_TOOLS}
    v = {"iverilog": "14.0", "yosys": "0.33", "verilator": "5.020"}
    assert T.fingerprint(present, v) == T.fingerprint(present, dict(v))


def test_a_version_only_difference_is_REFUSED_and_NAMES_the_tool():
    """A refusal nobody can act on gets worked around, so the sentence has to
    say which tool moved and to what."""
    present = {t: True for t in T.KEYED_TOOLS}
    base = _vprof(present, {"iverilog": "11.0", "yosys": "0.33",
                            "verilator": "5.020"})
    cur = _vprof(present, {"iverilog": "14.0", "yosys": "0.33",
                           "verilator": "5.020"})
    verdict, why = T.compare(base, cur)
    assert verdict == T.DIFFERENT, (verdict, why)
    assert "iverilog" in why and "11.0" in why and "14.0" in why, why
    # and it must NOT read as a presence move, which is a different remedy
    assert "PRESENT" not in why and "ABSENT" not in why, why


def test_a_PRESENCE_move_still_reports_as_a_presence_move():
    """The version branch must not swallow the case it was added beside."""
    base = _vprof({t: True for t in T.KEYED_TOOLS},
                  {t: "1.0" for t in T.KEYED_TOOLS})
    cur = _vprof({**{t: True for t in T.KEYED_TOOLS}, "iverilog": False},
                 {t: "1.0" for t in T.KEYED_TOOLS})
    verdict, why = T.compare(base, cur)
    assert verdict == T.DIFFERENT, (verdict, why)
    assert "iverilog" in why and "ABSENT" in why, why


def test_a_baseline_PREDATING_version_keying_refuses_rather_than_matching():
    """The compatibility question, answered in the refusing direction.

    A profile written before versions were keyed carries no `versions` key. It
    must not read as comparable to one that does — that would be the module
    silently accepting a measurement it cannot verify, which is the thing it
    was written to stop.
    """
    present = {t: True for t in T.KEYED_TOOLS}
    legacy = {"keyed": present, "recorded": {},
              "fingerprint": T.fingerprint(present)}   # no `versions`
    legacy["fingerprint"] = "deadbeefdeadbeef"          # an old-scheme stamp
    cur = _vprof(present, {"iverilog": "14.0", "yosys": "0.33",
                           "verilator": "5.020"})
    verdict, why = T.compare(legacy, cur)
    assert verdict == T.DIFFERENT, (verdict, why)
    assert "predates version-keyed" in why, why
    assert "re-measure" in why.lower(), why


def test_an_UNREADABLE_version_never_collides_with_a_REAL_one():
    """`?` must be a value no tool can actually report.

    CORRECTED after my own paired guard caught it. The first version of this
    test compared an installed-unreadable profile against an ABSENT one and
    asserted they differ — which they do, but because the PRESENCE bool differs,
    not because of the sentinel. It passed with `UNKNOWN_VERSION` set to
    anything at all, so it was checking a property adjacent to its own name.

    The real risk is collision: a sentinel that happens to look like a version
    makes a host that CANNOT read the version fingerprint identically to one
    running that version. So the comparison has to hold PRESENCE equal and vary
    only the version.
    """
    present = {t: True for t in T.KEYED_TOOLS}
    others = {"yosys": "0.33", "verilator": "5.020"}
    unreadable = T.fingerprint(present, {"iverilog": None, **others})
    for real in ("11.0", "14.0", "0.33", "5.020"):
        assert unreadable != T.fingerprint(present, {"iverilog": real, **others}), (
            f"an unreadable iverilog version fingerprints the same as {real} — "
            f"UNKNOWN_VERSION collides with a version a tool can report, so a "
            f"host that cannot answer reads as comparable to one that can")
    assert not T._VERSION_RE.fullmatch(T.UNKNOWN_VERSION), (
        f"UNKNOWN_VERSION={T.UNKNOWN_VERSION!r} parses as a version numeral, so "
        f"a real tool could report it")


def test_the_version_probe_reads_THIS_host_and_is_not_hardcoded():
    """Drives the real binaries. Skips rather than lying when none is present —
    a host with no keyed tool cannot answer this question either way."""
    vers = T.versions(T.KEYED_TOOLS)
    present = [t for t in T.KEYED_TOOLS if T.shutil.which(t)]
    if not present:
        pytest.skip("no KEYED tool on this host — nothing to read a version from")
    got = {t: vers[t] for t in present}
    assert any(v for v in got.values()), (
        f"every present tool returned an unreadable version: {got}. `-V` is the "
        f"flag all three answer; `--version` is rejected by iverilog, and a probe "
        f"that always fails would key on a constant and measure nothing")
    for t, v in got.items():
        if v is not None:
            assert T._VERSION_RE.fullmatch(v), (t, v)


def test_the_version_probe_bound_is_under_the_harness_ceiling():
    """A bound above 60s promises time a 180s harness will not give, and a hang
    then kills the SESSION instead of one test (vibe-ic#1181)."""
    import inspect
    sig = inspect.signature(T.tool_version)
    assert sig.parameters["timeout"].default <= 60, sig


def test_the_version_flag_is_the_one_ALL_THREE_tools_answer():
    """Pins the trap directly, because `--version` is the obvious choice and is
    wrong here.

    MEASURED on this host: `iverilog --version` -> rc=1,
    `iverilog: invalid option -- '-'`. A probe using it records None for
    iverilog on EVERY host, so the version key becomes a constant and the
    fingerprint silently reverts to presence-only while looking like it works.
    The `any(...)` vacuity guard above does not catch that, because yosys and
    verilator both accept `--version`.
    """
    assert T._VERSION_FLAG == "-V", (
        "`-V` is the flag all three KEYED tools answer with rc=0; iverilog "
        "rejects `--version`")
    if T.shutil.which("iverilog"):
        assert T.tool_version("iverilog") is not None, (
            "iverilog is on PATH and its version could not be read — the flag "
            "this module uses is one iverilog does not accept")
