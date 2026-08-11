#!/usr/bin/env python3
"""flow_compliance_check: an `all_of` sub-gate's INCOMPLETE / SUBSTANTIVE
disclosure must reach the step, not die one level below it.

THE DEFECT, and it is the one the code's own comment predicted
==============================================================
`_evaluate_gate`'s `all_of` branch forwards sub-gate hints through a WHITELIST,
and that whitelist carries this comment verbatim:

    "This list is a WHITELIST: a hint a sub-gate emits and this loop does not
     name is dropped here, silently, and the disclosure dies one level below
     the line that was supposed to carry it — which is precisely the shape of
     defect the tier exists to make visible."

vibe-ic#599 then added two tiers — `SUBSTANTIVE_PASS` and `INCOMPLETE` — to the
single-clause `program_exit_zero` branch and did NOT add them to this
whitelist. So a gate that printed `INCOMPLETE:` and exited 0 was tiered
correctly when it was a step's ONLY clause, and reported as a bare PASS when it
sat inside an `all_of`. MEASURED before the fix: step 33's authority clause
printed the token, exited 0, and `check_step` returned PASS with the hint
absent from `reasons` entirely.

WHY IT MATTERS HERE. "A cell that refuses is not a cell that passes" is only
true if the refusal is carried. A gate that refuses into a channel nobody reads
is indistinguishable from one that passed.

These tests drive REAL sub-gate programs — throwaway scripts written into a temp
directory, with only the checker's `PROGRAMS_DIR` redirected at them — rather
than stubbing `_check_program_exit_zero`'s return value. The defect was in how a
program's STDOUT crosses the process boundary and is then tiered, and a stubbed
return value never crosses it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow_compliance_check as fcc  # noqa: E402

_QUIET = "print('[PASS] quiet: examined 1 item(s)')\n"
_INCOMPLETE = ("print('detail line that would be kept anyway')\n"
               "print('INCOMPLETE: authority absent — nothing was compared')\n")
_SUBSTANTIVE = ("print('detail')\n"
                "print('SUBSTANTIVE_PASS: verified by another route')\n")


def _gate_dir(tmp_path: Path, **progs: str) -> Path:
    """Write throwaway gate programs and put them where the checker finds
    them. Returns the project dir the gate is evaluated against."""
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    for name, body in progs.items():
        (tmp_path / f"{name}.py").write_text(body)
    return proj


def _point_at(monkeypatch, tmp_path: Path) -> None:
    """`_check_program_exit_zero` builds `<PROGRAMS_DIR>/<name>.py` at call
    time, so redirecting the module global is enough to run throwaway gates —
    and it keeps this test off the real registry, where a name collision would
    make it measure some other program."""
    monkeypatch.setattr(fcc, "PROGRAMS_DIR", tmp_path)


def test_incomplete_hint_from_a_sub_gate_reaches_the_step(tmp_path,
                                                          monkeypatch):
    """The regression. Without the whitelist branch the returned reasons carry
    no INCOMPLETE hint and the step is reported as a bare PASS."""
    proj = _gate_dir(tmp_path, zz_incomplete_probe=_INCOMPLETE,
                     zz_quiet_probe=_QUIET)
    _point_at(monkeypatch, tmp_path)
    gate = {"all_of": [{"program_exit_zero": "zz_quiet_probe ."},
                       {"program_exit_zero": "zz_incomplete_probe ."}]}
    passed, reasons = fcc._evaluate_gate(proj, gate)
    assert passed is True
    hints = [r for r in reasons
             if r.startswith(fcc._INCOMPLETE_HINT_PREFIX)]
    assert hints, (
        "the INCOMPLETE disclosure died inside the all_of whitelist; "
        f"reasons={reasons!r}")
    assert "zz_incomplete_probe" in hints[0]


def test_substantive_hint_from_a_sub_gate_reaches_the_step(tmp_path,
                                                           monkeypatch):
    """#599's other tier, dropped by the same whitelist for the same reason."""
    proj = _gate_dir(tmp_path, zz_substantive_probe=_SUBSTANTIVE)
    _point_at(monkeypatch, tmp_path)
    gate = {"all_of": [{"program_exit_zero": "zz_substantive_probe ."}]}
    passed, reasons = fcc._evaluate_gate(proj, gate)
    assert passed is True
    assert any(r.startswith(fcc._SUBSTANTIVE_HINT_PREFIX) for r in reasons), (
        f"reasons={reasons!r}")


def test_a_quiet_sub_gate_raises_no_tier(tmp_path, monkeypatch):
    """The other direction of the control: forwarding must not INVENT a tier.
    A sub-gate that says nothing special leaves the step a plain PASS."""
    proj = _gate_dir(tmp_path, zz_quiet_probe=_QUIET)
    _point_at(monkeypatch, tmp_path)
    gate = {"all_of": [{"program_exit_zero": "zz_quiet_probe ."}]}
    passed, reasons = fcc._evaluate_gate(proj, gate)
    assert passed is True
    assert not [r for r in reasons
                if r.startswith(fcc._INCOMPLETE_HINT_PREFIX)
                or r.startswith(fcc._SUBSTANTIVE_HINT_PREFIX)]
