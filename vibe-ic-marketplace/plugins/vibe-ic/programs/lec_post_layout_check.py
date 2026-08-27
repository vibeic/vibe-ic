#!/usr/bin/env python3
"""lec_post_layout_check.py — POST-LAYOUT logic-equivalence gate.

WHY THIS EXISTS
===============
Step-13 LEC (`lec_equivalence_check.py`) proves RTL == the SYNTH (post-DFT)
netlist. It says NOTHING about what CTS / PnR / ECO / metal-fill did to that
netlist afterwards. Those steps insert clock-tree buffers, size/route cells,
apply hold-fix and timing/functional ECOs, and add physical-only fill — any of
which can (through a tool bug, a bad manual ECO, or a mis-applied spare-cell
patch) change the LOGIC of the routed netlist. A tape-out that only proved
RTL==synth ships a ROUTED netlist that was never re-proven equivalent.

This gate re-proves the FINAL routed/repaired netlist against a golden reference
(the synth netlist by default, or the RTL) with Yosys structural equivalence
(`equiv_make` + `equiv_simple` + `equiv_induct` + `equiv_status`) — the same
engine `eda_lvs mode=yosys_equiv` uses. Physical-only cells in the routed
netlist (tap / fill / decap / diode / endcap) carry no Liberty timing model and
would abort `hierarchy`; the recipe reads the PDK's blackbox Verilog (globbed,
PDK-AGNOSTIC) so those inert cells become empty blackboxes and the FUNCTIONAL
comparison proceeds.

TWO HALVES (mirrors si_signoff_timing_aware's program-first split)
=================================================================
(1) RECIPE + PARSER (pure, offline-testable):
      build_yosys_equiv_script(gold_v, gate_v, lib, top, blackbox_v=[...])
      parse_equiv_log(text) -> {proven, unproven, total, verdict, ...}
(2) SUBSTANCE GATE over the produced artefact (reports/phase3/lec_post_layout.json):
      evaluate_report(doc) -> PASS / FAIL / SKIP
    The phase3 runner writes that artefact by running the recipe in-container;
    this CLI then verifies its SUBSTANCE the same anti-fabrication way as the
    Step-13 gate.

VERDICT (§4.05 — a non-proof / vacuous match is a FAIL, never a pass)
====================================================================
  PASS   verdict==PROVEN_EQUIVALENT AND total_points>0 AND unproven==0
         AND non_equivalent==0 AND equivalent==true  (a REAL, non-vacuous proof)
  FAIL   NON_EQUIVALENT (routed netlist logic differs — a real silicon bug),
         UNPROVEN (equivalence NOT proven — a bounded/aborted/SAT-gap proof is
         not a clean pass), VACUOUS (equivalent==true but 0 points compared),
         or RUN_ERROR (yosys did not produce a parseable result).
  SKIP   no routed/repaired netlist exists yet (design not placed-and-routed) — an
         HONEST skip, never a vacuous pass. Non-blocking.

chip-/PDK-AGNOSTIC: no design-specific assumptions; the only PDK coupling is the
glob for a blackbox Verilog + a Liberty, both discovered from the PDK root.

CLI:
    python3 lec_post_layout_check.py <project_dir> [--json OUT]
    main(argv) -> int : 0 PASS / 1 FAIL / 2 IO-or-arg error.
    (SKIP exits 0 — an honest not-applicable, not a failure.)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

GATE = "lec_post_layout_check"

# Artefact the phase3 runner writes (relative to the project root).
LEC_POST_JSON_REL = "reports/phase3/lec_post_layout.json"
LEC_POST_RPT_REL = "reports/phase3/lec_post_layout.rpt"

# Verdict vocabulary.
V_PASS = "PROVEN_EQUIVALENT"
V_NONEQUIV = "NON_EQUIVALENT"
V_UNPROVEN = "UNPROVEN"
V_VACUOUS = "VACUOUS"
V_SKIP = "SKIP"
V_RUN_ERROR = "RUN_ERROR"


# ---------------------------------------------------------------------------
# (1a-probe) Functional read_liberty capability probe (SOUNDNESS gating)
# ---------------------------------------------------------------------------
# `read_liberty -lib <lib>` imports every cell as an UNINTERPRETED BLACKBOX;
# `equiv_make` then only STRUCTURALLY matches cells and ASSUMES matched cells are
# equal — it never proves the cell function, so a gold `nand2(a,b)` vs a gate
# `nor2(a,b)` (genuinely NOT equal) is FALSELY reported "proven". That is worse
# than a floor: it can green-light an inequivalent netlist. Functional
# `read_liberty <lib>` (NO `-lib`) instead expands every cell's `function` and
# ff/latch group into Yosys primitives the SAT engine models, so NAND≢NOR is
# correctly rejected AND a PnR buffer-insert (y=a vs y=buf(a)) proves.
#
# The only blocker to functional models was that functional `read_liberty`
# ABORTS parsing an integrated clock-gate cell ("Missing function on output
# GCLK … dlclkp" / a commercial ICG output) on a pre-fork Yosys — fixed in the
# vibeic-eda fork yosys 7c8d7a282. So the functional path is CAPABILITY-GATED:
# the runner tries functional and, on that abort, falls back to the (unsound but
# always-available) `-lib` recipe, RECORDING which path ran. This makes the fix
# safe to land BEFORE the image rebuild and auto-upgrade to the sound path after.
#
# NOTE: key ONLY on the read_liberty-time "Missing function on output" abort —
# NOT the equiv-time "No SAT model available for cell …" line, which is the
# NORMAL honest-gap signal for inert physical-only cells and must never trigger
# a spurious fallback.
_FUNC_READ_LIB_ABORT_RE = re.compile(r"Missing function on output", re.IGNORECASE)


def functional_read_liberty_aborted(log: str) -> bool:
    """True iff a Yosys log shows the pre-fork functional `read_liberty` abort
    (the ICG "Missing function on output …" parse error). PURE — the runner
    feeds the functional-recipe (or probe) log here to decide the -lib fallback.
    Does NOT match the equiv-time "No SAT model available" physical-cell gap."""
    return bool(_FUNC_READ_LIB_ABORT_RE.search(log or ""))


def build_functional_probe_script(lib: str) -> str:
    """A minimal Yosys script that just FUNCTIONALLY reads the Liberty (no
    `-lib`). On a binary that cannot build a function for every cell this ABORTS
    at read_liberty (e.g. on an integrated clock-gate output); where it is
    supported it succeeds. The runner classifies the probe with
    functional_read_liberty_supported() to pick the recipe WITHOUT paying for a
    full equiv run first."""
    return f"read_liberty {lib}\n"


def functional_read_liberty_supported(
    probe_rc: int,
    liberty_exists: bool,
    liberty_nonempty: bool,
) -> Tuple[bool, str]:
    """OBSERVABLE (v1.4.x): did the FUNCTIONAL `read_liberty` actually work?

    A CAPABILITY PROBE SHOULD PROBE. The old decision grepped the FULL equiv
    log for "Missing function on output". Two problems: (a) a reworded abort
    silently selected the UNSOUND `-lib` recipe with no trace, and (b) grepping
    the full equiv log meant any run whose transcript happened to contain that
    phrase — including a genuine MISMATCH run — could trigger the fallback.
    Running the dedicated probe instead ISOLATES the capability question from
    the equivalence result, so an equivalence outcome can never select the
    unsound recipe. That is a §4.05 TIGHTENING, not a widening.

    §4.05 — DIRECTION OF SAFETY IS INVERTED HERE. On the retry sites in this
    codebase, widening the trigger is safe because the fallback is another
    honest attempt. Here the fallback is the `-lib` BLACKBOX recipe, which is
    UNSOUND: it assumes matched cells are equal, so it can false-PASS NAND≡NOR.
    Widening what selects it would therefore widen what can PASS. So this
    deliberately does NOT fall back on every failure:

      * liberty missing / empty  -> NOT a capability gap, an INPUT defect. No
        fallback; the caller must fail honestly rather than run an unsound
        compare on a file it never read.
      * probe rc == 0            -> the sound functional recipe works. Use it.
      * probe rc != 0 on a real, non-empty liberty -> genuine capability gap in
        this binary. Fall back, and the caller RECORDS the unsound provenance.

    Returns (supported, reason). `supported=False` with a reason naming an input
    defect means "do not fall back" — the caller checks `liberty_exists` /
    `liberty_nonempty` itself, which is why they are explicit parameters."""
    if not liberty_exists:
        return False, ("liberty file does not exist — an INPUT defect, not a "
                       "capability gap; the unsound -lib fallback must NOT be "
                       "selected on a file that was never read")
    if not liberty_nonempty:
        return False, ("liberty file is empty — an INPUT defect, not a "
                       "capability gap; the unsound -lib fallback must NOT be "
                       "selected on a file with no cells")
    if probe_rc == 0:
        return True, ("functional read_liberty probe succeeded — the SOUND "
                      "recipe (proves each cell's function) is available")
    return False, (
        f"functional read_liberty probe FAILED (rc={probe_rc}) on a present, "
        f"non-empty liberty — this binary cannot build a function for every "
        f"cell (e.g. an integrated clock-gate output). Falling back to the "
        f"UNSOUND -lib blackbox recipe, recorded as such in the provenance")


def liberty_input_is_usable(liberty_exists: bool,
                            liberty_nonempty: bool) -> bool:
    """True iff the liberty is a real, non-empty file — i.e. a functional-read
    failure would be a CAPABILITY gap rather than an INPUT defect. Callers use
    this to refuse the unsound fallback on a bad input."""
    return bool(liberty_exists and liberty_nonempty)


# ---------------------------------------------------------------------------
# (1a) The Yosys equivalence recipe (PRODUCES the log the parser consumes)
# ---------------------------------------------------------------------------
# Auto-escalating sequential-induction depths for equiv_induct.
#
# Yosys `equiv_induct` defaults to `-seq 4` (4 induction frames). That is fine
# for a same-topology netlist-vs-netlist compare, but it FALSELY reports UNPROVEN
# when gold and gate are sequentially equivalent yet hold DIFFERENT internal state
# — the classic retiming / pipeline-rebalancing case (e.g. "multiply then delay 8"
# vs "delay 4, multiply, delay 4"): pure k-induction must span the full pipeline
# latency, so depth 4 leaves every output $equiv cell unproven. Escalating the
# depth is STRICTLY SAFE: k-induction is sound, so a deeper frame count proves
# only MORE genuinely-equivalent cells and NEVER stamps an inequivalent pair
# (empirically confirmed — a latency-7 vs latency-8 buggy pair stays fully
# unproven at -seq 8). Each successive equiv_induct only re-attempts the cells
# still unproven, so a design that closes at depth 4 pays ~nothing for the deeper
# passes; only genuinely deep pipelines run the expensive frames.
DEFAULT_SEQ_DEPTHS = (4, 16, 64)


# ---------------------------------------------------------------------------
# The Liberty is the ONLY source that carries cell FUNCTION; blackbox Verilog is
# an interface stub. Read them in that priority.
# ---------------------------------------------------------------------------
# Both sources describe the SAME standard cells, from opposite ends:
#   * the Liberty `.lib` carries each cell's `function` / ff / latch group ->
#     read_liberty (no `-lib`) expands it into Yosys primitives the SAT engine
#     can reason about. This is what an equivalence proof consumes.
#   * `<lib>__blackbox.v` declares the same cells as EMPTY modules (ports only,
#     no body). It exists to give a name+interface to the cells the Liberty
#     does NOT model at all -- fill / tap / endcap / antenna-diode / IO pads --
#     so `hierarchy` does not abort on the routed netlist.
# The recipe read the Liberty and then read the blackbox Verilog with plain
# `read_verilog -lib`, whose DEFAULT is to overwrite an existing module. Yosys
# refused the collision outright:
#     sky130_fd_sc_hd__blackbox.v:37: ERROR: Re-definition of module ...
# so the whole proof aborted (verdict RUN_ERROR, equivalence unproven) on every
# PDK that ships both a Liberty and a matching blackbox Verilog for one library.
#
# The fix is NOT to drop a source: dropping the Liberty leaves function-less
# stubs and the proof becomes VACUOUS in the worst way (equiv_make would assume
# matched cells equal -- NAND vs NOR would "prove"); dropping the blackbox
# Verilog leaves fill/tap/pads undefined and `hierarchy` aborts. Both are
# needed, with a PRIORITY: `-nooverwrite` makes the blackbox read ADDITIVE, so
# every cell the Liberty modelled keeps its FUNCTION and only the cells the
# Liberty never defined come from the stub. Nothing is discarded.
def _read_blackbox_cmd(path: str) -> str:
    """The Yosys read command for one blackbox-Verilog input.

    `-lib`         : ports only, no cell body (an inert blackbox).
    `-nooverwrite` : a module already defined (by read_liberty, which ran
                     first) is KEPT -- the empty stub never replaces a
                     functional Liberty model, and the frontend does not abort
                     on the re-definition it would otherwise refuse.
    """
    return f"read_verilog -lib -nooverwrite {path}"


def build_yosys_equiv_script(gold_v: str, gate_v: str, lib: str, top: str,
                             blackbox_v: Optional[List[str]] = None,
                             seq_depths: Optional[List[int]] = None,
                             strip_gate_ports: Optional[List[str]] = None,
                             functional_lib: bool = False) -> str:
    """Emit the Yosys .ys that structurally proves gold_v == gate_v.

    gold_v : golden reference netlist/RTL (e.g. <top>_synth.v or the RTL).
    gate_v : the netlist under test (the FINAL routed / ECO / filled netlist).
    lib    : Liberty for cell semantics (functional cells).
    blackbox_v : PDK blackbox Verilog files (physical-only cells: tap/fill/
                 decap/diode/endcap have no Liberty model and would abort
                 hierarchy). Read as `-lib -nooverwrite` so they can only ADD
                 the cells the Liberty does not define, never REPLACE a Liberty
                 cell (see _read_blackbox_cmd).
    seq_depths : ascending equiv_induct `-seq` depths to try in one script
                 (default DEFAULT_SEQ_DEPTHS = (4, 16, 64)). The escalation makes
                 the proof depth-adaptive so a retiming/pipeline-equivalent pair
                 proves at the depth matching its latency instead of falsely
                 failing at the shallow default. Sound: deeper only proves more.
    functional_lib : when True, read the Liberty FUNCTIONALLY (`read_liberty`
                 WITHOUT `-lib`) so equiv proves each cell's FUNCTION instead of
                 assuming matched cells equal — the SOUND path (rejects NAND≢NOR,
                 proves buffer-inserts). Requires the vibeic-eda fork yosys
                 (7c8d7a282: functional read models ICG clock gates); the runner
                 CAPABILITY-PROBES and only sets this True when the binary can do
                 it (else the unsound-but-available `-lib` path, functional_lib
                 False, is used and RECORDED). See functional_read_liberty_aborted.

    All paths are used verbatim (caller translates host->container). Same
    engine shape as `eda_lvs mode=yosys_equiv`."""
    bb = "\n".join(_read_blackbox_cmd(q) for q in (blackbox_v or []))
    bb_block = (bb + "\n") if bb else ""
    # v1.3.93 — the routed gate netlist carries top-level SUPPLY ports (VDD/VSS…
    # added by PDN insertion) that the pre-PnR synth GOLD reference does not, so
    # `equiv_make` aborts "Can't match gate port VDD_gate". Delete ONLY those
    # supply ports from the gate design (they carry no logic; the Liberty cells
    # are functional models without power pins). NEVER strip a non-supply port —
    # a functional gate/gold port mismatch is a real defect that must surface.
    strip = "".join(f"delete {top}/w:{p}\n" for p in (strip_gate_ports or []))
    strip_block = (strip + "opt_clean\n") if strip else ""
    depths = list(seq_depths) if seq_depths else list(DEFAULT_SEQ_DEPTHS)
    # Ascending, de-duplicated, positive; each pass only works the still-unproven
    # cells, so the shallow-first order keeps the common case cheap.
    depths = sorted({int(d) for d in depths if int(d) > 0})
    induct = "\n".join(f"equiv_induct -seq {d}" for d in depths) or "equiv_induct"

    if functional_lib:
        # FUNCTIONAL (SOUND) recipe. Per-side, three GOTCHAs make functional
        # cell models actually reach the SAT miter:
        #   GOTCHA 1 — `flatten` (before `design -stash`): `design -copy-from …
        #     {top}` copies ONLY {top}, NOT the per-cell function modules
        #     read_liberty created; without flatten the miter sees blackboxes
        #     again → "No SAT model available for cell …". flatten inlines the
        #     functional logic into {top} so the models survive the copy.
        #   GOTCHA 2 — `async2sync`: equiv's SAT cannot model level-sensitive
        #     $_DLATCH_*/$dlatch (the ICG model is a latch; proc may emit
        #     $dlatch). async2sync (lighter than clk2fflogic; verified
        #     sufficient) converts them; ORDER = after prep, before equiv_make.
        #   GOTCHA 3 — `opt -purge; opt_clean -purge` (BOTH sides): source-RTL
        #     dead unobservable public nets get $equiv key-points induction
        #     can't close → spurious unproven; purge prunes them. chip-agnostic.
        # The physical-only cell blackbox block ({bb_block}) is kept, and is
        # read AFTER read_liberty with -nooverwrite: fill/tap/decap/diode/
        # antenna carry no function and stay inert blackboxes, while every cell
        # the Liberty DID model keeps its function (see _read_blackbox_cmd).
        def _func_side(read_v: str, stash: str, extra_strip: str = "") -> str:
            return (f"read_liberty {lib}\n"
                    f"{bb_block}{read_v}\n"
                    f"prep -top {top}\n"
                    f"{extra_strip}"
                    f"flatten\n"
                    f"async2sync\n"
                    f"opt -purge\n"
                    f"opt_clean -purge\n"
                    f"splitnets -ports\n"
                    f"design -stash {stash}\n")
        gold_block = _func_side(f"read_verilog -sv {gold_v}", "gold")
        gate_block = _func_side(f"read_verilog -sv {gate_v}", "gate", strip_block)
        return (
            "# Vibe-IC post-layout LEC — FUNCTIONAL (sound) Liberty cell models.\n"
            f"{gold_block}\n{gate_block}\n"
            f"design -copy-from gold -as gold {top}\n"
            f"design -copy-from gate -as gate {top}\n"
            "equiv_make gold gate equiv\n"
            "hierarchy -top equiv\n"
            "equiv_simple\n"
            f"{induct}\n"
            "equiv_status\n")

    # BLACKBOX `-lib` recipe (available on ANY yosys; UNSOUND — equiv_make
    # assumes matched cells equal, so NAND≡NOR false-passes). Used only as the
    # fallback when the binary cannot do functional read_liberty. The blackbox
    # Verilog is read `-nooverwrite` here too: on this path both sources are
    # blackboxes so no function is at stake, but the frontend still refuses the
    # re-definition without it (the same RUN_ERROR abort).
    return f"""# Vibe-IC post-layout LEC — gold(reference) vs gate(routed) structural equiv.
read_liberty -lib {lib}
{bb_block}read_verilog -sv {gold_v}
prep -top {top}
splitnets -ports
design -stash gold

read_liberty -lib {lib}
{bb_block}read_verilog -sv {gate_v}
prep -top {top}
{strip_block}splitnets -ports
design -stash gate

design -copy-from gold -as gold {top}
design -copy-from gate -as gate {top}
equiv_make gold gate equiv
hierarchy -top equiv
equiv_simple
{induct}
equiv_status
"""


# ---------------------------------------------------------------------------
# (1b) Parse the yosys equiv log -> proven/unproven counts + verdict
# ---------------------------------------------------------------------------
# Final summary (equiv_status): "... N are proven and K are unproven"
_PROVEN_UNPROVEN_RE = re.compile(
    r"(\d+)\s+are\s+proven\s+and\s+(\d+)\s+are\s+unproven", re.IGNORECASE)
# Total: "Found N $equiv cells in equiv:" / "Found N $equiv cells"
_TOTAL_RE = re.compile(
    r"Found\s+(\d+)\s+\$equiv\s+cells(?!\s+\(|.*unproven)", re.IGNORECASE)
# Residual unproven (equiv_induct): "Found K unproven $equiv cells in module equiv:"
_RESIDUAL_UNPROVEN_RE = re.compile(
    r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+in\s+module", re.IGNORECASE)
# equiv_simple entry total: "Found N unproven $equiv cells (N groups) in equiv:"
_ENTRY_TOTAL_RE = re.compile(
    r"Found\s+(\d+)\s+unproven\s+\$equiv\s+cells\s+\(\d+\s+groups\)", re.IGNORECASE)
_SUCCESS_RE = re.compile(r"Equivalence\s+successfully\s+proven", re.IGNORECASE)
# SAT-model gap on a custom-PDK primitive (tool limitation, not a mismatch).
_SAT_GAP_RE = re.compile(
    r"has no model for cell type\s+`?\\?([A-Za-z0-9_]+)", re.IGNORECASE)
# A hard error that means yosys did not run to a verdict.
_HARD_ERR_RE = re.compile(
    r"^ERROR:", re.IGNORECASE | re.MULTILINE)


def parse_equiv_log(text: str) -> Dict[str, object]:
    """Parse a Yosys equiv log into structured counts + a verdict.

    Returns keys: proven, unproven, total, non_equivalent, equivalent,
    sat_unsupported_cells, verdict, parse_error."""
    if not text or not text.strip():
        return {"verdict": V_RUN_ERROR, "parse_error": True,
                "proven": None, "unproven": None, "total": None,
                "non_equivalent": None, "equivalent": False,
                "sat_unsupported_cells": [],
                "reason": "empty yosys log"}

    proven = unproven = total = None

    m = _PROVEN_UNPROVEN_RE.search(text)
    if m:
        proven = int(m.group(1))
        unproven = int(m.group(2))

    tm = _ENTRY_TOTAL_RE.search(text)
    if tm:
        total = int(tm.group(1))
    if total is None:
        tm2 = _TOTAL_RE.search(text)
        if tm2:
            total = int(tm2.group(1))

    # Residual unproven when the final summary line is absent (SAT-gap abort).
    if unproven is None:
        rm = _RESIDUAL_UNPROVEN_RE.search(text)
        if rm:
            unproven = int(rm.group(1))

    # Reconstruct: if we have total + one of proven/unproven, derive the other.
    if total is not None:
        if proven is not None and unproven is None:
            unproven = max(0, total - proven)
        elif unproven is not None and proven is None:
            proven = max(0, total - unproven)
    elif proven is not None and unproven is not None:
        total = proven + unproven

    sat_cells = sorted(set(_SAT_GAP_RE.findall(text)))
    hard_err = bool(_HARD_ERR_RE.search(text)) and total is None and proven is None
    success_line = bool(_SUCCESS_RE.search(text))

    # --- verdict ---
    if hard_err or (total is None and proven is None and unproven is None
                    and not success_line):
        verdict = V_RUN_ERROR
        equivalent = False
    elif success_line and (unproven is None or unproven == 0) and (total or 0) >= 0:
        # Yosys printed the canonical proof line. Still require non-vacuity when
        # a total is known: a 0-cell "success" is vacuous.
        if total is not None and total <= 0 and proven in (None, 0):
            verdict = V_VACUOUS
            equivalent = False
        else:
            verdict = V_PASS
            equivalent = True
    elif total is not None and total <= 0:
        verdict = V_VACUOUS
        equivalent = False
    elif unproven is not None and unproven > 0:
        # Equivalence NOT proven for these points. This covers both a genuine
        # mismatch and a SAT-model / bounded-proof gap; either way it is NOT a
        # clean pass (§4.05). We label UNPROVEN and expose sat cells so triage
        # can tell tool-limitation from real mismatch.
        verdict = V_UNPROVEN
        equivalent = False
    elif (total is not None and total > 0
          and (unproven == 0) and (proven is not None and proven >= total)):
        verdict = V_PASS
        equivalent = True
    else:
        # Have some numbers but they don't add up to a clean proof.
        verdict = V_UNPROVEN
        equivalent = False

    return {
        "verdict": verdict,
        "parse_error": verdict == V_RUN_ERROR,
        "proven": proven,
        "unproven": unproven,
        "total": total,
        # Yosys equiv_status folds a genuine mismatch into the unproven bucket;
        # non_equivalent is surfaced only if a downstream producer sets it.
        "non_equivalent": None,
        "equivalent": equivalent,
        "sat_unsupported_cells": sat_cells,
        "success_line": success_line,
    }


# ---------------------------------------------------------------------------
# (2) Substance gate over the produced JSON artefact
# ---------------------------------------------------------------------------
def _lc(doc: dict) -> dict:
    return {k.lower(): v for k, v in doc.items() if isinstance(k, str)}


def _int_or_none(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def evaluate_report(doc: dict) -> Dict[str, object]:
    """Verify the SUBSTANCE of a lec_post_layout.json artefact.

    PASS / FAIL / SKIP with the §4.05 anti-vacuous discipline. Independent of
    the artefact's self-declared boolean — we recompute from the counts."""
    lc = _lc(doc)
    verdict_in = str(lc.get("verdict", "")).upper()

    # SKIP — honest not-applicable (no routed netlist). Never a pass, never a fail.
    if lc.get("skipped") is True or verdict_in == V_SKIP:
        return {"gate": GATE, "result": "SKIP",
                "reason": lc.get("skip_reason")
                or "no routed/repaired netlist — design not placed-and-routed",
                "verdict": V_SKIP}

    total = _int_or_none(lc.get("total_points"))
    if total is None:
        total = _int_or_none(lc.get("total"))
    unproven = _int_or_none(lc.get("unproven_points"))
    if unproven is None:
        unproven = _int_or_none(lc.get("unproven"))
    proven = _int_or_none(lc.get("proven_points"))
    if proven is None:
        proven = _int_or_none(lc.get("proven"))
    non_equiv = _int_or_none(lc.get("non_equivalent_points"))
    if non_equiv is None:
        non_equiv = _int_or_none(lc.get("non_equivalent"))
    equivalent = lc.get("equivalent")

    findings: List[str] = []
    result = "FAIL"

    if verdict_in == V_RUN_ERROR:
        findings.append("LEC_POST_RUN_ERROR: yosys did not produce a parseable "
                        "equivalence result — equivalence is unproven.")
    elif verdict_in == V_NONEQUIV or (non_equiv is not None and non_equiv > 0):
        findings.append(f"LEC_POST_NONEQUIV: {non_equiv} non-equivalent "
                        "point(s) — the routed netlist logic DIFFERS from the "
                        "reference (a real silicon-correctness bug).")
    elif equivalent is True and total is not None and total <= 0:
        findings.append("LEC_POST_VACUOUS: equivalent==true but 0 points "
                        "compared — a vacuous claim, not a proof.")
    elif verdict_in == V_VACUOUS:
        findings.append("LEC_POST_VACUOUS: 0 equivalence points compared.")
    elif unproven is not None and unproven > 0:
        findings.append(f"LEC_POST_UNPROVEN: {unproven} unproven point(s) — "
                        "equivalence is NOT proven (bounded/aborted/SAT-gap "
                        "proof is not a clean LEC pass).")
    elif (verdict_in == V_PASS and total is not None and total > 0
          and (unproven == 0 or unproven is None)
          and (non_equiv in (0, None)) and equivalent is not False):
        result = "PASS"
    else:
        findings.append("LEC_POST_NO_EVIDENCE: cannot confirm a real, "
                        "non-vacuous proof (verdict/counts do not establish "
                        f"PROVEN_EQUIVALENT: verdict={verdict_in!r}, "
                        f"total={total}, unproven={unproven}, proven={proven}).")

    return {
        "gate": GATE,
        "result": result,
        "verdict": verdict_in or None,
        "total_points": total,
        "proven_points": proven,
        "unproven_points": unproven,
        "non_equivalent_points": non_equiv,
        "equivalent": equivalent,
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def check(project: Path) -> Dict[str, object]:
    json_path = project / LEC_POST_JSON_REL
    if not json_path.is_file():
        # No artefact at all: HONEST SKIP (the post-route step never ran because
        # the design has no routed netlist). §4.05 — an absent proof is never a
        # vacuous pass, but a not-placed-and-routed design is a legitimate SKIP,
        # not a FAIL of a check that could not apply.
        return {"gate": GATE, "result": "SKIP",
                "reason": f"{LEC_POST_JSON_REL} absent — post-layout LEC has "
                          "not run (design likely not placed-and-routed)",
                "verdict": V_SKIP}
    try:
        doc = json.loads(json_path.read_text(errors="replace"))
    except (OSError, ValueError) as e:
        return {"gate": GATE, "result": "FAIL",
                "findings": [f"LEC_POST_UNPARSEABLE: {json_path} is not valid "
                             f"JSON: {e}"],
                "verdict": V_RUN_ERROR}
    if not isinstance(doc, dict):
        return {"gate": GATE, "result": "FAIL",
                "findings": ["LEC_POST_UNPARSEABLE: top-level is not an object"],
                "verdict": V_RUN_ERROR}
    res = evaluate_report(doc)
    res["report"] = str(json_path)
    return res


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Post-layout LEC gate (RTL/synth == routed netlist).")
    ap.add_argument("project_dir", help="Project directory to scan")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the verdict JSON to this path")
    ns = ap.parse_args(argv)
    project = Path(ns.project_dir)
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 2
    res = check(project.resolve())
    out = json.dumps(res, indent=2)
    if ns.json_out:
        Path(ns.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(ns.json_out).write_text(out)
    print(out)
    # SKIP is an honest not-applicable -> exit 0 (does not block tape-out).
    if res["result"] == "PASS" or res["result"] == "SKIP":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
