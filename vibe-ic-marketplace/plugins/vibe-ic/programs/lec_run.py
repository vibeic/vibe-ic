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
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROGRAM = "lec_run"

DEFAULT_CONTAINER = "vibeic-eda"
DEFAULT_LIBERTY = (
    "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
    "sky130_fd_sc_hd__tt_025C_1v80.lib"
)
# Per-yosys-invocation budget. The equiv miter on a CPU-class gold (ibex:
# ~2k compared points through equiv_induct -seq 64) runs far past the old
# 1800s, and a killed run produced NO evidence — indistinguishable at the
# gate from a real mismatch. Tunable via --timeout for smaller budgets.
DEFAULT_YOSYS_TIMEOUT_S = 7200
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

# BUDGET-EXHAUSTED marker. A killed equiv run produced NO comparison, which
# the generic "no parseable result" wording rendered indistinguishable from a
# real mismatch at the gate. It stays a BLOCKING non-PASS (never a free pass),
# but the explanation must name the cause so a reader can raise --timeout
# instead of hunting a mismatch that was never found.
_TIMEOUT_MARKER = "[lec_run] ERROR: yosys equiv exceeded its time budget"
_TIMEOUT_RE = re.compile(re.escape(_TIMEOUT_MARKER))

# Canonical Yosys success line (corroboration for the gate's .rpt parse).
_SUCCESS_RE = re.compile(r"Equivalence\s+successfully\s+proven", re.IGNORECASE)

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
# Liberty / RTLIL / BLIF). Every design-BUILDING pass announces as "<NAME> pass".
_YOSYS_FRONTEND_PASS_RE = re.compile(r"\bfrontend\b", re.IGNORECASE)


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
    non_frontend = [p for p in passes
                    if not _YOSYS_FRONTEND_PASS_RE.search(p)]
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
    no-op when slang was not attempted or slang succeeded."""
    if not slang_retry_failed or parsed.get("verdict") != "INCONCLUSIVE":
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
    if parse_error and _fe_aborted:
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
        # The miter was still running when the budget expired: no comparison was
        # made, so this is NOT evidence of a mismatch — but it is also NOT a
        # pass. Blocking FAIL with the cause named (raise --timeout and re-run).
        equivalent = False
        verdict = "FAIL"
        verdict_explanation = (
            "Yosys equiv exceeded its time budget before equiv_status could "
            "report — 0 points compared, so NO equivalence evidence exists in "
            "either direction. This is a RESOURCE limit, not a proven "
            "mismatch: re-run with a larger --timeout to obtain a real "
            "verdict. Blocking (never a free pass) until it is decided.")
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
        equivalent = False
        verdict = "FAIL"
        verdict_explanation = (
            f"{proven if proven is not None else 0}/"
            f"{total if total is not None else '?'} proven, "
            f"{unproven if unproven is not None else '?'} unproven — the RTL "
            "and gate netlist may genuinely differ at these points.")

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


def build_equiv_script(gold_files: List[str], gate_netlist: str, top: str,
                       liberty: Optional[str],
                       blackbox_v: Optional[List[str]] = None,
                       gate_is_generic: bool = False,
                       gold_frontend: str = "verilog",
                       slang_prefix: str = "",
                       gold_defines: str = "-DSIMULATION -DYOSYS") -> str:
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
        gold_read_cmd = (f"{_plugin_line}read_slang {gold_read} "
                         f"--top {top} {gold_defines}")
    else:
        gold_read_cmd = f"read_verilog -sv {gold_read}"
    return (
        # --- gold = RTL, kept as generic satgen-modelable Yosys cells ---
        f"{gold_read_cmd}\n"
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
        f"equiv_make gold gate equiv\n"
        f"hierarchy -top equiv\n"
        f"equiv_simple\n"
        f"equiv_induct -seq 4\n"
        f"equiv_induct -seq 16\n"
        f"equiv_induct -seq 64\n"
        f"equiv_status\n"
    )


def run_yosys_equiv(container: str, ys_path_in_container: str,
                    timeout: int = DEFAULT_YOSYS_TIMEOUT_S):
    """Run `yosys -s <ys>` in the container. Returns (launched, raw_output).

    launched=False means Docker/Yosys could not run at all (the caller then
    returns 1 for a disclosed-skip). launched=True means Yosys emitted output
    (any outcome), which the parser then classifies."""
    try:
        r = _docker(
            container,
            f"yosys -s {shlex.quote(ys_path_in_container)} 2>&1",
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
    """All .v/.sv files under the gold RTL dir (sorted, absolute paths)."""
    if not gold_dir.is_dir():
        return []
    files = sorted(
        p for p in gold_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".v", ".sv"))
    return [str(p.resolve()) for p in files]


_MODULE_DECL_RE = re.compile(r"(?m)^\s*module\s+([A-Za-z_]\w*)")


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


def _resolve_gold_top(gold_files: List[str], top: str) -> "tuple[str, str]":
    """Ensure the LEC gold top is a module that actually exists in the RTL.

    A wrong top (e.g. the default 'chip_top' on a standalone 'spm' design) makes
    Yosys build 0 $equiv cells → a MISLEADING 'may genuinely differ' FAIL that
    proved nothing. If `top` is not declared, auto-correct to the sole ROOT
    module; if the choice is ambiguous, return top unchanged with a diagnostic
    note so the caller can emit an honest 'top not found' verdict instead of a
    fake mismatch. Returns (resolved_top, note)."""
    decls, insts = _gold_modules(gold_files)
    if not decls or top in decls:
        return top, ""
    roots = sorted(m for m in decls if m not in insts)
    if len(roots) == 1:
        return roots[0], (f"gold top '{top}' not found in RTL; auto-corrected to "
                          f"sole root module '{roots[0]}'")
    return top, (f"gold top '{top}' not found in RTL modules "
                 f"{sorted(decls)[:8]} and no unique root — cannot select a top")


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

    # Defense-in-depth: make sure the gold top actually exists in the RTL. A
    # wrong top (default 'chip_top' on a standalone 'spm') builds 0 $equiv cells
    # → a MISLEADING 'may genuinely differ' FAIL that proved nothing. Auto-correct
    # to the sole root, or emit an honest 'top not found' SKIPPED-CONDITION.
    resolved_top, top_note = _resolve_gold_top(gold_files, args.top)
    if top_note:
        print(f"[lec_run] {top_note}", file=sys.stderr)
    gold_decls, _ = _gold_modules(gold_files)
    if gold_decls and resolved_top not in gold_decls:
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
    gold_frontend = "verilog"
    gold_defines = "-DSIMULATION -DYOSYS"   # synth PRIMARY define set (mirrored)

    def _run(frontend: str, slang_prefix: str = "",
             defines: str = "-DSIMULATION -DYOSYS"):
        script = build_equiv_script(gold_files, gate_abs, resolved_top, liberty,
                                    gate_is_generic=gate_is_generic,
                                    gold_frontend=frontend,
                                    slang_prefix=slang_prefix,
                                    gold_defines=defines)
        ys_host.write_text(script, encoding="utf-8")
        return run_yosys_equiv(container, ys_in_container,
                               timeout=args.timeout)

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
                        slang_retry_failed = True
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
    report["gold_rtl_files"] = [Path(f).name for f in gold_files]
    # Provenance: which gold frontend + define set actually built the miter
    # (verilog | slang; -DSIMULATION vs -DSYNTHESIS — how synth built the gate).
    report["gold_frontend"] = gold_frontend
    report["gold_defines"] = gold_defines if gold_frontend == "slang" else None
    # WHY that frontend — empty when the built-in reader built the miter on the
    # first pass; otherwise the explicit justification for the slang fallback.
    report["gold_frontend_reason"] = gold_frontend_reason or None
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
    # parse-abort (a parse-abort is a truthful INCONCLUSIVE, not a tool failure).
    return 1 if (parsed["parse_error"]
                 and parsed["verdict"] != "INCONCLUSIVE") else 0


if __name__ == "__main__":
    sys.exit(main())
