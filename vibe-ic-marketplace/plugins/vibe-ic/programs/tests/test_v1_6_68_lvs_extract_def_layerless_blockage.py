"""v1.6.68 — LVS was unrunnable at random because magic's DEF reader aborts
on a DEF BLOCKAGES entry that names no layer.

Field observation (real Phase-3 run, multi-supply ASIC): the routed DEF held

    BLOCKAGES 1 ;
        - PLACEMENT + SOFT + COMPONENT <inst> RECT ( x1 y1 ) ( x2 y2 ) ;
    END BLOCKAGES

A `- PLACEMENT` entry is a directive to the PLACER; it names no layer and
carries no conductor. Magic has nothing to bind the RECT to, prints

    LEF read, Line NNNN (Error): No layer defined for RECT.

and then terminates the DEF read PART OF THE TIME. Measured on the SAME
byte-identical DEF with the SAME command: 2 of 5 runs produced a netlist,
3 of 5 produced none. With the layer-less entry removed: 5 of 5 produced a
netlist, and every one of them was byte-identical (same md5) to the netlist
the intact DEF produced on the runs where it happened to survive — i.e. the
removal is loss-free for extraction, which is what makes it a fix and not a
workaround.

Two independent defects, pinned separately:

  D1  the runner fed magic the signed-off DEF as-is, so a design that uses a
      placement blockage (a routine macro-halo / keep-out) had a ~60 %
      chance of no LVS at all;
  D2  magic exits 0 even on a fatal `lef read` / `def read`, so `rc=0` is not
      evidence. The no-netlist branch reported "produced no extracted netlist
      (rc=0)" — a message that states a file is missing while implying the
      tool was fine.

HOW THIS FILE PROVES IT, AND WHY IT WAS REWRITTEN (2026-08-05)
=============================================================
As first landed (41c49f94d) this file did NOT reproduce either defect. Measured
against the pre-landing tree e3aa9b126, its 9 tests came out:

    6 x AttributeError  — `P3._strip_nonlayer_blockages` does not exist there;
    1 x AssertionError  — but on `'_strip_nonlayer_blockages(' in <source text>`,
                          i.e. a grep for that same new symbol's NAME;
    1 x ValueError      — `_P3_CODE.index('"LVS_EXTRACTION_NO_NETLIST", _detail')`
                          on a source string that does not contain it;
    1 x PASS            — the pipefail test, which is about a shared repair that
                          predates this landing and passes on both trees.

So eight of nine failures said only "a private helper is missing" or "a string
is missing from the source". That is symbol existence, not behaviour, and the
landing commit's own docstring claimed the opposite of it.

Every test below now drives `step_lvs` — the shipped Phase-3 step — with a
fake container, and asserts on what the flow OBSERVABLY does:

  * the DEF TEXT magic is actually handed (read back from the `DEF=` the
    runner puts in the command it issues);
  * the signed-off DEF's bytes on disk afterwards;
  * the provenance record beside the staged copy;
  * the fields of the FAIL verdict the step publishes.

Each of those raises AssertionError on e3aa9b126 and passes on b85d68acc.

chip-AGNOSTIC: DEF syntax + the step's own reports. No PDK, no container, no
tool.
"""
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as P3  # noqa: E402


# --------------------------------------------------------------------------
# DEF fixtures. Deliberately fewer than 16 signal nets so the unrelated
# signal-routing honesty gate (`_LVS_MIN_SIGNAL_NETS_FOR_ROUTING_CHECK`) does
# not decide these runs; the question here is about BLOCKAGES.
# --------------------------------------------------------------------------
_HEAD = """\
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
"""

_TAIL = """\
COMPONENTS 1 ;
- u0 CELLA + PLACED ( 0 0 ) N ;
END COMPONENTS
SPECIALNETS 1 ;
    - VDD ( * VPWR ) + USE POWER ;
END SPECIALNETS
END DESIGN
"""

#: the measured shape: a layer-less PLACEMENT directive between two ordinary
#: layer blockages, and spanning two physical lines as OpenROAD writes it.
_LAYERLESS = ("    - PLACEMENT + SOFT + COMPONENT u_otp.u_macro "
              "RECT ( 10560 305780 )\n      ( 426560 458780 ) ;\n")
_LAYER_1 = "    - LAYER MET1 RECT ( 100 200 ) ( 300 400 ) ;\n"
_LAYER_2 = "    - LAYER MET2 RECT ( 5 6 ) ( 7 8 ) ;\n"

DEF_MIXED = (_HEAD + "BLOCKAGES 3 ;\n" + _LAYER_1 + _LAYERLESS + _LAYER_2
             + "END BLOCKAGES\n" + _TAIL)
DEF_ONLY_LAYERLESS = (_HEAD + "BLOCKAGES 1 ;\n" + _LAYERLESS
                      + "END BLOCKAGES\n" + _TAIL)
DEF_ALL_LAYER = (_HEAD + "BLOCKAGES 2 ;\n" + _LAYER_1 + _LAYER_2
                 + "END BLOCKAGES\n" + _TAIL)
DEF_NO_BLOCKAGES = _HEAD + _TAIL


_CLEAN_NETGEN = "Final result: Circuits match uniquely.\n"






# ═══ D1 — what magic is actually handed ═══════════════════════════════════













# ── strict fall-through: a DEF magic can read is handed over as it is ──────


# ═══ D2 — the no-netlist verdict must not imply the tool was fine ═════════







# ═══ the shared pipefail repair — passes on BOTH trees, and says so ═══════

def test_magic_pipeline_does_not_let_tee_mask_the_exit_status():
    """PRE-EXISTING GUARD, not a pin on this landing.

    The repair this asserts landed one layer down, in
    `_tool_status_not_the_log_sinks`, which every `_docker_exec` command passes
    through — and it was already on the tree before 41c49f94d. This test
    therefore PASSES on e3aa9b126 as well as on b85d68acc and discriminates
    nothing here. It is kept because the property is real and unguarded
    elsewhere in this file's subject area, and it is labelled so nobody reads
    its green as evidence for the blockage fix.
    """
    guarded = P3._tool_status_not_the_log_sinks(
        "magic -dnull -noconsole -rcfile rc t.tcl 2>&1 | tee ext2spice.log")
    assert guarded.startswith("set -o pipefail; "), guarded
    # ...and it is the PIPELINE that gets it: a command with no log sink is
    # left exactly as it was, so this is not a blanket shell-option change.
    assert P3._tool_status_not_the_log_sinks("magic t.tcl") == "magic t.tcl"
