"""Sign-off DRC gate must read the router DRC report's LAST iteration count.

DEFECT (vibe-ic, signoff_audit.py:1423-1425). The tapeout sign-off audit's
plain-text DRC reader `_drc_violation_count` extracts the violation count with
`re.search`, which returns the FIRST match. A detailed-route DRC report is
ITERATIVE — the router prints one running count per repair iteration
(`[INFO DRT-0199]  Number of violations = N`) and a report may hold more than
one route pass — so `re.search` reads the state BEFORE any repair. That first
count can be:

  * LARGER  than the final count → over-report → false FAIL on a clean design;
  * SMALLER than the final count → under-report → false PASS on a design that
    NEVER CONVERGED — the serious half: a sign-off gate silently passing dirty
    geometry.

Meanwhile the SAME plugin's `phase3_one_shot_runner._drt_final_violations`
documents "Uses the LAST" and returns `counts[-1]`. Two readers, one grammar,
different answers, by construction.

FIX. Both readers now route through one shared helper
`_signoff_drc_format.router_iter_last_count`, which takes the LAST count.

This test drives the REAL nested `_drc_violation_count` bytes (extracted from
`signoff_audit._check_tapeout` via AST, exec'd against the module's own
globals) so it is a genuine bidirectional negative control: it FAILs against
the byte-identical pre-fix program (which returns the first count) and PASSes
after. All four brief fixtures are covered — A (monotone-to-zero), B (two route
passes, non-monotone), C (single count), D (no count → must be None, not 0) —
plus the earlier-format branches (invariant 2) and reader agreement
(invariant 4).

Fixtures reproduce §3 of DEFECT_BRIEF.md verbatim; integers are the brief's
disclosed placeholders. No PDK, no design, no EDA tool.
"""
from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

import _signoff_drc_format as _sdf  # noqa: E402  the shared home


# --------------------------------------------------------------------------- #
# Extract the REAL nested `_drc_violation_count` from `_check_tapeout` so the   #
# test exercises the gate's actual source bytes, not a re-implementation.      #
# --------------------------------------------------------------------------- #


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return p


# --------------------------------------------------------------------------- #
# The four brief fixtures (§3, §5.2), verbatim structure.                       #
# --------------------------------------------------------------------------- #
FIXTURE_A = (
    "# router DRC report (SYNTHETIC FIXTURE - no PDK, no design)\n"
    "violation count summary: 0 violation(s) found\n"
    "drc source: final [INFO DRT-0199] count\n"
    "[INFO DRT-0199]   Number of violations = 100.\n"
    "[INFO DRT-0199]   Number of violations = 40.\n"
    "[INFO DRT-0199]   Number of violations = 10.\n"
    "[INFO DRT-0199]   Number of violations = 0.\n"
)
FIXTURE_B = (
    "# router DRC report (SYNTHETIC FIXTURE - no PDK, no design)\n"
    "drc source: final [INFO DRT-0199] count\n"
    "[INFO DRT-0199]   Number of violations = 5.\n"
    "[INFO DRT-0199]   Number of violations = 2.\n"
    "[INFO DRT-0199]   Number of violations = 0.\n"
    "[INFO DRT-0199]   Number of violations = 90.\n"
    "[INFO DRT-0199]   Number of violations = 30.\n"
    "[INFO DRT-0199]   Number of violations = 7.\n"
)
FIXTURE_C = (  # single count — "take the last" must degrade to "take the only"
    "# router DRC report (SYNTHETIC FIXTURE - no PDK, no design)\n"
    "[INFO DRT-0199]   Number of violations = 12.\n"
)
FIXTURE_D = (  # no count lines at all — must read None, never 0
    "# router DRC report (SYNTHETIC FIXTURE - no PDK, no design)\n"
    "this file was truncated before any iteration count was written\n"
)


# --------------------------------------------------------------------------- #
# 1. The gate reader itself — the bidirectional negative control.              #
#    Pre-fix these assert-7 / assert-0 lines fail (gate returns 5 / 100).      #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 2. Invariant 2 — the earlier format branches still win, not shadowed.        #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 3. The shared helper — the single implementation both readers now use.       #
# --------------------------------------------------------------------------- #
def test_shared_helper_takes_last():
    assert _sdf.router_iter_last_count(FIXTURE_A) == 0
    assert _sdf.router_iter_last_count(FIXTURE_B) == 7
    assert _sdf.router_iter_last_count(FIXTURE_C) == 12
    assert _sdf.router_iter_last_count(FIXTURE_D) is None


def test_shared_helper_completing_fallback():
    # older builds print no DRT-0199 line — fall back to Completing 100% with N,
    # still LAST.
    log = (
        "Completing 100% with 42 violations.\n"
        "Completing 100% with 3 violations.\n"
    )
    assert _sdf.router_iter_last_count(log) == 3


# --------------------------------------------------------------------------- #
# 4. Invariant 4 — the two readers agree BY CONSTRUCTION, on every fixture.     #
# --------------------------------------------------------------------------- #
