"""PSM's supply-source model on a block whose PDN straps are its supply pins.

WHY THIS EXISTS. A padless block (a core / hard macro) promotes its PDN strap
layers to supply PINS (`define_pdn_grid -pins`, see
`phase3_one_shot_runner._core_block_pin_layers_tcl`), because whoever
instantiates it reaches its supply through those ports. OpenROAD PSM, given no
`-vsrc` file, takes EVERY BPin shape as an ideal voltage source
(`IRSolver::generateSourceNodes`: sources from BTerms first, the generated
FULL/STRAPS/BUMPS pattern only when that set is empty). Promoting the straps
therefore silently turned every strap into an ideal supply: MEASURED on the
same spm x gf180mcuD layout, Metal4 strap current read exactly 0 A, the EM
peak fell 4.3x and the static IR 2-5x, and PSM-0073 (the generated bump
pattern the IR record declares as its conservative model) disappeared. Nothing
in the layout got better; the measurement stopped looking at the straps.

THE RULE. The supply pins a padless block ships are an INTERFACE, not a
source model. Every PSM session (static IR/EM, transient IR, the pre-route EM
presweep) marks them with PSM's own `PSM_DISCONNECT` BPin property
(`BPinNode::shouldConnect`) before solving, so PSM falls back to exactly the
model it used before the pins existed, and says so on a marker line the
records read back. The pins stay in the database and in the DEF.

WHICH PINS. Exactly the ones the promotion rule creates: the SPECIAL BTerms of
a POWER/GROUND net on a block with no placed pad master (the same database
fact the promotion keys on). A block with placed pads promotes nothing and is
left untouched, so a die keeps its pad-sourced model byte-for-byte.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

#: PSM's own BPin/box property; `BPinNode::shouldConnect` skips a source
#: carrying it (OpenROAD src/psm/src/node.h `kDisconnectProperty`).
DISCONNECT_PROPERTY = "PSM_DISCONNECT"

MARKER = "PSM_SOURCE_MODEL:"
_MARKER_RE = re.compile(
    r"^PSM_SOURCE_MODEL: promoted_supply_pins_excluded=(\d+) placed_pads=(\d+)\s*$",
    re.M)


def exclude_promoted_pins_tcl(var: str = "_vibeic_psm_props") -> str:
    """Tcl: mark the promoted supply pins so PSM does not source from them.

    Leaves the list of properties it set in ``$var`` (for
    `restore_promoted_pins_tcl`) and prints one ``PSM_SOURCE_MODEL:`` line."""
    return (
        f"set {var} {{}}\n"
        "set _vibeic_psm_pads 0\n"
        "foreach _vibeic_psm_i [[ord::get_db_block] getInsts] {\n"
        "  if {[[$_vibeic_psm_i getMaster] isPad] && [$_vibeic_psm_i isPlaced]} "
        "{ incr _vibeic_psm_pads }\n"
        "}\n"
        "if {$_vibeic_psm_pads == 0} {\n"
        "  foreach _vibeic_psm_n [[ord::get_db_block] getNets] {\n"
        "    if {[$_vibeic_psm_n getSigType] ni {POWER GROUND}} { continue }\n"
        "    foreach _vibeic_psm_t [$_vibeic_psm_n getBTerms] {\n"
        "      if {![$_vibeic_psm_t isSpecial]} { continue }\n"
        "      foreach _vibeic_psm_b [$_vibeic_psm_t getBPins] {\n"
        f"        set _vibeic_psm_p [odb::dbBoolProperty_find $_vibeic_psm_b {DISCONNECT_PROPERTY}]\n"
        "        if {$_vibeic_psm_p eq \"NULL\"} {\n"
        f"          set _vibeic_psm_p [odb::dbBoolProperty_create $_vibeic_psm_b {DISCONNECT_PROPERTY} 1]\n"
        "        } else { $_vibeic_psm_p setValue 1 }\n"
        f"        lappend {var} $_vibeic_psm_p\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
        f"puts \"{MARKER} promoted_supply_pins_excluded=[llength ${var}] "
        "placed_pads=$_vibeic_psm_pads\"\n")


def restore_promoted_pins_tcl(var: str = "_vibeic_psm_props") -> str:
    """Tcl: drop the properties `exclude_promoted_pins_tcl` set, for a session
    that goes on to write the database (the presweep runs inside PnR)."""
    return (f"foreach _vibeic_psm_p ${var} {{ odb::dbProperty_destroy $_vibeic_psm_p }}\n"
            f"set {var} {{}}\n")


def clear_generated_supply_pins_tcl() -> str:
    """Remove a padless grid's fixed supply BPins before rebuilding its PDN.

    PdnGen preserves FIRM BPins across ``pdngen -reset``. They describe the
    previous candidate's straps and obstruct a candidate at another pitch.
    Placed pad masters identify a die: its supply BPins belong to the pad ring
    and must survive the rebuild.
    """
    return (
        "set _vibeic_psm_pads 0\n"
        "foreach _vibeic_psm_i [[ord::get_db_block] getInsts] {\n"
        "  if {[[$_vibeic_psm_i getMaster] isPad] && [$_vibeic_psm_i isPlaced]} "
        "{ incr _vibeic_psm_pads }\n"
        "}\n"
        "if {$_vibeic_psm_pads == 0} {\n"
        "  foreach _vibeic_psm_n [[ord::get_db_block] getNets] {\n"
        "    if {[$_vibeic_psm_n getSigType] ni {POWER GROUND}} { continue }\n"
        "    foreach _vibeic_psm_t [$_vibeic_psm_n getBTerms] {\n"
        "      if {![$_vibeic_psm_t isSpecial]} { continue }\n"
        "      foreach _vibeic_psm_b [$_vibeic_psm_t getBPins] {\n"
        "        odb::dbBPin_destroy $_vibeic_psm_b\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n")


def read(log: str) -> Optional[Dict[str, int]]:
    """The last ``PSM_SOURCE_MODEL:`` line of a session log, or None when the
    session printed none (a producer that does not run this rule)."""
    found = _MARKER_RE.findall(log or "")
    if not found:
        return None
    excluded, pads = found[-1]
    return {"promoted_supply_pins_excluded": int(excluded),
            "placed_pads": int(pads)}


def describe(log: str) -> Dict[str, Any]:
    """The source model a PSM session solved on, derived from its own log.

    Read source-model selection from the native tool transcript."""
    rec = read(log)
    bump = re.search(r"PSM-0073[^\n]*", log or "")
    out: Dict[str, Any] = {"marker": rec, "psm_0073": bump.group(0) if bump else None}
    # Every model below is PSM's DEFAULT source resolution (no -vsrc file);
    # the text says which branch of it this session actually took.
    if rec is None:
        out["model"] = ("PSM default sources (BTerms, else the generated "
                        "pattern); the session printed no PSM_SOURCE_MODEL line")
    elif rec["promoted_supply_pins_excluded"] and bump:
        out["model"] = (
            "PSM default sources: generated bump pattern (PSM-0073); the "
            f"block's {rec['promoted_supply_pins_excluded']} promoted supply "
            f"pin(s) carry {DISCONNECT_PROPERTY} and are not sources")
    elif bump:
        out["model"] = ("PSM default sources: generated bump pattern "
                        "(PSM-0073); the block has no promoted supply pins")
    else:
        out["model"] = ("PSM default sources: the design's supply BTerms "
                        f"(placed pads {rec['placed_pads']})")
    return out
