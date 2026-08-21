#!/usr/bin/env python3
"""
fault_scan_chain_insert.py — REAL scan-chain insertion via `fault chain`.

Produces the IMPLEMENTATION netlist that carries the scan chain:

  <project>/phase2/stage2/dft/scan_netlist.v        (scan-inserted netlist)
  <project>/reports/phase2/dft/scan_chain.json      (MEASURED chain metadata)

WHY THIS PROGRAM EXISTS
-----------------------
Before it, `scan_netlist.v` was a BYTE COPY of `cut_netlist.v` — Fault's ATPG
*cut* view, in which every flip-flop has been replaced by a `<inst>.d`
pseudo-PI/PO pair.  That is a combinational transform for fault simulation; it
is not a netlist anyone can build.  Two things followed from it:

  * step 12 `opt_clean`ed the cut view into `post_dft_netlist.v`, so the
    artefact the flow calls "the post-DFT netlist" had ZERO flip-flops, and
    step 13 (`RTL == post-DFT netlist`) could not compare anything — a cut
    netlist is combinationally unequal to its RTL BY CONSTRUCTION;
  * place-and-route read `<top>_synth.v`, the PRE-DFT netlist, so the routed,
    tape-out-bound design carried NO SCAN CHAIN at all while ATPG reported
    stuck-at coverage on a netlist that never becomes silicon.

Standard ASIC practice is scan insertion BEFORE place-and-route: the routed
design carries the chain and the tape-out is production-testable, and the ATPG
cut view is DERIVED from the scan netlist rather than substituted for it.

WHAT IS MEASURED, NEVER ASSERTED
--------------------------------
`fault chain` prints its own chain counts, AND embeds a machine-readable
`/* FAULT METADATA: {...} */` header in the output netlist naming every chain
element in order.  This program reads BOTH and cross-checks them against the
flop count it counts in the INPUT netlist.  `chain_length_matches_flop_count`
is a MEASUREMENT — the run is not called good because the tool exited 0.

Exit 0 = a scan netlist was produced AND the chain covers every input flop.
Exit 1 = `fault chain` ran but the result does not measure clean (the JSON
         says exactly which check failed; no artefact is silently accepted).
Exit 2 = usage / IO / Docker error, or no Liberty resolvable for this PDK.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import _path_layout as _pl
import fault_atpg_run as _fatpg
import floorplan_contract as _fpc
import pdk_cell_models as _pcm  # ciel version-hash live resolution (gf180)


# ---------------------------------------------------------------------------
# Liberty resolution — `fault chain` REQUIRES --liberty (unlike `fault cut`)
# ---------------------------------------------------------------------------
# Container-absolute typical-corner Liberty per PDK, keyed by the SAME PDK ids
# `fault_atpg_run.PDK_CONFIG` uses, so a design can never resolve its cell
# MODEL from one library and its Liberty from another (the exact two-table
# defect ORGANIC #410 removed for the cell model).  A PDK absent from this
# table resolves nothing and the run REFUSES — it never substitutes another
# foundry's Liberty.
SCAN_LIBERTY = {
    "sky130": ("/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/"
               "sky130_fd_sc_hd__tt_025C_1v80.lib"),
    "gf180": ("/foss/pdks/ciel/gf180mcu/versions/"
              "8f2d1529c86235d726979eb9ecb7e9628108590b"
              "/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/"
              "gf180mcu_fd_sc_mcu7t5v0__tt_025C_1v80.lib"),
    "ihp-sg13g2": ("/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lib/"
                   "sg13g2_stdcell_typ_1p20V_25C.lib"),
    # NanGate45 / FreePDK45 (OpenROAD reference PDK). The container ships the
    # typical-corner Liberty; `fault chain` needs exactly this to stitch the
    # scan chain. Keyed by the same `nangate45` id fault_atpg_run.PDK_CONFIG now
    # uses, so cell-MODEL and Liberty can never resolve from different libraries
    # (the two-table invariant ORGANIC #410 established). See the PDK_CONFIG
    # note there: this makes scan insertion RUN on a mapped NanGate45 netlist
    # that was previously refused as pdk 'unmapped'.
    "nangate45": ("/foss/pdks/nangate45/libs.ref/NangateOpenCellLibrary/lib/"
                  "NangateOpenCellLibrary_typical.lib"),
}

# `fault chain`'s DFT port option names.  These are OPTION NAMES we pass, so
# the resulting port names are KNOWN, never sniffed out of the netlist.  The
# value is what functional mode drives them to (`sout` is an OUTPUT and is
# left dangling — it has no RTL counterpart).
FUNCTIONAL_MODE_TIEOFF = {"sin": 0, "shift": 0, "test": 0, "tck": 0}
SCAN_OUT_PORT = "sout"
DFT_PORTS = (*FUNCTIONAL_MODE_TIEOFF, SCAN_OUT_PORT)

SCAN_NETLIST_REL = "phase2/stage2/dft/scan_netlist.v"
SCAN_JSON_REL = "reports/phase2/dft/scan_chain.json"


# ---------------------------------------------------------------------------
# PURE parsers / measurers — unit-tested directly, no Docker, no filesystem
# ---------------------------------------------------------------------------

# `fault chain` stdout, verbatim shape:
#   Internal scan chain successfully constructed. Length: 64
#   Boundary scan cells successfully chained. Length:  34
#   Total scan-chain length:  98
_INTERNAL_RE = re.compile(r"Internal scan chain[^\n]*?Length:\s*(\d+)", re.I)
_BOUNDARY_RE = re.compile(r"Boundary scan cells[^\n]*?Length:\s*(\d+)", re.I)
_TOTAL_RE = re.compile(r"Total scan-chain length:\s*(\d+)", re.I)

_FAULT_META_RE = re.compile(
    r"/\*\s*FAULT METADATA:\s*'(?P<json>.*?)'\s*END FAULT METADATA\s*\*/",
    re.S)


def parse_chain_log(text: str) -> dict:
    """Chain counts scraped from `fault chain`'s OWN stdout.  PURE.

    Missing keys stay None — an absent count is never defaulted to 0, because
    0 is a meaningful (and disastrous) chain length and must not be
    manufacturable by a parse miss.
    """
    def _one(rx):
        m = rx.search(text or "")
        return int(m.group(1)) if m else None
    return {"internal": _one(_INTERNAL_RE),
            "boundary": _one(_BOUNDARY_RE),
            "total": _one(_TOTAL_RE)}


def parse_chain_metadata(netlist_text: str) -> dict | None:
    """The `/* FAULT METADATA: {...} END FAULT METADATA */` block `fault chain`
    embeds in its own output.  Returns the decoded dict, or None when absent or
    unparseable.  PURE.

    This is the ARTEFACT's own account of the chain — independent of the
    stdout scrape, which is why both are recorded and cross-checked.
    """
    m = _FAULT_META_RE.search(netlist_text or "")
    if not m:
        return None
    try:
        return json.loads(m.group("json"))
    except (ValueError, TypeError):
        return None


def chain_order_counts(meta: dict | None) -> dict:
    """Per-`kind` tally of the metadata's ordered chain element list.  PURE."""
    if not isinstance(meta, dict):
        return {}
    order = meta.get("order")
    if not isinstance(order, list):
        return {}
    return dict(Counter(str(e.get("kind")) for e in order
                        if isinstance(e, dict)))


def count_flops(netlist_text: str) -> int:
    """Flip-flop INSTANCE count in a technology-mapped netlist.  PURE.

    Reuses `fault_atpg_run`'s flop-instantiation regex and its
    already-PDK-agnostic flop-cell detector, so this program and the ATPG
    producer can never disagree about what a flop is.
    """
    cells = _fatpg.detect_dff_cells(netlist_text or "")
    wanted = {c.strip() for c in cells.split(",") if c.strip()}
    if not wanted:
        return 0
    n = 0
    for line in (netlist_text or "").splitlines():
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_$]*)\s+\\?\S+\s*\(", line)
        if m and m.group(1) in wanted:
            n += 1
    return n


# `fault chain` re-synthesises after inserting the chain and, in doing so,
# wraps the original module in an instance of its own.  Every internal wire
# therefore comes out renamed `\<instance>.<original name>`.  That prefix is
# what breaks yosys `equiv_make`'s BY-NAME gold/gate matching in step 13, so
# LEC has to reproduce it on the gold side.  It is MEASURED here, from the
# artefact, and recorded — never hard-coded into the LEC script.
def measure_internal_prefix(netlist_text: str,
                            dominance: int = 4) -> str | None:
    """The dotted prefix `fault chain` put on every internal wire name, or None.

    Returns the leading segment of escaped identifiers of the form
    `\\<seg>.<rest>` ONLY when one segment dominates the next-most-common by
    at least `dominance`x.  A netlist with no clear single wrapper instance
    yields None and the caller must then NOT claim a prefix — a wrong prefix
    would silently lower the number of compared LEC points rather than error.
    PURE.
    """
    ids = re.findall(r"\\([^\s;,()\[\]]+)", netlist_text or "")
    segs = Counter(i.split(".")[0] for i in ids if "." in i)
    if not segs:
        return None
    ranked = segs.most_common(2)
    top, top_n = ranked[0]
    if len(ranked) > 1 and top_n < ranked[1][1] * dominance:
        return None
    return top


def assess(chain_log: dict, meta: dict | None, input_flops: int) -> dict:
    """Turn the three independent measurements into a verdict.  PURE.

    The ONE thing this must never do is call a run good because the tool
    exited 0.  `ok` is True only when a chain length was actually measured and
    it accounts for every flop in the input netlist.
    """
    meta_internal = (meta or {}).get("internalCount")
    meta_boundary = (meta or {}).get("boundaryCount")
    log_internal = chain_log.get("internal")
    # Prefer the artefact's own metadata; fall back to the stdout scrape.
    internal = meta_internal if isinstance(meta_internal, int) else log_internal
    boundary = meta_boundary if isinstance(meta_boundary, int) else \
        chain_log.get("boundary")

    problems: list[str] = []
    if internal is None:
        problems.append(
            "no internal scan-chain length could be measured — neither the "
            "`fault chain` stdout count line nor the output netlist's FAULT "
            "METADATA header yielded one")
    if (isinstance(meta_internal, int) and isinstance(log_internal, int)
            and meta_internal != log_internal):
        problems.append(
            f"chain length disagrees between the tool's stdout "
            f"({log_internal}) and the netlist's own FAULT METADATA "
            f"({meta_internal})")
    if isinstance(internal, int):
        if input_flops <= 0:
            problems.append(
                "no flip-flops were counted in the INPUT netlist, so the "
                "chain length cannot be validated against anything")
        elif internal != input_flops:
            problems.append(
                f"scan chain covers {internal} flop(s) but the input netlist "
                f"instantiates {input_flops} — {input_flops - internal} "
                f"flip-flop(s) are NOT on the chain and are untestable")
    return {
        "internal_chain_length": internal,
        "boundary_chain_length": boundary,
        "input_flop_count": input_flops,
        "chain_length_matches_flop_count": (
            isinstance(internal, int) and input_flops > 0
            and internal == input_flops),
        "chain_log_counts": chain_log,
        "metadata_counts": {"internalCount": meta_internal,
                            "boundaryCount": meta_boundary},
        "metadata_order_kinds": chain_order_counts(meta),
        "problems": problems,
        "ok": not problems,
    }


def cell_histogram(netlist_text: str) -> dict:
    """`{cell_name: instance_count}` for a mapped netlist.  PURE.

    Used to record the AREA COST of scan insertion as an instance-count delta,
    so a reader can see what the chain actually costs without re-running
    anything.
    """
    hist: Counter = Counter()
    for line in (netlist_text or "").splitlines():
        m = re.match(r"\s*([A-Za-z][A-Za-z0-9_$]*__?[A-Za-z0-9_$]+)\s+\\?\S+\s*\(",
                     line)
        if m:
            hist[m.group(1)] += 1
    return dict(hist)


def resolve_liberty(pdk: str, override: str | None) -> tuple[str | None, str]:
    """(container-absolute Liberty path, provenance note).  PURE.

    An explicit `--liberty` always wins.  Otherwise the PDK id indexes
    SCAN_LIBERTY.  An unknown PDK resolves NOTHING — see the table comment.
    """
    if override:
        return override, "explicit --liberty"
    lib = SCAN_LIBERTY.get(pdk)
    if lib:
        return lib, f"SCAN_LIBERTY[{pdk!r}]"
    return None, (f"no Liberty configured for pdk {pdk!r} "
                  f"(known: {sorted(SCAN_LIBERTY)}) — pass --liberty")


# The project's OWN staged Liberty dir. A design on a PDK not in SCAN_LIBERTY
# (a foundry PDK the container does not ship, sniffed to 'unmapped') stages its
# corner libraries here — the SAME dir the pre-layout STA and pvt_matrix steps
# already read. Using it is NOT the cross-foundry substitution the SCAN_LIBERTY
# comment forbids: it is the design's own PDK, mounted under /work, so the chain
# is built from the very cells the netlist is mapped to.
_STAGED_LIBERTY_DIR = "input/pdk/liberty"
# Typical (TT) process-corner designators — the corner SCAN_LIBERTY itself pins
# for every built-in PDK (all its entries are `__tt_`/`_typ_`). Matched with the
# same general convention used elsewhere; no PDK / vendor cell is hard-coded.
_TYP_CORNER_RE = re.compile(
    r"(?:^|[_/\-.\s:,=])(tt|typical|typ|nom)(?:[_/\-.\s:,=]|$)", re.IGNORECASE)


def staged_own_liberty(project: Path) -> tuple[str | None, str]:
    """(container /work Liberty path, note) for the project's OWN staged corner
    libraries, or (None, note). PURE w.r.t. the project input.

    Picks the TYPICAL corner when the file names disclose one; if exactly one
    library is staged it is used unambiguously. Two-or-more staged with NO
    identifiable typical corner is AMBIGUOUS and REFUSES (None) rather than
    guess a corner — the same refuse-don't-guess stance as `resolve_liberty`.
    """
    lib_dir = project / _STAGED_LIBERTY_DIR
    if not lib_dir.is_dir():
        return None, f"no {_STAGED_LIBERTY_DIR}/ staged"
    libs = sorted(lib_dir.glob("*.lib"))
    if not libs:
        return None, f"no *.lib in {_STAGED_LIBERTY_DIR}/"
    typ = [p for p in libs if _TYP_CORNER_RE.search(p.name)]
    if len(typ) == 1:
        chosen = typ[0]
    elif len(libs) == 1:
        chosen = libs[0]
    else:
        return None, (
            f"{len(libs)} staged libraries and no single TYPICAL corner "
            f"identifiable by name ({[p.name for p in libs]}) — refusing to "
            f"guess a corner")
    return (f"/work/{_STAGED_LIBERTY_DIR}/{chosen.name}",
            f"project-staged {_STAGED_LIBERTY_DIR}/{chosen.name} (own PDK)")


# ---------------------------------------------------------------------------
# `inout` port handling — `fault chain` cannot parse a bidirectional port
# ---------------------------------------------------------------------------
# The pure netlist port helpers (find_inout_ports / port_is_connected /
# port_list_successor / strip_inout_ports / restore_inout_ports) live in
# `_dft_netlist_ports.py`, shared with `fault_atpg_run.py`'s ATPG cut — both
# fault entry points abort on an inout port.  Re-exported here so this module's
# callers and its tests keep referring to them unqualified.
from _dft_netlist_ports import (  # noqa: E402,F401
    find_inout_ports, port_is_connected, port_list_successor,
    strip_inout_ports, restore_inout_ports)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def decide_skip_boundary(project: Path, mode: str,
                         top_module: str | None) -> tuple[bool, dict]:
    """Resolve the `--skip-boundary` decision.  PURE w.r.t. the project input.

    `mode` is one of "auto" (default), "on", "off":
      * "on"  — always skip the boundary register (explicit override);
      * "off" — never skip it (explicit override, restores legacy default);
      * "auto" — DETERMINISTIC selection: skip iff the design is a fixed-pinout
        wrapper (see floorplan_contract.is_fixed_pinout_wrapper), because its
        ports are a parent interface, not chip pads.  No agent chooses this.

    Returns (skip: bool, evidence: dict).  The evidence records the mode and,
    in auto mode, the fixed-pinout contract that drove the decision — so a
    reader can audit WHY the boundary register was or was not inserted.
    """
    if mode == "on":
        return True, {"mode": "on",
                      "reason": "explicit --skip-boundary=on override"}
    if mode == "off":
        return False, {"mode": "off",
                       "reason": "explicit --skip-boundary=off override "
                                 "(legacy default: boundary scan inserted)"}
    # auto
    try:
        is_fixed, ev = _fpc.is_fixed_pinout_wrapper(project, top_module)
    except Exception as exc:                                   # noqa: BLE001
        # A detection failure must NEVER silently drop the boundary register —
        # fall back to the legacy default (insert it) and say why.
        return False, {"mode": "auto", "detection_error": str(exc),
                       "reason": "fixed-pinout detection failed → legacy "
                                 "default (boundary scan inserted)"}
    ev = dict(ev)
    ev["mode"] = "auto"
    return is_fixed, ev


# `--skip-boundary` was added to the `fault` fork after image 0.2.52 (present in
# 0.2.54+; MEASURED: `fault chain --help` on 0.2.52 does NOT list it, on 0.2.54
# does — same 0.9.4 binary string, rebuilt between tags). The boundary decision
# in `decide_skip_boundary` is PURE w.r.t. the project and image-INDEPENDENT, so
# on a fixed-pinout wrapper `auto` decides skip=True regardless of image. If that
# runs against an older `fault` the binary REJECTS the flag: MEASURED
#   `Error: Unknown option '--skip-boundary'` -> RC=64, no netlist produced.
# Without this classifier the failure surfaces as the generic "produced no scan
# netlist" and the wrapper that MOST needs skip-boundary silently loses its scan
# chain, the real cause (image too old) buried in log_tail with no remedy. This
# is chip-AGNOSTIC — it keys on the TOOL's own error string, not on any design.
_SKIP_BOUNDARY_UNSUPPORTED_RE = re.compile(
    r"(?:unknown|unrecognized|unexpected|invalid)\s+option[^\n]*--skip-boundary",
    re.IGNORECASE)


def skip_boundary_unsupported_in_log(log: str) -> bool:
    """True iff `fault chain`'s output shows it rejected `--skip-boundary` as an
    unsupported option.  PURE — a string check on the tool's own error,
    unit-testable without Docker.

    This detects the SYMPTOM only.  It does NOT establish the cause: the same
    error is produced both by a build that genuinely predates the flag and by a
    step that ran a DIFFERENT IMAGE than the run declared (measured: a run
    pinned to and verifying 0.2.58 executed this step in stock
    `hpretl/iic-osic-tools:latest`).  The caller names the image it used and
    lists both causes; do not re-collapse them to one here."""
    return bool(_SKIP_BOUNDARY_UNSUPPORTED_RE.search(log or ""))


# `fault chain` builds the scan wrapper's module HEADER from the design's own
# port list plus the scan pins (sin/sout/shift/tck/test), but declares the
# chain's reset in the BODY under the fixed name `rst`. When the design's reset
# is called anything else — `rst_ni`, `resetn`, `rst_n`, … — `rst` is declared
# and never listed, so fault's own yosys re-synthesis rejects the netlist it
# just wrote and NOTHING is published.
#
# MEASURED (vibe-ic, opentitan_aes x sky130A, image ghcr.io/vibeic/vibeic-eda:
# 0.2.54): `fault chain` reported "Internal scan chain successfully
# constructed. Length: 66 / Boundary scan cells ... 105 / Total ... 171" and
# then died with
#   chained.v.chain-intermediate.v:10209: ERROR: Module port `\rst' is not
#   declared in module header.
# The chain was BUILT and thrown away. Before this classifier the report said
# only "`fault chain` produced no scan netlist" + a log tail, so the next blind
# run could not tell this from a genuine no-flops design.
_MISSING_HEADER_PORT_RE = re.compile(
    r"Module port `\\?([^']+?)'\s+is not declared in module header", re.I)


def chain_resynth_missing_header_ports(log: str) -> list:
    """Port names `fault chain`'s own re-synthesis rejected as body-declared
    but absent from the wrapper's module header, in first-seen order.

    PURE — a string check on the tool's own error, unit-testable without
    Docker. Empty list means this failure mode is not present."""
    seen: list = []
    for m in _MISSING_HEADER_PORT_RE.finditer(log or ""):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


# The SECOND way `fault chain` builds a chain and then throws it away.
#
# fault's internal yosys re-synthesis must bind every module the netlist
# instantiates. A hard macro supplied to the flow as LEF + Liberty only — an
# ordinary design input, and what every SRAM/OTP/PHY IP ships — has no Verilog
# model in that yosys invocation, so `hierarchy -check` aborts. The chain is
# already built when this happens.
#
# Before this classifier the report carried only
#     "`fault chain` produced no scan netlist"
# which is TRUE and ADJACENT: it names the missing artefact, not the reason,
# and is byte-indistinguishable from a design that legitimately has no
# flip-flops to chain. Downstream, `cut_netlist.v` is then absent and the DT1 /
# DT2 transition- and path-delay steps record "NEVER RAN — precondition unmet",
# so the whole DFT tail reads as a capability that was never exercised rather
# than as one input the tool was never given.
#
# MEASURED (a design whose OTP macro is staged as LEF + Liberty with no Verilog
# model, ghcr.io/vibeic/vibeic-eda:0.2.65) — the tool's own lines:
#     Internal scan chain successfully constructed. Length: 271
#     Boundary scan cells successfully chained. Length:  3
#     Total scan-chain length:  274
#     Resynthesizing with yosys…
#     ERROR: Module `\<MACRO>' referenced in module `\<top>.original' in cell
#            `\<inst>' is not part of the design.
#     A yosys error has occurred.
#
# chip-AGNOSTIC: a pure string check on yosys' own error text. No vendor, SKU,
# process node or part number participates.
_UNRESOLVED_MODULE_RE = re.compile(
    r"Module\s+`\\?([^']+?)'\s+referenced\s+in\s+module\s+`\\?[^']*?'"
    r"\s+in\s+cell\s+`\\?[^']*?'\s+is\s+not\s+part\s+of\s+the\s+design",
    re.I)

#: `fault chain` prints this only after it has actually constructed a chain.
#: It is what licenses the "BUILT then discarded" claim — without it this
#: program would be asserting a build it never saw evidence of.
_CHAIN_TOTAL_LEN_RE = re.compile(
    r"Total\s+scan-chain\s+length:\s*(\d+)", re.I)


def chain_resynth_unresolved_modules(log: str) -> list:
    """Module names `fault chain`'s own re-synthesis could not bind, in
    first-seen order.

    These are modules the netlist INSTANTIATES but for which that yosys
    invocation was handed no model — typically a hard macro supplied as
    LEF/Liberty only. PURE — a string check on the tool's own error,
    unit-testable without Docker. Empty list means this failure mode is not
    present."""
    seen: list = []
    for m in _UNRESOLVED_MODULE_RE.finditer(log or ""):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def chain_reported_total_length(log: str):
    """The total scan-chain length `fault chain` reported CONSTRUCTING, or
    None when it never said it built one.

    Guards the `chain_built_then_discarded` claim: a report that asserts a
    chain was built and discarded, on a log that never showed a chain being
    built, would be this program inventing the very kind of adjacent fact the
    classifier exists to remove. PURE."""
    last = None
    for last in _CHAIN_TOTAL_LEN_RE.finditer(log or ""):
        pass
    return int(last.group(1)) if last else None


def run_chain(project: Path, netlist_rel: str, clock: str,
              pdk: str, reset: str | None = None,
              reset_active_low: bool = False,
              liberty_override: str | None = None,
              dff_cells_override: str | None = None,
              pdk_dir: Path | None = None,
              skip_boundary: str = "auto",
              top_module: str | None = None,
              timeout: int = 900) -> tuple[int, dict]:
    """Insert a real scan chain.  Returns (exit_code, report_dict).

    Never raises for a tool failure: every outcome comes back as a report the
    caller can write verbatim, so an absent artefact is never silence.

    `skip_boundary` ("auto"|"on"|"off", see decide_skip_boundary) governs
    whether `fault chain` inserts a top-level boundary-scan register.  In the
    default "auto" mode a fixed-pinout wrapper (FP_DEF_TEMPLATE) DETERMINISTIC-
    ally selects `--skip-boundary`; every other design keeps the legacy
    default.  The internal scan chain is inserted either way.
    """
    # Same resolver the ATPG producer uses — `fault chain` needs a
    # library-mapped netlist for exactly the reason `fault cut` does, so the
    # two must never pick different files.
    netlist_rel, switch_note = _fatpg.resolve_mapped_netlist(project,
                                                             netlist_rel)
    src = project / netlist_rel
    if not src.is_file():
        return 2, {"stage": "input", "error": f"netlist not found: {netlist_rel}"}
    netlist_text = src.read_text(encoding="utf-8", errors="replace")

    if _fatpg.is_generic_unmapped(netlist_text):
        return 2, {
            "stage": "input",
            "netlist": netlist_rel,
            "error": "netlist is a technology-GENERIC yosys netlist "
                     "($_DFF_/$_NAND_ …).  `fault chain` needs Liberty cell "
                     "names to build the chain; scan insertion must run after "
                     "technology mapping.",
        }

    pdk_cfg = _fatpg.PDK_CONFIG.get(pdk)
    if pdk_cfg is None:
        sniffed = _fatpg.sniff_pdk_from_netlist(netlist_text)
        if sniffed:
            pdk, pdk_cfg = sniffed, _fatpg.PDK_CONFIG[sniffed]

    liberty, lib_note = resolve_liberty(pdk, liberty_override)
    if liberty and pdk == "gf180" and not liberty_override:
        # Same staleness as fault_atpg_run's cell-model resolution — ciel's
        # gf180mcu path is content-addressed and SCAN_LIBERTY's hash is a
        # point-in-time fallback. Re-resolve live before trusting it.
        liberty = _pcm.materialize_gf180_paths(
            [liberty],
            lambda argv, t: _fatpg._run_docker(project, argv, timeout=t,
                                               pdk_dir=pdk_dir))[0]
    if not liberty:
        # PDK not in SCAN_LIBERTY and no explicit --liberty: fall back to the
        # design's OWN staged corner libraries. A foundry PDK the container does
        # not ship sniffs to 'unmapped', and the runner forwards no --liberty
        # for it — yet the design stages its libraries under input/pdk/liberty/
        # (the same dir STA/pvt already read). Without this, scan insertion is
        # unreachable for every non-built-in PDK that stages its own libs, which
        # then leaves step 11 MISSING and VOIDS the whole DFT-dependent tail.
        staged, staged_note = staged_own_liberty(project)
        if staged:
            liberty, lib_note = staged, staged_note
    if not liberty:
        return 2, {"stage": "liberty", "netlist": netlist_rel, "pdk": pdk,
                   "error": lib_note}

    # Flop cells: explicit override, else auto-detect from THIS netlist unioned
    # with the PDK seed — identical policy to `fault cut`, one implementation.
    if dff_cells_override:
        dff_cells = dff_cells_override
    else:
        detected = _fatpg.detect_dff_cells(netlist_text)
        seed = pdk_cfg.get("dff_cells") if pdk_cfg else None
        dff_cells = _fatpg.merge_dff_cells(seed, detected) or (seed or "DFF")

    dft_dir = _pl.dft_dir(project)
    dft_dir.mkdir(parents=True, exist_ok=True)
    # `fault chain` drops `<out>+attrs` and `<out>.chain-intermediate.v`
    # alongside its output.  Keep them out of the canonical dft dir by writing
    # into a scratch subdir, then publish only the netlist itself.
    work_rel = "phase2/stage2/dft/scan_chain_work"
    (project / work_rel).mkdir(parents=True, exist_ok=True)
    out_rel = f"{work_rel}/chained.v"

    # `fault chain` aborts on any `inout` port (see find_inout_ports).  Strip
    # UNCONNECTED inout ports from the netlist fault reads; connected ones stay
    # (and are reported).  The stripped ports are restored into fault's output.
    inout_ports = find_inout_ports(netlist_text)
    stripped_inout: dict = {}
    stripped_successors: dict = {}
    connected_inout: list = []
    fault_input_rel = netlist_rel
    for _name, _decl in inout_ports.items():
        if port_is_connected(netlist_text, _name):
            connected_inout.append(_name)
        else:
            stripped_inout[_name] = _decl
            stripped_successors[_name] = port_list_successor(netlist_text, _name)
    if stripped_inout:
        stripped_text = strip_inout_ports(netlist_text, list(stripped_inout))
        # Redirect ONLY if every targeted port actually left the netlist —
        # otherwise leave fault to fail honestly on the original.
        if not (set(find_inout_ports(stripped_text)) & set(stripped_inout)):
            fault_input_rel = f"{work_rel}/fault_input.v"
            (project / fault_input_rel).write_text(stripped_text,
                                                   encoding="utf-8")
        else:
            stripped_inout.clear()

    # Boundary-scan decision — DETERMINISTIC in the default "auto" mode: a
    # fixed-pinout wrapper (FP_DEF_TEMPLATE) gets `--skip-boundary`.  Recorded
    # in the report so the choice is auditable, never a silent flag.
    skip_boundary_flag, skip_boundary_evidence = decide_skip_boundary(
        project, skip_boundary, top_module)

    cmd = ["fault", "chain",
           "--liberty", liberty,
           "--clock", clock,
           "--dff", dff_cells,
           "-o", f"/work/{out_rel}"]
    if skip_boundary_flag:
        cmd.append("--skip-boundary")
    if reset:
        cmd += ["--reset", reset]
        if reset_active_low:
            cmd += ["--reset-active-low"]
    cmd.append(f"/work/{fault_input_rel}")

    ec, out, err = _fatpg._run_docker(project, cmd, timeout=timeout,
                                      pdk_dir=pdk_dir)
    log = (out + "\n" + err)
    produced = project / out_rel
    if ec != 0 or not produced.is_file():
        err_report = {"stage": "chain", "exit": ec, "netlist": netlist_rel,
                      "pdk": pdk, "liberty": liberty, "dff_cells": dff_cells,
                      "skip_boundary": skip_boundary_flag,
                      "skip_boundary_mode": skip_boundary,
                      "skip_boundary_evidence": skip_boundary_evidence,
                      "log_tail": log[-1500:],
                      "error": "`fault chain` produced no scan netlist"}
        if skip_boundary_flag and skip_boundary_unsupported_in_log(log):
            # DEGRADE LOUDLY, never silently: the deterministic decision was to
            # skip the boundary register (correct for a fixed-pinout wrapper),
            # but THIS build of `fault` predates `--skip-boundary` and rejected
            # it. Say the cause and BOTH remedies, so the next blind run's
            # failure is self-explaining instead of a generic "no scan netlist".
            err_report["skip_boundary_unsupported_by_binary"] = True
            # NAME THE IMAGE THAT ACTUALLY RAN. The previous wording asserted a
            # cause it never measured — "this build of the `fault` binary
            # predates the flag" — and the first thing a reader does with that
            # is check their image and find it is new enough. MEASURED on
            # caravel_user_project x sky130A (v1.9.65): the run was pinned to,
            # and reports/container_image.json VERIFIED,
            # the vibeic-eda fork at tag 0.2.58 (spelled without the registry
            # prefix on purpose: this is a HISTORICAL MEASUREMENT, not a live
            # image pointer for `sync_image_version.py` to keep in step), whose
            # `fault chain --help` DOES
            # list `--skip-boundary` — while this step resolved its own image
            # independently and ran stock hpretl/iic-osic-tools:latest, which
            # does not. "Your image is too old" was false; "a different image
            # ran than the one you pinned" was true. A diagnostic that names the
            # wrong cause costs more than one that names none, so this states
            # the image identity as the FIRST fact and offers the version
            # explanation only as one of the possibilities.
            err_report["image_used"] = _fatpg.DOCKER_IMAGE
            err_report["error"] = (
                f"`fault chain` rejected `--skip-boundary`. The image this step "
                f"ran in was {_fatpg.DOCKER_IMAGE!r} — verify it with "
                f"`docker run --rm --entrypoint bash {_fatpg.DOCKER_IMAGE} -lc "
                f"'fault chain --help' | grep skip-boundary` before concluding "
                f"anything about the binary's age. TWO distinct causes produce "
                f"this exact error: (1) the image is a build that predates the "
                f"flag (added to the fork after 0.2.52; MEASURED absent on "
                f"0.2.52, present on 0.2.54+); or (2) THIS STEP RAN A DIFFERENT "
                f"IMAGE THAN THE RUN DECLARED — it resolves an image of its own "
                f"by local-tag presence and falls back to the upstream "
                f"distribution, which ships stock tools without this project's "
                f"forks, so a run pinned to a new-enough image can still land "
                f"here. Compare the value above against "
                f"reports/container_image.json:image_ref. The fixed-pinout "
                f"wrapper's correct DFT is internal-scan-only, which needs "
                f"`--skip-boundary`. Remedies: (a) make this step use the run's "
                f"image — set VIBEIC_fatpg.DOCKER_IMAGE to it (the one-shot runner now "
                f"exports this automatically from the verified container); "
                f"(b) run in an image whose `fault chain --help` lists the flag "
                f"(>=0.2.54); or (c) set VIBEIC_DFT_SKIP_BOUNDARY=off to accept "
                f"legacy boundary-scan insertion — but on a fixed-pinout wrapper "
                f"that re-introduces the SS-corner setup violation (#604) and a "
                f"large area blow-up.")
            return 1, err_report
        _missing_hdr = chain_resynth_missing_header_ports(log)
        if _missing_hdr:
            # DEGRADE LOUDLY: the chain was CONSTRUCTED and then discarded by
            # fault's own re-synthesis. Say so, name the port, and name the
            # remedy — otherwise this is indistinguishable from a design that
            # legitimately has no scan chain to build.
            err_report["chain_resynth_missing_header_ports"] = _missing_hdr
            err_report["chain_built_then_discarded"] = True
            err_report["error"] = (
                f"`fault chain` BUILT the scan chain and then rejected its own "
                f"intermediate netlist: port(s) {_missing_hdr} are declared in "
                f"the wrapper's body but absent from its module header, so the "
                f"re-synthesis fault runs internally fails and nothing is "
                f"published. This is an upstream `fault chain` wrapper defect, "
                f"not a property of this design: fault names the chain reset "
                f"`rst` in the body while the header carries the design's own "
                f"reset name, so EVERY design whose reset is not literally "
                f"`rst` (rst_ni, rst_n, resetn, reset, …) hits it. The chain "
                f"itself is sound — see the constructed/boundary/total lengths "
                f"in log_tail. Remedies: (a) run in an image whose `fault "
                f"chain` emits the port in the header; or (b) re-drive the "
                f"design with its reset port named `rst`. VERIFIED on "
                f"opentitan_aes x sky130A: adding the missing name to the "
                f"header makes the identical intermediate elaborate under "
                f"`yosys hierarchy -check` with rc=0.")
            return 1, err_report
        _unresolved = chain_resynth_unresolved_modules(log)
        if _unresolved:
            # DEGRADE LOUDLY, exactly as the header-port branch above does.
            # The generic "produced no scan netlist" is true and useless here:
            # it describes the absent artefact, not the one missing input that
            # caused it, and it reads the same as a design with no flops.
            err_report["chain_resynth_unresolved_modules"] = _unresolved
            _total_len = chain_reported_total_length(log)
            if _total_len is not None:
                # Only claim BUILT-then-discarded when the tool itself said it
                # built one. Otherwise name the unresolved module and stop.
                err_report["chain_built_then_discarded"] = True
                err_report["chain_reported_total_length"] = _total_len
            err_report["error"] = (
                f"`fault chain`'s own yosys re-synthesis could not bind "
                f"module(s) {_unresolved}: the netlist INSTANTIATES them but "
                f"that yosys invocation was handed no model for them, so "
                f"`hierarchy -check` aborts and nothing is published"
                + (f" — AFTER the chain was successfully constructed "
                   f"(total scan-chain length {_total_len}; see log_tail). "
                   if _total_len is not None else ". ")
                + f"This is a MISSING INPUT, not a property of this design "
                f"and not an engine crash: a hard macro staged as LEF + "
                f"Liberty only (SRAM / OTP / PHY IP normally is) has no "
                f"Verilog view for `fault chain` to elaborate. Consequence if "
                f"unread: `cut_netlist.v` is never written, so the DT1 "
                f"transition-fault and DT2 path-delay steps both record "
                f"'NEVER RAN — precondition unmet' and the DFT tail looks "
                f"like an unexercised capability rather than one absent "
                f"input. Remedies: (a) give the re-synthesis a blackbox stub "
                f"for the macro built from its Liberty/LEF port list — the "
                f"flow already emits exactly this for the back end as "
                f"reports/phase3/physical_cell_stubs.v, and phase 3 already "
                f"discovers the macro library set via _discover_local_macros "
                f"over input/pdk_local/; or (b) stage a synthesizable "
                f"(blackbox-annotated) Verilog view of the macro alongside "
                f"its LEF/Liberty. NOTE `fault chain --help` declares "
                f"'-l, --liberty <liberty>  Liberty file. (Required.)' — "
                f"singular and NOT repeatable, so passing the macro's Liberty "
                f"as a second --liberty is not available.")
            return 1, err_report
        if connected_inout:
            # A CONNECTED bidirectional port cannot be stripped losslessly and
            # `fault chain` cannot represent it — name it, do not hide it.
            err_report["connected_inout_ports_unhandled"] = connected_inout
            err_report["error"] += (
                f" — netlist has CONNECTED inout port(s) {connected_inout} that "
                f"`fault chain` cannot classify and this program cannot strip "
                f"losslessly (they carry real nets). Scan insertion on a design "
                f"with a driven bidirectional top-level port is an open backlog "
                f"item (bidirectional boundary-scan cell).")
        return 1, err_report

    chained_text = produced.read_text(encoding="utf-8", errors="replace")
    if stripped_inout:
        # Restore the stripped inout port(s) into fault's published netlist, at
        # their original position, with their exact original declaration.
        chained_text = restore_inout_ports(chained_text, stripped_inout,
                                           stripped_successors)
        missing = [n for n in stripped_inout
                   if n not in find_inout_ports(chained_text)]
        if missing:
            # A published netlist MUST carry every original design port — never
            # ship one silently missing a pin.
            return 1, {"stage": "restore", "exit": ec, "netlist": netlist_rel,
                       "inout_ports_stripped": list(stripped_inout),
                       "error": f"failed to restore inout port(s) {missing} "
                                f"into the scan netlist — refusing to publish a "
                                f"netlist missing a design port"}
        produced.write_text(chained_text, encoding="utf-8")
    meta = parse_chain_metadata(chained_text)
    verdict = assess(parse_chain_log(log), meta, count_flops(netlist_text))

    before, after = cell_histogram(netlist_text), cell_histogram(chained_text)
    n_before, n_after = sum(before.values()), sum(after.values())

    report = {
        "tool": "fault chain",
        "image": _fatpg.DOCKER_IMAGE,
        "input_netlist": netlist_rel,
        "input_netlist_switch_note": switch_note,
        "output_netlist": SCAN_NETLIST_REL,
        "pdk": pdk,
        "liberty": liberty,
        "liberty_source": lib_note,
        "dff_cells": dff_cells,
        "clock": clock,
        "reset": reset,
        # Whether the top-level boundary-scan register was inserted, and WHY.
        # `--skip-boundary` is the deterministic choice for a fixed-pinout
        # wrapper (ports are a parent interface, not chip pads) — it removes
        # the SS-corner setup violation (#604) and the +707% area blow-up while
        # the internal scan chain is preserved.
        "skip_boundary": skip_boundary_flag,
        "skip_boundary_mode": skip_boundary,
        "skip_boundary_evidence": skip_boundary_evidence,
        "chain_exit": ec,
        # `inout` port handling (see find_inout_ports): which bidirectional
        # ports were stripped for `fault chain` and restored into its output,
        # and which connected ones could not be handled.
        "inout_ports_stripped_and_restored": list(stripped_inout),
        "inout_ports_connected_unhandled": connected_inout,
        "fault_input_netlist": fault_input_rel,
        # The five ports `fault chain` adds.  KNOWN because they are the
        # option names this program passes, not sniffed from the netlist.
        "dft_ports": list(DFT_PORTS),
        "functional_mode_tieoff": dict(FUNCTIONAL_MODE_TIEOFF),
        "scan_out_port": SCAN_OUT_PORT,
        # MEASURED from the artefact — LEC needs it to restore gold/gate name
        # correspondence (see fault_scan_chain_insert.measure_internal_prefix).
        "internal_wire_prefix": measure_internal_prefix(chained_text),
        "area_instances_before": n_before,
        "area_instances_after": n_after,
        "area_instances_delta": n_after - n_before,
        "area_instances_delta_pct": (
            round(100.0 * (n_after - n_before) / n_before, 2)
            if n_before else None),
        "cells_added": {k: after[k] - before.get(k, 0)
                        for k in after if after[k] != before.get(k, 0)},
        "log_tail": log[-1500:],
        **verdict,
    }
    if not verdict["ok"]:
        # A chain that does not account for every flop is NOT published as the
        # implementation netlist — publishing it would put an untestable
        # design into PnR under a name that says it is testable.
        report["published"] = False
        return 1, report

    (project / SCAN_NETLIST_REL).write_bytes(produced.read_bytes())
    report["published"] = True
    return 0, report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir")
    p.add_argument("--netlist", default="phase2/stage2/synth/netlist.v",
                   help="Synth netlist, relative to project_dir.  A generic "
                        "netlist is self-healed to its tech-mapped sibling by "
                        "fault_atpg_run.resolve_mapped_netlist.")
    p.add_argument("--clock", required=True)
    p.add_argument("--reset")
    p.add_argument("--reset-active-low", action="store_true")
    p.add_argument("--pdk", default="unmapped",
                   help="PDK id (same vocabulary as fault_atpg_run).  An "
                        "unknown id is re-derived from the netlist's cell "
                        "names; if that fails the run REFUSES rather than "
                        "substituting another library's Liberty.")
    p.add_argument("--liberty", default=None,
                   help="Container-absolute .lib path.  Wins over SCAN_LIBERTY.")
    p.add_argument("--dff-cells", default=None)
    p.add_argument("--skip-boundary", choices=("auto", "on", "off"),
                   default="auto",
                   help="Insert a top-level boundary-scan register? "
                        "'auto' (default) skips it iff the design is a "
                        "fixed-pinout wrapper (FP_DEF_TEMPLATE) — its ports "
                        "are a parent interface, not chip pads; 'on' always "
                        "skips; 'off' always inserts (legacy default).")
    p.add_argument("--top-module", default=None,
                   help="Top module name — used by 'auto' skip-boundary "
                        "detection to match the fixed-pinout DEF template to "
                        "THIS top.")
    p.add_argument("--pdk-dir", default=None)
    p.add_argument("--json", default=SCAN_JSON_REL,
                   help=f"Report JSON path relative to project "
                        f"(default {SCAN_JSON_REL})")
    p.add_argument("--timeout", type=int, default=900)
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"fault_scan_chain_insert: not a directory: {project}",
              file=sys.stderr)
        return 2

    ec, report = run_chain(
        project, args.netlist, args.clock, args.pdk,
        reset=args.reset, reset_active_low=args.reset_active_low,
        liberty_override=args.liberty, dff_cells_override=args.dff_cells,
        pdk_dir=Path(args.pdk_dir).resolve() if args.pdk_dir else None,
        skip_boundary=args.skip_boundary, top_module=args.top_module,
        timeout=args.timeout)

    out = project / args.json
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if ec == 0:
        print(f"fault_scan_chain_insert: chain length="
              f"{report['internal_chain_length']} internal + "
              f"{report['boundary_chain_length']} boundary; input flops="
              f"{report['input_flop_count']}; "
              f"matches={report['chain_length_matches_flop_count']}; "
              f"skip_boundary={report['skip_boundary']} "
              f"(mode={report['skip_boundary_mode']}); "
              f"area {report['area_instances_before']} -> "
              f"{report['area_instances_after']} instances "
              f"({report['area_instances_delta_pct']}%)")
    else:
        for pr in report.get("problems") or [report.get("error", "failed")]:
            print(f"fault_scan_chain_insert: {pr}", file=sys.stderr)
        print(f"  (see: {out})", file=sys.stderr)
    return ec


if __name__ == "__main__":
    sys.exit(main())
