"""Negative control for the timing-driven-buffer DPL-0036 legalization fix.

ROOT CAUSE (MEASURED — gf180mcuD ``subservient`` converge_1.5.65,
``phase3/stage3/pnr/openroad.log``):

    [INFO RSZ-0038] Inserted 564 buffers in 155 nets.
    [INFO DPL-0034] Detailed placement failed on the following 13 instances: ...
    [ERROR DPL-0036] Detailed placement failed inside DPL.
    Error: pnr.tcl, 137 DPL-0036

``global_placement -timing_driven`` runs repair_design DURING global placement
and inserts high-drive buffers on ultra-high-fanout nets (a 1273-sink clock
spine here). The WIDEST — the PDK drive-20 buffer (34.72 µm = 62 placement
sites) — cannot be legalized: at 42 % utilization the free area is fragmented,
so NO contiguous run of 62 empty sites exists anywhere reachable. PROVEN in the
container (OpenROAD 26Q3, real cells): even a full-die diamond search
(±3571 sites × ±510 rows) leaves the four drive-20 buffers un-placed
(``check_placement`` DPL-0033). The OLD template emitted a single, DEFAULT
window, UNGUARDED ``detailed_placement`` right after ``global_placement``, so
it hard-fails DPL-0036 and kills the flow BEFORE ``placed.def`` exists — and
``placement_legality_check`` (Step 17) then FAILs on the missing DEF.

THE NEGATIVE CONTROL (``test_no_bare_unguarded_legalize_after_global_placement``
and ``test_escalation_uses_measured_die_geometry``) FAILS on the pre-fix
template — the pre-fix emits exactly the bare ``detailed_placement`` these
tests forbid, and emits no full-die ``-max_displacement`` escalation — and
PASSES only once the escalating, guarded legalizer is in place.

PROOF the FIX works on real cells (manual, container run — reproduced then
fixed the identical scenario): 13 → 0 placement failures, ``check_placement``
clean, pre-CTS worst slack UNCHANGED (−21.33 ns vs −21.44 ns). See the
HANDOFF for the full end-to-end (route/DRC/LVS/multi-corner) validation.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_phase3_routability_driven_placement as B  # reuse the real _build
import phase3_one_shot_runner as R  # noqa: E402

_build = B._build
_command_lines = B._command_lines
_gp_cmd_lines = B._gp_cmd_lines
_gp_fallback_lines = B._gp_fallback_lines

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")


def _dpl_lines(tcl: str):
    """Every command line whose first token is ``detailed_placement``."""
    return [ln for ln in _command_lines(tcl)
            if ln.lstrip().split(" ", 1)[0] == "detailed_placement"]


# ── NEGATIVE CONTROL #1: the exact defect must be gone ─────────────────────

def test_no_bare_unguarded_legalize_after_global_placement():
    """The primary global_placement must NOT be followed by a bare, top-level
    (unguarded) ``detailed_placement`` — that lone call is the DPL-0036 flow
    killer. Every legalize call must instead be inside a ``catch`` (escalating
    legalizer) OR carry an explicit ``-max_displacement`` escalation.

    FAILS on the pre-fix template (which emits ``\\ndetailed_placement\\n`` at
    column 0 right after global_placement); PASSES post-fix.
    """
    tcl = _build()
    lines = tcl.splitlines()
    gp_idx = [i for i, ln in enumerate(lines)
              if ln.startswith("global_placement")]
    assert gp_idx, "expected a primary global_placement"
    # The line immediately following the PRIMARY global_placement must not be a
    # bare, column-0 `detailed_placement` (that is the removed defect).
    after = lines[gp_idx[0] + 1].rstrip()
    assert after != "detailed_placement", (
        "regression: bare unguarded `detailed_placement` re-introduced right "
        "after global_placement — this is the DPL-0036 flow killer")
    # Stronger: there must be NO top-level (column-0) bare detailed_placement
    # BETWEEN the primary global_placement and the placed.def write, because a
    # column-0 legalize is not wrapped in the escalating `catch`.
    try:
        placed = next(i for i, ln in enumerate(lines)
                      if "write_def" in ln and "placed.def" in ln)
    except StopIteration:
        placed = len(lines)
    bare = [ln for ln in lines[gp_idx[0] + 1:placed]
            if ln == "detailed_placement"]
    assert not bare, (
        f"unguarded top-level detailed_placement between global_placement and "
        f"placed.def: {bare}")


# ── NEGATIVE CONTROL #2: escalation is MEASURED (die geometry), not a literal ─

def test_escalation_uses_measured_die_geometry():
    """The full-die legalization retry must derive ``-max_displacement`` from
    the design's MEASURED die (die_w × die_h µm) — not a hard-coded number and
    not a design/PDK literal.

    FAILS pre-fix (no ``-max_displacement`` escalation is emitted at all).
    """
    tcl = _build(die_w=1234, die_h=987)
    md = [ln for ln in _command_lines(tcl)
          if "detailed_placement" in ln and "-max_displacement" in ln]
    assert md, "expected a -max_displacement escalation retry"
    assert all("{1234 987}" in ln for ln in md), (
        f"escalation must use the measured die geometry {{1234 987}}: {md}")
    # And a different die must flow through unchanged (proves it is not a
    # hard-coded constant).
    tcl2 = _build(die_w=500, die_h=640)
    assert any("{500 640}" in ln for ln in _command_lines(tcl2)
               if "detailed_placement" in ln)


# ── the fix's structure (all three escalation tiers present & ordered) ──────

def test_escalating_legalizer_has_all_three_tiers():
    tcl = _build()
    # tier 1: guarded default-window legalize
    assert re.search(r"catch\s*\{\s*detailed_placement\s*\}", tcl), \
        "tier-1 guarded default detailed_placement missing"
    # tier 2: full-die displacement retry
    assert re.search(
        r"catch\s*\{\s*detailed_placement -max_displacement", tcl), \
        "tier-2 full-die displacement retry missing"
    # tier 3: exclude the widest optimizer buffer, then re-place
    assert "set_dont_use $_wb" in tcl, "tier-3 widest-buffer exclusion missing"
    assert "_vic_widest_opt_buffer" in tcl, \
        "widest-buffer discovery proc missing"
    # discovery must be by PHYSICAL width via is_buffer (no cell-name literal)
    assert "is_buffer" in tcl and "getWidth" in tcl, \
        "widest buffer must be discovered by is_buffer + master width"


def test_fallback_replacement_matches_primary_command():
    """The tier-3 re-placement must reuse the IDENTICAL global_placement flags
    (routability/timing/density) as the primary — only the buffer pool changed.
    """
    for kw in ({}, {"timing_driven": False},
               {"routability_driven": False, "timing_driven": False}):
        tcl = _build(**kw)
        primary = _gp_cmd_lines(tcl)
        fallback = _gp_fallback_lines(tcl)
        assert len(primary) == 1, f"expected one primary GP: {primary}"
        assert len(fallback) == 1, f"expected one fallback GP: {fallback}"
        assert primary[0].strip() == fallback[0].strip(), (
            f"fallback re-placement must match primary: "
            f"{primary[0]!r} vs {fallback[0]!r}")


def test_hard_errors_rather_than_shipping_overlaps():
    """If even the buffer-excluded full-die re-place fails, the legalizer must
    HARD-``error`` (surfacing a genuine geometry problem) — never silently
    continue and write a placed.def with overlapping cells (which would swap
    DPL-0036 for a DRC-short / LVS-mismatch downstream)."""
    tcl = _build()
    assert re.search(r'error\s+"detailed_placement failed after excluding',
                     tcl), "final tier must hard-error, not mask the failure"


@needs_tclsh
def test_added_legalizer_block_is_valid_tcl():
    """Focused syntax check of JUST the escalating-legalizer block (proc +
    nested if/catch). The WHOLE-template tclsh parse is already pinned by
    test_v0_3_39_issue581_pnr_tcl_syntax; here we parse the added block in
    isolation so a brace/bracket slip in the new Tcl is caught locally."""
    gp = "global_placement -routability_driven -timing_driven -density 0.4"
    block = R._legalize_escalation_tcl(gp_cmd=gp, die_w=839, die_h=839)
    # `info complete` returns 1 iff the string is a syntactically complete Tcl
    # command sequence (balanced braces/brackets/quotes).
    script = f'if {{[info complete {{{block}}}]}} {{ puts COMPLETE }}'
    r = subprocess.run([tclsh], input=script, capture_output=True, text=True)
    assert "COMPLETE" in r.stdout, (
        f"added legalizer Tcl is not brace/bracket-complete: "
        f"{r.stderr}\n{r.stdout}")
