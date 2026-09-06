"""The self-contained scan judges CODE, so a comment must not decide it.

The contract asks a challenge author to keep the test self-contained, and an
author naturally records that in the header:

    // Self-contained: no `include, no $readmem, no file/system/DPI access.

That comment contains the literal tokens the forbidden-construct pattern looks
for, so `_CHALLENGE_FORBIDDEN.search(source)` on the RAW text rejected the file
for DECLARING its compliance. Measured 2026-09-06 on an RTLLM clean-room run:
TEN reviews came back `verification test is not self-contained` while all ten
files were clean once comments were stripped — a fifth of the dataset lost to a
guard a comment could flip.

The fix must not blunt the guard, so both directions are pinned here: prose can
no longer cause a rejection, and every real construct is still caught —
including one placed AFTER a comment on the same line, which a naive
line-dropping strip would miss.
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import benchmark_dispatch as B  # noqa: E402


#: The exact header that cost ten reviews.
_DECLARING_COMMENT = (
    "// Self-contained: no `include, no $readmem, no file/system/DPI access.\n"
    "module tb; initial $display(\"VIBEIC_AI_CHALLENGE=PASS\"); endmodule\n"
)


def test_a_comment_declaring_compliance_is_not_a_violation():
    """THE REGRESSION. The raw-text scan rejected this; the code is clean."""
    assert B._CHALLENGE_FORBIDDEN.search(_DECLARING_COMMENT), (
        "the raw pattern is expected to match this comment — that is the whole "
        "reason the scan must not be run on raw text; if this ever stops "
        "matching, this test is no longer pinning the defect it was written for")
    assert not B._challenge_forbidden_hit(_DECLARING_COMMENT), (
        "a challenge was rejected for a COMMENT that names the forbidden "
        "constructs while the code uses none of them")


def test_a_block_comment_cannot_cause_a_rejection_either():
    src = ("/* This test reads no external files:\n"
           "   no `include, no $readmemh, no DPI. */\n"
           "module tb; initial $display(\"VIBEIC_AI_CHALLENGE=PASS\"); endmodule\n")
    assert not B._challenge_forbidden_hit(src)


def test_every_real_construct_is_still_caught():
    """THE BIDIRECTIONAL CONTROL. Softening the scan must not soften it into
    nothing: a guard that accepts everything passes the tests above."""
    for label, src in (
        ("readmemh", 'module t; initial $readmemh("f.hex", m); endmodule'),
        ("readmemb", 'module t; initial $readmemb("f.bin", m); endmodule'),
        ("include", '`include "other.v"\nmodule t; endmodule'),
        ("fopen", 'module t; integer h; initial h = $fopen("x"); endmodule'),
        ("fread", 'module t; initial $fread(m, h); endmodule'),
        ("fscanf", 'module t; initial $fscanf(h, "%d", v); endmodule'),
        ("system", 'module t; initial $system("ls"); endmodule'),
        ("DPI", 'import "DPI-C" function int f(); module t; endmodule'),
    ):
        assert B._challenge_forbidden_hit(src), f"{label} is no longer caught"


def test_a_violation_after_a_comment_on_the_same_line_is_caught():
    """A line-oriented strip that dropped whole lines would miss this."""
    src = ('module t; // set up the memory\n'
           ' initial $readmemh("f.hex", m);\n'
           'endmodule\n')
    assert B._challenge_forbidden_hit(src)

    tail = '/* preamble */ module t; initial $fopen("x"); endmodule'
    assert B._challenge_forbidden_hit(tail)


def test_a_path_inside_a_string_is_not_stripped_away():
    """String literals are deliberately kept: the argument is what makes
    `$readmemh("f.hex", m)` a real call rather than an identifier."""
    src = 'module t; initial $readmemh("some/deep/path.hex", m); endmodule'
    assert B._challenge_forbidden_hit(src)


def test_the_call_sites_use_the_comment_aware_helper():
    """The helper is worth nothing if a call site still scans raw text."""
    source = (_PROGRAMS / "benchmark_dispatch.py").read_text(encoding="utf-8")
    assert "_CHALLENGE_FORBIDDEN.search(source)" not in source, (
        "a call site still scans the raw challenge text; route it through "
        "_challenge_forbidden_hit so comments cannot decide the verdict")
