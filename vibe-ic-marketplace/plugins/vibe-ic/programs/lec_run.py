#!/usr/bin/env python3
"""lec_run.py — Step 13 LEC PRODUCER (RTL ≡ synthesized gate netlist).

The flow's step-13 gate `lec_equivalence_check.py` VALIDATES
`reports/lec.json`, but nothing ever PRODUCED that artefact — step 13 was
an orphan. This program is the missing executor: it runs a REAL Yosys
equivalence check in the vibeic-eda container and writes a TRUTHFUL
`reports/lec.json` + `reports/lec.rpt`.

It is a PRODUCER, not the judge. It exits 0 whenever it successfully wrote
a truthful report — even when the design turned out non-equivalent, or when
the SAT engine was model-limited on custom-PDK primitives. The downstream
gate `lec_equivalence_check.py` is what decides PASS/FAIL. It exits 1 only
when Yosys / Docker could not run at all (so the runner can fall back to a
disclosed-skip).

The Yosys recipe is PORTED from the mature `yosys_equiv` LVS mode in
`mcp-eda/src/index.js` (equiv_make → equiv_simple → equiv_induct -seq
4/16/64 → equiv_status), including its ANTI-FABRICATION honesty: when
equiv_induct's SAT engine aborts on Liberty cells it cannot model (e.g.
`sky130_fd_sc_hd__lpflow_isobufsrc_1`), we surface a STRUCTURED
`sat_model_unsupported_cells[]` + `verdict:"SKIPPED-CONDITION"` +
`verdict_explanation` — never a fake pass, never the ambiguous `-1`
sentinel. Two recipe adaptations proven necessary against real Vibe-IC
synth netlists (Yosys 0.66, sky130A):
  * `read_verilog -icells` — synth netlists here escape internal gate
    types as user identifiers (`\\$_NOT_`); -icells re-binds them to the
    internal primitives so `hierarchy -check` does not error. Harmless for
    Liberty-mapped netlists (their cells are not `$`-prefixed).
  * `flatten` on both designs — the RTL gold carries sub-module hierarchy
    (e.g. chip_top -> spm); without flatten equiv_make sees an unmodelable
    hierarchical instance and aborts on it. equiv is a comparison of two
    flat cones, so flattening both is sound.

CLI contract (the runner calls this exactly):
    python3 lec_run.py <project_dir> \\
        --gold-rtl-dir phase2/stage1/rtl \\
        --gate-netlist phase2/stage2/synth/netlist.v \\
        --top <top_module> \\
        [--container vibeic-eda] \\
        [--liberty <abs .lib path inside container>] \\
        [--json reports/lec.json]
    main(argv=None) -> int   0 = report produced (PASS or honest SKIP)
                             1 = could not run the tool at all (real error)

Chip-AGNOSTIC — no design-specific assumptions; pure Yosys driving + text
parsing. The only cell names referenced are the PDK's own documented cells.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rtl_include_hub import (  # noqa: E402
    drop_include_hubs as _drop_include_hubs,
    macro_headers_first as _macro_headers_first,
)
import _hardmacro_stage as _hms  # noqa: E402 — staged SRAM/IP macro blackbox

PROGRAM = "lec_run"

DEFAULT_CONTAINER = "vibeic-eda"
DEFAULT_LIBERTY = (
    "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
    "sky130_fd_sc_hd__tt_025C_1v80.lib"
)
# TOTAL budget for the LEC step, shared by every attempt (see StepBudget).
# It used to be a PER-INVOCATION budget that each retry re-armed; it is now a
# deadline drawn down across attempts. The equiv miter on a CPU-class gold (ibex:
# ~2k compared points through equiv_induct -seq 64) runs far past the old
# 1800s, and a killed run produced NO evidence — indistinguishable at the
# gate from a real mismatch. Tunable via --timeout for smaller budgets.
# ORGANIC-20260801 — VIBEIC_LEC_YOSYS_TIMEOUT_S overrides the default for very
# large (>1M-cell) golds whose MONOLITHIC equiv legitimately exceeds — or is
# deliberately bounded below (a giant gold that cannot converge in any open-tool
# budget honestly lands SKIPPED-CONDITION, never a fake PASS) — the historical
# 7200s. Symmetric with the synth step's VIBEIC_PHASE2_SYNTH_TIMEOUT_S. The
# runner reads this SAME constant for its outer subprocess budget and inherits
# the env into the lec_run subprocess, so both stay in lock-step. Byte-identical
# (7200) when the env var is unset. chip-AGNOSTIC.
def _env_yosys_timeout_default() -> int:
    try:
        v = int(os.environ.get("VIBEIC_LEC_YOSYS_TIMEOUT_S", "") or 0)
        if v > 0:
            return v
    except ValueError:
        pass
    return 7200


DEFAULT_YOSYS_TIMEOUT_S = _env_yosys_timeout_default()
DEFAULT_JSON_REL = "reports/lec.json"
DEFAULT_RPT_REL = "reports/lec.rpt"

# ---------------------------------------------------------------------------
# Yosys equiv_status output parser (PURE — the tests call this directly).
#
# Ported verbatim in spirit from mcp-eda/src/index.js yosys_equiv parsing.
# Every regex below has been validated against real Yosys 0.66 output for
# BOTH the clean-PASS case (generic $_-primitive netlist) and the
# SAT-model-limited case (sky130_fd_sc_hd-mapped netlist).
# ---------------------------------------------------------------------------

# Final summary from `equiv_status` (present when the run completes):
#   "  Of those cells 71 are proven and 0 are unproven."
_FINAL_RE = re.compile(r"(\d+)\s+are\s+proven\s+and\s+(\d+)\s+are\s+unproven")

# Direct total — equiv_simple ENTRY line:
#   "Found 71 unproven $equiv cells (71 groups) in equiv:"
_EQUIV_SIMPLE_ENTRY_RE = re.compile(
    r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+\(\d+\s+groups\)\s+in\s+equiv\s*:")

# Direct total — final equiv_status header / older Yosys total line:
#   "Found 71 $equiv cells in equiv:"   (NB: no `unproven` infix)
_OLD_TOTAL_RE = re.compile(r"Found\s+(\d+)\s+\$equiv\s+cells")

# Fallback proven — equiv_simple's proved-count line:
#   "Proved 35 previously unproven $equiv cells."
_PROVED_SIMPLE_RE = re.compile(
    r"Proved\s+(\d+)\s+previously\s+unproven\s+\$equiv\s+cells")

# Forward-compat proven/total — a hypothetical newer "Proved M/N" shape.
_SIMPLE_SLASH_RE = re.compile(
    r"equiv_simple[^\n]*Proved\s+(\d+)/(\d+)\s+\$equiv\s+cells")

# Fallback unproven — equiv_induct residual line, anchored on `in module
# equiv:` so it does NOT collide with the equiv_simple entry line above:
#   "Found 35 unproven $equiv cells in module equiv:"
_INDUCT_FOUND_RE = re.compile(
    r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+in\s+module\s+equiv\s*:")

# SAT-model abort (chip-AGNOSTIC): the honest capability-gap signal.
#   "ERROR: No SAT model available for cell _204__gate (sky130_fd_sc_hd__lpflow_isobufsrc_1)."
_SAT_ABORT_RE = re.compile(
    r"No SAT model available for cell\s+(\S+)\s+\((\S+?)\)")

# Best-effort per-instance unproven cell list.
_UNPROVEN_LIST_RE = re.compile(r"Unproven\s+\$equiv\s+cells:\s*([^\n]+)")

# BUDGET-EXHAUSTED marker (#155 POSITIVE timeout discriminator). run_yosys_equiv
# (below) writes this EXACT string into the raw log ITSELF when the yosys
# subprocess is KILLED by the wall budget — it is NOT tool output a design could
# emit, so it can never be spoofed by a genuine-garbage log. Post-memory_map a
# memory-bearing design is genuinely satgen-modelable, so equiv_induct ATTEMPTS
# the full sequential proof; on a large design (e.g. sha256's memory-inclusive
# miter, or a whole AES cipher whose S-box/GF cones are SAT-intractable) that
# proof can exceed the LEC wall clock, leaving no final equiv_status → the run
# is killed. A killed run produced NO completed comparison, so the cause must be
# NAMED (raise --timeout) instead of read as a mismatch that was never found.
_TIMEOUT_MARKER = "[lec_run] ERROR: yosys equiv exceeded its time budget"
_TIMEOUT_RE = re.compile(re.escape(_TIMEOUT_MARKER))

# A wall-budget kill reaches run_yosys_equiv by TWO paths that must be treated
# identically:
#   (1) the HOST `subprocess.run(timeout=…)` raises subprocess.TimeoutExpired; or
#   (2) the CONTAINER-side `timeout` that _docker wraps every call in
#       (wrap_with_container_timeout, added to stop the orphaned-tool leak) fires
#       `margin_s` seconds BEFORE the host deadline, so yosys is already dead and
#       `docker exec` returns NORMALLY with GNU-`timeout`'s exit code — the host
#       run never times out and path (1) is structurally UNREACHABLE for the
#       container flow. GNU `timeout` reports 124 when its SIGTERM expiry killed
#       the command, and 137 (128+9) when `--kill-after` had to escalate to
#       SIGKILL (the usual outcome for yosys mid-SAT, which ignores SIGTERM). A
#       container OOM-kill also surfaces as 137 — likewise a resource-exhaustion
#       no-verdict run, not a proven mismatch — so folding it in here is correct.
# Without recognising path (2), a killed-mid-proof run (0 completed comparisons,
# no counterexample) is misread as a hard FAIL (measured on opentitan_aes ×
# sky130A: 27904 $equiv cells, killed at 7200s, booked verdict=FAIL "may
# genuinely differ" — a false non-equivalence that halted the whole flow).
_CONTAINER_TIMEOUT_RCS = (124, 137)

# EVIDENCE-BASED timeout split (merge of local FAIL vs origin #155
# SKIPPED-CONDITION). A wall-budget kill (parse_error + _TIMEOUT_RE) is a pure
# resource skip ONLY if the log carries NO recorded non-equivalence. This matches
# the UNMISTAKABLE counterexample / non-equivalence phrases a yosys/SAT run
# prints when it actually PROVED a difference — phrases a pure resource-
# exhaustion log can never contain. PRECISION-first: a miss degrades to the
# visible SKIPPED-CONDITION (never a PASS), a match escalates the timeout to a
# real FAIL. chip-AGNOSTIC — no chip/vendor literal.
_MISMATCH_EVIDENCE_RE = re.compile(
    r"counter-?example"
    r"|non-?equivalent"
    r"|inequivalent"
    r"|not\s+equivalent"
    r"|equivalence\s+(?:check\s+)?failed",
    re.IGNORECASE)

# Canonical Yosys success line (corroboration for the gate's .rpt parse).
_SUCCESS_RE = re.compile(r"Equivalence\s+successfully\s+proven", re.IGNORECASE)

# #208 — induction NON-CONVERGENCE signatures. A COMPLETED equiv_make miter can
# leave points `unproven` for two very different reasons:
#   (a) a genuine difference — which yosys backs with a COUNTEREXAMPLE
#       (_MISMATCH_EVIDENCE_RE), OR
#   (b) equiv_induct's SAT induction simply did NOT CONVERGE on a large
#       sequential design — a flat wall that proved NOTHING and recorded NO
#       counterexample. (b) is INCONCLUSIVE, not NOT_EQUIVALENT: non-convergence
#       is not non-equivalence. These match the two flat-wall shapes seen in the
#       wild (chip-AGNOSTIC — pure yosys phrases):
#   * the SAT base case cannot even be established (`Circuit inherently
#     diverges!` — equiv_induct aborts at base-case step k), and
#   * an equiv_induct pass that `Proved 0 previously unproven $equiv cells` — the
#     escalating `-seq 4/16/64` sweep made zero progress.
_INDUCT_DIVERGE_RE = re.compile(r"[Cc]ircuit\s+inherently\s+diverges", re.IGNORECASE)
_PROVED_ZERO_RE = re.compile(
    r"Proved\s+0\s+previously\s+unproven\s+\$equiv\s+cells")


# YOSYS'S OWN INTERNAL COMBINATIONAL CELL VOCABULARY.
#
# This is a CLOSED, TOOL-DEFINED set (yosys's internal cell library: the `$_*_`
# gate-level primitives and the coarse-grain word-level operators), NOT a guess
# about any PDK's cell names. Membership is used ONLY to establish the POSITIVE
# fact "every cell in this miter is combinational". Anything not listed -- a
# PDK Liberty cell, a `$mem`, a flip-flop, a cell type added by a future yosys
# -- makes the answer "unknown", which keeps the PREVIOUS behaviour exactly.
# The asymmetry is deliberate: an omission from this list can only cost us the
# stricter verdict, never grant a softer one.
_YOSYS_COMB_CELL_TYPES = frozenset("""
$_NOT_ $_BUF_ $_AND_ $_NAND_ $_OR_ $_NOR_ $_XOR_ $_XNOR_ $_ANDNOT_ $_ORNOT_
$_MUX_ $_NMUX_ $_MUX4_ $_MUX8_ $_MUX16_ $_AOI3_ $_OAI3_ $_AOI4_ $_OAI4_
$_TBUF_ $not $pos $neg $and $or $xor $xnor $reduce_and $reduce_or $reduce_xor
$reduce_xnor $reduce_bool $logic_not $logic_and $logic_or $shl $shr $sshl
$sshr $shift $shiftx $lt $le $eq $ne $eqx $nex $ge $gt $add $sub $mul $div
$mod $divfloor $modfloor $pow $mux $pmux $bmux $demux $bwmux $tribuf $lut
$sop $macc $macc_v2 $alu $lcu $fa $concat $slice $buf $equiv
""".split())

# A state-bearing miter and a stateless one are different questions, and only
# the first one `equiv_induct` can answer.
# The miter module name `build_equiv_script` always uses.
_MITER_MODULE = "equiv"
_STAT_MODULE_RE = re.compile(r"(?m)^\s*===\s+(\S+)\s+===\s*$")
# yosys prints the per-type histogram as "count", then 2+ spaces, then the
# cell type, indented under the module header; the SUMMARY lines above it
# ("113 cells", "222 wires") use a SINGLE space. Requiring 2+ spaces separates the two without
# keyword-matching, and keeps bare Liberty cell names (which must count as
# UNKNOWN, i.e. fail-open) in the histogram rather than dropping them.
_STAT_CELL_RE = re.compile(r"(?m)^[ \t]+(\d+)[ \t]{2,}(\S+)[ \t]*$")


def miter_is_stateless(text: str):
    """(stateless, evidence) -- True ONLY on positive evidence that the miter
    yosys built contains no state element at all.

    WHY THIS EXISTS -- MEASURED 2026-08-27, on unpatched main 40d0e14c08.
    A `popcount8` gold was synthesised, ONE gate in the netlist was mutated
    (`$_NAND_` -> `$_NOR_`), and `lec_run.py` reported that genuinely
    non-equivalent pair as **INCONCLUSIVE**, not FAIL. The mechanism:

      * the design is purely combinational, so `equiv_simple` correctly left
        the 4 differing output bits unproven;
      * the script then ran `equiv_induct -seq 4/16/64` anyway. On a miter with
        NO state there is nothing to induct over, so every rung necessarily
        printed `Proved 0 previously unproven $equiv cells.`;
      * `induction_did_not_converge` reads exactly that phrase as "a flat
        induction wall", and the classifier re-classes a flat wall from
        NOT_EQUIVALENT to INCONCLUSIVE.

    That re-class is right for a DEEP SEQUENTIAL design, where `-seq 64` really
    can run out of depth. On a stateless design it is unconditional: EVERY real
    combinational mismatch produces that phrase, so the discriminator says "not
    a mismatch" about every mismatch it is shown. A checker that cannot say
    FAIL is not a checker.

    THE OBSERVABLE, not a name guess: this reads the cell histogram YOSYS
    ITSELF printed for the miter module (`stat` after `equiv_make`), and
    returns True only when the histogram was found, counted at least one cell,
    and EVERY type in it is in yosys's own combinational vocabulary. A PDK
    Liberty cell, a `$mem`, a `$_DFF_*`, or any type this list does not know
    yields False -- i.e. the previous behaviour, unchanged. PURE."""
    # ANCHOR ON THE MITER MODULE BY NAME. `build_equiv_script` always builds
    # the miter as `equiv_make gold gate equiv`, so the histogram we need is
    # the one headed `=== equiv ===`. Anchoring matters: `prep` prints its OWN
    # `=== <gold-top> ===` statistics earlier in the same log, and taking
    # merely the LAST section would read the GOLD's cell mix on any log that
    # lacks the miter `stat` -- e.g. a log produced before this pass was added.
    # Requiring the miter's own section makes such a log answer "unknown"
    # (False), which is the previous behaviour, instead of answering from the
    # wrong design.
    mods = [m for m in _STAT_MODULE_RE.finditer(text or "")
            if m.group(1) == _MITER_MODULE]
    if not mods:
        return False, (f"no `stat` cell histogram for the miter module "
                       f"`{_MITER_MODULE}` in the log -- statelessness was "
                       f"not established, so the sequential-depth "
                       f"re-classification keeps its previous behaviour")
    last = mods[-1]
    section = (text or "")[last.end():]
    nxt = _STAT_MODULE_RE.search(section)
    if nxt:
        section = section[:nxt.start()]
    types = {}
    for m in _STAT_CELL_RE.finditer(section):
        cnt, name = int(m.group(1)), m.group(2)
        types[name] = cnt
    if not types:
        return False, ("`stat` reported no cell types for the miter -- "
                       "statelessness was not established")
    unknown = sorted(t for t in types if t not in _YOSYS_COMB_CELL_TYPES)
    if unknown:
        return False, (
            f"the miter contains cell type(s) outside yosys's combinational "
            f"vocabulary ({', '.join(unknown[:6])}) -- it may hold state, so "
            f"induction non-convergence remains a possible explanation")
    return True, (
        f"`stat` shows the miter is built entirely from combinational cells "
        f"({', '.join(sorted(types)[:6])}) -- it holds NO state, so temporal "
        f"induction had nothing to unroll and `Proved 0 previously unproven` "
        f"is the guaranteed output for ANY unproven point, mismatch or not. "
        f"Induction non-convergence cannot explain this result.")


def induction_did_not_converge(text: str):
    """(bool, evidence) — True when equiv_induct made NO progress (a flat wall)
    rather than finding a difference. PRECISION-first: the caller MUST also
    confirm NO counterexample (_MISMATCH_EVIDENCE_RE) before re-classing to
    INCONCLUSIVE, because a real non-equivalence also leaves points unproven but
    is witnessed by a counterexample. chip-AGNOSTIC: pure yosys log phrases."""
    if _INDUCT_DIVERGE_RE.search(text):
        return True, ("equiv_induct SAT base case could not be established "
                      "(`Circuit inherently diverges!`)")
    if _PROVED_ZERO_RE.search(text):
        return True, ("equiv_induct proved 0 previously-unproven cells across "
                      "the escalating -seq sweep (a flat induction wall)")
    return False, ""


# #778 / round-2 subservient×sky130A — the escalating `-seq 4/16/64` induction
# ladder can run OUT of depth on a deep bit-serial datapath (SERV accumulates
# its memory ADDRESS bit-serially, threading bufreg→bufreg2→arbiter→mux far past
# a single 32-cycle period) while its DEEPEST rung is STILL proving new cells.
# MEASURED (subservient×sky130A, 3544 points): equiv_simple proved 3369, then
# equiv_induct proved 35 (-seq 4), 22 (-seq 16), 27 (-seq 64) — a strictly
# positive, still-descending tail — leaving 91 unproven with ZERO counterexample
# (all on `o_wb_mem_adr`/`arbiter.o_wb_mem_adr`). That is "converging but
# ladder-exhausted", NOT a flat wall (`Proved 0`, handled above) and NOT a proven
# difference (a counterexample, handled by _MISMATCH_EVIDENCE_RE). It is the SAME
# disclosed sequential-depth capability gap as `induction_did_not_converge`, so
# it must ALSO reclassify to INCONCLUSIVE, never a false NOT_EQUIVALENT.
_EQUIV_INDUCT_MARKER_RE = re.compile(r"equiv_induct", re.IGNORECASE)


def induction_ladder_exhausted(text: str):
    """(bool, evidence) — True when the equiv_INDUCT ladder made POSITIVE but
    INCOMPLETE progress: at least one induct rung proved >0 previously-unproven
    cells, yet points remain unproven at equiv_status. This is the -seq depth
    budget running out on a deep sequential design, NOT a proven difference
    (witnessed by a counterexample) and NOT a flat wall (`Proved 0`). PRECISION-
    first / §4.05 NO-LEAK: the caller MUST also confirm NO counterexample AND
    unproven>0 before re-classing to INCONCLUSIVE. The `Proved N` scan is scoped
    to the region AFTER the first equiv_induct marker so equiv_simple's OWN
    proved-count can never trigger it — a genuine mismatch (MISMATCH_OUTPUT:
    equiv_simple proves 33, equiv_induct then proves 0 and leaves 7 unproven)
    has NO post-induct `Proved N>0` line and correctly stays FAIL. chip-AGNOSTIC:
    pure yosys log phrases, no chip/vendor literal."""
    m = _EQUIV_INDUCT_MARKER_RE.search(text)
    if not m:
        return False, ""
    induct_region = text[m.start():]
    proved = [int(n) for n in _PROVED_SIMPLE_RE.findall(induct_region)]
    total = sum(n for n in proved if n > 0)
    if total > 0:
        return True, (
            f"equiv_induct proved {total} previously-unproven cell(s) across "
            "the escalating -seq sweep but the ladder was exhausted before full "
            "convergence — a bounded sequential-depth induction gap, not a flat "
            "wall and not a counterexample")
    return False, ""

# Frontend-ABORT signatures — a read_verilog / read_slang failure that prevented
# ANY equivalence miter from being built (0 compared points). DISTINCT from a
# genuine mismatch (a miter DID run and left points unproven). A zero-miter abort
# is not classifiable as PASS or FAIL, so it re-classifies to INCONCLUSIVE rather
# than a false FAIL that cascade-marks downstream steps MISSING.
# SCOPE (v1.4.33): this signature now decides ONLY the VERDICT classification.
# WHICH FRONTEND reads the gold is decided by `should_retry_gold_with_slang`,
# which keys on the OBSERVABLE "no miter was built" rather than on the tool's
# error wording — an allow-list of phrasings silently skipped the capable
# frontend whenever a new abort was worded differently (how ibex was missed).
# TWO families, BOTH resolved by slang:
#   (A) PARSE / lex aborts — the built-in reader can't tokenise the SV closure
#       (package import before the ANSI port list, typedefs, unsupported syntax).
#   (B) ELABORATION aborts — the built-in reader PARSES but can't ELABORATE a
#       VALID SV-2017 construct that slang resolves. The canonical case is an SV
#       package/enum constant used as a parameter value, which yosys's built-in
#       const-evaluator mis-reports as non-constant (ibex, rv-ibex2 run:
#       "chip_top.sv:85: ERROR: Parameter u_ibex_core.RV32M with non-constant
#       value!"). Without (B) the retry never fired on ibex-class designs → a
#       false compared_points=0 FAIL cascading 24 steps.
# §4.05 NO-LEAK: widening the matcher widens what TRIGGERS a retry, never what
# PASSES. A genuine non-constant-param DESIGN bug is rejected by slang TOO; a
# slang-also-fails run STAYS FAIL (finalize_after_slang_retry never excuses it);
# and a miter that runs and leaves points unequal still FAILs. The retry only
# changes WHICH frontend reads the gold, never the equivalence verdict.
_FRONTEND_PARSE_ABORT_RE = re.compile(
    # (A) parse / lex aborts
    r"syntax\s+error"
    r"|unexpected\s+TOK_\w+"
    r"|TOK_PACKAGE|TOK_TYPEDEF"
    r"|unsupported\s+SystemVerilog"
    r"|can'?t\s+open\s+input\s+file"
    r"|unable\s+to\s+open"
    r"|no\s+such\s+file"
    r"|cannot\s+(?:find|open)\s+(?:file|module)"
    r"|failed\s+to\s+parse"
    # (B) elaboration aborts that slang resolves (SV package/enum-as-param-value)
    r"|Parameter\s+\S+\s+with\s+non-constant\s+value"
    r"|non-constant\s+value"
    r"|is\s+not\s+a\s+constant\b"
    r"|failed\s+to\s+evaluate",
    re.IGNORECASE)


def is_frontend_parse_abort(text: str) -> bool:
    """True iff a Yosys log carries a FRONTEND abort signature — a
    read_verilog/read_slang PARSE or ELABORATION failure that built no miter.
    PURE. Consulted ONLY when parse_error is True (0 miter), so it can only fire
    the slang retry / INCONCLUSIVE re-class on a zero-miter run — never on a real
    mismatch whose miter ran.

    v1.4.x — RETAINED for the slang-RETRY trigger and for the reason string, but
    NO LONGER the verdict classifier. INCONCLUSIVE-vs-FAIL on a zero-miter run is
    now decided by :func:`frontend_aborted_before_elaboration`, an observation of
    HOW FAR the run got rather than of how the tool phrased its abort."""
    return bool(_FRONTEND_PARSE_ABORT_RE.search(text or ""))


# HARD-MACRO STAGING GAP (#192) — yosys `hierarchy -check` aborts when the
# netlist instantiates a module whose definition was not read on that side:
#   ERROR: Module `\fakeram45_2048x39' referenced in module `\top' in cell
#          `\u_sram' is not part of the design.
# This is netgen-STABLE yosys wording (the `hierarchy` pass emits it verbatim
# for any unresolved instance). It aborts BEFORE `equiv_make`, so 0 points are
# ever compared — distinct from a genuine mismatch, whose miter DID run. The
# captured group is the unresolved (macro) module name, with any leading Verilog
# escape backslash stripped. chip/PDK-AGNOSTIC: keys on the yosys message shape,
# never on a design/macro literal.
_UNDEF_MODULE_RE = re.compile(
    r"Module\s+[`'\"]?\\?([A-Za-z_$][\w$]*)['`\"]?\s+referenced\s+in\s+module\b"
    r"[^\n]*?\bis\s+not\s+part\s+of\s+the\s+design",
    re.IGNORECASE)


def undefined_macro_modules(text: str) -> List[str]:
    """Sorted, de-duplicated module names the equiv run referenced but could
    not resolve — a hard macro (or any submodule) instantiated in the netlist
    whose definition was not staged, so `hierarchy -check` aborted before any
    miter was built. PURE.

    Consulted ONLY when parse_error is True (0 miter), so it can re-classify a
    zero-miter run to INCONCLUSIVE but can NEVER touch a run whose miter
    actually compared points — a real mismatch still FAILs."""
    return sorted({m.group(1) for m in _UNDEF_MODULE_RE.finditer(text or "")})


# ---------------------------------------------------------------------------
# STAGE-PROGRESS OBSERVABLE (v1.4.x) — how far did the yosys run actually get?
#
# THE RESIDUAL HALF OF THE ea13744db BUG. Frontend SELECTION moved to the
# observable there, but the VERDICT classification — INCONCLUSIVE vs FAIL on a
# zero-miter run — still keyed on `_FRONTEND_PARSE_ABORT_RE`. A reworded abort
# restores the false FAIL, which cascade-marks 24 downstream steps MISSING.
#
# The observable: yosys NUMBERS and ANNOUNCES every pass it dispatches
# ("1. Executing Verilog-2005 frontend: …", "2. Executing HIERARCHY pass …").
# Verified live on the vibeic-eda image:
#   read ok + hierarchy ok      -> passes = [Verilog-2005 frontend, HIERARCHY]
#   frontend abort (modern SV)  -> passes = [Verilog-2005 frontend]         <-- stopped AT the read
#   post-frontend failure       -> passes = [Verilog-2005 frontend, HIERARCHY]
#   yosys never ran / crashed   -> passes = []
# So "only frontend passes executed" is POSITIVE evidence that the read is where
# it stopped — i.e. no elaborated design was ever produced — whatever the tool
# said. Pass-class names ("… frontend") are yosys's own command-inventory
# naming, which is API-stable, unlike error phrasing which is not.
_YOSYS_PASS_RE = re.compile(r"^\s*[\d.]+\.\s+Executing\s+(.+?)\s*$", re.MULTILINE)
# A yosys READ pass announces itself as an "<X> frontend" (Verilog-2005 / SLANG /
# Liberty / RTLIL / BLIF). Every design-BUILDING pass announces as "<NAME> pass",
# and writers as "<NAME> backend".
#
# ANCHORED to where yosys structurally writes the class token, in two rounds of
# peer review with the sibling LVS wording fix.
#
# ROUND 1 (their finding): the captured pass name INCLUDES the pass ARGUMENTS —
# real yosys prints "Verilog-2005 frontend: /tmp/frontend/rtl/m.v" — so a bare
# \bfrontend\b also fires on a PATH containing that word. Misfires in the
# DANGEROUS direction: a design-BUILDING pass wrongly counted as a read pass
# empties the non-frontend list and buys the LENIENT verdict (INCONCLUSIVE).
#
# ROUND 2 (their sharpened threat model): requiring `frontend` to be followed by
# `:` / `.` / end was still forgeable, because those separators occur INSIDE
# arguments too — "SOMEPASS pass (reading /work/frontend.)" and
# "… (reading /work/frontend: x)" both satisfied it. Their sharper framing is the
# right one and generalises past LVS: THE DESIGN AND THE ENVIRONMENT NAME THEIR
# OWN THINGS, so any structural token matched against a region that contains
# paths / net names / cell names is a token those inputs can FORGE. (In netgen's
# case a SystemVerilog escaped identifier legally contains SPACES, so a net can
# spell a verdict phrase exactly.)
#
# So the class token is now read ONLY from the CLASS DESCRIPTOR — the text before
# the first argument separator (`:` for a frontend's file, `(` for a pass's
# description) — which is the one region yosys writes and the inputs cannot
# reach. Verified against real output: reads are "<X> frontend: <path>" or
# "<X> frontend."; builders are "<NAME> pass (<desc>)" or "<NAME> pass."; writers
# are "<X> backend.".
_YOSYS_PASS_ARG_SEP_RE = re.compile(r"[:(]")
_YOSYS_FRONTEND_CLASS_RE = re.compile(r"\bfrontend$", re.IGNORECASE)


def _yosys_pass_is_frontend(pass_name: str) -> bool:
    """True iff this yosys pass announcement is a READ (frontend) pass.

    Reads the class token from the DESCRIPTOR only, never from the arguments —
    see the note above. Fail-safe direction: anything unrecognised is treated as
    NOT a frontend pass, which pushes the verdict toward the BLOCKING outcome."""
    descriptor = _YOSYS_PASS_ARG_SEP_RE.split(pass_name or "", 1)[0]
    return bool(_YOSYS_FRONTEND_CLASS_RE.search(descriptor.strip().rstrip(".")))


def yosys_executed_passes(text: str) -> List[str]:
    """Ordered list of the yosys passes that ACTUALLY executed in this log.

    PURE. The primitive behind the stage-progress observable; exposed so a test
    can pin the parse against real transcripts."""
    return [m.group(1) for m in _YOSYS_PASS_RE.finditer(text or "")]


def frontend_aborted_before_elaboration(text: str) -> Tuple[bool, str]:
    """OBSERVABLE: did the run stop AT the frontend, producing no elaborated
    design? Returns (aborted_at_frontend, evidence).

    True requires POSITIVE evidence on BOTH counts:
      1. at least one pass executed AND it was a READ/frontend pass — so yosys
         genuinely ran and genuinely reached the read; and
      2. NO non-frontend pass ever executed — so the design was never built.

    This deliberately preserves the asymmetry the earlier fix imposed. A yosys /
    docker CRASH with no frontend evidence yields NO executed passes -> False ->
    the caller keeps the HARD FAIL. A run that got PAST the read and died later
    has a non-frontend pass in the list -> False -> HARD FAIL. Only the narrow
    "reached the read, never got past it" shape re-classifies to INCONCLUSIVE.

    §4.05 — INCONCLUSIVE is the LESS blocking outcome (a FAIL cascade-marks 24
    downstream steps MISSING), so widening it is the direction that could hide a
    genuine failure. That is exactly why this requires positive stage evidence
    rather than merely the ABSENCE of a recognised phrase. Neither outcome is
    ever a PASS: a miter that runs and leaves points unequal still FAILs."""
    passes = yosys_executed_passes(text)
    if not passes:
        return False, ("no yosys pass executed at all — the tool never reached "
                       "a frontend (crash / container / invocation failure); "
                       "there is no evidence of a frontend abort")
    non_frontend = [p for p in passes if not _yosys_pass_is_frontend(p)]
    if non_frontend:
        return False, (
            f"the run got PAST the read — {len(passes)} pass(es) executed and "
            f"{non_frontend[0]!r} ran after the frontend, so a design WAS "
            f"elaborated; whatever failed later is not a frontend abort")
    return True, (
        f"only frontend/read pass(es) executed ({', '.join(passes[:3])}"
        f"{'…' if len(passes) > 3 else ''}) and no design-building pass ever "
        f"ran — the read is where it stopped, so no elaborated design was "
        f"produced")


# SV-2017 gold signature — DESIGN properties the yosys built-in reader cannot
# reliably elaborate: a `package`/`interface` declaration, a package import, a
# package-scope reference (`pkg::CONST`, the ibex `ibex_pkg::RV32MFast`-as-param
# case), or a `typedef`. Used ONLY to EXPLAIN which frontend was chosen — never
# as the sole trigger, and never keyed on a chip name, a path, or an IC class.
_SV2017_GOLD_RE = re.compile(
    r"(?m)^\s*(?:package|interface)\s+\w+"
    r"|^\s*import\s+\w+\s*::"
    r"|^\s*typedef\b"
    r"|(?<![\w.])\w+\s*::\s*\w+")


def gold_requires_sv2017(gold_files: List[str]) -> bool:
    """True iff the gold RTL uses SV-2017 constructs beyond the yosys built-in
    reader's subset (package / interface / import / package-scope ref / typedef).
    PURE, filesystem-only, DESIGN-property driven."""
    for f in gold_files:
        try:
            text = Path(f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _SV2017_GOLD_RE.search(text):
            return True
    return False


# A WALL-BUDGET KILL IS NOT A FRONTEND FAILURE.
#
# MEASURED 2026-08-27 (VerilogEval-Human Prob030_popcount255, a 255-bit popcount
# whose gold is PURELY COMBINATIONAL): `yosys -s reports/lec_equiv.ys` ground at
# 99.9% CPU for the full 7195s container budget inside `equiv_simple`, was
# SIGTERMed, and left `parse_error=True` (no equiv_status, so nothing parsed).
# `should_retry_gold_with_slang` keys on exactly that observable - "the built-in
# gold read produced NO equivalence miter at all" - and so read the budget kill
# as a GOLD-READ failure and re-ran the WHOLE proof under `read_slang` with the
# SAME 7195s budget. Observed directly on the live sweep: yosys pid A went
# <defunct> at the deadline, reports/lec_equiv.ys was rewritten with
# `read_slang` 20s later, and a fresh yosys pid B started on it. NOTHING was
# written to reports/lec.json or reports/lec.rpt at the deadline - not a FAIL,
# not a SKIPPED-CONDITION, nothing - because the report is only written after
# the whole retry ladder finishes. With the -DSYNTHESIS rung as well, the same
# undecidable proof can consume THREE full budgets (~6h) before the honest
# "I could not decide this within the resources given" reaches disk.
#
# The retry rule was missing one conjunct: "no miter was built" must exclude
# "we never found out, because the clock killed it". Those are different facts.
# The gold read DEMONSTRABLY SUCCEEDED here - yosys reached `equiv_simple`,
# which is downstream of both reads - so a different FRONTEND cannot change the
# outcome; only a larger budget or a cheaper proof strategy could, and neither
# is what the retry does.
#
# `_TIMEOUT_MARKER` is written ONLY by this program's own two budget-kill paths
# (host `TimeoutExpired` and the container `timeout` rc in
# `_CONTAINER_TIMEOUT_RCS`) - it is never tool output a design could emit - so
# this discriminator cannot fire on any run that was not killed by OUR bound.
#
# DIRECTION OF RISK: declining the retry can only make the recorded outcome
# LESS conclusive, never more. It cannot manufacture a PASS (only a completed
# `equiv_status` with 0 unproven does that, and a killed run has no
# equiv_status), and it cannot hide a mismatch (a recorded counterexample keeps
# its FAIL through `_MISMATCH_EVIDENCE_RE` in the SAME branch). What it removes
# is one way to spend hours and record nothing. chip/PDK/tool-AGNOSTIC: keys
# only on this program's own marker.
def budget_kill_blocks_frontend_retry(gold_log: str) -> Tuple[bool, str]:
    """(blocked, evidence) - True iff <gold_log> was cut short by OUR OWN wall
    budget, which makes a gold-FRONTEND retry incapable of changing the answer.

    PURE. Returns False (retry stays available) for every log that does not
    carry `_TIMEOUT_MARKER`, so no run that ends on its own is moved."""
    if not _TIMEOUT_RE.search(gold_log or ""):
        return False, ""
    return True, (
        "the gold read was NOT the failure - yosys ran to its wall budget and "
        "was killed mid-proof (this program's own budget-exhaustion marker is "
        "in the log), so no equiv_status was reached. Re-reading the gold with "
        "a different frontend cannot make an undecided SAT proof converge; it "
        "only spends the budget again and delays the honest record. Raise "
        "--timeout / VIBEIC_LEC_YOSYS_TIMEOUT_S, or close the remainder with "
        "sign-off LEC.")


def should_retry_gold_with_slang(parsed: Dict, gold_log: str,
                                 requires_sv2017: bool) -> "tuple[bool, str]":
    """Decide whether to re-read the GOLD with `read_slang`. Returns (retry, why).

    THE RULE (general, design-driven): retry whenever the built-in gold read
    produced NO equivalence miter at all — i.e. `parse_error`, meaning yosys
    printed no proven/unproven/total counts and no SAT-model abort, so ZERO
    points were compared. A zero-miter run carries no equivalence evidence in
    either direction, and `read_slang` is the most capable SV-2017 frontend
    available (the same one `synth` falls back to), so it has not yet been given
    a chance to decide the question.

    WHY NOT the old rule: the retry used to fire only when the yosys log matched
    `_FRONTEND_PARSE_ABORT_RE` — a hard-coded allow-list of error PHRASINGS.
    Any zero-miter abort worded differently silently skipped the capable
    frontend and fell through to a FALSE FAIL (this is exactly how ibex's
    "Parameter ... with non-constant value" elaboration abort was missed until
    the phrase was hand-added). Keying on the OBSERVABLE (no miter was built)
    instead of on the tool's wording removes the whole class of misses.

    §4.05 NO-LEAK — widening the TRIGGER cannot widen what PASSES:
      * `parse_error` is False the moment a miter actually ran, so a genuine
        mismatch (miter ran, points left unproven) can NEVER reach this retry.
      * If slang also builds no miter, `finalize_after_slang_retry` keeps the
        verdict at FAIL — no free non-blocking pass.
      * The VERDICT classification (INCONCLUSIVE vs FAIL) still uses the narrow
        `is_frontend_parse_abort` signature, deliberately NOT widened here: a
        yosys/docker crash with no frontend-abort evidence stays a hard FAIL.
    The `why` string is recorded in reports/lec.json so the fallback and its
    justification are explicit and auditable.
    """
    if not parsed.get("parse_error"):
        return False, ""
    # A WALL-BUDGET KILL IS NOT A GOLD-READ FAILURE (measured 2026-08-27).
    # `parse_error` means "no miter counts were parsed", and a run KILLED at its
    # deadline mid-`equiv_induct` produces exactly that - with no equiv_status
    # line - even though the gold read SUCCEEDED and the proof was running. This
    # retry exists for a gold read that FAILED; firing it on a killed one asks a
    # different frontend to make a combinatorially explosive proof cheap, which
    # it cannot, and costs another full budget to find out (Prob030_popcount255:
    # 7195s ground, killed, then re-read with read_slang and started over).
    #
    # ASSEMBLY v1.11.95 - TWO BRANCHES IMPLEMENTED THIS SAME GUARD, and only one
    # copy may survive. The predicate is IDENTICAL: budget_kill_blocks_frontend_
    # retry's whole test is `_TIMEOUT_RE.search(gold_log)`, and `_TIMEOUT_RE` is
    # written ONLY by the two kill paths in `run_yosys_equiv`, so its presence is
    # unambiguous evidence of budget exhaustion. The named function is kept
    # because it is a superset: same predicate, PLUS the evidence string that
    # reaches reports/lec.json, and it is the form under test
    # (test_lec_bounded_proof.py::test_budget_killed_log_blocks_the_retry). A
    # second inline `_TIMEOUT_RE.search` here would be an unreachable duplicate
    # of one decision, not a second guard.
    #
    # 4.05 NO-LEAK: this only ever turns a retry OFF - it can never widen what
    # PASSES, and it leaves the timeout VERDICT classification untouched. The
    # genuine gold-read failures this retry was written for carry no such
    # marker, so that recovery is unaffected. Declining here is what lets the
    # SKIPPED-CONDITION verdict the classifier ALREADY computes actually reach
    # reports/lec.json.
    _budget_blocked, _budget_ev = budget_kill_blocks_frontend_retry(gold_log)
    if _budget_blocked:
        return False, _budget_ev
    # AND THE NOT-BLOCKED ANSWER IS RECORDED TOO (#313 §6). "the budget-kill
    # check ran and did not block" and "the budget-kill check never ran" are
    # different facts about a run, and until this line the log could not tell
    # them apart — the decline was audible and the non-decline was silent,
    # which is the asymmetry `silent_decline_audit` exists to remove. It names
    # `_budget_blocked` so the predicate's own answer is in the record, not
    # merely its consequence.
    print(f"[lec_run] gold-frontend retry: budget-kill check consulted, "
          f"_budget_blocked={_budget_blocked!r} — not declined here.",
          file=sys.stderr)
    if is_frontend_parse_abort(gold_log):
        return True, ("built-in read_verilog -sv aborted with a frontend "
                      "parse/elaboration signature and built no miter")
    if requires_sv2017:
        return True, ("built-in read_verilog -sv built no miter and the gold "
                      "RTL uses SV-2017 constructs (package / interface / "
                      "import / package-scope ref / typedef) outside its "
                      "supported subset")
    return True, ("built-in read_verilog -sv built no miter (0 compared "
                  "points, no equivalence evidence) — the capable SV-2017 "
                  "frontend has not been tried yet")


def finalize_after_slang_retry(parsed: Dict, slang_retry_failed: bool) -> Dict:
    """Downgrade a provisional INCONCLUSIVE verdict to FAIL when the read_slang
    gold-read retry was attempted and slang ALSO could not build a miter.

    §4.05 NO-LEAK: INCONCLUSIVE (a non-blocking SKIPPED-CONDITION) is only
    justified when the capable SV-2017 frontend was NOT tried (e.g. slang
    unavailable). Once slang — the most capable frontend — has ALSO failed to
    elaborate the gold, the design is not excused as a built-in-reader tool gap;
    a genuine elaboration error must NOT get a free non-blocking pass. PURE; a
    no-op when slang was not attempted or slang succeeded.

    EXCEPTION — the #192 hard-macro staging gap is NOT a gold-frontend failure.
    That INCONCLUSIVE is raised when the GATE side's `hierarchy -check` aborts
    because the netlist instantiates a hard macro whose definition was never
    staged into the miter. The gold RTL elaborated fine; no frontend, however
    capable, can supply a module that is not there, so "slang also failed" is
    not evidence about this design at all. Downgrading it re-introduces exactly
    the harm #192 removed — a comparison that never started, booked as a proven
    non-equivalence — and worse, the downgrade's own text tells the operator to
    "fix the elaboration error", pointing at RTL that is provably fine.

    Measured 2026-07-22 on a design carrying a `pdk_local` SRAM macro: `lec.json`
    came out `verdict=FAIL`, `compared_points=0`, explanation "Neither
    read_verilog -sv nor the read_slang SV-2017 frontend could elaborate the
    gold", while that same JSON carried
    `undefined_macro_modules: ["<the macro>"]` and `lec.rpt` ended on the
    gate-side line `ERROR: Module '\\<macro>' referenced in module '\\<top>' in
    cell '\\<inst>' is not part of the design.` — after the gold had already run
    58 passes. The classification was right and the finalizer overwrote it.

    Keyed on the recorded `undefined_macro_modules`, so it is chip-, macro- and
    PDK-AGNOSTIC, and it cannot excuse a real gold elaboration failure (which
    records no undefined macro)."""
    if not slang_retry_failed or parsed.get("verdict") != "INCONCLUSIVE":
        return parsed
    if parsed.get("undefined_macro_modules"):
        # Gate-side hard-macro staging gap — nothing to do with the gold
        # frontend. Keep the #192 INCONCLUSIVE and its remediation.
        return parsed
    out = dict(parsed)
    out["verdict"] = "FAIL"
    out["equivalent"] = False
    out["verdict_explanation"] = (
        "Neither read_verilog -sv nor the read_slang SV-2017 frontend could "
        "elaborate the gold to build an equivalence miter (0 compared points). "
        "With the capable frontend ALSO failing, this is not excused as a "
        "built-in-reader tool gap → reported as FAIL (fix the elaboration "
        "error). §4.05: a slang-also-fails run never becomes a non-blocking "
        "INCONCLUSIVE.")
    return out


def parse_equiv_output(text: str) -> Dict:
    """Parse raw Yosys equiv_status stdout into a structured verdict.

    Returns a dict with:
        proven, unproven, total            : Optional[int]
        sat_model_unsupported_cells        : List[{"cell", "cell_type"}]
        unproven_cells                     : List[str]
        success_line                       : bool
        parse_error                        : bool
        equivalent                         : bool
        verdict                            : "PASS"|"SKIPPED-CONDITION"|"FAIL"
        verdict_explanation                : str

    Never fabricates: when nothing is parseable, parse_error is True and the
    counts stay None (never the ambiguous -1 sentinel).
    """
    text = text or ""

    final = _FINAL_RE.search(text)
    proven: Optional[int] = int(final.group(1)) if final else None
    unproven: Optional[int] = int(final.group(2)) if final else None
    total: Optional[int] = None

    m = _EQUIV_SIMPLE_ENTRY_RE.search(text)
    if m:
        total = int(m.group(1))
    if total is None:
        m = _OLD_TOTAL_RE.search(text)
        if m:
            total = int(m.group(1))

    if proven is None:
        m = _PROVED_SIMPLE_RE.search(text)
        if m:
            proven = int(m.group(1))
    if proven is None or total is None:
        m = _SIMPLE_SLASH_RE.search(text)
        if m:
            if proven is None:
                proven = int(m.group(1))
            if total is None:
                total = int(m.group(2))

    if unproven is None:
        m = _INDUCT_FOUND_RE.search(text)
        if m:
            unproven = int(m.group(1))

    # Reconstruct the missing piece from the other two when possible.
    if total is None and proven is not None and unproven is not None:
        total = proven + unproven
    if total is not None and proven is not None and unproven is None:
        unproven = total - proven
    if total is not None and unproven is not None and proven is None:
        proven = total - unproven

    sat_aborts: List[Dict[str, str]] = [
        {"cell": mm.group(1), "cell_type": mm.group(2)}
        for mm in _SAT_ABORT_RE.finditer(text)
    ]

    ml = _UNPROVEN_LIST_RE.search(text)
    unproven_cells = (
        [t for t in re.split(r"[,\s]+", ml.group(1)) if t][:50] if ml else []
    )

    success_line = bool(_SUCCESS_RE.search(text))

    parse_error = proven is None and unproven is None and total is None \
        and not sat_aborts

    matched = (
        not parse_error
        and unproven == 0
        and (proven or 0) > 0
        and not sat_aborts
    )

    _fe_aborted, _fe_evidence = frontend_aborted_before_elaboration(text)
    _undef_macros = undefined_macro_modules(text)
    if parse_error and _undef_macros:
        # HARD-MACRO STAGING GAP (#192). The netlist instantiates a module whose
        # definition was not staged on this side, so `hierarchy -check` aborted
        # BEFORE equiv_make and 0 points were compared. A killed-before-it-ran
        # comparison is NOT a proven non-equivalence — yet booking it as FAIL
        # (which is what the generic parse_error branch below does) reports a
        # comparison that never started as if equivalence had been tested and
        # failed. That is the exact harm in #192. Classify INCONCLUSIVE: a
        # disclosed staging gap, non-blocking, never a vacuous PASS.
        #
        # We deliberately do NOT auto-stage the macro into the miter and
        # re-compare. In-container negative controls proved that naive symmetric
        # staging (the full behavioural model on both sides) AND a `-lib`
        # blackbox BOTH produce a FALSE PASS on a memory macro — even for a
        # genuine logic bug in the netlist that FEEDS the macro — because yosys
        # equiv's name-based net matching mis-handles the hierarchical macro I/O
        # (the blackbox loses its port directions; the full model name-aliases
        # the macro output net to a top port). A false LEC PASS ships a broken
        # netlist as verified, which is strictly worse than the false FAIL this
        # fix removes. Sound hard-macro equivalence needs a blackbox
        # assume-guarantee this recipe cannot guarantee → close with sign-off
        # LEC (Conformal/VC LEC), which does.
        equivalent = False
        verdict = "INCONCLUSIVE"
        verdict_explanation = (
            "LEC built NO equivalence miter — the netlist instantiates hard "
            f"macro/submodule(s) {_undef_macros} whose definition was not "
            "staged, so `hierarchy -check` aborted before equiv_make and 0 "
            "points were compared. NOT a proven non-equivalence (no miter ran) "
            "→ INCONCLUSIVE, never a hard FAIL that cascade-marks downstream "
            "steps MISSING and never a vacuous PASS. Close with sign-off LEC "
            "(Conformal/VC LEC), which handles hard macros with a sound "
            "blackbox assume-guarantee. See reports/lec.rpt for the hierarchy "
            "error.")
    elif parse_error and _fe_aborted:
        # OBSERVABLE (v1.4.x): the run REACHED the read and never got past it,
        # so no elaborated design was ever produced and NO miter was built → 0
        # compared points. Not classifiable as PASS or FAIL → INCONCLUSIVE.
        # Decided by stage progress, NOT by how the frontend phrased its abort —
        # a reworded abort used to restore the false FAIL that cascade-marks 24
        # downstream steps MISSING.
        # §4.05: this requires POSITIVE stage evidence, so a crash with no
        # frontend evidence, and a run that died AFTER elaborating, both stay
        # HARD FAIL below. A genuine miter that runs and leaves unproven points
        # still FAILs; only the zero-miter stopped-at-the-read shape re-classes.
        equivalent = False
        verdict = "INCONCLUSIVE"
        verdict_explanation = (
            "Yosys built NO equivalence miter — the run stopped AT the frontend "
            "so no elaborated design was ever produced, leaving 0 compared "
            f"points. Observable: {_fe_evidence}. Not classifiable as PASS or "
            "FAIL → INCONCLUSIVE (the static/functional sign-off is not decided "
            "here; re-run with the slang frontend or fix the read error). See "
            "reports/lec.rpt for the frontend error.")
    elif parse_error and _TIMEOUT_RE.search(text):
        # MERGE (#155 origin SKIPPED-CONDITION vs local FAIL) — EVIDENCE-BASED
        # SPLIT: the miter was still running when the wall budget expired, leaving
        # no equiv_status (parse_error) but the self-written timeout marker.
        # Classify by the ACTUAL EVIDENCE in the log, not a binary policy:
        #   * if the LEC actually RECORDED a mismatch / counterexample before it
        #     was killed → a proven non-equivalence is a real FAIL regardless of
        #     the timeout (a mismatch found is a mismatch found);
        #   * otherwise (pure resource/time exhaustion, 0 points decided) →
        #     SKIPPED-CONDITION: a DISCLOSED budget/capability gap (the SAME
        #     family as the $mem_v2 SAT-model skip below), NOT a proven mismatch
        #     — so origin #155 holds: a slow-but-not-disproven proof (e.g.
        #     sha256's >1200s memory-inclusive miter) is NOT spuriously FAILed.
        # It is STILL a visible non-PASS (equivalent:false, verdict != PASS),
        # never a silent free pass — so local's "a resource limit is never a free
        # pass" ALSO holds: a real regression cannot hide behind it.
        # §4.05: the mismatch discriminator is PRECISION-first — it fires only on
        # an unmistakable non-equivalence phrase a pure-timeout log cannot carry,
        # so the DANGEROUS direction (a spurious FAIL on a slow proof) cannot
        # occur; a missed mismatch degrades to the visible SKIPPED-CONDITION.
        equivalent = False
        if _MISMATCH_EVIDENCE_RE.search(text):
            verdict = "FAIL"
            verdict_explanation = (
                "Yosys equiv exceeded its time budget, but the log RECORDED a "
                "mismatch / counterexample before it was killed — a proven "
                "non-equivalence is a real FAIL regardless of the timeout. See "
                "reports/lec.rpt for the recorded counterexample.")
        else:
            verdict = "SKIPPED-CONDITION"
            verdict_explanation = (
                "Yosys equiv exceeded its time budget before equiv_status could "
                "report — 0 points compared and NO mismatch was recorded, so "
                "there is no equivalence evidence in either direction. This is a "
                "DISCLOSED budget/capability gap (the same family as the $mem_v2 "
                "SAT-model skip), NOT a proven mismatch: raise --timeout or close "
                "the remainder with sign-off LEC (Conformal/VC LEC). It stays a "
                "visible non-PASS (equivalent:false) — never a silent free pass a "
                "regression could hide behind.")
    elif parse_error:
        # HARD FAIL, deliberately NOT re-classified: there is no positive
        # evidence the FRONTEND is where this stopped. Either yosys never ran
        # (crash / container failure) or it elaborated a design and died later —
        # both are real failures, and INCONCLUSIVE (the less blocking outcome)
        # must never be reachable without stage evidence. The observable that
        # ruled it out is recorded so the distinction is auditable.
        equivalent = False
        verdict = "FAIL"
        verdict_explanation = (
            "Yosys produced no parseable equivalence result — the equiv "
            "check did not reach a verdict (see reports/lec.rpt for the raw "
            f"tool log). NOT re-classified as INCONCLUSIVE because {_fe_evidence}"
            " — a run with no frontend-abort evidence stays a blocking FAIL.")
    elif (_TIMEOUT_RE.search(text)
          and proven is None and unproven is None
          and not _MISMATCH_EVIDENCE_RE.search(text)):
        # ORGANIC v1462 (ibex/CPU-class) — a wall-clock TIMEOUT killed the run
        # BEFORE any completed equiv_status verdict: NO `N are proven and M are
        # unproven` line was ever emitted (proven AND unproven both unknown),
        # only the INITIAL `$equiv` cell TOTAL leaked into the parse (so
        # parse_error is False and the parse_error+timeout branch above was
        # skipped — that is the bug this branch fixes). yosys was killed
        # mid-equiv_simple, so ZERO points were decided in EITHER direction and
        # NO counterexample was recorded. This is the SAME zero-completed-
        # comparison class as the frontend parse-abort (INCONCLUSIVE), NOT a
        # proven mismatch — blocking the whole flow on it is a false FAIL that
        # cascade-marks downstream steps MISSING.
        #
        # §4.05 PRECISION-first / NO-LEAK: this fires ONLY when NEITHER a proven
        # NOR an unproven count exists (no completed comparison) AND no
        # counterexample phrase is present. A COMPLETED miter that left points
        # unproven (e.g. sha256: `952 are proven and 1034 are unproven` — both
        # parsed) has proven!=None and NEVER reaches here → it stays a real FAIL
        # (the tested `miter ran, unproven>0 = FAIL` doctrine is untouched). A
        # timeout that DID record `_MISMATCH_EVIDENCE_RE` escalates to the
        # blocking FAIL below. Never a PASS — equivalent stays False.
        equivalent = False
        verdict = "INCONCLUSIVE"
        verdict_explanation = (
            "Yosys equiv was KILLED by the wall-clock budget BEFORE any "
            "completed equiv_status verdict — no `N proven / M unproven` line "
            "was emitted (only the initial $equiv cell total was seen) and NO "
            "counterexample was recorded, so 0 points were decided in either "
            "direction. A budget-exhausted proof is NOT a proven "
            "non-equivalence → INCONCLUSIVE (a disclosed budget gap: raise "
            "--timeout or close with sign-off LEC). It stays a visible non-PASS "
            "(equivalent:false), never a silent free pass a regression could "
            "hide behind.")
    elif matched:
        equivalent = True
        verdict = "PASS"
        verdict_explanation = (
            f"all {proven}/{proven} $equiv cells proven; RTL and gate "
            "netlist structurally equivalent"
            + (" (Yosys: Equivalence successfully proven!)"
               if success_line else ""))
    elif sat_aborts:
        equivalent = False
        verdict = "SKIPPED-CONDITION"
        types = sorted({c["cell_type"] for c in sat_aborts})
        verdict_explanation = (
            f"Yosys proved {proven if proven is not None else '?'}/"
            f"{total if total is not None else '?'} structural equivalence; "
            f"{len(sat_aborts)} cell(s) lacked a SAT model in equiv_induct "
            f"(custom-PDK Liberty primitives without Yosys built-in "
            f"semantics: {', '.join(types[:6])}). This is a disclosed tool "
            "capability-gap, NOT a proven mismatch — sign-off LEC "
            "(Conformal/VC LEC) required to close the remainder.")
    else:
        # A COMPLETED miter left points unproven. #208 — distinguish a genuine
        # difference (witnessed by a COUNTEREXAMPLE) from equiv_induct simply
        # NOT CONVERGING (a flat wall that proved nothing and recorded no
        # counterexample). The latter is INCONCLUSIVE, not NOT_EQUIVALENT: a
        # non-convergent induction is not evidence of non-equivalence.
        # §4.05 PRECISION-first / NO-LEAK: the re-class fires ONLY when there is
        # (i) positive non-convergence evidence AND (ii) NO counterexample. A
        # real mismatch prints a counterexample → _MISMATCH_EVIDENCE_RE matches
        # → stays the blocking FAIL below; a miter that leaves points unproven
        # WITHOUT the flat-wall signature also stays FAIL. Never a PASS.
        _noconv, _noconv_ev = induction_did_not_converge(text)
        _has_ctrex = bool(_MISMATCH_EVIDENCE_RE.search(text))
        # A STATELESS MITER CANNOT HAVE AN INDUCTION-DEPTH PROBLEM. See
        # miter_is_stateless: on a combinational miter every rung of the
        # `-seq` ladder is guaranteed to print `Proved 0 previously unproven`
        # for any point equiv_simple left open, so the flat-wall signature
        # fires on EVERY real combinational mismatch and laundered it into a
        # non-blocking INCONCLUSIVE. Requiring positive evidence that the
        # miter holds state is what lets the FAIL survive. Fail-CLOSED: when
        # statelessness cannot be established, `_stateless` is False and this
        # line is a no-op -- every sequential design keeps today's verdict.
        _stateless, _stateless_ev = miter_is_stateless(text)
        if _stateless:
            _noconv = False
            _noconv_ev = _stateless_ev
        # #778 — a `-seq` ladder that ran out of depth WHILE STILL PROVING new
        # cells on its deepest rung (converging, not a flat wall) is the same
        # disclosed sequential-depth capability gap. Only consulted when there is
        # neither a flat wall nor a counterexample, so it can never soften a real
        # mismatch (which prints a counterexample → stays the blocking FAIL).
        if not _noconv and not _has_ctrex and not _stateless:
            _noconv, _noconv_ev = induction_ladder_exhausted(text)
        # A WALL-CLOCK KILL THAT MADE PARTIAL PROGRESS.
        #
        # The three budget guards above all have a precondition this shape
        # fails, so it fell through to the blocking FAIL below:
        #   * the `parse_error + _TIMEOUT_RE` branch needs NOTHING parsed;
        #   * the `proven is None and unproven is None` branch needs NEITHER
        #     count parsed;
        #   * `induction_did_not_converge` needs `Proved 0` or `Circuit
        #     inherently diverges`, and `induction_ladder_exhausted` needs an
        #     `equiv_induct` marker — NEITHER exists when the clock kills the
        #     run during equiv_simple, before equiv_induct ever starts.
        #
        # So a run killed mid-`equiv_simple` AFTER it proved some cells parses
        # as `proven=N>0`, `unproven=total-N>0`, no flat wall, no ladder, no
        # counterexample — and was reported as
        #     "N/T proven, U unproven — the RTL and gate netlist MAY GENUINELY
        #      DIFFER at these points."
        # from a log whose last line is this program's OWN
        # `_TIMEOUT_MARKER`. That is the exact harm the module docstring says
        # this file exists to prevent: "a killed run produced NO evidence —
        # indistinguishable at the gate from a real mismatch", to be "NAMED
        # (raise --timeout) instead of read as a mismatch that was never
        # found."
        #
        # THE PRECISE DISTINCTION — a MEASURED unproven count vs an INFERRED
        # one. This is the line the existing doctrine already draws, which the
        # budget branches simply never consulted:
        #
        #   * `equiv_status` emitted "Of those cells N are proven and M are
        #     unproven" (_FINAL_RE). Those M points WERE attempted and left
        #     unproven — a real per-point verdict. A timeout marker arriving
        #     afterwards (e.g. rc=137 re-attaching it) cannot retract it, and
        #     it must STAY FAIL. Asserted by
        #     `test_lec_run.test_container_timeout_rc_with_recorded_mismatch_still_fails`
        #     and `test_v1462_lvs_lec_manifest_capture
        #      .test_timeout_with_partial_completed_verdict_still_fails`.
        #
        #   * NO `_FINAL_RE` line: `unproven` was not measured at all, it was
        #     RECONSTRUCTED by `total - proven` further up. Those points were
        #     never attempted — the clock killed the run first. Reporting them
        #     as points where the designs "may genuinely differ" states a
        #     comparison that never happened.
        #
        # So the re-class fires only on (timeout marker) AND (no completed
        # equiv_status) AND (no counterexample). §4.05 PRECISION-first /
        # NO-LEAK: each of the three conjuncts removes a way this could soften
        # a real result, and `_TIMEOUT_RE` is written only by the two kill
        # paths in run_yosys_equiv, so an in-budget run is untouched.
        _budget_killed = bool(_TIMEOUT_RE.search(text))
        _measured_verdict = bool(_FINAL_RE.search(text))
        if _budget_killed and not _measured_verdict and not _has_ctrex \
                and not _noconv:
            _noconv = True
            _noconv_ev = (
                "the wall-clock budget killed yosys mid-proof, before "
                "equiv_induct ran — the unproven remainder was never "
                "attempted, not refuted")
        # NO-COMPLETED-COMPARISON KILL (measured: opentitan_aes × sky130A).
        # A miter WAS built — `not parse_error`, so `total` is known — but
        # NEITHER a proven NOR an unproven count was ever recorded: equiv_make
        # ran and then NO equiv_simple / equiv_induct / equiv_status verdict
        # reached the log, and NO counterexample was seen. A COMPLETED equiv
        # pass ALWAYS emits at least one count — equiv_status' "N proven / M
        # unproven" (_FINAL_RE), equiv_simple's "Proved N previously unproven"
        # (_PROVED_SIMPLE_RE, N may be 0), or equiv_induct's "Found N unproven
        # … in module equiv" (_INDUCT_FOUND_RE) — so `proven is None AND
        # unproven is None` means the proof was CUT OFF before any point was
        # decided: an external kill / crash / container interruption that did
        # NOT route through the wall-budget marker path (_TIMEOUT_RE absent, so
        # _budget_killed above did not fire). Zero decided points + zero
        # counterexamples = no equivalence evidence in EITHER direction — the
        # exact no-evidence state this module's docstring exists to keep OUT of
        # a false NOT_EQUIVALENT ("a killed run produced NO evidence —
        # indistinguishable at the gate from a real mismatch"). §4.05 NO-LEAK:
        # a real mismatch carries a counterexample (_has_ctrex) OR a completed
        # status with unproven>0 (proven parsed), so it can NEVER reach here —
        # this softens ONLY a run that decided nothing. INCONCLUSIVE, never
        # FAIL, never PASS. MEASURED WITNESS: opentitan_aes's Step-13 lec.rpt
        # ended mid-`equiv_simple` (only ~1720/31850 cells attempted, no
        # equiv_status, no "Proved N", no marker) and was booked FAIL "may
        # genuinely differ" — a fabricated non-equivalence that blocked 24
        # downstream steps.
        _no_completed_comparison = (proven is None and unproven is None)
        if _no_completed_comparison and not _has_ctrex and not _noconv:
            _noconv = True
            _noconv_ev = (
                "equiv_make built the miter but NO equiv_simple/induct/status "
                "verdict was ever recorded (no proven and no unproven count) "
                "and no counterexample was seen — the proof was cut off before "
                "any point was decided (an interrupted/killed/crashed run "
                "outside the wall-budget marker path)")
        if _no_completed_comparison and _noconv and not _has_ctrex:
            # The miter was built but the proof was cut off before ANY point was
            # decided. Distinct wording from the convergence-wall case below:
            # equiv_induct never even ran here, so "did NOT converge" would be
            # inaccurate — the run recorded NO verdict at all.
            equivalent = False
            verdict = "INCONCLUSIVE"
            verdict_explanation = (
                f"A {total if total is not None else '?'}-point equivalence "
                "miter was built, but the proof recorded NO decided points "
                f"({_noconv_ev}) and NO counterexample "
                "(non_equivalent_points=0). A run that decided nothing is NOT "
                "evidence of non-equivalence: a real difference produces a "
                "counterexample or a completed equiv_status with unproven>0. "
                "→ INCONCLUSIVE (a killed/interrupted run outside the "
                "wall-budget marker path), never a false NOT_EQUIVALENT. Re-run "
                "uninterrupted (raise --timeout) or close with sign-off LEC "
                "(Conformal/VC LEC). Visible non-PASS (equivalent:false) — "
                "never a vacuous PASS a regression could hide behind.")
        elif _noconv and not _has_ctrex and (unproven or 0) > 0:
            equivalent = False
            verdict = "INCONCLUSIVE"
            verdict_explanation = (
                f"{proven if proven is not None else 0}/"
                f"{total if total is not None else '?'} proven, "
                f"{unproven if unproven is not None else '?'} unproven — but "
                "equiv_induct did NOT converge "
                f"({_noconv_ev}) and NO counterexample was recorded "
                "(non_equivalent_points=0). Non-convergence is NOT "
                "non-equivalence: a real difference produces a counterexample. "
                "→ INCONCLUSIVE (a disclosed sequential-depth capability gap), "
                "never a false NOT_EQUIVALENT. Close the remainder with sign-off "
                "LEC (Conformal/VC LEC), which handles deep sequential "
                "induction. Visible non-PASS (equivalent:false) — never a "
                "vacuous PASS a regression could hide behind.")
        else:
            equivalent = False
            verdict = "FAIL"
            verdict_explanation = (
                f"{proven if proven is not None else 0}/"
                f"{total if total is not None else '?'} proven, "
                f"{unproven if unproven is not None else '?'} unproven — the RTL "
                "and gate netlist may genuinely differ at these points."
                + (" A counterexample was recorded in the tool log."
                   if _has_ctrex else ""))

    return {
        "proven": proven,
        "unproven": unproven,
        "total": total,
        "sat_model_unsupported_cells": sat_aborts,
        "unproven_cells": unproven_cells,
        "success_line": success_line,
        "parse_error": parse_error,
        "equivalent": equivalent,
        "verdict": verdict,
        "verdict_explanation": verdict_explanation,
        # #192: hard macro(s) the run could not resolve (empty unless a
        # `hierarchy -check` abort on an unstaged module drove the INCONCLUSIVE
        # classification above).
        "undefined_macro_modules": _undef_macros,
    }


def build_report(parsed: Dict, top: str, gate_netlist: str,
                 liberty: Optional[str]) -> Dict:
    """Shape a parse result into the reports/lec.json schema the gate reads."""
    proven = parsed["proven"]
    unproven = parsed["unproven"]
    return {
        "equivalent": parsed["equivalent"],
        # proven $equiv cell count — >0 required for a non-vacuous PASS.
        "compared_points": proven if proven is not None else 0,
        # The SIZE of the proof obligation, i.e. how many $equiv points
        # equiv_make built. `parse_equiv_output` has always measured this (it
        # is the `total` it uses to reconstruct the other two counts) and
        # build_report has always dropped it, so an INCONCLUSIVE lec.json said
        # `compared_points: 0` and gave a reader NO way to tell "the budget
        # nearly covered it, raise --timeout" from "this miter is orders of
        # magnitude beyond any budget on this machine". Those call for opposite
        # actions. None only when no total was parseable (never fabricated).
        "miter_points": parsed.get("total"),
        # Yosys equiv_status does not emit a distinct proven-non-equivalent
        # count; a genuine difference surfaces as `unproven`, so this stays 0.
        "non_equivalent_points": 0,
        "unproven_points": unproven if unproven is not None else 0,
        "gold": f"{top} (RTL)",
        "gate": f"{Path(gate_netlist).name} (synth)",
        "tool": "yosys equiv_make+equiv_simple+equiv_induct",
        "verdict": parsed["verdict"],
        # A frontend parse-abort built no miter → INCONCLUSIVE (0 compared
        # points); the downstream gate treats this as a non-blocking
        # SKIPPED-CONDITION, never a hard FAIL nor a vacuous PASS.
        "inconclusive": parsed["verdict"] == "INCONCLUSIVE",
        # #208: True when the INCONCLUSIVE was reached by a COMPLETED miter that
        # left points unproven because equiv_induct did not converge (a flat
        # wall, no counterexample) — as opposed to the #192 zero-miter aborts.
        # Auditable so a reviewer sees this is a sequential-depth gap, not a
        # proven non-equivalence.
        "non_convergence": (parsed["verdict"] == "INCONCLUSIVE"
                            and (unproven or 0) > 0),
        # #192: names the unstaged hard macro(s) when a `hierarchy -check` abort
        # drove INCONCLUSIVE; empty on every other outcome. Auditable so a
        # reviewer sees WHY no miter was built.
        "undefined_macro_modules": parsed.get("undefined_macro_modules", []),
        "sat_model_unsupported_cells": parsed["sat_model_unsupported_cells"],
        "unproven_cells": parsed["unproven_cells"],
        "verdict_explanation": parsed["verdict_explanation"],
        "liberty": liberty,
        "program": PROGRAM,
    }


# ---------------------------------------------------------------------------
# Container plumbing (patterned on analog_real_corner_sweep._docker).
# ---------------------------------------------------------------------------
def _docker(container: str, cmd: str, timeout: int = 120):
    """Run `cmd` in the container under a bounded budget.

    The command carries its OWN container-side deadline a few seconds before
    the host's. Without it, `subprocess.run`'s timeout kills the `docker exec`
    CLIENT only — Docker does not propagate that inward, so the tool (here a
    yosys equivalence run on a whole gate netlist, which can be tens of GB of
    RAM) is ORPHANED and keeps burning a core and its memory unsupervised.
    This function's own `except TimeoutExpired` handler shows the timeout is an
    expected outcome, which makes the leak an expected outcome too.

    Same defect shape as the one measured leaking in the Phase-2 synth
    dispatch; fixed here by pattern from that measurement, using the shared
    helper. chip/tool-AGNOSTIC."""
    try:
        import _docker_watchdog as _dw
        cmd = _dw.wrap_with_container_timeout(cmd, timeout)
    except Exception:  # nosec — never let hardening break the call
        pass
    return subprocess.run(
        ["docker", "exec", container, "bash", "-lc", cmd],
        capture_output=True, text=True, timeout=timeout)


def _docker_exec3(container: str, cmd: str):
    """`(rc, out, err)` docker-exec adapter matching the `exec_fn` contract of
    synth_frontend.resolve_slang_load_prefix (used to probe the slang load
    prefix for the gold-read slang fallback). Never raises — returns a non-zero
    rc + empty streams on failure so the caller keeps the fork-safe default."""
    try:
        r = _docker(container, cmd, timeout=60)
        return r.returncode, r.stdout, r.stderr
    except (subprocess.SubprocessError, OSError) as exc:
        return 1, "", str(exc)


def _container_available(container: str) -> bool:
    try:
        return _docker(container, "true", timeout=30).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def _container_file_exists(container: str, path: str) -> bool:
    try:
        r = _docker(container, f"test -f {shlex.quote(path)}", timeout=30)
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False




def _strip_login_banner(text: str) -> str:
    """Drop the container login-profile `[INFO] ...` banner lines that
    `bash -lc` prints before the actual tool output (they are PATH/PYTHONPATH
    noise, not Yosys output). chip-AGNOSTIC."""
    return "\n".join(
        ln for ln in (text or "").splitlines()
        if not ln.lstrip().startswith("[INFO]"))


# A Yosys pre-techmap netlist instantiates its cells as ESCAPED internal-
# primitive identifiers (`\$_DFF_P_`, `\$_NAND_`, `\$_NOT_`, …). Detect that
# vocabulary structurally so the gate-read recipe can switch to `-icells`
# (which re-binds those names to real internal cells instead of aborting
# `hierarchy -check` on an "undefined module `\$_DFF_P_'"). Anchored on the
# backslash-escaped `\$_` prefix (tool-defined, NOT a chip/PDK literal) so it
# never matches an RTL wire named `$foo` or a Liberty cell `sky130_fd_sc_hd__*`.
_GENERIC_PRIM_RE = re.compile(r"\\\$_[A-Z]")


def _netlist_uses_generic_primitives(path: str) -> bool:
    """True iff <path> is a generic Yosys `$_`-primitive (pre-techmap) netlist —
    i.e. it instantiates escaped internal-gate identifiers like `\\$_DFF_P_`.
    chip/PDK-AGNOSTIC: keys only on the Yosys-defined `\\$_` prefix."""
    try:
        text = Path(path).read_text(errors="ignore")
    except OSError:
        return False
    return bool(_GENERIC_PRIM_RE.search(text))


# ---------------------------------------------------------------------------
# FUNCTIONAL-MODE (scan-aware) COMPARISON
# ---------------------------------------------------------------------------
# When the gate netlist is a REAL scan-inserted implementation netlist (see
# programs/fault_scan_chain_insert.py), it carries five DFT ports the RTL gold
# does not have — `sin`, `shift`, `test`, `tck` (inputs) and `sout` (output) —
# and its internal wires all carry the prefix `fault chain`'s resynthesis put
# on them.  Two things then break, and BOTH are name/interface problems, not
# equivalence problems:
#
#   1. `equiv_make` HARD-ERRORS on a gate port with no gold counterpart:
#        ERROR: Can't match gate port `test_gate' to a gold port.
#      MEASURED.  So the DFT ports must be REMOVED, not merely constrained;
#      a yosys `connect -set test 1'b0` tie-off leaves them in the port list.
#   2. `equiv_make` matches gold/gate wires BY NAME.  A uniform prefix on one
#      side destroys every internal correspondence and leaves only the output
#      port, which drops the miter from 97 compared points to 1 and sends
#      `equiv_induct` into a non-converging wall.  MEASURED: 63 proven with the
#      prefix mirrored, vs 1 unproven point without.
#
# The fix is a one-level wrapper on EACH side, with the gold wrapper's instance
# name chosen (an escaped identifier containing a dot) so the two `flatten`
# prefixes come out byte-identical:
#
#   gate:  rename <top> <top>__scan
#          module <top>(<rtl ports>)  { <top>__scan \_LECWRAP (…, .sin(1'b0),
#              .shift(1'b0), .test(1'b0), .tck(1'b0), .sout()) }
#   gold:  rename <top> <top>__rtl
#          module <top>(<rtl ports>)  { <top>__rtl \_LECWRAP.<prefix> (…) }
#
# WHAT THIS IS NOT.  It does not compare a different netlist: the file read on
# the gate side is the post-DFT netlist itself, and the wrapper only ties the
# DFT controls to their functional-mode values and drops the scan output.  The
# tie-off VALUES are load-bearing and proven so by controls: tying `test` to 1
# instead of 0 leaves 0 of 63 points proven, tying `shift` to 1 leaves 32
# unproven, and a one-gate `nor2_1`→`nand2_1` corruption of the scan netlist
# leaves 1 unproven.  All three FAIL, so the comparison cannot be vacuous.
#
# EVERY NAME HERE IS KNOWN, NOT SNIFFED.  The four tie-off ports and `sout` are
# `fault chain` OPTION names the scan producer passes; the internal prefix is
# MEASURED from the artefact by `fault_scan_chain_insert.measure_internal_prefix`
# and travels in `reports/phase2/dft/scan_chain.json`.  When the prefix cannot
# be measured the wrapper is still emitted WITHOUT it (the DFT ports still have
# to go) and the compared-point count simply drops — recorded in the report as
# `scan_functional_mode.internal_prefix: null`, never silently.

_LEC_WRAP_INST = "_LECWRAP"


def scan_mode_from_meta(meta: Optional[Dict]) -> Optional[Dict]:
    """Normalise `reports/phase2/dft/scan_chain.json` into the wrapper inputs.

    Returns None when the metadata does not describe a published scan netlist —
    an unpublished or failed chain must never trigger functional-mode wrapping,
    because then the gate netlist has no DFT ports and the wrapper would be a
    pure fabrication.  PURE.
    """
    if not isinstance(meta, dict):
        return None
    if not meta.get("published"):
        return None
    tie = meta.get("functional_mode_tieoff")
    sout = meta.get("scan_out_port")
    if not isinstance(tie, dict) or not tie or not isinstance(sout, str):
        return None
    prefix = meta.get("internal_wire_prefix")
    return {
        "tieoff": {str(k): int(v) for k, v in tie.items()},
        "scan_out_port": sout,
        "internal_prefix": prefix if isinstance(prefix, str) and prefix
                           else None,
    }


def build_scan_wrappers(top: str, rtl_ports: List[Tuple[str, str, str]],
                        scan_mode: Dict) -> Tuple[str, str]:
    """(gate_wrapper_verilog, gold_wrapper_verilog).  PURE.

    `rtl_ports` is the gold top's port list as `(direction, range, name)`
    triples — taken from the RTL, so the wrapper's interface IS the RTL's
    interface by construction and cannot drift from it.
    """
    decls = "\n".join(f"  {d} {r}{n};".replace("  ", " ").rstrip()
                      for d, r, n in rtl_ports)
    names = ", ".join(n for _, _, n in rtl_ports)
    conns = ", ".join(f".{n}({n})" for _, _, n in rtl_ports)
    tie = ", ".join(f".{p}(1'b{v})"
                    for p, v in sorted(scan_mode["tieoff"].items()))
    header = (f"/* GENERATED by lec_run.build_scan_wrappers — functional-mode\n"
              f"   comparison of the post-DFT scan netlist.  Do not edit. */\n")
    gate = (f"{header}"
            f"module {top}({names});\n{decls}\n"
            f"  {top}__scan \\{_LEC_WRAP_INST} (\n"
            f"    {conns},\n"
            f"    {tie}, .{scan_mode['scan_out_port']}());\n"
            f"endmodule\n")
    # The gold instance name reproduces the gate's FULL flatten prefix —
    # `<wrapper instance>.<fault-chain prefix>` — as one escaped identifier.
    pref = scan_mode.get("internal_prefix")
    gold_inst = f"{_LEC_WRAP_INST}.{pref}" if pref else _LEC_WRAP_INST
    gold = (f"{header}"
            f"module {top}({names});\n{decls}\n"
            f"  {top}__rtl \\{gold_inst} ({conns});\n"
            f"endmodule\n")
    return gate, gold


def build_equiv_script(gold_files: List[str], gate_netlist: str, top: str,
                       liberty: Optional[str],
                       blackbox_v: Optional[List[str]] = None,
                       gate_is_generic: bool = False,
                       gold_frontend: str = "verilog",
                       slang_prefix: str = "",
                       gold_defines: str = "-DSIMULATION -DYOSYS",
                       scan_mode: Optional[Dict] = None,
                       gate_wrapper_v: str = "",
                       gold_wrapper_v: str = "") -> str:
    """Build the Yosys RTL(gold)≡synth-netlist(gate) equiv script.

    v1.3.85 — APPROACH C (satgen-modelable BOTH sides). Step-13 compares an RTL
    gold against a Liberty-mapped synth gate — two DIFFERENT cell vocabularies,
    so `equiv_simple` cannot structural-match and EVERY point falls to the
    `equiv_induct` SAT engine. The prior recipes handed those points a Liberty
    cell the SAT engine cannot model:
      * `read_liberty -lib <lib>` (the delegated post-layout gate==gate recipe)
        imports the cells as BLACKBOXES with no logic → satgen aborts
        "ERROR: No SAT model available for cell _197__gate (NAND2D1)".
      * `-icells` + flatten aborted `hierarchy` on the Liberty-blackbox flop.
    The fix: on the GATE side read the Liberty WITHOUT `-lib` and with
    `-ignore_miss_func`, which EXPANDS every combinational cell's `function`
    and every `ff`/`latch` group into Yosys internal primitives
    (`NAND2D1` → `$_AND_`+`$_NOT_`; `DFFHQD1` → `$_DFF_P_`), then `flatten`
    inlines them so the netlist is pure `$_`-primitive logic the SAT engine CAN
    model. The GOLD stays RTL (coarse `$`-cells, already satgen-modelable).
    `-ignore_miss_func` degrades HONESTLY: a cell with no `function` (e.g. a
    clock-gating latch `TLATNCAD*`) stays a blackbox, and if the design uses one
    `equiv_induct` still emits "No SAT model …" → SKIPPED-CONDITION, never a
    fake pass.  Measured on a commercial-PDK spm: 65/65 $equiv cells proven, 0 unproven,
    "Equivalence successfully proven!"; a one-gate NAND2D1→NOR2D1 corruption of
    the netlist leaves 2 unproven → the gate FAILs (false-clean-PROOF). The
    induction escalates 4→16→64 frames so a pipelined design proves at the depth
    matching its latency (spm needs frame 2). chip-/PDK-AGNOSTIC.

    `liberty` may be None (a generic `$_`-primitive netlist needs no Liberty; it
    is already satgen-modelable). `blackbox_v` — PDK physical-only cell Verilog
    (fill/tap/decap) read `-lib` so those inert cells become empty blackboxes;
    empty for a pre-PnR synth netlist (those cells are inserted later).

    `gate_is_generic=True` — the gate is a pre-techmap Yosys netlist whose cells
    are escaped internal primitives (`\\$_DFF_P_`, `\\$_NAND_`, …). Read it with
    `read_verilog -icells` and NO Liberty: `-icells` re-binds those escaped names
    to real internal cells so `hierarchy -check` RESOLVES them (a plain
    `read_verilog` treats `\\$_DFF_P_` as an undefined user module and ABORTS
    before `equiv_make` → 0 $equiv points → a false compared_points=0 FAIL). The
    resulting `$_`-primitive gate is already satgen-modelable, so equiv proceeds
    normally. chip/PDK-AGNOSTIC — no Liberty vocabulary is involved.

    #155 — a `memory_map` PASS runs on EACH side after `prep` / `hierarchy`
    (which have already run `proc; memory_collect`, so any memory is a packed
    `$mem`/`$mem_v2` cell) and BEFORE `flatten`, legalizing the memory to
    flops + address-decode gates that equiv_induct's satgen CAN model. Without
    it a memory-bearing gold aborts `equiv_induct` with `No SAT model available
    for cell … ($mem_v2)` → an honest SKIPPED-CONDITION that never actually
    compared the design. This is plain stock-yosys 1042b3f55 (no fork flag, no
    capability probe — the `memory_map` command has shipped for years). ORDER
    IS LOAD-BEARING: it must run PRE-flatten (a `memory_map` placed AFTER
    `flatten`/`splitnets` leaves every $equiv point unproven — verified 0/8 vs
    136/0 in-container), and each side must legalize its own module BEFORE
    `equiv_make` merges them. NO-LEAK: on a design with NO memory `memory_map`
    is a no-op, so a non-memory LEC verdict is byte-unchanged; a memory-bearing
    EQUIVALENT design now PROVES ("Equivalence successfully proven!"), and a
    broken one stays unproven → FAIL (sound negative)."""
    gold_read = " ".join(gold_files)
    bb = "".join(f"read_verilog -lib {q}\n" for q in (blackbox_v or []))
    if gate_is_generic:
        # Pre-techmap `$_`-primitive gate: -icells re-binds the escaped names so
        # `hierarchy -check` resolves them (no Liberty; already satgen-modelable).
        gate_read = f"{bb}read_verilog -icells {gate_netlist}\n"
    elif liberty:
        # Expand Liberty cells to $_ primitives (functions + ff/latch groups),
        # skipping any cell with no function (stays blackbox → honest SAT gap).
        gate_read = (f"read_liberty -ignore_miss_func {liberty}\n"
                     f"{bb}read_verilog {gate_netlist}\n")
    else:
        gate_read = f"{bb}read_verilog -sv {gate_netlist}\n"
    # GOLD frontend: default is yosys's built-in `read_verilog -sv` (SV subset).
    # On a real SV CPU/SoC gold (package-scope refs like `pkg::`, unpacked-array
    # ports) that reader parse-ABORTS → 0 miter → a FALSE FAIL. `gold_frontend=
    # "slang"` reads the gold with `read_slang` — the SAME full SV-2017 frontend
    # the synth step auto-falls-back to (synth_frontend.decide_synth_frontend) —
    # so a design that SYNTHESISES cleanly is also LEC-comparable. On a non-fork
    # image `read_slang` needs `plugin -i slang` first (slang_prefix carries it);
    # the vibeic-eda fork ships it built-in (slang_prefix == "").
    # The slang read must MIRROR the synth invocation's DEFINE SET, not just
    # read_slang alone (rv-aes): synth reads `-DSIMULATION -DYOSYS` primary and
    # retries `-DSYNTHESIS -DYOSYS` when a sim-only construct ($urandom /
    # std::randomize / $value$plusargs in a dead `ifdef SIMULATION arm) breaks
    # the build. `gold_defines` carries whichever set main() is on, so the gold
    # elaborates the same arm synth built the gate from (else the miter aborts
    # on $urandom). Default is the synth PRIMARY set; main() flips it to
    # -DSYNTHESIS on the same sim-only-construct signature synth uses.
    if gold_frontend == "slang":
        _plugin_line = ("plugin -i slang\n"
                        if "plugin" in (slang_prefix or "") else "")
        # --single-unit: read ALL gold files as ONE compilation unit, so a
        # macro defined in an early file is visible to every later file. This
        # MIRRORS the shared preprocessor scope of the successive
        # `read_verilog` calls synth uses. Without it slang makes each CLI file
        # its own unit, and a design whose modules rely on a cross-file
        # `` `define `` (the ordinary Verilog header idiom) aborts with
        # "unknown macro or compiler directive" — a read abort, hence 0
        # compared points. `_resolve_gold_files` guarantees the macro headers
        # are concatenated first, which single-unit reads REQUIRE.
        gold_read_cmd = (f"{_plugin_line}read_slang --single-unit {gold_read} "
                         f"--top {top} {gold_defines}")
    else:
        gold_read_cmd = f"read_verilog -sv {gold_read}"
    # FUNCTIONAL-MODE WRAPPING (scan netlists only).  Both halves are emitted
    # together or not at all: a gold wrapper without a gate wrapper would
    # compare the RTL against nothing, and a gate wrapper without a gold one
    # would leave the prefixes unmirrored.  When `scan_mode` is None every
    # string below is empty and the script is BYTE-IDENTICAL to the pre-change
    # one — a non-scan design's verdict cannot move.
    gold_rename = gold_wrap_read = ""
    gate_rename = gate_wrap_read = ""
    if scan_mode and gate_wrapper_v and gold_wrapper_v:
        gold_rename = f"rename {top} {top}__rtl\n"
        gold_wrap_read = f"read_verilog -sv {gold_wrapper_v}\n"
        gate_rename = f"rename {top} {top}__scan\n"
        gate_wrap_read = f"read_verilog -sv {gate_wrapper_v}\n"
    return (
        # --- gold = RTL, kept as generic satgen-modelable Yosys cells ---
        f"{gold_read_cmd}\n"
        # Scan functional-mode only: rename the RTL top out of the way and read
        # the wrapper that re-declares `{top}` with the RTL's own port list, so
        # `prep -top {top}` elaborates the wrapper and `flatten` stamps the
        # gate's prefix onto every gold wire.  Empty otherwise.
        f"{gold_rename}"
        f"{gold_wrap_read}"
        f"prep -top {top}\n"
        # #155: legalize any $mem/$mem_v2 (packed by prep's memory_collect) to
        # flops+decode BEFORE flatten so equiv_induct's satgen can model it;
        # PRE-flatten placement is load-bearing (0/8 vs 136/0). No-op when the
        # design has no memory. Plain stock-yosys command — no fork flag/probe.
        f"memory_map\n"
        f"flatten\n"
        # ASYNC-FF LEGALIZATION: an async-reset/-set FF (SV `always @(posedge clk
        # or negedge rst_n)`) maps to `$_DFF_PN0_`/`$_DFFSR_*`, which
        # equiv_induct's SAT engine cannot model — it aborts "No SAT model
        # available for async FF cell … ($_DFF_PN0_). Consider running
        # `async2sync` or `clk2fflogic` first." (observed on ibex, rv-ibex2).
        # async2sync converts the async control into synchronous D-input logic the
        # SAT engine CAN model. Applied UNIFORMLY on BOTH sides and AFTER flatten,
        # regardless of which frontend read the gold — so the read_slang gold-read
        # retry path (SV-package designs like ibex, which are exactly the async-
        # reset CPUs) is covered too. SOUND: it is an identical modeling transform
        # on gold and gate, so an equivalent design stays equivalent and a real
        # reset-behaviour difference still surfaces as unproven. No-op on a design
        # with no async FF (spm 65/65 unchanged). Verified in-container: an
        # async-reset DFF pair stops at the async-FF SAT abort WITHOUT this and
        # proves "4/4, Equivalence successfully proven!" WITH it.
        f"async2sync\n"
        f"opt_clean\n"
        f"splitnets -ports\n"
        f"design -stash gold\n"
        # --- gate = synth netlist; Liberty cells EXPANDED to $_ logic then
        #     flattened in so the SAT engine can model every point ---
        f"{gate_read}"
        # Scan functional-mode only: rename the scan netlist's top out of the
        # way and read the wrapper that ties `shift`/`test`/`sin`/`tck` to their
        # functional-mode values and leaves `sout` dangling, so the gate's port
        # set matches the gold's and `equiv_make` does not abort.  Empty
        # otherwise.
        f"{gate_rename}"
        f"{gate_wrap_read}"
        f"hierarchy -check -top {top}\n"
        # #155: same memory legalization on the gate side, in case the gate
        # netlist still carries a $mem*/$mem_v2 cell (no-op otherwise).
        f"memory_map\n"
        f"flatten\n"
        f"async2sync\n"   # async-FF legalization (see the gold side) — both sides
        f"opt_clean\n"
        f"splitnets -ports\n"
        f"design -stash gate\n"
        f"design -copy-from gold -as gold {top}\n"
        f"design -copy-from gate -as gate {top}\n"
        f"equiv_make gold gate {_MITER_MODULE}\n"
        f"hierarchy -top {_MITER_MODULE}\n"
        # READ-ONLY report pass. It prints the miter's cell histogram, which is
        # the OBSERVABLE `miter_is_stateless` reads to decide whether temporal
        # induction could have had anything to unroll. Without it the parser
        # has to guess, and the guess it used to make was "assume a flat
        # induction wall explains this", which turned every combinational
        # mismatch into a non-blocking INCONCLUSIVE. `stat` mutates no design
        # and costs no solver time.
        f"stat\n"
        # SAT-FREE structural pre-reduction BEFORE any SAT is spent. equiv_struct
        # merges the $equiv key-points whose driving cones are structurally
        # identical across gold and gate (the majority of a name-mapped
        # RTL-vs-synth miter) by structural hashing alone — no solver call. This
        # is SOUND: it only collapses provably-identical structure, so it can
        # NEVER launder a real mismatch into a proof (a genuinely different cone
        # survives to equiv_simple/equiv_induct below). Without it, equiv_simple
        # SAT-hammers EVERY key-point including the trivially-identical ones, so a
        # large design (measured: a 31 850-point AES miter) exhausts the wall
        # clock mid-equiv_simple and yields a false INCONCLUSIVE. equiv_struct
        # AUGMENTS, never REPLACES, the SAT stages that follow — it only shrinks
        # the set they must decide (measured 31 850 -> 3 333, a 10x cut). This is
        # the same pre-pass yosys's own `equiv_opt` runs. chip/PDK-AGNOSTIC.
        f"equiv_struct\n"
        f"equiv_simple\n"
        f"equiv_induct -seq 4\n"
        f"equiv_induct -seq 16\n"
        f"equiv_induct -seq 64\n"
        f"equiv_status\n"
    )


# ---------------------------------------------------------------------------
# STEP WALL BUDGET — measured ONCE, from the FIRST attempt, across ALL retries.
# ---------------------------------------------------------------------------
# THE DEFECT THIS EXISTS TO PREVENT (measured 2026-08-27 on the VerilogEval-Human
# sweep `_vehuman_clean156`, problem `Prob030_popcount255` — a 255-bit popcount
# whose `equiv_induct` is combinatorially explosive):
#
#   Every attempt used to be handed the SAME constant `args.timeout`. The gold
#   read ground for the full 7195s budget, was killed, and the slang gold-read
#   retry started the SAME problem over with a FRESH full 7195s. A deadline that
#   a retry re-arms is not a deadline: the real bound was `timeout x attempts`
#   (three straight-line attempts x 7200s = SIX HOURS against a nominal "7200s
#   budget"), and NOTHING measured total elapsed. A 156-problem sweep whose
#   MEDIAN problem takes ~30s sat on ONE problem for 131 minutes with a 0-byte
#   dispatch log — from outside, indistinguishable from a sweep making progress.
#
# THE RULE: the budget is a DEADLINE, established before the first attempt. Each
# attempt gets what is LEFT of it, never a fresh copy. When nothing meaningful
# is left the next attempt is NOT LAUNCHED, and the step records how many
# attempts it made and how long they took — so an exhausted proof is visibly
# different from a finished one.
#
# Injectable clock so the ceiling is testable without spending it.
_MIN_ATTEMPT_BUDGET_S = 30


class StepBudget:
    """TOTAL wall-clock budget for one LEC step, shared by every attempt.

    `next_attempt_budget()` returns the REMAINING seconds, or 0 once less than
    `floor_s` is left. 0 means "do not launch" — never "launch with no limit".
    A retry can only ever SHRINK what is left, so the total time this step can
    consume is bounded by `total_s` no matter how many attempts the retry logic
    decides to make.
    """

    def __init__(self, total_s: int, floor_s: int = _MIN_ATTEMPT_BUDGET_S,
                 clock=time.monotonic) -> None:
        self.total_s = int(total_s)
        self.floor_s = int(floor_s)
        self._clock = clock
        self._t0 = clock()
        self.attempts: List[Dict] = []

    def elapsed_s(self) -> float:
        return self._clock() - self._t0

    def remaining_s(self) -> int:
        return int(round(self.total_s - self.elapsed_s()))

    def next_attempt_budget(self) -> int:
        """Seconds the NEXT attempt may run. 0 = the step budget is spent.

        The FIRST attempt always receives the whole budget. The floor exists to
        refuse a POINTLESS RETRY on a nearly-spent budget; it must never turn a
        small operator-configured `--timeout` into "do not run at all", which
        would convert a tight budget into a step that produces no evidence.
        """
        left = self.remaining_s()
        if not self.attempts:
            return max(left, 1)
        return left if left >= self.floor_s else 0

    def exhausted(self) -> bool:
        return self.next_attempt_budget() == 0

    def record(self, frontend: str, defines: str, budget_s: int,
               elapsed_s: float, launched: bool, timed_out: bool) -> None:
        """Record an attempt that WAS launched."""
        self.attempts.append({
            "attempt": len(self.attempts) + 1,
            "gold_frontend": frontend,
            "gold_defines": defines,
            "budget_sec": budget_s,
            "elapsed_sec": round(elapsed_s, 2),
            "launched": launched,
            "killed_by_budget": timed_out,
        })

    def skipped(self, frontend: str, defines: str, why: str) -> None:
        """Record a retry the budget REFUSED to launch."""
        self.attempts.append({
            "attempt": len(self.attempts) + 1,
            "gold_frontend": frontend,
            "gold_defines": defines,
            "budget_sec": 0,
            "elapsed_sec": 0.0,
            "launched": False,
            "killed_by_budget": False,
            "not_launched_reason": why,
        })

    def count_launched(self) -> int:
        return sum(1 for a in self.attempts if a["launched"])


def annotate_step_budget(report: Dict, budget: "StepBudget") -> Dict:
    """Record WHAT was attempted, WHICH resource ran out, and HOW MANY attempts
    were made onto the verdict the parser already produced.

    ADDITIVE ONLY — it never touches `verdict` or `equivalent`. A budget-killed
    proof already classifies as a DISCLOSED non-PASS (`SKIPPED-CONDITION`, or
    `INCONCLUSIVE` on the zero-completed-comparison path); neither is a PASS and
    neither is a FAIL, which is the honest outcome for a proof that did not
    finish. What was MISSING was the EVIDENCE of how much was spent and how
    often it was retried — the absence that made a re-armed deadline look
    exactly like progress from outside.
    """
    launched = [a for a in budget.attempts if a["launched"]]
    report["lec_attempts"] = len(launched)
    report["lec_attempts_detail"] = list(budget.attempts)
    report["step_budget_sec"] = budget.total_s
    report["step_elapsed_sec"] = round(budget.elapsed_s(), 2)
    report["step_budget_exhausted"] = budget.exhausted()
    report["exhausted_resource"] = (
        "wall_clock_seconds" if budget.exhausted() else None)
    if budget.exhausted():
        report["verdict_explanation"] = (
            (report.get("verdict_explanation") or "").rstrip()
            + f" STEP BUDGET: exhausted the TOTAL {budget.total_s}s wall-clock "
              f"budget for this step after {len(launched)} attempt(s), "
              f"{report['step_elapsed_sec']}s elapsed. The resource that ran "
              "out is WALL-CLOCK TIME, not equivalence evidence: the designs "
              "are neither proven equivalent nor proven different. Raise "
              "--timeout / VIBEIC_LEC_YOSYS_TIMEOUT_S, or close the remainder "
              "with sign-off LEC.")
    return report


def run_yosys_equiv(container: str, ys_path_in_container: str,
                    timeout: int = DEFAULT_YOSYS_TIMEOUT_S,
                    workdir: Optional[str] = None):
    """Run `yosys -s <ys>` in the container. Returns (launched, raw_output).

    launched=False means Docker/Yosys could not run at all (the caller then
    returns 1 for a disclosed-skip). launched=True means Yosys emitted output
    (any outcome), which the parser then classifies.

    `workdir` runs the gold+gate read from a chosen directory. This is the
    plugin's own `cwd=design_dir` rule (the one `benchmark_score_cwd_guard.py`
    enforces for testbench runs) applied to the LEC read, and it is REQUIRED
    for correctness rather than convenience: a design's memory-initialisation
    and include references (`$readmemh`/`$readmemb`/`` `include ``) are
    ORDINARILY written as RELATIVE paths, and the synthesis that produced the
    gate netlist resolved them because it ran beside the resources the runner
    staged for it. Reading the gold from a DIFFERENT directory makes those same
    relative paths unresolvable, which aborts the gold elaboration and yields a
    zero-point miter — reported downstream as a non-equivalence verdict about a
    design that was never compared. Passing None preserves the previous
    behaviour exactly."""
    cmd = f"yosys -s {shlex.quote(ys_path_in_container)} 2>&1"
    if workdir:
        cmd = f"cd {shlex.quote(workdir)} && " + cmd
    try:
        r = _docker(
            container,
            cmd,
            timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return (bool(_strip_login_banner(out).strip()),
                _strip_login_banner(out)
                + f"\n{_TIMEOUT_MARKER} after {timeout}s")
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"[lec_run] ERROR: could not exec yosys: {exc}"

    out = _strip_login_banner(r.stdout or "")
    # Launched iff we saw genuine Yosys output (banner or an equiv/error line);
    # a docker-daemon / no-such-container failure yields no Yosys banner.
    launched = ("Yosys" in out or "$equiv" in out
                or "No SAT model" in out or "ERROR:" in out)
    # CONTAINER-side budget kill (path (2), see _CONTAINER_TIMEOUT_RCS): the
    # `timeout` _docker wraps the call in fires before the host deadline, so we
    # arrive here NORMALLY with GNU-`timeout`'s exit code instead of via
    # subprocess.TimeoutExpired above. Re-attach the SAME marker the host path
    # writes, so the parser's budget-exhaustion branch (INCONCLUSIVE /
    # SKIPPED-CONDITION) fires instead of misreading a killed-mid-proof run as a
    # hard FAIL. This is a no-verdict signal ONLY: a COMPLETED miter (proven /
    # unproven parsed) or a recorded counterexample never reaches that branch —
    # both keep their real FAIL — so this can neither fabricate a PASS nor hide a
    # real mismatch (proven on opentitan_aes × sky130A and covered by the tests).
    if launched and getattr(r, "returncode", 0) in _CONTAINER_TIMEOUT_RCS:
        out = out.rstrip("\n") + f"\n{_TIMEOUT_MARKER} after {timeout}s"
    return launched, out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
# Corner preference when several Liberty files exist: the TYPICAL/NOMINAL
# corner carries the functional cell models used for equivalence. We only pick
# WHICH existing Liberty to read — we never guess a cell model.
_LIB_CORNER_RANK = ("typ", "_tt_", "tt_", "typical", "nom", "_nn_", "nn_")


def _discover_project_liberty(project: Path) -> Optional[Path]:
    """Find the design's OWN PDK Liberty inside the project tree (PURE).

    The Step-13 runner passes no --liberty, so without this the producer falls
    back to the sky130 DEFAULT_LIBERTY — useless for a commercial-PDK design
    whose cells (e.g. commercial-PDK NAND2D1 / DFFHQD1) are only SAT-modelable from ITS
    own Liberty. Searches the canonical Vibe-IC PDK location
    (`input/pdk/liberty/*.lib`) first, then a bounded `input/**.lib` fallback,
    and prefers the typical/nominal corner. Returns None if the project ships no
    Liberty (the caller then keeps the CLI/default). Filesystem-only — no
    container, no design-specific assumption."""
    candidates: List[Path] = []
    prime = project / "input" / "pdk" / "liberty"
    if prime.is_dir():
        candidates = sorted(prime.glob("*.lib"))
    if not candidates:
        inp = project / "input"
        if inp.is_dir():
            candidates = sorted(inp.rglob("*.lib"))
    if not candidates:
        return None

    def _rank(p: Path) -> int:
        name = p.name.lower()
        for i, tag in enumerate(_LIB_CORNER_RANK):
            if tag in name:
                return i
        return len(_LIB_CORNER_RANK)

    candidates.sort(key=lambda p: (_rank(p), str(p)))
    return candidates[0]


def _resolve_gold_files(gold_dir: Path) -> List[str]:
    """The .v/.sv gold sources to read, as absolute paths.

    Alphabetically sorted, then TWO chip-AGNOSTIC corrections that make the
    gold read match what phase-2 synth already does (see `_rtl_include_hub`):

    1. INCLUDE-HUB AGGREGATORS ARE DROPPED. A file that `` `include ``s a
       sibling which is ALSO staged standalone defines every included module
       twice, so the read ABORTS and the miter is built from 0 points. Phase-2
       synth's selector has excluded these since #614; the gold read did not,
       so a design that SYNTHESISED cleanly could still produce a zero-point
       LEC. (That zero-point run is already reported honestly as INCONCLUSIVE
       by #192's stage-progress observable rather than a false
       NOT_EQUIVALENT — this change is what turns the honest non-result into
       an actual comparison.)

    2. PURE MACRO HEADERS ARE MOVED FIRST, because the slang gold read is a
       SINGLE compilation unit (`--single-unit`) that concatenates the files in
       CLI order. Alphabetical order resolves cross-file `` `define ``s only by
       luck of filename.

    Both are no-ops on a gold dir with no aggregator and no macro header."""
    if not gold_dir.is_dir():
        return []
    files = sorted(
        p for p in gold_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".v", ".sv"))
    files = _macro_headers_first(_drop_include_hubs(files))
    return [str(p.resolve()) for p in files]


_MODULE_DECL_RE = re.compile(r"(?m)^\s*module\s+([A-Za-z_]\w*)")


# The wrappers' interface is taken from the SCAN NETLIST's own module header,
# minus the DFT ports — never re-parsed out of the RTL.  Two reasons:
#   * the netlist header is generated Verilog-2005 (`module m(a, b); input a;
#     output [3:0] b;`), which parses unambiguously, whereas the RTL may be
#     ANSI or non-ANSI SystemVerilog with parameters and typedefs;
#   * `fault chain` only ADDS ports, so "scan netlist ports minus the DFT
#     ports" IS the RTL's port list.  If it ever were not, `equiv_make` aborts
#     loudly on the mismatch — the failure mode is a visible error, not a
#     quietly wrong comparison.
_NL_MODULE_HDR_RE = re.compile(
    r"^\s*module\s+(?P<name>\\?[\w$]+)\s*\((?P<ports>[^)]*)\)\s*;",
    re.M)
_NL_PORT_DECL_RE = re.compile(
    r"^\s*(?P<dir>input|output|inout)\s+(?:wire\s+|reg\s+)?"
    r"(?P<range>\[[^\]]*\]\s*)?(?P<name>\\?[\w$]+)\s*;",
    re.M)


def netlist_top_ports(netlist_text: str, top: str,
                      exclude: Optional[List[str]] = None
                      ) -> List[Tuple[str, str, str]]:
    """`[(direction, range_or_empty, name)]` for module `top`, in header order.

    `exclude` drops named ports (the DFT ports) from the result.  Returns []
    when the module header cannot be found — the caller must then NOT wrap,
    rather than wrap against a guessed interface.  PURE.
    """
    drop = set(exclude or ())
    body = None
    for m in _NL_MODULE_HDR_RE.finditer(netlist_text or ""):
        if m.group("name").lstrip("\\") == top:
            body = (m.group("ports"), netlist_text[m.end():])
            break
    if body is None:
        return []
    order = [p.strip().lstrip("\\") for p in body[0].split(",") if p.strip()]
    decls: Dict[str, Tuple[str, str]] = {}
    for d in _NL_PORT_DECL_RE.finditer(body[1]):
        nm = d.group("name").lstrip("\\")
        if nm in decls:
            continue
        decls[nm] = (d.group("dir"), (d.group("range") or "").strip())
    out: List[Tuple[str, str, str]] = []
    for nm in order:
        if nm in drop or nm not in decls:
            continue
        direction, rng = decls[nm]
        out.append((direction, f"{rng} " if rng else "", nm))
    return out


def _gold_modules(gold_files: List[str]) -> "tuple[set, set]":
    """(declared_modules, instantiated_module_names) across the gold RTL.

    A module is a ROOT if it is declared but never instantiated by another —
    the natural top. Instantiation is detected conservatively as
    `D [#(...)] <inst> (`, which a `module D (` declaration never matches."""
    decls: set = set()
    parts: List[str] = []
    for f in gold_files:
        try:
            t = Path(f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        parts.append(t)
        decls.update(_MODULE_DECL_RE.findall(t))
    corpus = "\n".join(parts)
    insts: set = set()
    for d in decls:
        if re.search(r"(?<![\w.])" + re.escape(d)
                     + r"\s+(?:#\s*\([\s\S]*?\)\s*)?[A-Za-z_]\w*\s*\(", corpus):
            insts.add(d)
    return decls, insts


_MODULE_BODY_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)\b(.*?)\bendmodule\b",
                             re.S)


def _gold_child_map(gold_files: List[str], decls: set) -> "dict":
    """{module: set(modules it instantiates)} across the gold RTL.

    Same conservative instantiation shape `_gold_modules` uses, but scoped to
    each module BODY so the hierarchy — not just the flat instantiated set —
    is available."""
    children: dict = {}
    for f in gold_files:
        try:
            text = Path(f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in _MODULE_BODY_RE.finditer(text):
            name, body = m.group(1), m.group(2)
            kids = children.setdefault(name, set())
            for d in decls:
                if d == name:
                    continue
                if re.search(r"(?<![\w.])" + re.escape(d)
                             + r"\s+(?:#\s*\([\s\S]*?\)\s*)?[A-Za-z_]\w*\s*\(",
                             body):
                    kids.add(d)
    return children


def _descendants(children: dict, root: str) -> set:
    """Every module reachable BELOW `root` in the gold hierarchy."""
    seen: set = set()
    stack = [root]
    while stack:
        for child in children.get(stack.pop(), ()):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def _gate_modules(gate_netlist: Optional[str]) -> "tuple[set, set]":
    """(declared_modules, instantiated_module_names) in the GATE netlist.

    The exact mirror of `_gold_modules` for the other side of the comparison.
    An equivalence miter needs the top to exist on BOTH sides; a gate netlist
    is usually flattened to a single root, so its declared set is small and
    decisive."""
    if not gate_netlist:
        return set(), set()
    try:
        text = Path(gate_netlist).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set(), set()
    decls: set = set(_MODULE_DECL_RE.findall(text))
    insts: set = set()
    for d in decls:
        if re.search(r"(?<![\w.])" + re.escape(d)
                     + r"\s+(?:#\s*\([\s\S]*?\)\s*)?[A-Za-z_]\w*\s*\(", text):
            insts.add(d)
    return decls, insts


def _top_is_comparable(gold_files: List[str], gate_netlist: Optional[str],
                       top: str) -> bool:
    """Is `top` declared on BOTH sides, so a miter can actually be built?

    This is the PROPERTY the top guard exists to defend. A side whose module
    set cannot be read at all (empty) is not evidence of absence and does not
    veto — only a side that demonstrably declares other modules does."""
    gold_decls, _ = _gold_modules(gold_files)
    gate_decls, _ = _gate_modules(gate_netlist)
    if gold_decls and top not in gold_decls:
        return False
    if gate_decls and top not in gate_decls:
        return False
    return True


def _resolve_gold_top(gold_files: List[str], top: str,
                      gate_netlist: Optional[str] = None) -> "tuple[str, str]":
    """Ensure the LEC top is a module that actually exists on BOTH sides.

    A wrong top (e.g. the default 'chip_top' on a standalone 'spm' design) makes
    Yosys build 0 $equiv cells → a MISLEADING 'may genuinely differ' FAIL that
    proved nothing. If `top` is not declared, auto-correct to the sole ROOT
    module; if the choice is ambiguous, return top unchanged with a diagnostic
    note so the caller can emit an honest 'top not found' verdict instead of a
    fake mismatch. Returns (resolved_top, note).

    THE GATE SIDE COUNTS TOO. Checking only the gold made "the top exists in
    the RTL" a PROXY for the property above, and the two come apart on any
    design whose RTL declares more than one root — e.g. an RTL set carrying
    both an ASIC top and a board/FPGA top, where synthesis builds the gate from
    one of them. The gold then declares the caller's top, this guard passes it
    through, and `hierarchy -check -top <top>` aborts on a gate netlist that
    has no such module: zero compared points, reported as a verdict about the
    design. A gate netlist we cannot read yields an empty set and vetoes
    nothing, so a design that resolves today cannot be moved by this."""
    decls, insts = _gold_modules(gold_files)
    resolved, note = top, ""
    if decls and top not in decls:
        roots = sorted(m for m in decls if m not in insts)
        if len(roots) != 1:
            return top, (f"gold top '{top}' not found in RTL modules "
                         f"{sorted(decls)[:8]} and no unique root — cannot "
                         "select a top")
        resolved = roots[0]
        note = (f"gold top '{top}' not found in RTL; auto-corrected to sole "
                f"root module '{roots[0]}'")

    gate_decls, gate_insts = _gate_modules(gate_netlist)
    if gate_decls and resolved not in gate_decls:
        # The candidate must be the gate netlist's SOLE ROOT (what the gate
        # actually IS) and must be DECLARED BY THE GOLD (so there is something
        # to compare it against). An unreadable gold is never enough on its own
        # to let the gate pick a top, and an ambiguous or empty intersection
        # returns a note so the caller emits an honest SKIPPED-CONDITION —
        # never a fabricated mismatch and never a fabricated agreement.
        shared = (decls & gate_decls) if decls else set()
        cands = sorted(m for m in shared if m not in gate_insts)
        if len(cands) == 1:
            # NO-LEAK BAR: never silently substitute a PROPER PART of the
            # design the caller asked about. A candidate that is a DESCENDANT
            # of the requested top would shrink the comparison's scope while
            # still reporting a verdict in the caller's name — the exact
            # proxy-for-the-property shape this fix exists to remove. A
            # SIBLING top (an RTL set carrying an ASIC top and a board top,
            # each instantiating the same blocks) is a naming mismatch and is
            # the case worth correcting; a descendant is a scope reduction and
            # is refused.
            below = _descendants(_gold_child_map(gold_files, decls), resolved) \
                if decls else set()
            if cands[0] in below:
                return resolved, (
                    f"the gate netlist holds '{cands[0]}', which is a SUBMODULE "
                    f"of the requested top '{resolved}' — refusing to compare a "
                    "proper part of the design under the top's name")
            return cands[0], (
                f"top '{resolved}' is declared by the RTL but is not a module "
                f"of the gate netlist {sorted(gate_decls)[:8]}; auto-corrected "
                f"to '{cands[0]}', the gate's sole root and a sibling top the "
                "RTL also declares")
        return resolved, (
            f"top '{resolved}' is not a module of the gate netlist "
            f"{sorted(gate_decls)[:8]} and no unique comparable top exists "
            "— cannot select a top")
    return resolved, note


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Step 13 LEC PRODUCER — real Yosys RTL≡gate equivalence "
                    "check → reports/lec.json (+ lec.rpt).")
    ap.add_argument("project_dir", help="Project directory")
    ap.add_argument("--gold-rtl-dir", default="phase2/stage1/rtl",
                    help="Dir of RTL .v/.sv (the gold), relative to project")
    ap.add_argument("--gate-netlist", default="phase2/stage2/synth/netlist.v",
                    help="Synth netlist (the gate), relative to project")
    ap.add_argument("--top", required=True, help="Top module name")
    ap.add_argument("--container", default=DEFAULT_CONTAINER,
                    help="Docker container running yosys (default vibeic-eda)")
    ap.add_argument("--liberty", default=DEFAULT_LIBERTY,
                    help="Absolute .lib path INSIDE the container")
    ap.add_argument("--timeout", type=int, default=DEFAULT_YOSYS_TIMEOUT_S,
                    help="Per-yosys-invocation budget in seconds "
                         f"(default {DEFAULT_YOSYS_TIMEOUT_S})")
    ap.add_argument("--json", default=DEFAULT_JSON_REL,
                    help="Output JSON path, relative to project")
    ap.add_argument("--scan-meta", default=None,
                    help="Path (project-relative) to the scan-chain metadata "
                         "written by fault_scan_chain_insert.py "
                         "(reports/phase2/dft/scan_chain.json).  When it is "
                         "present AND declares a PUBLISHED scan netlist, the "
                         "gate is compared in FUNCTIONAL MODE: the DFT control "
                         "ports are tied to their functional values, the scan "
                         "output is dropped, and the gold is given the gate's "
                         "own internal-wire prefix so equiv_make can still "
                         "match points by name.  Absent or unpublished → the "
                         "script is byte-identical to the non-scan one.")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[lec_run] ERROR: not a directory: {project}", file=sys.stderr)
        return 1

    json_out = project / args.json
    rpt_out = project / DEFAULT_RPT_REL
    json_out.parent.mkdir(parents=True, exist_ok=True)
    rpt_out.parent.mkdir(parents=True, exist_ok=True)

    gold_dir = project / args.gold_rtl_dir
    gate_netlist = project / args.gate_netlist

    gold_files = _resolve_gold_files(gold_dir)
    if not gold_files:
        print(f"[lec_run] ERROR: no .v/.sv gold RTL under {gold_dir}",
              file=sys.stderr)
        return 1
    if not gate_netlist.is_file():
        print(f"[lec_run] ERROR: gate netlist not found: {gate_netlist}",
              file=sys.stderr)
        return 1

    container = args.container
    if not _container_available(container):
        print(f"[lec_run] ERROR: container '{container}' not available "
              "(docker/yosys cannot run) — runner should disclosed-skip.",
              file=sys.stderr)
        return 1

    # Verify the Liberty file exists in-container; omit it if absent (generic
    # $_-primitive netlists need no Liberty; Liberty-mapped netlists will then
    # honestly hit unmodelable cells → SKIPPED-CONDITION, never a fake pass).
    liberty: Optional[str] = args.liberty
    # Prefer the PROJECT's own PDK Liberty over the (sky130) CLI default: the
    # runner passes no --liberty, and a commercial-PDK design's cells are only
    # SAT-modelable from ITS Liberty. Discovery wins whenever the caller did not
    # override the default, OR the given Liberty is not visible in-container.
    proj_lib = _discover_project_liberty(project)
    if proj_lib is not None and (
            args.liberty == DEFAULT_LIBERTY
            or not _container_file_exists(container, args.liberty)):
        liberty = str(proj_lib)
        print(f"[lec_run] auto-discovered project Liberty: {liberty}",
              file=sys.stderr)
    liberty_present = bool(liberty) and _container_file_exists(container, liberty)
    if liberty and not liberty_present:
        print(f"[lec_run] WARN: Liberty not found in-container: {liberty} "
              "— proceeding without it.", file=sys.stderr)
        liberty = None

    # Defense-in-depth: make sure the top actually exists on BOTH sides. A
    # wrong top (default 'chip_top' on a standalone 'spm') builds 0 $equiv cells
    # → a MISLEADING 'may genuinely differ' FAIL that proved nothing. Auto-correct
    # to the sole root, or emit an honest 'top not found' SKIPPED-CONDITION.
    # The GATE netlist is consulted as well: a top the gold declares but the
    # gate does not is exactly as un-comparable as one the gold lacks, and
    # aborts `hierarchy -check` before a single $equiv point is built.
    _gate_for_top = str(gate_netlist.resolve()) if gate_netlist else None
    resolved_top, top_note = _resolve_gold_top(gold_files, args.top,
                                               _gate_for_top)
    if top_note:
        print(f"[lec_run] {top_note}", file=sys.stderr)
    if not _top_is_comparable(gold_files, _gate_for_top, resolved_top):
        top_note = top_note or (
            f"top '{resolved_top}' is not declared on both the RTL and the "
            "gate netlist, so no equivalence miter can be built")
        parsed = {
            "proven": None, "unproven": None, "total": None,
            "sat_model_unsupported_cells": [], "unproven_cells": [],
            "success_line": False, "parse_error": False, "equivalent": False,
            "verdict": "SKIPPED-CONDITION",
            "verdict_explanation": (
                top_note + " — LEC not run (no fabricated mismatch). Pass a "
                "valid --top or resolve the RTL top."),
        }
        report = build_report(parsed, args.top, str(gate_netlist.resolve()),
                              liberty)
        rpt_out.write_text(
            f"[lec_run] {top_note}\nLEC not run; honest SKIPPED-CONDITION.\n",
            encoding="utf-8")
        json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        print(f"[lec_run] SKIPPED-CONDITION → {json_out}")
        return 0

    gate_abs = str(gate_netlist.resolve())

    # ORGANIC-20260801 — an instantiated hard-macro (SRAM/IP) whose model is
    # STAGED under input/pdk_local (L8) is UNDEFINED in rtl/, so the GOLD read
    # aborts `unknown module <macro>` (0 compared points → false FAIL) and the
    # synth GATE netlist instantiates it without a module decl. Blackbox the
    # macro on BOTH sides — prepend a `(* blackbox *)` stub to the gold read
    # AND pass it as `blackbox_v` for the gate read — so the miter proves the
    # surrounding logic under an assume-guarantee on identical macro
    # interfaces. No-op when the design stages no hard-macro (byte-identical).
    macro_blackbox_v: List[str] = []
    for _m in _hms.staged_hardmacro_models(project, gold_files):
        if _m["v"] is not None:
            _stub = _hms.emit_blackbox_stub(
                _m["v"], _m["name"], rpt_out.parent / "lec_hardmacro_bb")
            macro_blackbox_v.append(str(_stub.resolve()))
    if macro_blackbox_v:
        gold_files = macro_blackbox_v + gold_files
        print(f"[lec_run] staged hard-macro blackbox: "
              f"{[Path(s).name for s in macro_blackbox_v]}", file=sys.stderr)

    # A pre-techmap generic `$_`-primitive netlist must be read with `-icells`
    # and NO Liberty, else `hierarchy -check` aborts on an undefined `\$_DFF_P_`
    # module before any $equiv point is built (compared_points=0 false-FAIL).
    gate_is_generic = _netlist_uses_generic_primitives(gate_abs)
    if gate_is_generic:
        liberty = None
        print("[lec_run] gate is a generic $_-primitive netlist → "
              "read_verilog -icells (no Liberty).", file=sys.stderr)
    # Write the .ys into the (bind-mounted) project reports dir so the
    # container sees it at the same absolute path (same assumption that lets
    # yosys read the RTL/netlist by their host absolute paths).
    ys_host = rpt_out.parent / "lec_equiv.ys"
    ys_in_container = str(ys_host.resolve())
    # CWD: read the gold from the GATE NETLIST'S OWN DIRECTORY — the directory
    # the flow stages the gate's companion resources into (memory-init images,
    # `include headers). A design's `$readmemh`/`$readmemb`/`` `include ``
    # arguments are ordinarily written as RELATIVE paths, so a read performed
    # from anywhere else cannot resolve them; the gold elaboration then aborts
    # and the miter is empty, which is reported downstream as a non-equivalence
    # verdict about a design that was never compared. This is the plugin's own
    # `cwd=design_dir` rule (the one `benchmark_score_cwd_guard.py` enforces for
    # testbench runs) applied to the LEC read. Falls back to the gold RTL dir,
    # then to None (the previous behaviour) when neither directory exists, so
    # no design that resolves today can be moved by this.
    equiv_workdir: Optional[str] = None
    for _cand in (Path(gate_abs).parent,
                  Path(gold_files[0]).parent if gold_files else None):
        if _cand is not None and _cand.is_dir():
            equiv_workdir = str(_cand.resolve())
            break
    if equiv_workdir:
        print(f"[lec_run] gold+gate read cwd = {equiv_workdir} "
              "(mirrors the synth cwd so relative $readmemh/`include resolve)",
              file=sys.stderr)
    gold_frontend = "verilog"
    gold_defines = "-DSIMULATION -DYOSYS"   # synth PRIMARY define set (mirrored)

    # --- functional-mode (scan) comparison ---------------------------------
    # Only fires when the caller NAMED a scan-chain metadata file AND that file
    # declares a published scan netlist AND the gate netlist really carries the
    # DFT ports it describes.  Any one of those missing → no wrapping at all,
    # and the emitted script is byte-identical to the pre-change one.  Each
    # decision is recorded in `scan_functional_mode` in the report, so a reader
    # can see WHY the comparison was or was not functional-mode constrained.
    scan_mode: Optional[Dict] = None
    scan_record: Dict = {"requested": bool(args.scan_meta), "applied": False,
                         "reason": "no --scan-meta given"}
    gate_wrapper_v = gold_wrapper_v = ""
    if args.scan_meta:
        meta_path = project / args.scan_meta
        try:
            _meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _meta, scan_record["reason"] = None, (
                f"scan metadata unreadable ({meta_path}): {exc}")
        _sm = scan_mode_from_meta(_meta)
        if _meta is not None and _sm is None:
            scan_record["reason"] = (
                "scan metadata does not declare a PUBLISHED scan netlist with "
                "a functional-mode tie-off — not wrapping (a wrapper over a "
                "netlist with no DFT ports would be a fabrication)")
        if _sm is not None:
            _nl_text = Path(gate_abs).read_text(encoding="utf-8",
                                                errors="ignore")
            _dft = sorted({*_sm["tieoff"], _sm["scan_out_port"]})
            _all_ports = netlist_top_ports(_nl_text, resolved_top)
            _have = {n for _, _, n in _all_ports}
            _absent = [p for p in _dft if p not in _have]
            _rtl_ports = netlist_top_ports(_nl_text, resolved_top,
                                           exclude=_dft)
            if not _all_ports:
                scan_record["reason"] = (
                    f"could not read module {resolved_top}'s port list out of "
                    f"the gate netlist — not wrapping against a guessed "
                    f"interface")
            elif _absent:
                # The gate is NOT the scan netlist the metadata describes.
                # Wrapping anyway would tie off ports that do not exist and the
                # comparison would say nothing about the real artefact.
                scan_record["reason"] = (
                    f"gate netlist {Path(gate_abs).name} does not carry the "
                    f"DFT port(s) {_absent} the scan metadata declares — the "
                    f"gate is not the scan netlist, so functional-mode "
                    f"constraints are NOT applied")
            else:
                gate_src, gold_src = build_scan_wrappers(
                    resolved_top, _rtl_ports, _sm)
                gate_w = rpt_out.parent / "lec_scan_gate_wrapper.v"
                gold_w = rpt_out.parent / "lec_scan_gold_wrapper.v"
                gate_w.write_text(gate_src, encoding="utf-8")
                gold_w.write_text(gold_src, encoding="utf-8")
                gate_wrapper_v = str(gate_w.resolve())
                gold_wrapper_v = str(gold_w.resolve())
                scan_mode = _sm
                scan_record = {
                    "requested": True, "applied": True,
                    "reason": "gate carries the declared DFT ports",
                    "tieoff": _sm["tieoff"],
                    "scan_out_port_dangling": _sm["scan_out_port"],
                    "internal_prefix": _sm["internal_prefix"],
                    "compared_interface_ports": [n for _, _, n in _rtl_ports],
                    "gate_wrapper": str(gate_w.relative_to(project)),
                    "gold_wrapper": str(gold_w.relative_to(project)),
                }
                print(f"[lec_run] functional-mode scan comparison: tie "
                      f"{_sm['tieoff']}, drop '{_sm['scan_out_port']}', "
                      f"gold prefix {_sm['internal_prefix']!r}",
                      file=sys.stderr)
    if scan_record.get("requested") and not scan_record.get("applied"):
        print(f"[lec_run] scan functional-mode NOT applied: "
              f"{scan_record['reason']}", file=sys.stderr)

    def _run(frontend: str, slang_prefix: str = "",
             defines: str = "-DSIMULATION -DYOSYS"):
        script = build_equiv_script(gold_files, gate_abs, resolved_top, liberty,
                                    blackbox_v=macro_blackbox_v or None,
                                    gate_is_generic=gate_is_generic,
                                    gold_frontend=frontend,
                                    slang_prefix=slang_prefix,
                                    gold_defines=defines,
                                    scan_mode=scan_mode,
                                    gate_wrapper_v=gate_wrapper_v,
                                    gold_wrapper_v=gold_wrapper_v)
        ys_host.write_text(script, encoding="utf-8")
        # THE TOTAL, NOT A FRESH COPY. Handing `args.timeout` here is the defect
        # measured on 2026-08-27: it re-armed the deadline on every attempt.
        # Every attempt now draws from the SAME StepBudget deadline.
        _attempt_budget = budget.next_attempt_budget()
        _started = budget.elapsed_s()
        _launched, _raw = run_yosys_equiv(container, ys_in_container,
                                          timeout=_attempt_budget,
                                          workdir=equiv_workdir)
        budget.record(frontend, defines, _attempt_budget,
                      budget.elapsed_s() - _started, _launched,
                      bool(_TIMEOUT_RE.search(_raw)))
        return _launched, _raw

    # The deadline is established HERE, once, before the first attempt.
    budget = StepBudget(args.timeout)
    t0 = time.time()
    launched, raw = _run("verilog")

    # SLANG GOLD-READ FALLBACK: the built-in `read_verilog -sv` gold read ABORTED
    # (no miter built) on an SV closure the reader can't PARSE (package-scope
    # refs, unpacked-array ports) OR can't ELABORATE (an SV package/enum constant
    # used as a parameter value → the built-in const-evaluator's "non-constant
    # value" abort; ibex). Retry the gold with `read_slang` — a COMPLETE MIRROR
    # of the synth frontend: the SAME SV-2017 reader AND the SAME define-set
    # progression (rv-aes). synth reads `-DSIMULATION -DYOSYS` primary and, on a
    # sim-only-construct failure ($urandom / std::randomize / $value$plusargs in
    # a dead `ifdef SIMULATION arm), retries `-DSYNTHESIS -DYOSYS` (the
    # synthesizable `else — the arm the gate was actually built from). Mirror
    # that two-pass so the gold matches the gate. Only retry on a genuine
    # zero-miter abort; if slang ALSO fails (under BOTH define sets), record it
    # so the verdict is finalized to FAIL (never a non-blocking pass for a design
    # the capable frontend also can't build).
    slang_retry_failed = False
    gold_frontend_reason = ""
    if launched:
        _p1 = parse_equiv_output(raw)
        _retry_gold, gold_frontend_reason = should_retry_gold_with_slang(
            _p1, raw, gold_requires_sv2017(gold_files))
        if _retry_gold and budget.next_attempt_budget() == 0:
            # THE CEILING IS THE TOTAL: a retry that would re-arm a spent budget
            # is not launched at all. Only the RETRY is refused — the verdict
            # stays whatever the evidence already supports.
            budget.skipped("slang", gold_defines,
                           "step wall budget exhausted before the gold-read "
                           "retry")
            print("[lec_run] gold-frontend retry NOT launched: the step's "
                  f"total {budget.total_s}s wall budget is spent "
                  f"({round(budget.elapsed_s(), 2)}s elapsed). A retry must "
                  "not re-arm a deadline.", file=sys.stderr)
            _retry_gold = False
        if _retry_gold:
            try:
                from synth_frontend import resolve_slang_load_prefix
                slang_prefix = resolve_slang_load_prefix(container, _docker_exec3)
            except Exception:
                slang_prefix = ""  # fork-safe default: read_slang built-in
            print(f"[lec_run] FALLBACK gold frontend verilog → slang: "
                  f"{gold_frontend_reason}. Retrying the gold read with "
                  "read_slang (SV-2017 frontend, -DSIMULATION define set).",
                  file=sys.stderr)
            launched2, raw2 = _run("slang", slang_prefix, gold_defines)
            if launched2:
                _p2 = parse_equiv_output(raw2)
                raw = raw2
                gold_frontend = "slang"
                if not _p2["parse_error"]:
                    print("[lec_run] read_slang gold read built a miter "
                          "(SV-2017 frontend).", file=sys.stderr)
                else:
                    # DEFINE-SET MIRROR (synth #668): did slang die on a sim-only
                    # construct ($urandom etc.) in the dead `ifdef SIMULATION arm?
                    # Retry under -DSYNTHESIS (the synthesizable else — how synth
                    # built the gate), reusing the SAME decision the synth path
                    # uses (synth_frontend_should_retry_under_synthesis).
                    _retry = False
                    try:
                        from synth_frontend import \
                            synth_frontend_should_retry_under_synthesis
                        from synth_frontend import read_text_blob
                        # v1.4.x OBSERVABLE-OVER-WORDING: the OBSERVABLE is that
                        # the slang gold read built no miter (_p2 parse_error —
                        # the `else` we are in); the DESIGN PROPERTY (does the
                        # gold source branch on the define set) comes from the
                        # gold RTL itself, not from slang's phrasing.
                        _retry, _reason = \
                            synth_frontend_should_retry_under_synthesis(
                                raw2,
                                rtl_text_blob=read_text_blob(gold_files),
                                produced_output=False)
                    except Exception:
                        _retry = False
                    # TWO INDEPENDENT DECLINES, both kept, in this order.
                    # (1) A wall-budget kill on the slang rung is not a
                    # define-set problem either (same measurement and reasoning
                    # as budget_kill_blocks_frontend_retry). Without this the
                    # THIRD rung spends a third full budget on the same
                    # undecided proof before anything is recorded. `_b3` is read
                    # again below, so this must run first.
                    _b3, _b3_ev = budget_kill_blocks_frontend_retry(raw2)
                    if _b3:
                        _retry = False
                        gold_frontend_reason = _b3_ev
                        print("[lec_run] -DSYNTHESIS gold retry DECLINED: "
                              + _b3_ev, file=sys.stderr)
                    else:
                        # The same asymmetry as the call site in
                        # `should_retry_gold_with_slang` above: without this
                        # branch a reader cannot tell a check that RAN and
                        # passed from one that was never reached, and the third
                        # rung then spends a full budget with nothing in the
                        # log to say why it was allowed to.
                        print(f"[lec_run] -DSYNTHESIS gold retry: budget-kill "
                              f"check consulted, _b3={_b3!r} — not declined "
                              f"here.", file=sys.stderr)
                    # (2) A DIFFERENT condition: the rung was not killed, but
                    # the step's TOTAL wall budget is already spent, so a retry
                    # would have to re-arm a deadline. Budget accounting, not a
                    # kill marker - neither test implies the other, so neither
                    # may replace the other.
                    if _retry and budget.next_attempt_budget() == 0:
                        budget.skipped(
                            "slang", "-DSYNTHESIS -DYOSYS",
                            "step wall budget exhausted before the define-set "
                            "retry")
                        print("[lec_run] -DSYNTHESIS retry NOT launched: the "
                              f"step's total {budget.total_s}s wall budget is "
                              "spent. A retry must not re-arm a deadline.",
                              file=sys.stderr)
                        _retry = False
                    if _retry:
                        gold_defines = "-DSYNTHESIS -DYOSYS"
                        print("[lec_run] read_slang -DSIMULATION died on a "
                              "sim-only construct → retrying -DSYNTHESIS (mirror "
                              "synth #668).", file=sys.stderr)
                        launched3, raw3 = _run("slang", slang_prefix, gold_defines)
                        if launched3:
                            _p3 = parse_equiv_output(raw3)
                            raw = raw3
                            if _p3["parse_error"]:
                                slang_retry_failed = True
                        else:
                            slang_retry_failed = True
                    else:
                        # slang failed for a non-define reason → no free pass.
                        slang_retry_failed = not _b3
                    if slang_retry_failed:
                        print("[lec_run] read_slang could not build the gold "
                              "miter under either define set → verdict finalized "
                              "to FAIL (no free pass).", file=sys.stderr)
    elapsed = round(time.time() - t0, 2)

    # Always persist the raw tool log for transparency / gate corroboration.
    rpt_out.write_text(raw, encoding="utf-8")

    if not launched:
        print(f"[lec_run] ERROR: yosys did not run in '{container}' "
              "— runner should disclosed-skip. Raw log at reports/lec.rpt.",
              file=sys.stderr)
        # Still emit a truthful diagnostic JSON (equivalent:false, no fake data).
        diag = build_report(
            {"proven": None, "unproven": None, "total": None,
             "sat_model_unsupported_cells": [], "unproven_cells": [],
             "success_line": False, "parse_error": True, "equivalent": False,
             "verdict": "FAIL",
             "verdict_explanation": (
                 "Yosys/Docker could not run — no equivalence evidence "
                 "produced. See reports/lec.rpt.")},
            resolved_top, gate_abs, liberty)
        diag = annotate_step_budget(diag, budget)
        json_out.write_text(json.dumps(diag, indent=2, ensure_ascii=False))
        return 1

    parsed = parse_equiv_output(raw)
    # §4.05 NO-LEAK: if the slang retry was attempted and slang ALSO failed to
    # build a miter, downgrade the provisional INCONCLUSIVE to FAIL — a design
    # the capable SV-2017 frontend cannot elaborate is not a free non-blocking
    # pass. No-op when slang was not attempted or succeeded.
    parsed = finalize_after_slang_retry(parsed, slang_retry_failed)
    report = build_report(parsed, resolved_top, gate_abs, liberty)
    report["elapsed_sec"] = elapsed
    # WHAT was attempted, WHICH resource ran out, HOW MANY attempts. Additive:
    # never changes verdict/equivalent.
    report = annotate_step_budget(report, budget)
    report["gold_rtl_files"] = [Path(f).name for f in gold_files]
    # Provenance: which gold frontend + define set actually built the miter
    # (verilog | slang; -DSIMULATION vs -DSYNTHESIS — how synth built the gate).
    report["gold_frontend"] = gold_frontend
    report["gold_defines"] = gold_defines if gold_frontend == "slang" else None
    # WHY that frontend — empty when the built-in reader built the miter on the
    # first pass; otherwise the explicit justification for the slang fallback.
    report["gold_frontend_reason"] = gold_frontend_reason or None
    # THE BOUND AND WHETHER IT WAS HIT. Without these a reader of lec.json
    # cannot tell a proof that DECIDED nothing from a proof that was never
    # given enough resources to decide anything -- the exact confusion that
    # made a 2h grind indistinguishable from a hang. `yosys_budget_s` is the
    # bound the CALLER set (--timeout / VIBEIC_LEC_YOSYS_TIMEOUT_S);
    # `budget_exhausted` is True only when THIS program's own budget-kill
    # marker is in the log; `proof_stages_attempted` names the yosys passes
    # that actually ran, so "what was attempted" is evidence, not a guess.
    report["yosys_budget_s"] = args.timeout
    report["budget_exhausted"] = bool(_TIMEOUT_RE.search(raw))
    report["proof_stages_attempted"] = yosys_executed_passes(raw)[:40]
    # WHAT WAS CONSTRAINED, ALWAYS. Recorded on every run — including the runs
    # where nothing was constrained, with the reason — so a PASS on a scan
    # netlist can never be read without seeing the mode it was proven in, and a
    # scan netlist compared WITHOUT the constraints is visible as such rather
    # than looking like an ordinary comparison.
    report["scan_functional_mode"] = scan_record
    json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print(json.dumps({
        "verdict": report["verdict"],
        "equivalent": report["equivalent"],
        "compared_points": report["compared_points"],
        "unproven_points": report["unproven_points"],
        "sat_model_unsupported_cells":
            len(report["sat_model_unsupported_cells"]),
        "json": str(json_out),
        "rpt": str(rpt_out),
    }, indent=2, ensure_ascii=False))

    # PRODUCER contract: 0 whenever a truthful verdict was written (PASS,
    # SKIPPED-CONDITION, INCONCLUSIVE, or an evidence-backed FAIL). 1 only when
    # Yosys ran but produced no parseable evidence AND it is not a frontend
    # parse-abort (INCONCLUSIVE) nor a disclosed wall-budget skip
    # (SKIPPED-CONDITION) — both are truthful, visible-non-PASS verdicts, not
    # tool failures. An evidence-backed timeout FAIL keeps parse_error+FAIL → 1.
    return 1 if (parsed["parse_error"]
                 and parsed["verdict"] not in ("INCONCLUSIVE",
                                               "SKIPPED-CONDITION")) else 0


if __name__ == "__main__":
    sys.exit(main())
