"""The two BIDIRECTIONAL controls in this directory are executed by pytest.

THE DEFECT. `tests/test_arith_declaration_emit_equals_separator.py` and
`tests/test_atpg_exit_code_not_signal.py` are named `test_*.py` and live in the
suite directory, but each defines only a `main()` and an
`if __name__ == "__main__"` guard — no `def test_*`, no test class. Measured on
`a38902d16`, they are the ONLY 2 of 2467 `test_*.py` files that collect nothing:

    $ pytest tests/test_atpg_exit_code_not_signal.py
    no tests collected in 0.32s          (pytest exit 5)

and `grep -rl` finds no runner, workflow, or script that invokes either. So
~14 assertions sat in the tree, passing, executed by nothing — while counting
toward the file census as if they were coverage. That is the shape this repo
removes elsewhere ("a checker only its own test runs"), inverted: a test that
nothing runs at all.

WHY A WRAPPER RATHER THAN A REWRITE. Both files are deliberately parameterised
by the program PATH, because their contract is bidirectional: the same file
must FAIL against the pre-fix program and PASS against the post-fix one.
Rewriting them as plain pytest tests against the shipped module would execute
the assertions but throw the negative half away — and the negative half is the
one that catches "tighten the filter until the count is zero". Both directions
are driven here instead, so the contract each docstring states is the contract
that runs.

THE PERTURBATIONS ARE THE PRE-FIX STATE, NOT AN ARBITRARY BREAK. Each removes
exactly the construct its control was written to prove:

  * `fault_atpg_run.atpg_exit_is_signal_death` — without it, a high exit code is
    read as death-by-signal on the number alone, which is the defect.
  * `arith_declaration_emit._derive_multiplier_algorithm`'s `=` in the
    separator class `[:\\-–=]` — the pre-fix regex accepted `Algorithm:` and not
    `algorithm = <v>`.

A perturbation that broke something else would prove the control runs without
proving it discriminates.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent

#: Comfortably under the 60 s per-call ceiling (180 s harness // 3): a bound at
#: or above it promises time the harness will not give (#542).
_TIMEOUT_S = 50


def _run(control: Path, target: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(control), str(target)],
        capture_output=True, text=True, timeout=_TIMEOUT_S)


#: ``(control, program, perturb)`` — perturb returns the PRE-FIX source text.
def _break_atpg(src: str) -> str:
    out = src.replace("def atpg_exit_is_signal_death(", "def _removed_(", 1)
    assert out != src, "atpg_exit_is_signal_death is gone — update this control"
    return out


def _break_arith(src: str) -> str:
    out, n = re.subn(r"\[:\\-–=\]", "[:\\\\-–]", src, count=1)
    if n == 0:                       # the class is written literally in-source
        out = src.replace("[:\\-–=]", "[:\\-–]", 1)
    assert out != src, "the `=` separator class moved — update this control"
    return out


CASES = (
    pytest.param("test_atpg_exit_code_not_signal.py", "fault_atpg_run.py",
                 _break_atpg, id="atpg_exit_is_not_a_signal"),
    pytest.param("test_arith_declaration_emit_equals_separator.py",
                 "arith_declaration_emit.py", _break_arith,
                 id="arith_equals_separator"),
)


@pytest.mark.parametrize("control,program,perturb", CASES)
def test_the_control_passes_against_the_shipped_program(
        control, program, perturb):
    """FORWARD: the shipped program satisfies its own control."""
    proc = _run(_HERE / control, _PROGRAMS / program)
    assert proc.returncode == 0, (
        f"{control} FAILS against the shipped {program} — this is a real red "
        f"that nothing was running:\n{proc.stdout}\n{proc.stderr}")


@pytest.mark.parametrize("control,program,perturb", CASES)
def test_the_control_still_fails_against_the_pre_fix_program(
        control, program, perturb, tmp_path):
    """PAIRED GUARD: a control that cannot fail is not a control.

    Without this, wiring the file in would prove only that it runs — and a
    control that passes against everything is exactly what these two files were
    written to prevent.
    """
    stage = tmp_path / "programs"
    shutil.copytree(_PROGRAMS, stage, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    target = stage / program
    target.write_text(perturb(target.read_text(encoding="utf-8")),
                      encoding="utf-8")

    proc = _run(_HERE / control, target)
    # Both streams: the arith control reports its held negative on STDERR
    # ("NEGATIVE CONTROL HELD — …"), and an assertion that printed only stdout
    # would report an empty reason for a real failure.
    assert proc.returncode != 0, (
        f"{control} PASSED against a {program} with the fixed construct "
        f"REMOVED — the control asserts nothing:\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")


def test_no_test_file_collects_zero_tests():
    """The census that made the two findable, kept live.

    A file named `test_*.py` that defines no test is invisible to pytest and
    counted by every file census — so it reads as coverage while asserting
    nothing. The two known ones are exempt BY NAME because they are driven
    above; a third would be a new one.
    """
    driven = {c.values[0] for c in CASES}
    silent = sorted(
        p.name for p in _HERE.glob("test_*.py")
        if p.name not in driven
        and not re.search(r"^\s*(async\s+)?def test_|^\s*class Test",
                          p.read_text(encoding="utf-8", errors="replace"),
                          re.M))
    assert not silent, (
        "test_*.py file(s) defining no test function — pytest collects "
        f"nothing from them and no runner invokes them: {silent}")
