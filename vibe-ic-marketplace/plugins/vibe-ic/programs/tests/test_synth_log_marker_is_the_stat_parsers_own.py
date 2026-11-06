"""The synth-log marker is the stat PARSER's, not a second spelling of it (icspm2).

MEASURED FAILURE THIS PINS
==========================
A completed gf180mcuD run of `spm` (2026-09-15, lane icspm2) synthesised
perfectly — 449 cells, 65 `$_DFF_P_`, `Found and reported 0 problems`, two
complete `stat` tables in a 691-line `phase2/stage2/synth/yosys.log` — and

    reports/phase2/gates/synth_log_audit.json
        "expect_matched": [], "reject_matched": [], "pass": false
        ERROR EXPECTED_NOT_FOUND: None of the expected patterns were found
        details: Expected patterns: ['Number of cells', 'Number of wires']

    reports/phase2/gates/eda_log_check_receipt.json   verdict: FAIL

    step_internal_fail_bubble_up_check
        [STEP_FAIL_NOT_BUBBLED] reports/phase2/gates/eda_log_check_receipt.json
                                verdict=FAIL                            rc 1

`grep -n "Number of" <that log>` returns NOTHING. The shipped image's yosys
(0.68+) writes the BARE stat form:

    === spm ===
            +----------Local Count, excluding submodules.
          714 wires
          449 cells

`design_one_shot_runner._SYNTH_LOG_EXPECT` asserted the LABELLED form alone,
while `_yosys_stat` — the runner's own stat parser, called from the very step
that writes this log — has known all three forms since v1.7.36. Two gates went
red on a correct synthesis because one assertion was written from memory
instead of from the parser.

THE PROPERTY
============
If `_yosys_stat` can read a stat block out of a log, the synth-log audit passes
over that same log; if it cannot, the audit fails. Anything else is the drift
that caused the defect.
"""
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _yosys_stat as _ystat          # noqa: E402


HEAD = """\
-- Running command `read_verilog -sv /p/phase2/stage1/rtl/spm.v; synth -top spm; stat' --

1. Executing Verilog-2005 frontend: /p/phase2/stage1/rtl/spm.v
2. Executing SYNTH pass.
"""

# The shipped image's form, copied from the measured log.
BARE_STAT = HEAD + """\
8. Printing statistics.

=== spm ===

        +----------Local Count, excluding submodules.
        |
      714 wires
      869 wire bits
        5 ports
      449 cells
       65   $_DFF_P_
      221   $_NAND_

End of script. Logfile hash: fca6275efd
"""

LABELLED_STAT = HEAD + """\
8. Printing statistics.

=== spm ===

   Number of wires:                714
   Number of wire bits:            869
   Number of cells:                449
     $_DFF_P_                       65

End of script.
"""

LIBERTY_STAT = HEAD + """\
8. Printing statistics.

=== spm ===

      349 5.84E+03 cells
       64 3.14E+03   sg13g2_dfrbpq_1

   Chip area for module '\\spm': 5841.196200
"""

# A synthesis that died before `stat` — the gate MUST still bite.
NO_STAT = HEAD + """\
ERROR: Module `\\spm' referenced in module `\\top' in cell `\\u0' is not part of the design.
"""






# ---------------------------------------------------------------------------
# DIRECTION 1 — the measured false failure is gone
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# DIRECTION 2 — the gate still bites
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# THE BINDING ITSELF — not a re-typed copy
# ---------------------------------------------------------------------------


def test_no_published_pattern_carries_the_split_metacharacter():
    """`eda_log_check` SPLITS --expect-pattern on `|` before compiling, so a
    pattern containing one would be torn in half and silently never match."""
    for pat in _ystat.CELL_COUNT_LINE_PATTERNS:
        assert "|" not in pat, pat




def test_the_published_patterns_are_the_ones_the_parser_compiles():
    """`_yosys_stat`'s own regexes are compiled FROM the published strings."""
    assert _ystat._LABELLED_CELLS_RE.pattern == _ystat.CELL_COUNT_LINE_PATTERNS[0]
    assert _ystat._BARE_CELLS_RE.pattern == _ystat.CELL_COUNT_LINE_PATTERNS[1]


# ---------------------------------------------------------------------------
# END TO END through the runner's own step
# ---------------------------------------------------------------------------
