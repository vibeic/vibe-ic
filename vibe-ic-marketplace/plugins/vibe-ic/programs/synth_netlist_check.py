#!/usr/bin/env python3
"""
synth_netlist_check.py — Deterministic synthesis netlist validation checker.

Verifies that a synthesized Verilog netlist exists and contains a reasonable
number of cell instances. This catches the common failure where synthesis
either failed silently (producing an empty netlist) or produced a trivially
small design (suggesting major module omissions).

What it catches:
  1. MISSING_NETLIST — the netlist file does not exist
  2. EMPTY_NETLIST — the netlist file is empty or contains no Verilog
  3. TOO_FEW_CELLS — cell instance count is below the minimum threshold
     (WARNING only when the structure-aware floor cannot vouch — see below)
  4. NO_MODULE — no module definition found in the netlist
  5. STALE_NETLIST — the netlist is OLDER than the RTL it is judged against
     (ORGANIC-20260606-synth-netlist-stale-on-regate #426: a close-loop
     re-gate must never be judged against the previous run's ghost netlist)
  6. OUTPUTS_TIED_CONSTANT — every module output is driven only by constants
     (the real pruned-stub signature)

Structure-aware floor (ORGANIC-20260606-min-cells-floor-tiny-designs #427):
a legitimately tiny correct design (an 8-DFF shifter, a 3-cell pulse FSM, a
5-cell edge detector) cannot grow on retry, so a flat min-cells ERROR is
unactionable noise. Resolution order:
  (a) PASS when the netlist's sequential-cell count >= the RTL's declared
      register bit count (needs --rtl; a shift register legitimately
      synthesizes to exactly its DFFs);
  (b) zero cells / outputs tied constant stay hard ERRORs (real stubs);
  (c) otherwise a below-threshold count is a WARNING (disclosed, non-fatal).

Usage:
    python3 synth_netlist_check.py --netlist synth/netlist.v
        [--min-cells 10] [--rtl <rtl.v> ...]

Exit codes:
    0 = valid netlist (warnings allowed)
    1 = missing, empty, stale, stub, or structurally invalid
    2 = parse error / invalid arguments

Generality: works for ANY Verilog gate-level netlist.
No external tool dependencies — pure Python.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _audit_receipt import emit_receipt  # noqa: E402


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    severity: str       # ERROR, WARNING, INFO
    category: str       # MISSING_NETLIST, EMPTY_NETLIST, TOO_FEW_CELLS, NO_MODULE
    message: str
    details: str = ""


# ---------------------------------------------------------------------------
# Verilog keywords — NOT cell instantiations
# ---------------------------------------------------------------------------
VERILOG_KEYWORDS = {
    'module', 'endmodule', 'input', 'output', 'inout', 'wire', 'reg',
    'assign', 'always', 'initial', 'begin', 'end', 'if', 'else',
    'case', 'endcase', 'for', 'while', 'parameter', 'localparam',
    'generate', 'endgenerate', 'function', 'endfunction', 'task',
    'endtask', 'specify', 'endspecify', 'primitive', 'endprimitive',
    'table', 'endtable', 'supply0', 'supply1', 'tri', 'tri0', 'tri1',
    'wand', 'wor', 'trireg', 'integer', 'real', 'time', 'realtime',
    'genvar', 'default', 'posedge', 'negedge', 'or', 'and', 'not',
    'nand', 'nor', 'xor', 'xnor', 'buf', 'bufif0', 'bufif1',
    'notif0', 'notif1',
}

# Pattern: CellType InstanceName ( ... )
# v1.6.194 (#81 P1) — `\w` excludes `$`, so yosys primitive-form
# cells like `$_NAND_ u1 (.A(a), ...)` were silently uncounted.
# v1.6.195 (#82 P0) — `write_verilog -noexpr` emits primitives in
# Verilog escaped-identifier form `\$_NAND_  u1 (...)` because `$`
# is a special char inside identifiers. Accept optional leading
# `\` so the canonical yosys output form counts. Counter buckets
# strip the leading `\` so `\$_NAND_` and `$_NAND_` dedup to the
# same key.
# chip-AGNOSTIC: structural identifier shape, not chip class.
CELL_INST_RE = re.compile(
    # group 1 = cell type (with optional $ or \), group 2 = instance name.
    # v0.1.32 — instance name MUST allow yosys-escaped identifiers
    # `\<chars-until-whitespace>` (e.g. `\u.q_reg[0]`, `\$auto$_NN_`) since
    # those are EVERYWHERE in yosys -noexpr -nostr -noattr output.
    # Without this, DFF-heavy designs (JC_counter / right_shifter) emit
    # `$_DFF_PN0_ \u.q_reg[0] (` and the base `\w+` rejects everything
    # after the `\` because of the `.[]` chars.
    r'^\s*(\\?\$?[A-Za-z_$][\w$]*)\s+(\\\S+|\w+)\s*\(',
    re.MULTILINE,
)
# v0.1.32 — yosys `write_verilog -noexpr -nostr -noattr` emits cell-instance
# lines with /* _NNN_ */ block comments between the type and the instance
# name (e.g. `$_DFF_PN0_ /* _04_ */ s4_reg (`) AND between the instance name
# and the port-list paren (e.g. `\$_NOT_  _03_ /* _05_ */ (`). The base regex
# above rejects both forms. We strip the block comments before matching so
# DFF-heavy designs (JC_counter, right_shifter) are counted correctly.
# chip-AGNOSTIC.
_YOSYS_BLOCK_COMMENT_RE = re.compile(r"/\*[^*]*?\*/")
MODULE_RE = re.compile(r'^\s*module\s+(\w+)', re.MULTILINE)


def count_cell_instances(netlist_text: str) -> Tuple[int, Dict[str, int]]:
    """Count cell instances in a gate-level Verilog netlist.

    Returns (total_count, cell_type_counts).
    """
    cell_counts: Dict[str, int] = {}
    lines = netlist_text.split('\n')
    in_module_header = False

    for line in lines:
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('//'):
            continue

        # Track module header
        if re.match(r'^\s*module\s+', stripped):
            if ');' in stripped:
                in_module_header = False
            else:
                in_module_header = True
            continue
        if in_module_header:
            if ');' in stripped:
                in_module_header = False
            continue

        # Skip non-instantiation lines
        if stripped.startswith(('wire', 'reg', 'assign', 'input', 'output',
                                'inout', 'parameter', 'localparam', '`',
                                'endmodule', '//')):
            continue

        # v0.1.32 — strip yosys `/* _NNN_ */` block comments embedded in
        # cell-instance lines so the regex can match. Without this, DFF-heavy
        # designs emit lines like `$_DFF_PN0_ /* _04_ */ s4_reg (` that the
        # CELL_INST_RE never matches → false TOO_FEW_CELLS / total_cells=0.
        stripped_nc = _YOSYS_BLOCK_COMMENT_RE.sub(" ", stripped).strip()
        m = CELL_INST_RE.match(stripped_nc) or CELL_INST_RE.match(stripped)
        if m:
            cell_type = m.group(1)
            # v1.6.195 (#82 P0) — yosys escaped-identifier `\$_*_`
            # and bare `$_*_` are the same cell type; dedup by
            # stripping any leading backslash before keying.
            canonical = cell_type.lstrip("\\")
            if canonical.lower() not in VERILOG_KEYWORDS:
                cell_counts[canonical] = cell_counts.get(canonical, 0) + 1

    total = sum(cell_counts.values())
    return total, cell_counts


# Sequential-cell fingerprint: yosys `$_DFF_*_` / `$_SDFF*_` / `$_DLATCH*_`
# primitives and PDK flop/latch cell names (…dfxtp…, …sdf…, …latch…).
# chip-AGNOSTIC: structural cell-family vocabulary, not a chip class.
_SEQ_CELL_RE = re.compile(r"(?i)(?:\$_S?DFF|\$_DLATCH|\$_SR|dff|sdf|latch)")

# RTL register declaration: `reg [h:l] name` / `reg name` (also `logic`).
_RTL_REG_DECL_RE = re.compile(
    r"^\s*(?:output\s+)?(?:reg|logic)\s*(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?"
    r"\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)", re.MULTILINE)
_RTL_NB_ASSIGN_RE = re.compile(r"\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*<=")


def rtl_declared_register_bits(rtl_texts: List[str]) -> int:
    """Best-effort total bit count of RTL registers that are actually
    nonblocking-assigned somewhere (a `reg` used purely combinationally
    does not demand a flop). Used by the structure-aware floor (#427)."""
    total = 0
    for text in rtl_texts:
        assigned = set(_RTL_NB_ASSIGN_RE.findall(text))
        for m in _RTL_REG_DECL_RE.finditer(text):
            hi, lo, names = m.group(1), m.group(2), m.group(3)
            width = abs(int(hi) - int(lo)) + 1 if hi is not None else 1
            for nm in (n.strip() for n in names.split(",")):
                if nm in assigned:
                    total += width
    return total


def _outputs_tied_constant(text: str) -> List[str]:
    """Output ports of the FIRST module whose only drivers are constant
    assigns (`assign y = 1'b0;` / `1'hx`) — the real pruned-stub signature.
    Returns the constant-tied output names ONLY when every driven output is
    constant-tied (a partially-constant design is legitimate)."""
    # output declarations appear both as standalone lines AND inside the
    # module header port list (ANSI style) — no line anchor.
    outs = re.findall(r"\boutput\s+(?:reg\s+|wire\s+)?(?:\[[^\]]*\]\s*)?"
                      r"([A-Za-z_]\w*)", text)
    if not outs:
        return []
    const_tied, otherwise_driven = [], []
    for o in outs:
        drivers = re.findall(
            r"^\s*assign\s+" + re.escape(o) + r"\s*(?:\[[^\]]*\])?\s*=\s*([^;]+);",
            text, re.MULTILINE)
        if not drivers:
            otherwise_driven.append(o)   # cell-driven or undriven: not const
            continue
        if all(re.fullmatch(r"\s*\d+'[bhd][0-9a-fxz_]+\s*", d) for d in drivers):
            const_tied.append(o)
        else:
            otherwise_driven.append(o)
    return const_tied if const_tied and not otherwise_driven else []


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
def audit_netlist(
    netlist_path: Path,
    min_cells: int = 10,
    rtl_paths: List[Path] = (),
) -> Tuple[List[Finding], dict]:
    """Check netlist existence, freshness vs RTL, and structural substance.

    Returns (findings, stats).
    """
    findings: List[Finding] = []
    stats = {
        "file_exists": False,
        "file_size_bytes": 0,
        "has_module": False,
        "total_cells": 0,
        "unique_cell_types": 0,
        "cell_type_counts": {},
        "sequential_cells": 0,
        "rtl_register_bits": None,
        "outputs_tied_constant": [],
        "stale_vs_rtl": False,
    }

    # Check file exists
    if not netlist_path.exists():
        findings.append(Finding(
            severity="ERROR",
            category="MISSING_NETLIST",
            message=f"Netlist file not found: {netlist_path}",
        ))
        return findings, stats

    stats["file_exists"] = True
    stats["file_size_bytes"] = netlist_path.stat().st_size

    # Staleness guard (#426): a netlist OLDER than any RTL file it is judged
    # against is the previous run's ghost — a close-loop re-gate must refuse
    # it instead of grading the pre-edit design.
    rtl_files = [p for p in rtl_paths if p.is_file()]
    if rtl_files:
        nl_mtime = netlist_path.stat().st_mtime
        stale_against = [str(p) for p in rtl_files
                         if p.stat().st_mtime > nl_mtime]
        if stale_against:
            stats["stale_vs_rtl"] = True
            findings.append(Finding(
                severity="ERROR",
                category="STALE_NETLIST",
                message=(
                    f"Netlist is OLDER than the RTL it is judged against — "
                    f"re-run synthesis before gating (judging a re-gated "
                    f"design on the prior run's netlist grades ghost data)."),
                details=f"newer RTL: {stale_against}",
            ))
            return findings, stats

    # Read file
    text = netlist_path.read_text(errors='replace')

    # Check for empty
    non_comment_lines = [
        l for l in text.split('\n')
        if l.strip() and not l.strip().startswith('//')
    ]
    if not non_comment_lines:
        findings.append(Finding(
            severity="ERROR",
            category="EMPTY_NETLIST",
            message="Netlist file is empty or contains only comments",
        ))
        return findings, stats

    # Check for module definition
    modules = MODULE_RE.findall(text)
    stats["has_module"] = len(modules) > 0
    if not modules:
        findings.append(Finding(
            severity="ERROR",
            category="NO_MODULE",
            message="No module definition found in netlist",
        ))
        return findings, stats

    # Count cells
    total_cells, cell_counts = count_cell_instances(text)
    stats["total_cells"] = total_cells
    stats["unique_cell_types"] = len(cell_counts)
    stats["cell_type_counts"] = cell_counts

    if total_cells == 0:
        # v1.6.194 (#81 P1) — detect yosys expression-form output.
        # When yosys' write_verilog emits cells as `assign x = ~(...);`
        # / `always @(posedge clk) ...` instead of `$_NAND_` /
        # `$_DFF_*_` cell-instance lines, the netlist passes
        # signature checks (module + body content) but our cell
        # counter sees zero. The structural fingerprint of
        # expression-form output: ≥1 `always` keyword AND ≥1 `assign`
        # AND zero `$_*_` literals. When this pattern hits, point
        # the reviewer at the write_verilog flag rather than just
        # reporting an opaque "no cell instances".
        # chip-AGNOSTIC: purely structural detection of yosys
        # writer-flag-induced expression form.
        _expr_form = (
            re.search(r"^\s*always\b", text, re.MULTILINE) is not None
            and re.search(r"^\s*assign\s+", text,
                          re.MULTILINE) is not None
            and "$_" not in text
        )
        if _expr_form:
            findings.append(Finding(
                severity="ERROR",
                category="EMPTY_NETLIST",
                message=(
                    "Netlist has module + assign/always content but "
                    "ZERO `$_*_` primitive cell instances — yosys "
                    "expression-form output detected. Add `-noexpr` "
                    "to the `write_verilog` invocation so primitives "
                    "are emitted as cell instances (see v1.6.194 / "
                    "#81 P0 — `-nostr` is NOT the right flag; "
                    "`-noexpr` is)."),
            ))
        else:
            findings.append(Finding(
                severity="ERROR",
                category="EMPTY_NETLIST",
                message="Netlist contains a module definition but no cell instances",
            ))
    elif total_cells < min_cells:
        # Structure-aware floor (#427). A retry cannot grow a correct tiny
        # design, so a flat-count ERROR is unactionable; vouch structurally
        # first, hard-fail only on the real stub signatures, and otherwise
        # disclose as a WARNING.
        seq_cells = sum(c for t, c in cell_counts.items()
                        if _SEQ_CELL_RE.search(t))
        stats["sequential_cells"] = seq_cells
        const_outs = _outputs_tied_constant(text)
        stats["outputs_tied_constant"] = const_outs
        rtl_bits = None
        if rtl_files:
            rtl_bits = rtl_declared_register_bits(
                [p.read_text(errors="replace") for p in rtl_files])
            stats["rtl_register_bits"] = rtl_bits
        if const_outs:
            # (b) the real pruned-stub signature: every output constant-tied
            findings.append(Finding(
                severity="ERROR",
                category="OUTPUTS_TIED_CONSTANT",
                message=(
                    f"All module outputs are tied to constants "
                    f"({const_outs}) — synth pruned the design to a stub."),
                details=f"Cell types: {dict(sorted(cell_counts.items()))}",
            ))
        elif rtl_bits is not None and rtl_bits > 0 and seq_cells >= rtl_bits:
            # (a) sequential cells cover the RTL's register bits — a shift
            # register legitimately synthesizes to exactly its DFFs. PASS.
            findings.append(Finding(
                severity="INFO",
                category="TINY_DESIGN_VOUCHED",
                message=(
                    f"{total_cells} cells < min_cells={min_cells}, but "
                    f"sequential cells ({seq_cells}) cover the RTL's "
                    f"declared register bits ({rtl_bits}) — legitimately "
                    f"tiny design, structure-aware floor PASS."),
            ))
        else:
            # (c) cannot vouch structurally: disclose, do not block — the
            # flat count alone is not evidence of a stub (#427).
            findings.append(Finding(
                severity="WARNING",
                category="TOO_FEW_CELLS",
                message=(
                    f"Netlist has {total_cells} cell instance(s), below the "
                    f"advisory floor of {min_cells} — review whether the "
                    f"design is legitimately tiny (pass --rtl to let the "
                    f"structure-aware floor vouch via register-bit cover)."),
                details=f"Cell types: {dict(sorted(cell_counts.items()))}",
            ))

    return findings, stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# STEP 9's OTHER DECLARED ARTEFACT — the AREA / STATS accounting
#
# Step 9 declares TWO outputs:
#
#     phase2/stage2/synth/netlist.v
#     phase2/stage2/synth/area.rpt OR phase2/stage2/synth/stats.json
#
# This program opened only the first. `provenance_check`, the step's other gate
# program, reads `provenance.jsonl`. So the step's own AREA claim — the number
# a reader quotes as "the synthesised design is N cells / X um^2" — was gated by
# nothing at all.
#
# The measurement itself is real: `_yosys_stat.emit_stats_json` parses the
# yosys `stat` block out of the synth log and writes `cells`, `chip_area`,
# the `netlist` it measured and that netlist's `netlist_sha256`. What was never
# checked is that the accounting DESCRIBES THE NETLIST BEING GATED.
#
# WHAT "DESCRIBES THIS NETLIST" IS, AND WHAT IT IS NOT
# ----------------------------------------------------
# The first cut of this gate tested two proxies and both were the wrong
# quantity, in the two opposite directions the campaign keeps producing:
#
#   * MTIME. "stats.json older than netlist.v" is not staleness, it is
#     ORDERING. `design_one_shot_runner.step_yosys_synth` rewrites the netlist
#     at the top of every synth pass and writes stats.json at the bottom, so on
#     the second pass of a converged project the previous pass's stats.json is
#     unavoidably older than the netlist that was just re-emitted from the same
#     RTL — byte-identical content, an honest area number, and an ERROR. Worse,
#     the ERROR returned before stats.json was refreshed, so the project could
#     never recover: measured PASS / FAIL / FAIL over three passes. An mtime
#     ordering says nothing about whether the numbers are true.
#
#   * FILENAME. "stats.json records netlist=netlist.v but I was handed
#     netlist_yosys.v" is not a different design, it is an ALIAS: the runner
#     copies one to the other byte for byte so the canonical name exists for
#     downstream gates. A name comparison calls two identical files different
#     designs, which is the opposite error.
#
# The quantity that actually decides the claim is the netlist's CONTENT. The
# emitter records `netlist_sha256` of the file it measured; this gate hashes
# the file it was handed and compares. Same bytes -> the numbers describe this
# netlist, whatever it is called and whenever it was written. Different bytes
# -> the accounting is for a design that is not the one being gated, which is
# the real lie both proxies were groping at.
#
# The NAME still has one job, and only one: grading a disagreement. A record
# that names THIS path and disagrees with it is a ghost — the file was replaced
# and the accounting was not — and that blocks. A record that names ANOTHER
# file in the same directory is a real measurement of a different netlist, and
# that is reported without blocking, because the flow really does put two
# netlists there (see the branch's own comment). The name never decides
# AGREEMENT: identical bytes are the same design under any filename.
#
# WHY THIS IS NOT SELF-CERTIFICATION
# ----------------------------------
# `step_yosys_synth` now emits stats.json BEFORE it invokes this program (it
# has to: the file must describe the netlist the gate is about to judge), so on
# the runner path this gate does see an artefact its own run produced — and it
# is never allowed to earn credit from that. Nothing here PASSES a step because
# stats.json exists: absence is INFO, an unbindable record is a WARNING, and
# the only rc-1 outcomes are CONTRADICTIONS between two independently written
# facts (the digest the emitter recorded, and the bytes on disk now). The
# emitter also cannot make the comparison true by fiat — when the synth capture
# carries no stat block it writes nothing and removes its own stale artefact,
# so the run drops to the honest MISSING that step 9's `required_outputs`
# reports. On the flow-gate path (`program_exit_zero: synth_netlist_check
# --netlist phase2/stage2/synth/netlist.v ...`) the artefact pre-exists the
# audit outright.
#
# `_yosys_stat`'s anti-fabrication contract ("None means no measurement;
# callers MUST NOT write stats.json in that case") also becomes enforceable
# here: a `cells: 0` record is a zeroed measurement that the contract says
# should never have been written.
#
# ABSENCE IS DISCLOSED, NOT FAILED: the entry is an any-of and step 9's
# `required_outputs` (ALL-of-N across entries) already reports a run that
# produced neither. The gate states the gap instead of double-failing it.
# ---------------------------------------------------------------------------
STATS_JSON_NAME = "stats.json"
AREA_RPT_NAME = "area.rpt"
STEP9_DECLARED_AREA = ("phase2/stage2/synth/area.rpt OR "
                       "phase2/stage2/synth/stats.json")
#: Field `_yosys_stat` / `synth_area_stats_emit` record the measured netlist's
#: digest under. Kept as a literal rather than imported so this gate still runs
#: when it is copied out of the plugin.
NETLIST_DIGEST_FIELD = "netlist_sha256"


def _names_this_netlist(recorded: object, netlist_path: Path) -> bool:
    """Does the record's ``netlist`` field name the file under audit?

    Component-wise SUFFIX match (never a substring one — ``netlist.v`` and
    ``eco_netlist.v`` share a tail), with a same-file fallback for a
    differently-spelled root. Used ONLY to grade a digest disagreement, never
    to decide agreement: two files with the same bytes are the same design
    whatever they are called.
    """
    if not isinstance(recorded, str) or not recorded.strip():
        return False
    rec_parts = [p for p in
                 PurePosixPath(recorded.strip().replace("\\", "/")).parts
                 if p not in (".", "", "/")]
    act_parts = [p for p in PurePosixPath(netlist_path.as_posix()).parts
                 if p not in (".", "", "/")]
    if rec_parts and len(rec_parts) <= len(act_parts) \
            and act_parts[-len(rec_parts):] == rec_parts:
        return True
    try:
        return ((netlist_path.parent / recorded.strip()).resolve()
                == netlist_path.resolve())
    except OSError:
        return False


def _sha256_file(path: Path) -> Optional[str]:
    """``"sha256:<hex>"`` for ``path``, or ``None`` when it cannot be read.

    ``None`` is a failed measurement, not a zero: every caller below states the
    gap rather than comparing against a stand-in value.
    """
    try:
        h = hashlib.sha256()
        with path.open("rb") as fp:
            for chunk in iter(lambda: fp.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return "sha256:" + h.hexdigest()


def _first_present(rec: dict, names: Tuple[str, ...]):
    """``(value, field-name)`` for the first of *names* the record carries.

    Step 9's one declared area artefact has two writers with two payload
    schemas; a reader that knows only one of them silently reports "not
    recorded" for a number that IS recorded. Returns ``(None, None)`` when the
    record carries none of the spellings.
    """
    for name in names:
        if name in rec:
            return rec.get(name), name
    return None, None


def audit_area_stats(netlist_path: Path) -> Tuple[List[Finding], dict]:
    """Cross-check step 9's area/stats artefact against the netlist gated here.

    Both artefacts are looked for beside the netlist, which is where the flow
    declares them and where `_yosys_stat.emit_stats_json` writes them.

    The decision is content-bound: `netlist_sha256` in the record against the
    digest of the file under audit. See the block comment above for why neither
    the artefacts' mtime ordering nor their filenames can stand in for it.
    """
    findings: List[Finding] = []
    synth_dir = netlist_path.parent
    stats_path = synth_dir / STATS_JSON_NAME
    area_path = synth_dir / AREA_RPT_NAME
    actual_digest = _sha256_file(netlist_path)
    info = {
        "declared": STEP9_DECLARED_AREA,
        "stats_json": str(stats_path) if stats_path.is_file() else None,
        "area_rpt": str(area_path) if area_path.is_file() else None,
        "recorded_cells": None,
        "recorded_chip_area": None,
        "recorded_chip_area_unit": None,
        "recorded_netlist": None,
        # The whole verdict, laid out so a reader can redo it by hand.
        "audited_netlist": str(netlist_path),
        "audited_netlist_sha256": actual_digest,
        "recorded_netlist_sha256": None,
        "netlist_binding": "NO_ARTEFACT",
    }
    if not stats_path.is_file() and not area_path.is_file():
        findings.append(Finding(
            severity="INFO",
            category="NO_AREA_ARTEFACT",
            message=(f"neither {STATS_JSON_NAME} nor {AREA_RPT_NAME} is "
                     f"present beside the netlist, so step 9's declared area "
                     f"claim ({STEP9_DECLARED_AREA}) is not cross-checked "
                     f"here; the step's required_outputs is what reports it"),
        ))
        return findings, info

    if stats_path.is_file():
        try:
            rec = json.loads(stats_path.read_text(errors="replace"))
        except (OSError, ValueError) as exc:
            info["netlist_binding"] = "UNREADABLE"
            findings.append(Finding(
                severity="ERROR",
                category="BAD_AREA_ARTEFACT",
                message=(f"{STATS_JSON_NAME} is not readable JSON ({exc}) — "
                         f"step 9's declared area artefact carries no "
                         f"measurement, and unmeasured is not zero"),
            ))
            return findings, info
        if not isinstance(rec, dict):
            info["netlist_binding"] = "UNREADABLE"
            findings.append(Finding(
                severity="ERROR",
                category="BAD_AREA_ARTEFACT",
                message=f"{STATS_JSON_NAME} is not a JSON object",
            ))
            return findings, info

        # BOTH PRODUCERS' SPELLINGS, on purpose. Step 9's ONE declared area
        # artefact has TWO writers and they do not share a payload schema:
        # `_yosys_stat` writes `cells` / `chip_area`, while
        # `synth_area_stats_emit` writes `cell_count` / `chip_area`
        # (programs/synth_area_stats_emit.py:424,428). Reading only the first
        # spelling made this gate blind on exactly the artefacts the second
        # producer writes: a `{"cell_count": 0}` record — a zeroed measurement,
        # the thing ZEROED_AREA_ARTEFACT exists to refuse — returned rc 0 with
        # no findings, and `recorded_cells` was reported as null for a record
        # that does carry a count, which is a MEASURED quantity reported as
        # unmeasured. Neither producer's field is preferred; whichever is
        # present is read, and `recorded_cells_field` says which one was.
        cells, cells_field = _first_present(rec, ("cells", "cell_count"))
        # NEW NAME FIRST, legacy second: an artefact written before the
        # rename still reads, and a fresh one is never matched by the
        # name that asserted a unit it did not carry.
        area, area_field = _first_present(rec, ("chip_area", "chip_area_um2"))
        info["recorded_cells"] = cells
        info["recorded_cells_field"] = cells_field
        info["recorded_chip_area"] = area
        info["recorded_chip_area_unit"] = rec.get("chip_area_unit")
        info["recorded_chip_area_field"] = area_field
        info["recorded_netlist"] = rec.get("netlist")

        if isinstance(cells, int) and not isinstance(cells, bool) and cells <= 0:
            findings.append(Finding(
                severity="ERROR",
                category="ZEROED_AREA_ARTEFACT",
                message=(
                    f"{STATS_JSON_NAME} records {cells_field}={cells}. "
                    f"`_yosys_stat.emit_stats_json` returns None rather than "
                    f"writing the file when the synth log carries no stat "
                    f"block, so a zeroed record is a measurement that should "
                    f"never have been written — step 9 would report an area "
                    f"claim for an unmeasured synthesis"),
            ))

        recorded_digest = rec.get(NETLIST_DIGEST_FIELD)
        info["recorded_netlist_sha256"] = (
            recorded_digest if isinstance(recorded_digest, str) else None)
        if not isinstance(recorded_digest, str) or not recorded_digest.strip():
            # Say the gap out loud rather than pass on silence. An artefact
            # written before the binding existed (or by a third-party emitter)
            # genuinely cannot be tied to this netlist — but a run that simply
            # does not carry the field is not thereby proven wrong, so this
            # discloses and does not block.
            info["netlist_binding"] = "UNBOUND"
            findings.append(Finding(
                severity="WARNING",
                category="AREA_ARTEFACT_UNBOUND",
                message=(
                    f"{STATS_JSON_NAME} carries no {NETLIST_DIGEST_FIELD}, so "
                    f"nothing ties step 9's area claim to the netlist under "
                    f"audit ({netlist_path.name}); the record names "
                    f"netlist={rec.get('netlist')!r}, and a NAME cannot tell "
                    f"this run's netlist from the previous run's at the same "
                    f"path. Re-run synthesis to have the emitter bind them"),
            ))
        elif actual_digest is None:
            info["netlist_binding"] = "NETLIST_UNREADABLE"
            findings.append(Finding(
                severity="WARNING",
                category="AREA_ARTEFACT_UNBOUND",
                message=(f"{netlist_path.name} could not be hashed, so the "
                         f"{NETLIST_DIGEST_FIELD} recorded in "
                         f"{STATS_JSON_NAME} could not be checked — "
                         f"unmeasured, not agreed"),
            ))
        elif recorded_digest.strip() == actual_digest:
            info["netlist_binding"] = "MATCH"
        elif _names_this_netlist(rec.get("netlist"), netlist_path):
            # SAME PATH, DIFFERENT BYTES. The record claims to account for this
            # very file and does not. Nothing legitimate produces that: the
            # emitters write the digest of the file they measured, so a
            # disagreement means the netlist was replaced after the accounting
            # was written and the accounting was not refreshed. This is the
            # ghost artefact, and it blocks.
            info["netlist_binding"] = "MISMATCH"
            findings.append(Finding(
                severity="ERROR",
                category="AREA_ARTEFACT_WRONG_NETLIST",
                message=(
                    f"{STATS_JSON_NAME} says it was measured on "
                    f"{rec.get('netlist')!r}, which IS the netlist under "
                    f"audit ({netlist_path}), but the contents no longer "
                    f"agree: the record was measured on "
                    f"{recorded_digest.strip()} and the file now hashes to "
                    f"{actual_digest} — step 9's area claim is a previous "
                    f"synthesis's number attached to this netlist"),
                details=(f"recorded {recorded_digest.strip()} != actual "
                         f"{actual_digest}"),
            ))
        else:
            # DIFFERENT PATH, DIFFERENT BYTES. The artefact accounts for
            # another netlist that lives in the same directory. Reported, not
            # blocked — and the reason is measured, not assumed: the synthesis
            # directory legitimately holds more than one netlist, and the two
            # producers of this ONE declared artefact do not agree on which of
            # them it describes. `design_one_shot_runner.step_yosys_synth`
            # writes it for `netlist.v`; `phase3_one_shot_runner.step_synth`
            # writes `<top>_synth.v` into the same directory and its emitter
            # overwrites the same stats.json for THAT file, while the
            # canonical `netlist.v` alias is only created when absent — so on
            # a phase2-then-phase3 run the accounting is genuinely about the
            # other netlist. Failing that would redden step 9 on every full
            # run; passing it in silence would let a reader quote an area
            # number for a design that is not the one being gated. Naming both
            # files is the honest tier, and picking which synthesis step 9
            # should account for is a flow decision this gate must not make on
            # its own.
            info["netlist_binding"] = "DESCRIBES_ANOTHER_NETLIST"
            findings.append(Finding(
                severity="WARNING",
                category="AREA_ARTEFACT_DESCRIBES_ANOTHER_NETLIST",
                message=(
                    f"{STATS_JSON_NAME} accounts for "
                    f"{rec.get('netlist')!r} ({recorded_digest.strip()}), "
                    f"not for the netlist under audit ({netlist_path}, "
                    f"{actual_digest}) — step 9's area claim is a real "
                    f"measurement of a DIFFERENT file in this directory, so "
                    f"quoting it as this netlist's area would be wrong"),
                details=(f"recorded {recorded_digest.strip()} != actual "
                         f"{actual_digest}"),
            ))
    elif area_path.is_file():
        # `area.rpt` is the free-text alternative the step allows. It carries
        # no machine-readable binding to any netlist, so the only thing that
        # can be decided about it here is whether it carries a measurement at
        # all; the missing binding is disclosed rather than assumed away.
        info["netlist_binding"] = "UNBOUND"
        findings.append(Finding(
            severity="WARNING",
            category="AREA_ARTEFACT_UNBOUND",
            message=(f"{AREA_RPT_NAME} is a free-text report with no "
                     f"{NETLIST_DIGEST_FIELD}, so step 9's area claim cannot "
                     f"be tied to the netlist under audit "
                     f"({netlist_path.name}) by this gate"),
        ))
        try:
            if not area_path.read_text(errors="replace").strip():
                findings.append(Finding(
                    severity="ERROR",
                    category="BAD_AREA_ARTEFACT",
                    message=(f"{AREA_RPT_NAME} is empty — step 9's declared "
                             f"area artefact carries no measurement"),
                ))
        except OSError as exc:
            findings.append(Finding(
                severity="ERROR",
                category="BAD_AREA_ARTEFACT",
                message=f"{AREA_RPT_NAME} unreadable: {exc}",
            ))
    return findings, info


# ---------------------------------------------------------------------------
# THE CELL CENSUS MUST REACH THE VERDICT (63x8 artefact finding, step 9 / dim 2)
#
# THE DEFECT. This program counts every cell instance in the netlist and
# ENUMERATES them by type in `stats.cell_type_counts`. It then forms no opinion
# about any of it. MEASURED on the published run named by the ledger entry
# ART-NETLIST-PRIMITIVE-SWAP, substituting `$_AND_` for `$_NAND_` at all 221
# instantiation sites — 221 gates whose output is inverted with respect to what
# synthesis produced, a netlist that no longer implements the RTL:
#
#     synth_netlist_check --netlist phase2/stage2/synth/netlist.v --json ...
#         -> rc=0   total_cells 449 before and after,
#            and `$_AND_: 221` PRINTED IN THE GATE'S OWN REPORT
#
# The gate listed the substituted primitive and passed. A report that states a
# fact and passes anyway is not a weaker check than one that does not state it;
# it is the same check with better documentation, and it reads to a reviewer as
# though the fact was considered.
#
# WHAT DECIDES IT — THE TOOL'S OWN OUTPUT. `design_one_shot_runner.
# step_yosys_synth` writes the synthesiser's output to `netlist_yosys.v` and
# COPIES it to the canonical `netlist.v` that every downstream gate reads. So
# the tool's own artefact is on disk beside the one under audit, and the census
# of the audited file is a checkable claim about it rather than a number with
# no second opinion anywhere. A cell census that disagrees with the census of
# the file the tool actually wrote is one of two things, and both block: the
# audited netlist was edited after synthesis, or it is a previous pass's ghost.
#
# WHY THE ALIAS AND NOT THE SYNTH LOG — MEASURED, NOT PREFERRED. The obvious
# second authority is the yosys `stat` block, and it is NOT used here, because
# one synthesis invocation writes SEVERAL netlists and logs a stat block for
# each. Measured on that same run, the LAST stat block in the two logs beside
# this netlist describes two different files:
#
#     yosys.log  -> 449 cells  {$_DFF_P_ 65, $_NAND_ 221, $_NOR_ 128, $_NOT_ 35}
#     synth.log  -> 287 cells  (the technology-mapped census of `spm_synth.v`)
#
# Only the first describes `netlist.v`. A rule of the shape "compare against the
# last stat block in the log beside the netlist" would raise a CONTRADICTION on
# a run where nothing whatever is wrong — a ruler change reported as a defect,
# which is the failure this campaign is least entitled to commit. Nothing here
# reads a log; if a log-sourced authority is ever added it needs its own way to
# say WHICH netlist a block describes, and that is not this change.
#
# ABSENCE IS DISCLOSED, NEVER FAILED. A netlist with no tool-emitted sibling is
# reported as uncorroborated with the count of sources that were found (zero),
# and the verdict is formed exactly as before. That follows the house rule
# `gate_zero_denominator_refuses_check` states in its own words — refusing on a
# zero denominator is a separate, individually measured change, and a blanket
# one was tried in this repo and reverted after it flipped 182 of 182 run dirs.
# ---------------------------------------------------------------------------
#: The name `design_one_shot_runner` writes the SYNTHESISER'S OWN output under,
#: before copying it to the canonical `netlist.v`. A literal, because it is a
#: fixed part of the flow's own artefact contract and pinned by its own test —
#: not a chip, PDK, or process token.
TOOL_EMITTED_NETLIST_NAME = "netlist_yosys.v"


def tool_emitted_netlist(netlist_path: Path) -> Optional[Path]:
    """The synthesiser's own output file beside ``netlist_path``, or ``None``.

    ``None`` when it is absent, unreadable, or IS the file under audit — a gate
    pointed straight at the tool's output has no independent second copy to
    corroborate against, and pretending otherwise would compare a file with
    itself and call the agreement evidence.
    """
    candidate = netlist_path.parent / TOOL_EMITTED_NETLIST_NAME
    if not candidate.is_file():
        return None
    try:
        if candidate.resolve() == netlist_path.resolve():
            return None
    except OSError:                       # pragma: no cover - defensive
        return None
    return candidate


def audit_cell_census(netlist_path: Path, cell_counts: Dict[str, int],
                      total_cells: int) -> Tuple[List[Finding], dict]:
    """``(findings, info)`` for the census cross-check against the tool's output.

    The comparison is over the CELL CENSUS, not over bytes. Two files that
    instantiate the same cells in the same numbers are the same design however
    they are formatted, and a byte comparison would block on a re-write that
    changed nothing — the same wrong quantity `audit_area_stats` documents
    rejecting for mtime and filename.
    """
    findings: List[Finding] = []
    info: dict = {
        "corroborating_sources": 0,
        "source": None,
        "audited_total_cells": total_cells,
        "tool_total_cells": None,
        "status": "",
    }

    source = tool_emitted_netlist(netlist_path)
    if source is None:
        info["status"] = "NO_TOOL_EMITTED_NETLIST"
        findings.append(Finding(
            severity="INFO",
            category="CELL_CENSUS_UNCORROBORATED",
            message=(
                f"the cell census was read from the netlist under audit and "
                f"corroborated against 0 independent source(s): no "
                f"{TOOL_EMITTED_NETLIST_NAME} beside it. The counts below are "
                f"this file's own word about itself."),
            details=f"searched: {netlist_path.parent / TOOL_EMITTED_NETLIST_NAME}",
        ))
        return findings, info

    try:
        tool_text = source.read_text(errors="replace")
    except OSError as exc:
        info["status"] = "TOOL_NETLIST_UNREADABLE"
        findings.append(Finding(
            severity="WARNING",
            category="CELL_CENSUS_UNCORROBORATED",
            message=(
                f"{source.name} is present but could not be read "
                f"({type(exc).__name__}), so the census is uncorroborated. NOT "
                f"read is not agreement."),
        ))
        return findings, info

    tool_total, tool_counts = count_cell_instances(tool_text)
    info.update({"corroborating_sources": 1, "source": str(source),
                 "tool_total_cells": tool_total})

    audited = dict(cell_counts)
    types = sorted(set(audited) | set(tool_counts))
    differing = {t: {"audited": audited.get(t, 0), "tool": tool_counts.get(t, 0)}
                 for t in types if audited.get(t, 0) != tool_counts.get(t, 0)}
    info["cell_types_differing"] = differing

    if not differing and tool_total == total_cells:
        info["status"] = "AGREE"
        return findings, info

    info["status"] = "CONTRADICTS"
    findings.append(Finding(
        severity="ERROR",
        category="CELL_CENSUS_CONTRADICTS_TOOL",
        message=(
            f"the audited netlist instantiates a different set of cells from "
            f"the one the synthesiser itself wrote beside it "
            f"({source.name}): {total_cells} cell(s) here against "
            f"{tool_total} there. A netlist that disagrees with the tool's own "
            f"output was either edited after synthesis or is a previous pass's "
            f"ghost, and neither is the design this step certifies."),
        details=f"per-type disagreement (audited vs tool): {differing}",
    ))
    return findings, info


def build_report(findings: List[Finding], stats: dict,
                 netlist_path: str, min_cells: int) -> dict:
    n_err = sum(1 for f in findings if f.severity == "ERROR")
    return {
        "program": "synth_netlist_check",
        "version": "1.1.0",
        "netlist": netlist_path,
        "min_cells": min_cells,
        "summary": {
            "file_exists": stats["file_exists"],
            "total_cells": stats["total_cells"],
            "unique_cell_types": stats["unique_cell_types"],
            # A PASS states how much it looked at. `total_cells` is the
            # netlist's own word about itself; this is how many INDEPENDENT
            # sources that word was checked against, so a reader can tell an
            # uncorroborated census from a corroborated one without opening
            # `stats`.
            "cell_census_corroborating_sources":
                stats.get("cell_census", {}).get("corroborating_sources", 0),
            "cell_census_status":
                stats.get("cell_census", {}).get("status", ""),
            "findings_count": len(findings),
            "error_count": n_err,
            # since v1.1.0 (#427): WARNING/INFO findings no longer fail the gate —
            # pass = no ERROR (TOO_FEW_CELLS alone is advisory now).
            "pass": n_err == 0,
        },
        "stats": stats,
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify synthesis netlist exists and has reasonable cell count"
    )
    parser.add_argument('--netlist', required=True,
                        help="Path to synthesized Verilog netlist")
    parser.add_argument('--min-cells', type=int, default=10,
                        help="Advisory cell-count floor (default: 10)")
    parser.add_argument('--rtl', nargs='*', default=[],
                        help="RTL source files the netlist is judged against "
                             "(enables the staleness guard #426 and the "
                             "register-bit structure-aware floor #427)")
    parser.add_argument('--json', default=None,
                        help="Output JSON report path")
    args = parser.parse_args(argv)

    netlist_path = Path(args.netlist)
    findings, stats = audit_netlist(netlist_path, args.min_cells,
                                    [Path(p) for p in args.rtl])

    # Step 9's OTHER declared artefact. Only meaningful once the netlist is
    # readable — the area accounting is a claim ABOUT the netlist, so an
    # absent netlist is already the finding.
    if stats.get("file_exists"):
        area_findings, area_info = audit_area_stats(netlist_path)
        findings.extend(area_findings)
        stats["area_stats"] = area_info

    # The census this program already enumerated, put to the tool that produced
    # it. Gated on `has_module` rather than `file_exists`: the earlier returns
    # for an empty / module-less netlist leave `cell_type_counts` empty, and
    # comparing an empty census against a real one would relabel an existing
    # EMPTY_NETLIST error as a contradiction.
    if stats.get("has_module"):
        census_findings, census_info = audit_cell_census(
            netlist_path, stats.get("cell_type_counts", {}),
            stats.get("total_cells", 0))
        findings.extend(census_findings)
        stats["cell_census"] = census_info

    report = build_report(findings, stats, str(netlist_path), args.min_cells)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)
        # #2050 — producer-written receipt (see programs/_audit_receipt.py).
        # The subject is the netlist AND every RTL file it was judged against,
        # so a receipt taken before an RTL edit does not read as backing for
        # the netlist after it. `examined` counts the cells the verdict is
        # about; an unreadable netlist is a FAIL over 0 cells, and the
        # compliance checker reports that as FAIL, not as an empty audit.
        emit_receipt(
            'synth_netlist_check', args.json,
            'PASS' if report["summary"]["pass"] else 'FAIL',
            int(stats.get("total_cells") or 0),
            [netlist_path] + [Path(x) for x in args.rtl],
            extra={'unique_cell_types': stats.get("unique_cell_types"),
                   'min_cells': args.min_cells})

    print(report_json)
    return 0 if report["summary"]["pass"] else 1


if __name__ == '__main__':
    sys.exit(main())
