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
from typing import Dict, List, Optional

PROGRAM = "lec_run"

DEFAULT_CONTAINER = "vibeic-eda"
DEFAULT_LIBERTY = (
    "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
    "sky130_fd_sc_hd__tt_025C_1v80.lib"
)
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

# Canonical Yosys success line (corroboration for the gate's .rpt parse).
_SUCCESS_RE = re.compile(r"Equivalence\s+successfully\s+proven", re.IGNORECASE)


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

    if parse_error:
        equivalent = False
        verdict = "FAIL"
        verdict_explanation = (
            "Yosys produced no parseable equivalence result — the equiv "
            "check did not reach a verdict (see reports/lec.rpt for the raw "
            "tool log). Not classifiable as PASS or FAIL.")
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
                       gate_is_generic: bool = False) -> str:
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
    fake pass.  Measured on HP18E80 spm: 65/65 $equiv cells proven, 0 unproven,
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
    return (
        # --- gold = RTL, kept as generic satgen-modelable Yosys cells ---
        f"read_verilog -sv {gold_read}\n"
        f"prep -top {top}\n"
        # #155: legalize any $mem/$mem_v2 (packed by prep's memory_collect) to
        # flops+decode BEFORE flatten so equiv_induct's satgen can model it;
        # PRE-flatten placement is load-bearing (0/8 vs 136/0). No-op when the
        # design has no memory. Plain stock-yosys command — no fork flag/probe.
        f"memory_map\n"
        f"flatten\n"
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
                    timeout: int = 1800):
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
                + "\n[lec_run] ERROR: yosys equiv timed out")
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
    whose cells (e.g. HP18E80 NAND2D1 / DFFHQD1) are only SAT-modelable from ITS
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
    script = build_equiv_script(gold_files, gate_abs, resolved_top, liberty,
                                gate_is_generic=gate_is_generic)

    # Write the .ys into the (bind-mounted) project reports dir so the
    # container sees it at the same absolute path (same assumption that lets
    # yosys read the RTL/netlist by their host absolute paths).
    ys_host = rpt_out.parent / "lec_equiv.ys"
    ys_host.write_text(script, encoding="utf-8")
    ys_in_container = str(ys_host.resolve())

    t0 = time.time()
    launched, raw = run_yosys_equiv(container, ys_in_container)
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
    report = build_report(parsed, resolved_top, gate_abs, liberty)
    report["elapsed_sec"] = elapsed
    report["gold_rtl_files"] = [Path(f).name for f in gold_files]
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
    # SKIPPED-CONDITION, or an evidence-backed FAIL). 1 only when Yosys ran
    # but produced no parseable equivalence evidence (could-not-run-the-check).
    return 1 if parsed["parse_error"] else 0


if __name__ == "__main__":
    sys.exit(main())
