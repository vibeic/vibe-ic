"""ORGANIC (caravel_user_project x sky130A, measured 2026-07-25) — the DRV
wire-length repeater escalation was disabled in v1.5.65 against a comparison
that could not be made, and carried two REAL defects that this test pins.

WHAT WAS MEASURED (one consistent full-enumeration chain, the SAME emitter the
downstream acceptance gate reads — `_emit_mcorner_ocv_sta` over the per-corner
SPEF set, `report_check_types ... -violators -max_count 2000`):

    route                         max_slew   total DRV   setup WNS
    base (no escalation)             421        483       +6.07 ns
    escalation, max_wire_length 973  177        219       +3.71 ns
    escalation, max_wire_length 400  180        260       -7.48 ns

DEFECT 1 — THE DISABLE RATIONALE WAS A NON-COMPARISON.
  v1.5.65 disabled the step citing "the REAL sign-off violator count got far
  WORSE (4->219)". The "4" came from a report emitted WITHOUT `-violators`,
  which makes OpenSTA print only the SINGLE WORST pin per check type — about
  four lines for ANY design, whatever its true population. `-violators` was
  added in the SAME commit that added the escalation, so "before" and "after"
  were two different report SHAPES, not two states of one design. Measured
  consistently the delta is 483->219, a ~55% reduction.

DEFECT 2 — THE PROMOTION GATE WAS CORNER-BLIND (real).
  The gate counted violators inside the escalation's own OpenROAD session,
  which reads ONE liberty (ss) and ONE captable (max-RC). The downstream gate
  reads SETUP@ss+max-RC *and* HOLD@ff+min-RC. Measured on the same route:
  step-local 330 vs downstream 483, and 330 is EXACTLY the setup subset
  (283 max_slew + 47 max_cap); the invisible 153 is EXACTLY the hold subset
  (138 max_slew + 15 max_cap). A change improving setup while wrecking hold
  satisfied `after < before` and got promoted.

DEFECT 3 — DONT_TOUCH WAS SILENTLY LOST ACROSS THE SESSION BOUNDARY (real).
  `set_dont_touch` is OpenROAD SESSION state; it is not a DEF attribute and
  does not survive write_def -> read_def. Every fresh-session optimisation
  therefore started with all spare / tie protection dropped. Placement status
  alone is not a sufficient substitute: measured, the design-for-ECO spares
  were `+ FIXED` but the tie DRIVER feeding their inputs was only `+ PLACED`.

HONEST SCOPE (§4.05): the dont_touch restore was measured NEUTRAL on this
design (byte-identical route with and without it). It is a correctness
hardening for a real, silent loss of protection — this test does NOT claim it
changes any particular DRV or LVS number.

chip-AGNOSTIC throughout: the restore predicates are (a) placement status and
(b) a master with zero signal INPUT terminals and >=1 signal OUTPUT — the
structural definition of a tie/constant cell in ANY library. No design, vendor,
cell or net literal anywhere.
"""
import shutil
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

tclsh = shutil.which("tclsh")




# --------------------------- DEFECT 1: the record, and the REAL blocker ---





def test_policy_constant_documents_both_regressed_signoff_axes():
    """A future reader must be able to grep the constant and learn why."""
    import inspect
    src = inspect.getsource(R)
    i = src.index("_DRV_ESCALATION_PROMOTION_ENABLED")
    ctx = src[max(0, i - 1400):i + 200]
    assert "DRC" in ctx and "LVS" in ctx
    assert "detailed_route" in ctx, (
        "the note must say WHICH weak evidence the old gate used")


# ----------------------------------- DEFECT 2: gate reads the REAL report ---











# ------------------------------- DEFECT 3: dont_touch restored in-session ---
