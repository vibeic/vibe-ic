"""#559 — converting `fpga_wrapper_input_polluter_check`, and the third question.

#492's bar has two halves: repairing an argv must not turn a silent skip into a
universal FAIL, and must not turn it into a PASS over an empty denominator.
Both were re-derived over the 107 tracked rtl directories, on a scratch mirror.

Both cleared — and the conversion would still have been wrong, because a gate
can clear both halves precisely BY BEING INCAPABLE OF FAILING:

    $ fpga_wrapper_input_polluter_check.py --rtl <a three-inout AND wrapper>
    Files scanned : 1
    Warnings      : 1          <- it found the exact defect it exists to find
    PASS                       <- rc=0

Without `--strict` a detected polluter is a WARNING and the gate exits 0. Wired
plain it would have passed 107/107 for the same reason it passes a design that
has the defect. `--strict` makes the finding blocking, and the corpus is still
0 FAIL with it on.

So there is a third question, asked here and not in #492: CAN this gate fail?
The injected-polluter test below is that question, and it runs through the
umbrella's own argv builder rather than a re-typed command line — a re-typed
argv agrees with the umbrella by coincidence.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
GATE = "fpga_wrapper_input_polluter_check"

#: A wrapper that ANDs three inout pins — the pattern the gate exists to catch.
POLLUTER_RTL = """\
module fpga_wrap(inout wire pin_a, inout wire pin_b, inout wire pin_c,
                 output wire rx);
  assign rx = pin_a & pin_b & pin_c;
endmodule
"""

#: A wrapper with a single bench-wired pin: the shape that must NOT be flagged.
CLEAN_RTL = """\
module fpga_wrap(inout wire pin_a, output wire rx);
  assign rx = pin_a;
endmodule
"""


def _load_flow():
    spec = importlib.util.spec_from_file_location(
        "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["flow_compliance_check"] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load_flow()


def _run_via_umbrella(rtl_dir: pathlib.Path):
    argv = F._structural_gate_argv(GATE, rtl_dir, rtl_dir=rtl_dir)
    return _pr.run(argv, capture_output=True, text=True)


def test_gate_is_registered_with_an_adapter():
    assert GATE in F._STRUCTURAL_GATE_ARGV_ADAPTERS
    assert F._STRUCTURAL_GATE_ARGV_ADAPTERS[GATE] == ("--rtl",)


def test_strict_is_carried_as_a_bare_flag():
    """`--strict` takes no value; the valued-flag table cannot express it."""
    assert F._STRUCTURAL_GATE_BARE_FLAGS.get(GATE) == ("--strict",)


def test_umbrella_argv_pairs_values_and_appends_bare_flags(tmp_path):
    """The bare flag must arrive with NO path after it."""
    argv = F._structural_gate_argv(GATE, tmp_path, rtl_dir=tmp_path)
    assert argv[-1] == "--strict", argv
    assert argv[-3:-1] == ["--rtl", str(tmp_path)], argv


def test_bare_flags_do_not_leak_into_other_gates(tmp_path):
    """A gate with no bare-flag entry must keep the argv it had."""
    argv = F._structural_gate_argv("sustained_vs_edge_check", tmp_path,
                                   rtl_dir=tmp_path)
    assert argv[1:] == [str(_PROGRAMS / "sustained_vs_edge_check.py"),
                        "--rtl-dir", str(tmp_path)], argv


def test_the_gate_can_fail(tmp_path):
    """The third question. Without this the two #492 halves are satisfiable by
    a checker that never returns non-zero."""
    (tmp_path / "wrap.v").write_text(POLLUTER_RTL, encoding="utf-8")
    proc = _run_via_umbrella(tmp_path)
    assert proc.returncode == 1, (
        "the umbrella's argv does not make a detected polluter blocking; "
        f"rc={proc.returncode}\n{(proc.stdout + proc.stderr)[:600]}")


def test_without_strict_the_same_input_passes(tmp_path):
    """Pins WHY the bare flag is load-bearing rather than decorative.

    If this ever starts failing, `--strict` has stopped being what makes the
    finding blocking, and the adapter entry needs re-deriving rather than
    trusting.
    """
    (tmp_path / "wrap.v").write_text(POLLUTER_RTL, encoding="utf-8")
    proc = _pr.run(
        [sys.executable, str(_PROGRAMS / f"{GATE}.py"), "--rtl", str(tmp_path)],
        capture_output=True, text=True)
    assert proc.returncode == 0
    assert re.search(r"Warnings\s*:\s*[1-9]", proc.stdout), (
        "expected the polluter to be DETECTED but not blocking without "
        f"--strict: {proc.stdout!r}")


def test_a_clean_wrapper_passes(tmp_path):
    """The accept case. Without it, a gate that failed everything would satisfy
    every other assertion here."""
    (tmp_path / "wrap.v").write_text(CLEAN_RTL, encoding="utf-8")
    proc = _run_via_umbrella(tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[:600]


def test_denominator_is_stated_and_non_empty(tmp_path):
    """Half two of #492, at the single-project level.

    The corpus sweep measured `Files scanned` between 1 and 102 and never 0
    across all 107 directories; this pins that the field exists at all, since a
    sweep cannot run in a unit test.
    """
    (tmp_path / "wrap.v").write_text(CLEAN_RTL, encoding="utf-8")
    proc = _run_via_umbrella(tmp_path)
    m = re.search(r"Files scanned\s*:\s*(\d+)", proc.stdout)
    assert m, f"gate does not state its denominator: {proc.stdout!r}"
    assert int(m.group(1)) == 1, proc.stdout


def test_empty_rtl_dir_is_not_a_silent_pass(tmp_path):
    """An empty directory must not read as a clean project.

    Not asserted as a specific exit code: what matters is that the output does
    not claim a scan it did not perform. If the gate ever starts reporting
    `Files scanned : 0` alongside PASS, that is the vacuous shape returning.
    """
    proc = _run_via_umbrella(tmp_path)
    m = re.search(r"Files scanned\s*:\s*(\d+)", proc.stdout)
    if m and int(m.group(1)) == 0:
        assert proc.returncode != 0, (
            "gate reports 0 files scanned and still exits 0; a project with no "
            "RTL would be certified as having no polluter")
