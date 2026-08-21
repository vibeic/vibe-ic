#!/usr/bin/env python3
"""Tests for spec_lint_review_detect — the lint-review-task detector."""
import importlib.util
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "spec_lint_review_detect", _PROGRAMS / "spec_lint_review_detect.py")
_M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_M)
detect = _M.detect_lint_review


# The real cvdp_copilot_IIR_filter_0019 prose shape (the coverage-gap case).
IIR = """\
The `iir_filter` module maintains historical input and output values. However,
the module contains several lint issues that may impact synthesis or simulation.

Perform a **LINT code review** on the `iir_filter` module, addressing the
following issues:

- **Unused parameter**
- **Width mismatch**
- **Latch inference**
- **Undriven signal**
- **Combinational logic in sequential block**
- **Uninitialized register**

Only provide the **Lint-clean RTL code** in the response.
"""


def test_iir_detects_lint_review():
    r = detect(IIR)
    assert r["is_lint_review"] is True
    assert "lint-code-review" in r["evidence"] or "lint-clean" in r["evidence"]
    assert r["requirement"] and "verilator" in r["requirement"].lower()


def test_iir_enumerates_named_issues():
    r = detect(IIR)
    got = set(r["issues_requested"])
    for expected in ("unused-parameter", "width-mismatch", "latch-inference",
                     "undriven-signal", "comb-in-seq-block",
                     "uninitialized-register"):
        assert expected in got, f"missing {expected}: {got}"


def test_two_named_issues_alone_fire():
    # without the formal "LINT code review" header, a lint marker + ≥2 named lint
    # classes (incl. the reversed "inferred latch" wording) still = lint task
    txt = ("Fix the following lint issues in this module: a width mismatch and "
           "an inferred latch.")
    r = detect(txt)
    assert r["is_lint_review"] is True
    assert set(r["issues_requested"]) >= {"width-mismatch", "latch-inference"}


def test_passing_mention_does_not_fire():
    # a design prompt that merely PROMISES clean lint is NOT a lint-review task
    txt = ("Design a 16-bit adder with carry-out. The reference implementation "
           "is written so it will not produce any lint warnings.")
    r = detect(txt)
    assert r["is_lint_review"] is False, r["evidence"]


def test_plain_functional_prompt_does_not_fire():
    r = detect("Design a UART transmitter at 115200 baud with a 50 MHz clock.")
    assert r["is_lint_review"] is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
