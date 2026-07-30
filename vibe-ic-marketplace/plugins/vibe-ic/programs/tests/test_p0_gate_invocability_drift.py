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
    deleted rather than obeyed."""
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
