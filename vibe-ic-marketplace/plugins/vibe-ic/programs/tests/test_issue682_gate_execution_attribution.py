"""#682 — a gate that never ran read exactly like one that passed.

`flow_compliance_check` reported a STEP's verdict and never named the GATE that
produced it. Only the failing branches wrote the command; a gate that ran and
passed left no trace. So `grep -c <gate> flow_compliance_check.log` returned 0
for a gate that had just written `{"verdict": "FAIL", "rc": 1}`, 0 for one that
certainly ran, and 0 for one that was never wired — three different facts, one
answer.

It cost a false alarm: a round-report concluded from that grep that
`drv_promotion_corroboration` writes a blocking FAIL the compliance gate never
reads. Verified false — the gate is wired at step 23, it ran, it wrote its
verdict, and step 23 was FAIL. The inference only looked sound because the record
could not separate "never read" from "not recorded".

MEASURED after the fix, on the caravel_user_project x sky130A cell:

    GATE EXECUTION LEDGER: 74 invocation(s)
      GATE_RAN formal_proof_evidence_check         rc=0   PASS
      GATE_RAN cpu_functional_oracle_waiver_check  rc=1   FAIL
      ...
    gates recorded as RUN: 71
      drv_promotion_corroboration_check      did NOT run in this cell
      sta_corner_record_completeness_check   did NOT run in this cell

Same shape as #544 ("the run looked clean because the only gate that would have
disagreed had not spoken"), which fixed the AGGREGATION and left the
OBSERVABILITY open.
"""
from __future__ import annotations

import re
import importlib.util
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]





# ── the name a reader greps for ───────────────────────────────────────────




# ── a passing gate is recorded, which is the whole point ──────────────────






# ── the wiring, which is what makes it a record at all ────────────────────


# ──────────────────────────────────────────────────────────────────────
# READING THE WRAPPER'S OWN SOURCE
# ──────────────────────────────────────────────────────────────────────
# THE SLICE WAS THE DEFECT, and it cost a red on main that named the wrong thing.
#
# Three tests below used to extract "the wrapper" as the TEXT BETWEEN two `def`
# names -- `src[index("def _check_program_exit_zero") :
# index("def __check_program_exit_zero")]`. Nothing keeps those two definitions
# adjacent. #2501's receipt redirect landed `_resolved_key` and
# `_receipt_off_a_produced_document` in the gap, and their PROSE says "the readers
# run AFTER the subprocess" and "subprocess call" -- so
# `assert "subprocess" not in wrapper` went red on a property that is TRUE.
#
# MEASURED on main 1f537b5c0: the wrapper's own source is 213 lines, carries all
# three hint sentinels, and contains no `subprocess` at all; the slice dragged in
# 102 further lines defining two unrelated helpers.
#
# So the extraction is now by AST -- the function's OWN segment, whatever sits
# after it -- and the search runs over CODE with comments and string literals
# blanked. That is strictly stronger than the slice in both directions: a
# subprocess call added to the wrapper is still caught, and prose about one
# anywhere in the module is not.


def _code_only(text: str) -> str:
    """`text` with comments and string literals blanked, so a token search reads
    CODE. Length and line structure are preserved so an index into the result
    still points at the right line."""
    import io
    import tokenize
    out = list(text)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                (r1, c1), (r2, c2) = tok.start, tok.end
                lines = text.splitlines(keepends=True)
                base = sum(len(l) for l in lines[:r1 - 1])
                start = base + c1
                end = (sum(len(l) for l in lines[:r2 - 1]) + c2)
                for k in range(start, min(end, len(out))):
                    if out[k] != "\n":
                        out[k] = " "
    except (tokenize.TokenError, IndentationError):
        # A fragment that does not tokenize on its own is returned unchanged:
        # conservative, since the only cost is a search that also reads prose.
        return text
    return "".join(out)










# ── the repaired instrument, driven in both directions ─────────────────────







def test_code_only_blanks_strings_and_keeps_the_line_shape():
    """`_code_only` is load-bearing for both arms above, so it is driven directly:
    a token inside a literal is gone, a token in code survives, and the line
    count does not move (an index into the result still points at the right
    line)."""
    src = ('x = "subprocess in a literal"  # and in a comment\n'
           'import subprocess\n')
    out = _code_only(src)
    assert out.count("\n") == src.count("\n")
    assert out.splitlines()[0].count("subprocess") == 0, out.splitlines()[0]
    assert "subprocess" in out.splitlines()[1]
