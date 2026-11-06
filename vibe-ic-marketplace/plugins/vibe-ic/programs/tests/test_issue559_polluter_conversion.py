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
