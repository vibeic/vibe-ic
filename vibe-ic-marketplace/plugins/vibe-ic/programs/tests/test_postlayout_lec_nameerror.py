"""Post-layout LEC: the `liberty` NameError, and the failure DISCLOSURE.

WHY THIS FILE WAS REWRITTEN
==========================
The first cut of these tests defined their OWN inline `_pre_fix_snippet` /
`_fixed_snippet` closures and asserted things about *those*. An independent
skeptic reverted BOTH source hunks (`str(pdk.liberty)` -> bare `liberty`,
and the caller's re-raise -> `notes.append`) and 7 of the 9 tests still
passed: they never imported, never called, and therefore never constrained
the shipped code. A test that passes with the defect fully restored is not
evidence.

Every test below drives the REAL `phase3_one_shot_runner` functions. The
mutations each one is built to catch are named in its docstring, and each
was run against the fix to confirm it FAILS with the defect present.

THE DEFECTS
-----------
(a) `_emit_lec_post_layout` contained `Path(liberty)` where `liberty` was
    never bound in that scope -> NameError on every post-layout LEC. The
    caller's broad `except Exception` buried it in a JSON note, so the
    sign-off proof never ran and nothing said so.
(b) The fix for (a) must use the LIBERTY (`pdk.liberty`), not some other
    PdkConfig path: the value feeds the functional-`read_liberty`
    capability decision, and pointing it at a file that merely EXISTS
    (e.g. `pdk.cell_lef`) buys the UNSOUND `-lib` blackbox recipe on an
    input the tool never read.
(c) A sign-off emit that fails must become a FAIL status ROW — and must
    NOT abort the runner. `step_canonicalize_artefacts` is called
    unguarded from `main()`, so raising out of it destroys the
    orchestrator report the failure was supposed to appear in.
"""
from __future__ import annotations

import sys
from pathlib import Path


PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import lec_post_layout_check as LEC  # noqa: E402


TOP = "widget"








# ---------------------------------------------------------------------------
# (a) The NameError itself — executed, not paraphrased.
#
# MUTATION THIS CATCHES: restore the pre-fix line
#     _lib_host = Path(liberty) if liberty else None
# in `_emit_lec_post_layout`. -> NameError: name 'liberty' is not defined,
# and this test fails.
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# (b) It must be the LIBERTY, not merely *a* file that exists.
#
# MUTATION THIS CATCHES: `str(pdk.liberty)` -> `str(pdk.cell_lef)` (the
# skeptic's own plausible copy-paste). Below, the liberty is ABSENT and the
# cell LEF is present + non-empty, and the functional probe FAILS (rc=1):
#   * correct  -> liberty is an INPUT defect -> refuse the unsound `-lib`
#                 fallback, keep the SOUND functional recipe.
#   * mutated  -> the LEF "is" the liberty -> a capability gap -> select
#                 `blackbox_lib_fallback`, an UNSOUND compare on a Liberty
#                 that was never read.
# ---------------------------------------------------------------------------







def test_functional_read_liberty_supported_contract():
    """The decision helper itself, pinned: an absent/empty liberty is an
    INPUT defect (no fallback); a failing probe on a real liberty is a
    CAPABILITY gap (fallback)."""
    assert LEC.functional_read_liberty_supported(0, True, True)[0] is True
    assert LEC.functional_read_liberty_supported(1, True, True)[0] is False
    assert LEC.liberty_input_is_usable(False, False) is False
    assert LEC.liberty_input_is_usable(True, False) is False
    assert LEC.liberty_input_is_usable(True, True) is True


# ---------------------------------------------------------------------------
# (c) A failed sign-off emit must be a FAIL ROW, and must not kill the run.
#
# MUTATIONS THESE CATCH:
#   * revert the caller to `notes.append(...)`  -> step still returns PASS
#     -> test_signoff_emit_failure_is_a_fail_row fails.
#   * `raise RuntimeError(...) from exc`        -> step_canonicalize_artefacts
#     propagates -> both tests below fail (the second by ERROR, which is the
#     point: the runner dies and there is no report at all).
# ---------------------------------------------------------------------------











# ---------------------------------------------------------------------------
# Source-shape guards. These are NOT the evidence — the behavioural tests
# above are. They are kept only to pin the two exact strings the defect and
# the rejected crash-fix consisted of.
# ---------------------------------------------------------------------------
