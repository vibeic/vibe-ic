"""#701 — a hard macro the power grid could not reach looked like no macro.

THE DEFECT
----------
`_macro_pdn_grid_plan` returned `None` when a hard macro's own OBS blocked
EVERY routing layer above its supply-pin layer. `None` was ALSO what the same
function returned for "this design has no hard macros at all", so
`_build_macro_pdn_grid_tcl` emitted the empty string and the run's PDN note was
BYTE-IDENTICAL to a macro-free design.

Reproduced on PUBLIC sky130A material (the sky130 1kbyte SRAM macro + the
sky130_fd_sc_hd tech LEF), three cases, one flow:

    A. macro as the PDK ships it          -> plan BUILT, 586 bytes of Tcl,
                                             note " + macro_grid(met3->met4@…)"
    B. same macro, vendor also blocking
       the layers above the pin layer     -> plan None, 0 bytes, note ""
    C. CONTROL: no hard macro at all      -> plan None, 0 bytes, note ""

B and C agreed in every observable the flow produced. Two different facts about
the world collapsed onto one output, and the dropped macro first surfaced
several steps downstream as PSM-0038/0039/0069 with nothing pointing back.

The plan dict already carried `refused_for_blockage` for exactly this report —
and it could only ever be populated on the SUCCESS path. When the OBS rule
removed every candidate strap layer there was no plan to hang the reason on,
and the reason was discarded.

WHAT THIS FILE PINS
-------------------
The OBSERVABLE PROPERTY, at the altitude the flow actually emits: the PDN Tcl
that `_build_pdn_tcl` writes into pnr.tcl. Nothing here asserts a sentinel
value, a return type or a field name of the planner, so a DIFFERENT correct fix
passes these unchanged. What must hold:

  * B and C no longer produce the same text.
  * B NAMES the macro and the layers its OBS took off the table.
  * B does NOT build a grid anyway — the OBS is not overridden. A green run and
    a defiant grid are both wrong answers; the right one is a loud refusal.
  * C is unchanged: a genuinely macro-free design must not start emitting a
    refusal, and it must stay byte-identical to a run with no macro LEFs.
  * A is unchanged: a macro the grid CAN reach still gets exactly the grid it
    got before, to the byte.

The last two are the controls that matter. A "fix" that refuses more and more
until nothing is ever planned would satisfy the first three and destroy the
flow; only A and C catch it.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN / "programs"))
mod = importlib.import_module("phase3_one_shot_runner")


# --------------------------------------------------------------- fixtures --
# No PDK literal anywhere: layer names, directions, pitches and every dimension
# are invented here, exactly as the neighbouring PDN tests do. The public-PDK
# reproduction that opened the issue lives in the PR body; this file reproduces
# the same SHAPE without vendoring a foundry LEF.
def _stack(prefix: str = "M",
           dirs=("HORIZONTAL", "VERTICAL", "HORIZONTAL",
                 "VERTICAL", "HORIZONTAL", "VERTICAL"),
           pitch: float = 0.5, width: float = 0.2) -> str:
    return "".join(
        f"LAYER {prefix}{i}\n  TYPE ROUTING ;\n  DIRECTION {d} ;\n"
        f"  PITCH {pitch} ;\n  WIDTH {width} ;\nEND {prefix}{i}\n"
        for i, d in enumerate(dirs, 1))


CELL_LEF = """\
MACRO cellA
  CLASS core ;
  SIZE 2.0 BY 10.0 ;
  PIN VDD
    DIRECTION INOUT ;
    USE POWER ;
    PORT
      LAYER M1 ;
        RECT 0.0 9.6 2.0 10.4 ;
    END
  END VDD
  PIN VSS
    DIRECTION INOUT ;
    USE GROUND ;
    PORT
      LAYER M1 ;
        RECT 0.0 -0.4 2.0 0.4 ;
    END
  END VSS
END cellA
"""

MACRO_W, MACRO_H = 400.0, 140.0
MACRO_NAME = "HARDBLOCK_NVMA"

# One hard macro. Supply pins on M3, each with a port wide enough in BOTH axes
# for a legal strap pitch on either strap layer, so the ONLY thing that can stop
# the grid is the OBS. (A port that is a sliver in one axis is a different, real
# refusal — exercised separately below — and would confound this one.)
MACRO_HEAD = f"""\
MACRO {MACRO_NAME}
    CLASS BLOCK ;
    SIZE {MACRO_W} BY {MACRO_H} ;
    PIN PWRA
        DIRECTION INPUT ;
        USE POWER ;
        PORT
         LAYER M3 ;
          RECT 160 0 172 12 ;
        END
    END PWRA
    PIN GNDA
        DIRECTION INPUT ;
        USE GROUND ;
        PORT
         LAYER M3 ;
          RECT 120 0 132 12 ;
        END
    END GNDA
"""

# The same macro with SLIVER supply ports: 12um along the strap, 0.4um across
# it. No legal pitch can be guaranteed to cross those, which was ANOTHER silent
# `None` on the same code path.
SLIVER_MACRO = f"""\
MACRO SLIVERBLOCK
    CLASS BLOCK ;
    SIZE {MACRO_W} BY {MACRO_H} ;
    PIN PWRA
        DIRECTION INPUT ;
        USE POWER ;
        PORT
         LAYER M3 ;
          RECT 160 0 160.4 12 ;
        END
    END PWRA
END SLIVERBLOCK
"""


def _macro(obs_layers=(), obs_size=None) -> str:
    """The macro, optionally declaring `obs_layers` blocked over `obs_size`
    (its whole footprint by default) — plain LEF grammar, and the ordinary
    vendor stance for an NVM or high-voltage block."""
    lef = MACRO_HEAD
    if obs_layers:
        w, h = obs_size or (MACRO_W, MACRO_H)
        lef += "  OBS\n    LAYER OVERLAP ;\n" \
               f"      RECT 0 0 {MACRO_W} {MACRO_H} ;\n"
        for layer in obs_layers:
            lef += f"    LAYER {layer} ;\n      RECT 0 0 {w} {h} ;\n"
        lef += "  END\n"
    return lef + f"END {MACRO_NAME}\n"


SIGNAL_ONLY_MACRO = """\
MACRO SIGBLOCK
    CLASS BLOCK ;
    SIZE 10 BY 10 ;
    PIN A
        DIRECTION INPUT ;
        USE SIGNAL ;
        PORT
         LAYER M3 ;
          RECT 0 0 1 1 ;
        END
    END A
END SIGBLOCK
"""


# The macro grid the flow builds for the REACHABLE macro, to the byte. Pinned
# as a literal so any change to what a reachable macro gets is a deliberate,
# visible edit — this is the half of the contract a refusal must not touch.
GRID_A_LINES = (
    "  define_pdn_grid -macro -name macro_grid -voltage_domains CORE \\\n"
    "      -cells {" + MACRO_NAME + "} -grid_over_pg_pins\n"
    "  add_pdn_stripe -grid macro_grid -layer M4 -width 0.8 -pitch 12.0"
    " -offset 0\n"
    "  add_pdn_connect -grid macro_grid -layers {M3 M4}\n"
    "  add_pdn_connect -grid macro_grid -layers {M4 M5}\n")


# ═══════════════════════════════════════════════════════════════════════════
# THE DEFECT: B and C were the same text
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# THE REVERSE CASES — the controls that catch a filter tightened to zero
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
# THE RUNNER READS IT BACK  (this implementation's seam, stated as such)
# ═══════════════════════════════════════════════════════════════════════════


HOSTILE_NAME = 'B$AD["x"]'


def _is_one_tcl_literal(puts_line: str) -> bool:
    body = puts_line[len("puts "):]
    if not (body.startswith('"') and body.endswith('"')):
        return False
    inner = body[1:-1]
    return not any(c in inner for c in ('"', "$", "[", "]", "\\", "{", "}"))


# ═══════════════════════════════════════════════════════════════════════════
# REPORTED, NOT BLOCKING — and the argument for it, kept next to the code
# ═══════════════════════════════════════════════════════════════════════════
def test_no_reachable_path_returns_no_grid_with_no_explanation():
    """COVERAGE CONTROL, and coupled to this implementation on purpose.

    The defect was ONE `return None` with no reason. There were seven of them,
    and six were silent for the same reason the seventh was. This walks every
    exit of the planner and asserts the invariant that replaced them: once a
    hard-macro POWER/GROUND port has been seen, "no grid" is never the whole
    answer. A branch added later that returns no plan and no reason fails here.

    The one exemption is stated explicitly, not left implicit: a block with no
    PG port at all asked for nothing, so nothing is the complete answer."""
    tech = _stack()
    stripes = [{"layer": "M4", "width": 0.8, "pitch": 20, "offset": 0},
               {"layer": "M5", "width": 0.8, "pitch": 20, "offset": 0}]

    def plan_for(lefs, t=tech, st=stripes):
        return mod._macro_pdn_grid_outcome(lefs, t, st, "M1")

    # (label, args) -> every distinct exit the planner has
    exits = {
        "no routing layers":     ([_macro()], "not a lef", stripes),
        "pin layer not routing": ([_macro().replace("LAYER M3", "LAYER NOPE")],
                                  tech, stripes),
        "pins above every strap": ([_macro().replace("LAYER M3", "LAYER M6")],
                                   tech, stripes),
        "all candidates blocked": ([_macro(obs_layers=("M4", "M5"))], tech,
                                   stripes),
        "no perpendicular partner": ([_macro()], tech, [stripes[0]]),
        "strap width unusable":  ([_macro()], tech,
                                  [{"layer": "M4", "width": 0, "pitch": 20,
                                    "offset": 0}, stripes[1]]),
        "no port wide enough":   ([SLIVER_MACRO], tech, stripes),
    }
    reasons = set()
    for label, args in exits.items():
        got = plan_for(*args)
        assert got["plan"] is None, label
        assert got["refusals"], f"{label}: no grid AND no reason — the defect"
        for rec in got["refusals"]:
            assert rec["masters"], f"{label}: refused without naming a macro"
            assert rec["reason"].strip(), f"{label}: no machine token"
            assert rec["detail"].strip(), f"{label}: no sentence for a human"
            reasons.add(rec["reason"])
    # every exit has its OWN token: one token for seven causes is the same
    # collapse this issue is about, moved down a level
    assert len(reasons) == len(exits), sorted(reasons)

    # the exemption, and the success path, both still hold
    assert plan_for([SIGNAL_ONLY_MACRO]) == {"plan": None, "refusals": []}
    built = plan_for([_macro()])
    assert built["plan"] is not None and built["refusals"] == []
