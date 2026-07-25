#!/usr/bin/env python3
"""lec_gate_netlist_select.py — ATPG-cut-netlist predicate + safe gate selector.

When the OSS Fault ATPG path runs, fault_atpg_run.py intentionally byte-copies
the combinational CUT netlist over the scan netlist so that downstream
`post_dft_opt` gets the correct combinational view for timing optimisation.
The cut netlist DELETES every flip-flop and replaces it with a pair of
top-level pseudo-ports: `_NNN_` (the flop's Q, a primary input) and
`\\_NNN_.d` (the flop's D, a primary output).

When design_one_shot_runner selects `post_dft_netlist.v` as the LEC gate,
it therefore presents a netlist with ZERO flip-flops and dozens of `<inst>.d`
pseudo-ports that are absent from the 5-port RTL.  yosys `equiv_make` aborts:

    ERROR: Can't match gate port `_508_.d_gate' to a gold port.

and the run produces compared_points == 0 with no equivalence verdict.
lec_equivalence_check.py then misclassifies this structural abort as
LEC_NOT_EQUIVALENT — a FALSE diagnosis that sends the next agent to fix the
design when the design is fine.

This module provides:

  is_atpg_cut_artifact(netlist_path, ref_ports) -> bool
      Structural predicate — True iff the candidate netlist looks like an
      ATPG cut artifact.  Chip-AGNOSTIC: keys on observable structural
      properties (FF count == 0 while ref has FFs, or extra ports with the
      `<inst>.d` naming pattern), never on a filename, module name, or PDK
      cell literal.

  select_gate_netlist(project, top_name, ref_ports, ref_ff_count) -> (path, reason)
      Picks the best non-cut gate netlist available for LEC, falling back
      from post_dft_netlist.v → <top>_synth.v → netlist.v.  Returns the
      chosen Path and a human-readable reason string recorded in the report.

  classify_port_abort(log_text, compared_points) -> str | None
      Given an LEC log and a compared_points count, returns an accurate
      verdict string when a structural port-match abort is detected.  Returns
      None when the run looks normal (no action needed).  The caller uses this
      to avoid reporting a tool abort as LEC_NOT_EQUIVALENT.

  CANONICAL_STATUS  = "LEC_GATE_NETLIST_UNUSABLE"
  CANONICAL_VERDICT = "INCONCLUSIVE-STRUCTURAL"

FAIL-CLOSED contract
--------------------
Every path that cannot confirm the design is equivalent still emits a
non-PASS verdict.  The predicate only REJECTS a candidate; it never PASSES
a design.  Genuine LEC_NOT_EQUIVALENT findings on a valid netlist are
preserved.

PURE: no subprocess, no Docker, no network.  Filesystem reads only.
Chip-AGNOSTIC: no design, module, or PDK literal is hard-coded.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Exported status / verdict tokens (used by callers and the test suite)
# ---------------------------------------------------------------------------
CANONICAL_STATUS = "LEC_GATE_NETLIST_UNUSABLE"
CANONICAL_VERDICT = "INCONCLUSIVE-STRUCTURAL"

# ---------------------------------------------------------------------------
# Verilog port-list parser — STRUCTURAL only (no elaboration needed)
# ---------------------------------------------------------------------------

# Match the module header line to extract the raw port list string.
#   module <name> ( <ports> );
_MODULE_HDR_RE = re.compile(
    r"\bmodule\s+\w+\s*\(([^)]*)\)\s*;", re.DOTALL)

# Match individual port declarations (directions + optional vector + name).
# Handles both ANSI style (dir inside port list) and non-ANSI (separate decl).
_PORT_DECL_RE = re.compile(
    r"\b(input|output|inout)\s+(?:wire\s+)?(?:\[\s*\d+\s*:\s*\d+\s*\]\s+)?(\\\S+|\w+)",
    re.IGNORECASE)

# Match `wire <name>;` or `reg <name>;` declarations that are also ports
# (non-ANSI style — the port name is re-declared as a net).
_WIRE_DECL_RE = re.compile(
    r"^\s*(?:input|output|inout)\s+(?:wire\s+)?(?:\[\s*\d+\s*:\s*\d+\s*\]\s+)?(\\\S+|\w+)\s*;",
    re.MULTILINE | re.IGNORECASE)

# ATPG cut pseudo-port pattern: `\_NNN_.d` (escaped Verilog identifier whose
# base name ends in `.d`).  The instance pseudo-port is the DATA INPUT that
# replaces the deleted flop's D pin.  chip-AGNOSTIC: keys only on the `.d`
# suffix inside an escaped identifier — that suffix is Fault's canonical
# naming convention for ALL designs.
_CUT_PORT_RE = re.compile(r"\\(\S+)\.d\b")

# Sequential-cell patterns — chip-AGNOSTIC.  We recognise:
#   * Yosys generic primitives: $_DFF_P_, $_DFF_N_, $_DFFE_*, $_SDFF_*, $_ALDFF_*
#   * Generic RTL: $dff, $adff, $sdff
#   * Liberty-mapped DFF/DFX cells:
#     - sky130:  dfxtp, dfxbp, dfrtp, dfstp, dfbbp, sdfxtp, sedfxtp, …
#     - generic: dff*, dfb*, dlatch*
#     Any identifier segment that starts with `df` or `dff` or `sdff` or
#     `dlatch` — we match the SEGMENT inside the cell name after splitting on
#     non-alphanumeric characters, so `sky130_fd_sc_hd__dfxtp_1` matches
#     because its segment `dfxtp` starts with `df`.
# We deliberately stay broad rather than enumerating specific PDK families:
# a miss in one direction only means we DON'T flag a cut artifact (fail-safe),
# and the pseudo-port check is a second, independent signal.
_FF_CELL_RE = re.compile(
    r"(?:"
    r"\$_[DS]?[A-Z]*DFF[A-Z_]*_"       # Yosys generic: $_DFF_P_, $_DFFE_PP0P_, etc.
    r"|\$(?:s?a?d?dff|aldff)\b"         # Yosys RTL: $dff, $sdff, $adff, $aldff
    r"|(?<![A-Za-z])(?:"               # not preceded by a letter (segment boundary)
    r"s?e?d?ff[A-Za-z0-9]*"            # dff, sdff, edff, sdfx, dfxtp, dfbbn …
    r"|df[bfxrstpaln][A-Za-z0-9]*"     # dfx*, dfr*, dfs*, dfb*, dfp* (sky130 dfxtp)
    r"|dlatch[A-Za-z0-9]*"             # dlatch, dlatchp, dlatchn …
    r")"
    r")",
    re.IGNORECASE)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_safe(path: Path) -> str:
    """Read a Verilog file, stripping // and /* */ comments to avoid false
    matches inside comment strings."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    # Strip block comments
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    # Strip line comments
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def _extract_ports(text: str) -> Set[str]:
    """Return the set of top-level port names from a Verilog module source."""
    # Try ANSI module header first (most synthesised netlists use ANSI style).
    m = _MODULE_HDR_RE.search(text)
    ports: Set[str] = set()
    if m:
        hdr = m.group(1)
        for dm in _PORT_DECL_RE.finditer(hdr):
            ports.add(dm.group(2).lstrip("\\"))
    # Also collect non-ANSI port declarations in the module body.
    for dm in _WIRE_DECL_RE.finditer(text):
        ports.add(dm.group(1).lstrip("\\"))
    # Fallback: bare names in the module header port list (no direction).
    if not ports and m:
        hdr = m.group(1)
        for tok in re.split(r"[\s,]+", hdr):
            tok = tok.strip().lstrip("\\")
            if re.match(r"^[A-Za-z_$][\w$]*$", tok):
                ports.add(tok)
    return ports


def _count_ff_cells(text: str) -> int:
    """Count the number of sequential-cell instantiation lines in Verilog."""
    count = 0
    for line in text.splitlines():
        # Skip port/wire declarations; look for cell instance lines.
        # A cell instantiation looks like:   sky130_fd_sc_hd__dfxtp_1 _123_ (
        # or: $_DFF_P_ _123_ (
        # We count lines that contain a FF-pattern token AND an opening `(`.
        if "(" in line and _FF_CELL_RE.search(line):
            count += 1
    return count


def _count_cut_pseudo_ports(text: str) -> int:
    """Count `<inst>.d` pseudo-ports exposed as top-level ports."""
    return len(_CUT_PORT_RE.findall(text))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_atpg_cut_artifact(
    netlist_path: Path,
    ref_ports: Optional[Set[str]] = None,
    ref_ff_count: Optional[int] = None,
) -> Tuple[bool, str]:
    """Structural predicate: True iff *netlist_path* is an ATPG-cut artifact.

    Decision rule (two independent signals — either is sufficient):

      Signal A — pseudo-port pattern:
        The candidate has top-level ports whose names match `<inst>.d`
        (Fault's cut pseudo-port convention).  This is a direct structural
        fingerprint of a cut netlist and is independent of the reference.

      Signal B — FF-count drop with reference context:
        If `ref_ff_count` is provided AND > 0, and the candidate has 0
        sequential cells, the candidate is flagged.  This catches cut
        netlists that happen not to use the `.d` suffix (non-standard ATPG
        tool) or where the pattern match missed some cells.

    Returns (is_cut, reason_string).  PURE, chip-AGNOSTIC.
    """
    text = _read_safe(netlist_path)
    if not text:
        return False, ""

    cut_ports = _count_cut_pseudo_ports(text)
    if cut_ports > 0:
        return (
            True,
            f"ATPG-cut artifact: {cut_ports} '<inst>.d' pseudo-port(s) in "
            f"top-level port list (Fault cut-DFF replacement convention); "
            f"every flip-flop has been deleted and replaced by pseudo-ports — "
            f"equiv_make cannot match these against RTL ports.",
        )

    if ref_ff_count is not None and ref_ff_count > 0:
        cand_ff = _count_ff_cells(text)
        if cand_ff == 0:
            # Also check ref_ports mismatch as corroboration.
            cand_ports = _extract_ports(text)
            extra: Set[str] = set()
            if ref_ports:
                extra = cand_ports - ref_ports
            return (
                True,
                f"ATPG-cut artifact: 0 sequential cells while reference has "
                f"{ref_ff_count} flip-flop(s); "
                + (f"candidate exposes {len(extra)} extra port(s) absent from "
                   f"RTL ({sorted(extra)[:5]}{'...' if len(extra) > 5 else ''}). "
                   if extra else "")
                + "The candidate is a combinational-cut view, not a synthesis netlist.",
            )

    return False, ""


def select_gate_netlist(
    project: Path,
    top_name: str,
    ref_ports: Optional[Set[str]] = None,
    ref_ff_count: Optional[int] = None,
) -> Tuple[Optional[Path], str]:
    """Choose the best non-cut gate netlist available for LEC.

    Preference order:
      1. phase2/stage2/synth/post_dft_netlist.v  — if NOT a cut artifact
      2. phase2/stage2/synth/<top>_synth.v       — Liberty-backed, always preferred
      3. phase2/stage2/synth/netlist.v            — generic yosys netlist

    Returns (chosen_path, reason).  *reason* explains WHY a candidate was
    rejected and which fallback was chosen — this is written into the LEC
    report so a future reader knows exactly what happened.

    If ALL candidates are cut artifacts or missing, returns (None, reason).
    """
    synth_dir = project / "phase2" / "stage2" / "synth"
    candidates = [
        synth_dir / "post_dft_netlist.v",
        synth_dir / f"{top_name}_synth.v",
        synth_dir / "netlist.v",
    ]

    rejected: List[str] = []
    for cand in candidates:
        if not cand.is_file():
            continue
        is_cut, cut_reason = is_atpg_cut_artifact(cand, ref_ports, ref_ff_count)
        if is_cut:
            rejected.append(
                f"Rejected {cand.name}: {cut_reason}"
            )
            continue
        # Accepted.
        reason_parts = []
        if rejected:
            reason_parts.append(
                "ATPG-cut netlist(s) rejected: "
                + "; ".join(rejected)
            )
        reason_parts.append(
            f"Selected {cand.name} as LEC gate netlist"
            + (" (first non-cut candidate)" if rejected else "")
        )
        return cand, ".  ".join(reason_parts)

    # All candidates rejected or absent.
    reason = (
        "No usable gate netlist found for LEC.  "
        + "  ".join(rejected)
        if rejected
        else "No gate netlist candidates exist under phase2/stage2/synth/."
    )
    return None, reason


# ---------------------------------------------------------------------------
# Port-abort classifier
# ---------------------------------------------------------------------------

# yosys equiv_make error when a gate port has no matching gold port.
# chip-AGNOSTIC: keys on the yosys error wording, never on a specific port name.
_EQUIV_MAKE_PORT_ABORT_RE = re.compile(
    r"Can'?t\s+match\s+gate\s+port\s+`[^']+'\s+to\s+a\s+gold\s+port",
    re.IGNORECASE)


def classify_port_abort(
    log_text: str,
    compared_points: int,
) -> Optional[str]:
    """Return CANONICAL_VERDICT when a structural port-match abort is detected.

    A structural port-match abort (equiv_make cannot match gate ports to gold
    ports) leaves compared_points == 0 because no miter was ever built.  This
    is NOT a semantic non-equivalence — it is a structural tool abort caused by
    selecting the wrong input netlist.  It must NOT be reported as
    LEC_NOT_EQUIVALENT.

    Returns CANONICAL_VERDICT ("INCONCLUSIVE-STRUCTURAL") when:
      * compared_points == 0  AND
      * the log contains the yosys equiv_make port-match abort error.

    Returns None otherwise (normal run — caller decides the verdict).

    FAIL-CLOSED: we only reclassify when both conditions hold simultaneously.
    A run with compared_points > 0 or without the abort signature is left
    alone; a genuine mismatch (non_equivalent_points > 0) will still fail at
    the substance gate.
    """
    if compared_points != 0:
        return None
    if _EQUIV_MAKE_PORT_ABORT_RE.search(log_text or ""):
        return CANONICAL_VERDICT
    return None
