"""Phase-3 CONGESTION-DRIVEN (routability-driven) global placement.

A full-OpenTitan-class AES peripheral (~39k cells) has high-fanout crypto
datapath nets (SBox / MixColumns wide-XOR trees, key-schedule fanout) that
create detailed-route congestion, so the design only routes at a very sparse
die. OpenROAD's `global_placement -routability_driven` (RePlAce routability
mode) estimates routing congestion during placement and spreads / inflates
cells in congested regions so such a design can route at a denser die. It is
a placement-QUALITY knob: it changes NOTHING about connectivity or logic and
OpenROAD reverts the routability loop if it diverges — so `_build_pnr_tcl_text`
emits it by DEFAULT (chip-AGNOSTIC, applies to every design).

`placement_padding_sites` is an OPTIONAL, version-correct extra congestion
knob (`set_placement_padding -global`), left OFF by default (padding changes
every design unconditionally).

HONESTY: this is the STANDARD OSS mechanism for a congested design; it does
NOT by itself GUARANTEE a denser route. The empirical benefit (does AES now
route at a denser die?) needs a live PnR run to confirm — these tests pin the
EMITTER (correct flag + well-formed TCL + no structural regression), not the
routing outcome.

Flag names verified against the container's OpenROAD 26Q1-990-g15af3a5c0:
    global_placement [...] [-routability_driven] [...] [-density target_density]
    set_placement_padding -global|-masters|-instances [-right N] [-left N]
Both parse cleanly (a bare `global_placement -routability_driven -density 0.5`
errors only with `GPL-0130 No rows defined` — a runtime "no design" error, not
"unknown option").
"""
import re
import shutil
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

tclsh = shutil.which("tclsh")
sys.path.insert(0, str(Path(__file__).resolve().parent))










# ── default: routability-driven is ON, density kept, exactly once ──────────







# ── gate branch: routability can be turned OFF (chip-AGNOSTIC signal) ───────



# ── optional padding knob: OFF by default, correct syntax when enabled ─────









# ── well-formedness: balanced braces + real tclsh parse ────────────────────





# ── regression: the rest of the template is UNCHANGED in structure ─────────



# An anchor is a STAGE COMMAND, not a token. The docstring above protects the
# order in which the flow's stages RUN; `str.find` answered a different
# question -- where the word first appears -- and the deck legitimately names
# `global_route` long before it calls it: the route-guide discipline preamble
# (982c8d222) asks `info commands global_route`, `rename`s it and wraps it in a
# `proc` at line 16 of the emitted deck, while the stage's own call is at line
# 608. The substring match read that preamble as the global_route stage and
# reported "out of order" for a deck whose stages had not moved.
#
# A command word is one that begins a Tcl command: at line start, or directly
# after `{`, `[` or `;` (which covers `if {[catch {detailed_route ...`). A word
# used as an ARGUMENT -- `info commands global_route`, `rename global_route`,
# `proc global_route`, a comment -- is not a command and cannot stand in for a
# stage. Every anchor must still be present and still in order.






# ── container OpenROAD flag verification (runs where openroad is on PATH) ───

@pytest.mark.skipif(shutil.which("openroad") is None,
                    reason="openroad not on PATH (container-only tool)")
def test_openroad_accepts_routability_driven_flag():
    """When openroad is reachable (inside the iic-osic-tools container CI),
    assert `help global_placement` advertises the exact flags we emit."""
    res = _pr.run(
        ["openroad", "-no_init", "-exit"],
        input="help global_placement\n",
        capture_output=True, text=True)
    out = res.stdout + res.stderr
    assert "-routability_driven" in out
    assert "-timing_driven" in out
    assert re.search(r"-density\s+target_density", out)


# -- timing-driven placement: DEFAULT-ON slack-weighted global placement ----
# ORGANIC (sha256 x sky130A): routability_driven placement left the SS
# post-route setup WNS deeply negative because global placement was BLIND to
# the 25.907 ns clock. `-timing_driven` net-weights placement by setup slack so
# critical-path cells cluster. Negative control: git-checkout the pre-fix runner
# -> these assertions fail (no global_placement line carries -timing_driven).










# ── approach (a): multi-corner liberty for the PnR session (ss setup/ff hold) ──
# Repair the SLOW (ss) setup corner BEFORE detailed route by loading the PDK's
# OWN ss/tt/ff corner libs into the PnR session (define_corners + read_liberty
# -corner), so repair_timing -setup optimizes ss instead of only tt. RED on the
# pre-fix runner: `_build_pnr_tcl_text` has no `corner_liberty_block` kwarg
# (TypeError) and `_v1_5_37a_multicorner_pnr_block` does not exist
# (AttributeError) — every assertion below fails until the fix is wired in.
