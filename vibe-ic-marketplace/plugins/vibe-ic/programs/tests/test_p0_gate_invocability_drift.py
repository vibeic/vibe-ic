#!/usr/bin/env python3
"""vibe-ic — the P0 umbrella's silent gates cannot grow in number.

Every test here is about a REFUSAL or about the discriminator, because the
passing case was never the problem: 33 registered gates already return no verdict
while P0 reports PASS (vibe-ic#559). What must not happen is a 34th arriving
unnoticed.
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import p0_gate_invocability_drift_check as D  # noqa: E402


# ---------------------------------------------------------------------------
# the discriminator — rc 2 alone is not "argparse rejected the argv"
# ---------------------------------------------------------------------------

def _script(tmp_path: Path, name: str, body: str) -> list:
    p = tmp_path / name
    p.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return [sys.executable, str(p)]


def test_argparse_rejection_is_detected(tmp_path):
    argv = _script(tmp_path, "needs_flag.py", (
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--rtl-dir', required=True)\n"
        "p.parse_args()\n"))
    assert D._rejects_the_umbrella_argv(argv) is True


def test_a_gates_own_exit_2_is_not_an_argparse_rejection(tmp_path):
    """THE measurement defect this discriminator exists for. Counting bare
    `rc == 2` reports 181 of 243 gates as un-invocable, because most of them use
    exit 2 for their own missing-input error. Only argparse prints `usage:`."""
    argv = _script(tmp_path, "own_exit2.py", (
        "import sys\n"
        "print('error: not a directory: /nope', file=sys.stderr)\n"
        "sys.exit(2)\n"))
    assert D._rejects_the_umbrella_argv(argv) is False


def test_a_wording_we_did_not_anticipate_is_still_caught(tmp_path):
    """Filtering on the error TEXT only finds the phrasings someone thought of.
    argparse's own `usage:` line is present whatever the message says."""
    argv = _script(tmp_path, "odd_wording.py", (
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('mode', choices=['a', 'b'])\n"
        "p.parse_args()\n"))
    assert D._rejects_the_umbrella_argv(argv) is True


def test_a_timeout_is_not_a_rejection(tmp_path, monkeypatch):
    """A gate that runs long got PAST parsing. Calling that a rejection would
    turn a slow machine into a wave of false findings."""
    monkeypatch.setattr(D, "GATE_TIMEOUT_S", 1)
    argv = _script(tmp_path, "slow.py", "import time\ntime.sleep(30)\n")
    assert D._rejects_the_umbrella_argv(argv) is False


# ---------------------------------------------------------------------------
# the subset predicate — the whole point of the program
# ---------------------------------------------------------------------------

def _fake_measure(measured):
    return lambda jobs=8: {"registered": 243, "measured": sorted(measured)}


def test_a_new_un_invocable_gate_fails(monkeypatch, capsys):
    """THE defect. A gate registered without an adapter returns no verdict and
    P0 still says PASS, so nothing else in the tree notices."""
    monkeypatch.setattr(D, "KNOWN_NOT_INVOCABLE", ("a", "b"))
    monkeypatch.setattr(D, "measure", _fake_measure({"a", "b", "brand_new"}))
    assert D.main([]) == D.RC_DRIFT
    assert "brand_new" in capsys.readouterr().err


def test_fixing_a_gate_does_not_fail(monkeypatch, capsys):
    """Subset, not equality: shrinking the set is the goal, so it must not be an
    error. Equality would make every fix a red build and the check would be
    deleted rather than obeyed. The remaining gate `a` is LICENSED here so this
    exercises the KNOWN-subset ratchet in isolation, not the #559 round-6
    undecided-silence ratchet (which has its own test below)."""
    import flow_compliance_check as F
    monkeypatch.setattr(F, "_UNDRIVABLE_BY_STRUCTURAL_UMBRELLA", {"a": {}})
    monkeypatch.setattr(D, "KNOWN_NOT_INVOCABLE", ("a", "b"))
    monkeypatch.setattr(D, "measure", _fake_measure({"a"}))
    assert D.main([]) == D.RC_OK
    assert "now accept" in capsys.readouterr().err


def test_a_fix_cannot_pay_for_a_new_silent_gate(monkeypatch, capsys):
    """Why the predicate is a subset and not a count. The total is unchanged
    here — one fixed, one new — and a ratchet on the NUMBER would pass."""
    monkeypatch.setattr(D, "KNOWN_NOT_INVOCABLE", ("a", "b"))
    monkeypatch.setattr(D, "measure", _fake_measure({"a", "brand_new"}))
    assert D.main([]) == D.RC_DRIFT


# ---------------------------------------------------------------------------
# the measurement cannot report a vacuous clean
# ---------------------------------------------------------------------------

def test_an_empty_registry_is_not_a_clean_result(monkeypatch):
    import flow_compliance_check as F
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES", ())
    res = D.measure()
    assert "error" in res, "an empty registry reported zero silent gates"


def test_a_crash_is_not_a_finding(monkeypatch, capsys):
    """rc 1 means `a new un-invocable gate exists`. An uncaught exception
    reaching the caller would publish that claim from a program that measured
    nothing."""
    def boom(jobs=8):
        raise RuntimeError("subprocess layer died")
    monkeypatch.setattr(D, "check", boom)
    assert D.main([]) == D.RC_CANNOT_MEASURE
    assert "NOT MEASURED" in capsys.readouterr().err


def test_the_argv_comes_from_the_umbrellas_own_builder(monkeypatch):
    """A re-typed argv agrees with the umbrella by coincidence. `_structural_gate_argv`
    was named as a function in #492 precisely so tests drive the same code, and a
    measurement that bypasses it measures a different program."""
    import flow_compliance_check as F
    seen = []
    real = F._structural_gate_argv

    def spy(gate_name, project, **kw):
        seen.append(gate_name)
        return real(gate_name, project, **kw)

    monkeypatch.setattr(F, "_structural_gate_argv", spy)
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES", ("module_port_audit",))
    D.measure(jobs=1)
    assert seen == ["module_port_audit"]


def test_the_recorded_set_has_no_duplicates_and_is_sorted():
    """It is edited by hand as gates are triaged; a duplicate would silently
    weaken nothing but signals a bad merge, and sorted order keeps the diff of a
    removal to one line."""
    rec = list(D.KNOWN_NOT_INVOCABLE)
    assert len(rec) == len(set(rec))
    assert rec == sorted(rec)



# ---------------------------------------------------------------------------
# vibe-ic#559 — WHICH silences are licensed
# ---------------------------------------------------------------------------

def test_a_recorded_measurement_makes_a_silence_licensed(monkeypatch):
    """The distinction the #492 table move exists to enable: a gate somebody
    measured and decided to keep silent is a different fact from one nobody
    looked at, and only the second is work to do."""
    import flow_compliance_check as F
    monkeypatch.setattr(F, "P0_RTL_DIR_GROUP_MEASUREMENT", {"a": (0, 0)})
    monkeypatch.setattr(F, "_ZERO_DENOMINATOR_CLASSIFICATION", {"b": {}})
    monkeypatch.setattr(F, "_STRUCTURAL_GATE_ARGV_ADAPTERS", {})
    monkeypatch.setattr(D, "KNOWN_NOT_INVOCABLE", ("a", "b", "c"))
    monkeypatch.setattr(D, "measure", _fake_measure({"a", "b", "c"}))
    res = D.check()
    assert res["licensed_silence"] == ["a", "b"]
    assert res["undecided_silence"] == ["c"]


def test_an_absent_record_is_not_a_licence(monkeypatch):
    """FAIL-SAFE DIRECTION. If the record cannot be read, every gate must read as
    undecided rather than as quietly approved — over-reporting work to do, never
    under-reporting it. Without this, a rename of the table would silently mark
    all 33 as licensed and #559's remainder would read as zero."""
    import builtins
    real = builtins.__import__

    def boom(name, *a, **k):
        if name == "flow_compliance_check":
            raise ImportError("simulated")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    monkeypatch.setattr(D, "KNOWN_NOT_INVOCABLE", ("a", "b"))
    monkeypatch.setattr(D, "measure", _fake_measure({"a", "b"}))
    res = D.check()
    assert res["licensed_silence"] == []
    assert res["undecided_silence"] == ["a", "b"]


def test_undecided_silence_is_now_a_hard_error(monkeypatch, capsys):
    """vibe-ic#559 (round 6) — THE INVARIANT REVERSAL, made explicit.

    Before round 6 an un-invocable gate with no recorded decision was REPORTED
    and never failed on: the undecided count was legitimately non-zero because
    the last 12 had not yet been measured, and failing on it would have made
    unavoidable debt read as a red build. Round 6 measured and recorded all 12
    (`_UNDRIVABLE_BY_STRUCTURAL_UMBRELLA`), so the real undecided count reaches
    0 — and a check that CAN reach 0 must fail when it does not, or it is the
    exact 'silence reads as benign' defect the whole file exists to kill.

    Here `a` and `b` reject the argv and are in NO licensed table, so they are
    undecided and the gate now FAILs on them. This is the negative control for
    the round-6 ratchet."""
    import flow_compliance_check as F
    monkeypatch.setattr(F, "P0_RTL_DIR_GROUP_MEASUREMENT", {})
    monkeypatch.setattr(F, "_ZERO_DENOMINATOR_CLASSIFICATION", {})
    monkeypatch.setattr(F, "_STRUCTURAL_GATE_ARGV_ADAPTERS", {})
    monkeypatch.setattr(F, "_SEMANTIC_ARGV_UNDRIVABLE", {})
    monkeypatch.setattr(F, "_NOT_A_PROJECT_GATE", {})
    monkeypatch.setattr(F, "_UNDRIVABLE_BY_STRUCTURAL_UMBRELLA", {})
    monkeypatch.setattr(D, "KNOWN_NOT_INVOCABLE", ("a", "b"))
    monkeypatch.setattr(D, "measure", _fake_measure({"a", "b"}))
    assert D.main([]) == D.RC_DRIFT       # undecided -> HARD ERROR
    assert "NO recorded decision" in capsys.readouterr().err


def test_a_gate_needing_only_paths_is_a_wiring_gap():
    """17 of the 21 need a project path, an RTL dir, an out dir or a top-module —
    all things the umbrella already computes. That is mechanical work."""
    assert {"--rtl-dir"} <= D.UMBRELLA_SUPPLIABLE
    assert {"--out-dir", "--project-dir", "--top-module"} <= D.UMBRELLA_SUPPLIABLE
    assert D.POSITIONAL_MARKER in D.UMBRELLA_SUPPLIABLE


def test_a_design_specific_value_is_NOT_umbrella_suppliable():
    """No umbrella can synthesise a design's CRC signal name or a tristate bus's
    drivers. Handing them a placeholder turns an honest NOT_INVOCABLE into a WRONG
    verdict, which is strictly worse than the silence."""
    for flag in ("--crc-signal", "--bus-name", "--drivers", "--end-signal",
                 "--vectors-json", "--min-cycles"):
        assert flag not in D.UMBRELLA_SUPPLIABLE, flag


def test_the_split_is_reported_and_sums_to_the_undecided_pile(monkeypatch):
    """Counting the two piles together hides which work is mechanical and which is
    a de-registration, so they are separate keys — and they must account for every
    undecided gate."""
    res = D.check(jobs=8)
    if "error" in res:
        import pytest as _p
        _p.skip("cannot measure here")
    und = set(res["undecided_silence"])
    assert set(res["wiring_gap"]) | set(res["needs_design_value"]) == und
    assert not (set(res["wiring_gap"]) & set(res["needs_design_value"]))


def test_an_unclassifiable_gate_reads_as_a_wiring_gap(monkeypatch):
    """FAIL-SAFE. If the argv builder cannot be imported the split cannot be made;
    everything lands in the mechanical pile, over-stating it rather than quietly
    shrinking the one that needs a human decision."""
    import builtins
    real = builtins.__import__

    def boom(name, *a, **k):
        if name == "flow_compliance_check":
            raise ImportError("simulated")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    out = D._split_undecided(["x", "y"])
    assert out["wiring_gap"] == ["x", "y"]
    assert out["needs_design_value"] == []

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
