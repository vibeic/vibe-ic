#!/usr/bin/env python3
"""
fault_atpg_run.py — Open-source ATPG via Fault (cloudv-io/fault).

Runs Fault's `cut` + `atpg` subcommands on a synthesized netlist to produce
stuck-at test vectors and a coverage metric, then emits the artefacts
required by flow Step 11 (DFT insertion):

  <project>/dft/cut_netlist.v          (Fault's COMBINATIONAL ATPG cut view —
                                        every flop replaced by a `<inst>.d`
                                        pseudo-PI/PO pair.  NOT a scan netlist
                                        and never published as one; the real
                                        scan-inserted implementation netlist is
                                        produced by fault_scan_chain_insert.py)
  <project>/dft/atpg_coverage.rpt       (human-readable coverage ratio + count)
  <project>/dft/transition_atpg_plan.md (launch-off-capture / at-speed
                                         two-pattern mechanism plan +
                                         engine-capability record)
  <project>/reports/dft/coverage.json   (machine-readable with
                                         stuck_at_ge_target: bool and a
                                         `transition` fault-model block)

Eliminates the "no commercial ATPG" waiver (feedback_plugin_usage_discipline.md,
2026-04-22).

FOUNDRY-GRADE DEFAULT (2026-07 DFT-depth raise): the stuck-at target now
defaults to 95 % (foundry / ATE sign-off bar), configurable UP to 98 % via
`--min-coverage`. The old lenient 80 % pass is gone — a design below the
target FAILs (exit 1), never a lenient pass.

TWO FAULT MODELS:
  * stuck-at  — Fault's combinational stuck-at ATPG (real coverage number).
  * transition (at-speed / launch-off-capture) — a SECOND fault model with
    its own target (`--transition-target`, default 90 %). The launch-off-
    capture two-pattern mechanism + plan is always emitted; the coverage
    NUMBER is only reported if the underlying OSS engine can actually run
    transition ATPG. Fault (cloudv-io) is a single-pattern combinational
    stuck-at engine and does NOT support transition/delay ATPG, so the
    honest outcome is `transition.engine_limited = true` with a documented
    reason — never a fabricated transition-coverage number.

Usage:
    python3 fault_atpg_run.py <project_dir> \\
        --netlist synth/netlist.v \\
        --top aon_timer \\
        --clock clk_i \\
        [--pdk gf180] [--min-coverage 95] [--transition-target 90] \\
        [--tv-count 100] [--no-transition]

Requires the pinned vibeic-eda Docker image (Fault + GF180 cell model); see
_resolve_docker_image() for the pin + fallback order.
Fault ≈ 10-60 s for typical <5k-cell designs.

Exit 0 = stuck-at coverage >= target AND all artefacts produced.
Exit 1 = stuck-at coverage below target OR Fault failed.
Exit 2 = usage / IO / Docker error.

Note: a transition ENGINE limitation (Fault cannot do at-speed) is honestly
recorded but does NOT by itself fail this producer — the DFT sign-off gate
(dft_signoff_check.py) is where the "transition >= target OR documented
engine-limited" policy is enforced.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
import _path_layout as _pl
import _commercial_pdk as _cpdk  # config-driven commercial-PDK id (NDA: no SKU in source)
import _container_exec as _CE  # vibe-ic#623 — the deadline goes INSIDE the container
try:  # sibling module; programs/ is on sys.path when run as a script
    import _docker_memory as _dmem
except ImportError:  # pragma: no cover - packaged/flattened layouts
    from . import _docker_memory as _dmem  # type: ignore
import _eda_image as _img
import pdk_cell_models as _pcm  # ciel version-hash live resolution (gf180)


def _resolve_docker_image() -> str:
    """Resolve the EDA docker image, preferring the forked vibeic-eda
    distribution (the iic-osic-tools fork this plugin ships, carrying Fault +
    iverilog + yosys) over the upstream image.

    The version is ASKED FOR, not remembered. It used to be a pinned literal
    kept in step by `sync_image_version.py`, on the stated grounds that the tag
    "matches what the plugin was verified against" — and nothing ever verified
    that. vibeic-eda's own release gate does, and `_eda_image` asks the registry
    which image is current rather than trusting a local `:latest`, which is how
    this once resolved to `hpretl/iic-osic-tools:latest` on a machine that had
    only the fork and made the whole DFT step die on image-not-found.
    chip-AGNOSTIC."""
    return _img.resolve()


DOCKER_IMAGE = _resolve_docker_image()

# Foundry / ATE sign-off bar. Stuck-at coverage at 95 %+ is the widely-quoted
# minimum foundry acceptance floor; 98 %+ is the common aggressive target.
# Configurable via --min-coverage (may be set as high as 98/99).
FOUNDRY_STUCK_AT_DEFAULT = 95.0
# Transition (at-speed) coverage floors are typically a few points below the
# stuck-at floor because at-speed test escapes are harder; 90 % is a common
# foundry transition-fault target.
FOUNDRY_TRANSITION_DEFAULT = 90.0

# Keywords that, if present in `fault atpg --help`, would indicate the engine
# advertises a transition / at-speed / delay-fault (two-pattern) capability.
# Fault (cloudv-io) exposes none of these — its ATPG is single-pattern
# combinational stuck-at only. Probed at run time; NEVER assumed.
_TRANSITION_CAPABILITY_KEYWORDS = (
    "transition", "at-speed", "at speed", "atspeed",
    "launch-off-capture", "launch off capture", "launch-off-shift",
    "delay fault", "delay-fault", "delayfault", "two-pattern",
    "two pattern", "--slow", "--fast",
)

# Per-PDK defaults: verilog cell-model path (inside Docker) + DFF cell names.
# pdk=custom reads paths from --cell-model-path and --dff-cells flags.
PDK_CONFIG = {
    "gf180": {
        "cell_model": (
            "/foss/pdks/ciel/gf180mcu/versions/"
            "8f2d1529c86235d726979eb9ecb7e9628108590b"
            "/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0"
            "/verilog/gf180mcu_fd_sc_mcu7t5v0.v"
        ),
        "dff_cells": "gf180mcu_fd_sc_mcu7t5v0__dffq_1,gf180mcu_fd_sc_mcu7t5v0__dffrq_1",
    },
    # sky130A high-density stdcell library (default OpenLane PDK).
    # Added 2026-05-24 for v2 e2e benchmark spm_e2e — covers the broad
    # sky130_fd_sc_hd DFF family (dfxtp / dfrtp / dfstp / dfbbn / sdfxtp) plus the
    # ENABLE-flop family edfxtp/sedfxtp (yosys maps $_DFFE_* → edfxtp — the single
    # most common flop on real sky130 synth, e.g. 1024 in subservient; v1.4.21).
    "sky130": {
        # v1.8.43 — `primitives.v` named EXPLICITLY and FIRST, mirroring the
        # `ihp-sg13g2` entry below. ATPG already got it implicitly (via
        # `_cell_model_prep`'s co-located-primitives.v prepend), but Step 29's
        # consumer `pdk_cell_models.container_model_paths` has no such implicit
        # step, so on sky130 it handed iverilog a model whose UDPs are undefined:
        # `67 error(s) during elaboration` / `sky130_fd_sc_hd__udp_dff$P_pp$PG$N
        # referenced 64 times`, and canonical Step 29 came out MISSING on every
        # sky130 run. `_cell_model_prep` is now idempotent so naming it here does
        # not concatenate it twice.
        "cell_model": (
            "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/verilog/"
            "primitives.v "
            "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/verilog/"
            "sky130_fd_sc_hd.v"
        ),
        "dff_cells": (
            "sky130_fd_sc_hd__dfxtp_1,sky130_fd_sc_hd__dfxtp_2,"
            "sky130_fd_sc_hd__dfxtp_4,"
            "sky130_fd_sc_hd__dfrtp_1,sky130_fd_sc_hd__dfrtp_2,"
            "sky130_fd_sc_hd__dfrtp_4,"
            "sky130_fd_sc_hd__dfstp_1,sky130_fd_sc_hd__dfstp_2,"
            "sky130_fd_sc_hd__dfstp_4,"
            "sky130_fd_sc_hd__sdfxtp_1,sky130_fd_sc_hd__sdfxtp_2,"
            "sky130_fd_sc_hd__sdfrtp_1,sky130_fd_sc_hd__sdfrtp_2,"
            "sky130_fd_sc_hd__edfxtp_1,sky130_fd_sc_hd__edfxbp_1,"
            "sky130_fd_sc_hd__sedfxtp_1,sky130_fd_sc_hd__sedfxbp_1"
        ),
    },
    # IHP SG13G2 (open-source 130nm BiCMOS). Without this entry the PDK
    # resolved to `generic_unmapped` and the runner fell back to the SKY130
    # cell model — on an ihp-sg13g2 run the ATPG plan literally recorded
    # "Cell model : /foss/pdks/sky130A/.../sky130_fd_sc_hd.v" and iverilog
    # died with "Unknown module type: sky130_fd_sc_hd__udp_mux_4to2"
    # (atpg_exit 171, faults_total 0). Reaching into another foundry's PDK
    # is never right; the correct model is this PDK's own shipped Verilog.
    # sg13g2_udp.v holds the UDP primitives the stdcell models reference and
    # must be read alongside sg13g2_stdcell.v.
    "ihp-sg13g2": {
        "cell_model": (
            "/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/verilog/"
            "sg13g2_udp.v "
            "/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/verilog/"
            "sg13g2_stdcell.v"
        ),
        # The full SG13G2 flop family (both drives), incl. the scan variants.
        "dff_cells": (
            "sg13g2_dfrbp_1,sg13g2_dfrbp_2,"
            "sg13g2_dfrbpq_1,sg13g2_dfrbpq_2,"
            "sg13g2_sdfrbp_1,sg13g2_sdfrbp_2,"
            "sg13g2_sdfrbpq_1,sg13g2_sdfrbpq_2,"
            "sg13g2_sdfbbp_1"
        ),
    },
    # NanGate45 / FreePDK45 open academic 45nm stdcell library (OpenROAD's
    # reference PDK; ships in the container at /foss/pdks/nangate45). Without
    # this entry a FULLY tech-mapped NanGate45 netlist (NAND2_X1 / DFF_X1 /
    # SDFF_X1, no Yosys generic primitives) sniffs to None -> the DFT step reads
    # that None as `generic_unmapped` and refuses scan insertion with
    # "no Liberty configured for pdk 'unmapped'", even though the netlist is
    # mapped and the container ships this library's Liberty. That is the exact
    # "could not NAME the PDK" != "no library-mapped cells" confusion the
    # `netlist_is_library_mapped` docstring (above) warns about, surfacing on
    # the resolution side. Adding the entry is the same remedy applied to
    # ihp-sg13g2 above; it teaches the sniff (via pdk_cell_prefixes) and gives
    # scan insertion its Liberty (SCAN_LIBERTY in fault_scan_chain_insert.py).
    #
    # cell_model is None ON PURPOSE: this build's container ships NO NanGate45
    # Verilog simulation model (only .lib / .lef / .gds / .cdl), so Fault's
    # iverilog-based stuck-at fault simulation cannot run. With cell_model=None,
    # run_fault returns rc=2 "no Verilog cell model resolved" — an HONEST,
    # disclosed engine-limited skip, NOT a fabricated coverage number and NOT a
    # crash. This REPLACES the false "unsupported pdk: unmapped" (which wrongly
    # blamed the netlist) with the true state: NanGate45 IS recognised and
    # scan-insertable; only its ATPG fault-sim is engine-limited here.
    "nangate45": {
        "cell_model": None,
        "dff_cells": (
            "DFF_X1,DFF_X2,DFFR_X1,DFFR_X2,DFFS_X1,DFFS_X2,"
            "DFFRS_X1,DFFRS_X2,SDFF_X1,SDFF_X2,SDFFR_X1,SDFFR_X2,"
            "SDFFS_X1,SDFFS_X2,SDFFRS_X1,SDFFRS_X2"
        ),
    },
}

# commercial 180nm PDK — used in the v046 aon_timer pilot and the spm
# commercial-PDK flow. This proprietary (NDA) PDK ships a Verilog simulation
# model but the run-dir PDK often carries only the liberty; point
# --cell-model-path at the model copied into the run dir's input/pdk/verilog/.
# The dff_cells value is a SEED only — the real set is auto-detected from the
# netlist by detect_dff_cells() (unioned in), so a design that uses DFFHQD1
# (not the seeded DFFRQD1/DFFSQD1) is still cut correctly.
#
# The SKU and its paths come from the private config (see _commercial_pdk); the
# entry is only present when the owner has configured it (public installs get an
# unchanged sky130/gf180 PDK_CONFIG — no commercial entry, no SKU literal).
if _cpdk.COMMERCIAL_PDK_ID:
    _commercial_cfg = _cpdk.commercial_pdk_config()
    if _commercial_cfg:
        PDK_CONFIG[_cpdk.COMMERCIAL_PDK_ID] = _commercial_cfg

# Matches a flip-flop cell INSTANTIATION line: `CELLNAME instname (`. Anchored to
# line start + requires an instance name and an opening paren so a `wire dff_x;`
# declaration can never match. Two flop-cell naming conventions, both matched so
# the auto-detect is a true PDK-agnostic SUPERSET (never dependent on a seed):
#   1. commercial PREFIX — `DFF*` / `SDFF*` (e.g. DFFHQD1, SDFFRQD1);
#   2. OSS-PDK INFIX — `<lib>_[_][s][e]df…` where the flop family sits after the
#      library separator, with optional scan (`s`) and/or enable (`e`)
#      variant letters: sky130 `__dfxtp`/`__dfrtp`/`__dfstp`/`__dfbbn`/`__sdfxtp`
#      AND the enable families `__edfxtp`/`__sedfxtp` (yosys maps `$_DFFE_*` →
#      `edfxtp`, the SINGLE most common flop on real sky130 synth — e.g. 1024 in
#      subservient); gf180 `__dffq`/`__sdffq`/`__edffq`.
#      The separator is `_{1,2}`, NOT a literal `__`: sky130 and gf180 both use a
#      DOUBLE underscore, but that is a convention of those two libraries, not of
#      OSS PDKs generally. IHP SG13G2 uses a SINGLE one (`sg13g2_dfrbpq_1`,
#      `sg13g2_sdfrbp_1`), so a `__`-anchored pattern detected ZERO flops there.
#      That reopened exactly the empty-detect hole this comment warns about
#      below: measured on spm x ihp-sg13g2 (2026-07-21), a netlist with 65
#      `sg13g2_dfrbpq_1` instances detected none, `fault cut` fell back to the
#      seed `--dff DFFHQD1` (a commercial-PDK name absent from the design), cut
#      nothing, and transition_coverage.json reported `scan_flops: 0` →
#      `NOT_APPLICABLE` → the DT1 at-speed gate scored PASS on a design whose
#      flops were never cut. A vacuous pass, not coverage.
#   3. GENERIC YOSYS PRIMITIVE — `\$_[…]DFF[…]_` escaped internal-cell FFs in a
#      PRE-TECHMAP netlist: `\$_DFF_P_`, `\$_DFFE_PP_`, `\$_SDFF_PP0_`,
#      `\$_DFFSR_PPP_` (the Fault-emitted cut/scan netlists are in THIS vocabulary
#      — a bogus non-cut full of `\$_DFF_P_` must be recognised as still-having-
#      flops so the cut-validity guard regenerates it). Latches (`\$_DLATCH_*`)
#      and `\$_SR_*` never carry `DFF`, so they never match.
# The three vocabularies together make the detect a TRUE superset. Non-flop cells
# never match: delay=`__dly`, latch=`__dl*`/`__lat*`/`\$_DLATCH`, buffer=`__buf`,
# mux=`__mux` — none reach `df`/`DFF`. This closes the empty-detect failure mode
# (WRONG `--dff` seed → `fault cut` cutting nothing → un-cut flops → a false
# NOT_APPLICABLE the coverage gate would silently pass — gate-gaming).
_DFF_INST_RE = re.compile(
    r'^\s*('
    r'S?DFF[A-Za-z0-9_]*'                        # commercial prefix DFF*/SDFF*
    r'|[A-Za-z][A-Za-z0-9_]*_{1,2}s?e?df[a-z0-9_]*'  # OSS-PDK infix *_[_][s][e]df…
    r'|\\\$_[A-Z]*DFF[A-Z0-9_]*'                  # generic Yosys \$_…DFF…_ primitive
    r')\s+\\?[^\s()]+\s*'
    # A yosys `write_verilog` netlist prints the cell's auto-name as an INLINE
    # block comment BETWEEN the instance name and its `(` — e.g.
    #   \$_DFF_P_  \mprj.counter.count_reg[0]  /* _1154_ */ (
    # A bare `\s*\(` tail then never reaches the paren, so a generic pre-techmap
    # netlist ($_DFF_P_) — and equally a mapped netlist whose flop line carries
    # such a comment — detects ZERO flops, `--dff` falls back to a hard-coded
    # seed that matches nothing, `fault cut` cuts nothing, and a sequential
    # design self-skips as NOT_APPLICABLE. Tolerate zero-or-more inline block
    # comments (line-bounded — `[^\n]` never swallows the next line's `(`).
    r'(?:/\*[^\n]*?\*/\s*)*'
    r'\(', re.MULTILINE | re.IGNORECASE)


# ---------------------------------------------------------------------------
# LIBERTY-DERIVED (name-independent) sequential-cell identification.
#
# WHY THIS EXISTS. `_DFF_INST_RE` above is a NAMING-CONVENTION matcher, and a
# naming convention is a property of a particular library, never of silicon.
# Every widening of that regex is a bet that the next PDK spells its flops the
# way the last one did, and the bet has already been lost once: a `__`-anchored
# separator matched sky130/gf180 and detected ZERO flops in a library that
# separates with a single underscore — 0 of 65 instantiated flops, no scan chain
# cut, and `scan_flops: 0` scored a PASS. The regex was then widened to `_{1,2}`,
# which fixes that one library and leaves the same bet standing for the next.
#
# A cell's `ff` / `ff_bank` group in the Liberty the flow ALREADY reads is
# authoritative: it is the library's own machine-readable declaration that the
# cell holds state. Its NAME is not. So the primary identification is
#   {modules instantiated in the netlist} INTERSECT {cells with an `ff` group}
# which involves no cell-name vocabulary whatsoever and works for any library,
# including ones that have not been written yet.
#
# The name pattern is KEPT, but demoted to a SUPERSET safety net: it is unioned
# in (it can only ADD flops, never remove them), and it still covers the
# pre-techmap generic-Yosys vocabulary (`\$_DFF_P_`) that no Liberty declares.
# The direction of the fallback matters — see `sequential_evidence`: a claim
# that a design HAS flops may rest on either source, but a claim that a design
# has NONE (the claim that licenses a NOT_APPLICABLE self-skip) requires the
# authoritative one.
_LIB_COMMENT_RE = re.compile(r'/\*.*?\*/', re.S)
# One ordered token stream: cell headers, sequential-group headers, and braces.
# `\bcell` requires a word boundary, so `test_cell` / `scaled_cell` /
# `cell_footprint` never match as a cell header.
_LIB_TOKEN_RE = re.compile(
    r'\bcell\s*\(\s*"?(?P<name>[A-Za-z_][A-Za-z0-9_$.\-]*)"?\s*\)'
    r'|(?P<ff>\bff(?:_bank)?\s*\()'
    r'|(?P<latch>\blatch(?:_bank)?\s*\()'
    r'|(?P<open>\{)|(?P<close>\})')

# Any `<module> <instance> (` line. Deliberately UNCONSTRAINED: the result is
# only ever INTERSECTED with a Liberty-declared cell set, so Verilog keywords
# and other noise cannot survive the intersection. No cell-name vocabulary.
_INST_RE = re.compile(
    r'^[ \t]*\\?([A-Za-z_$][A-Za-z0-9_$.\\/\[\]-]*)[ \t]+\\?[^\s();,]+[ \t]*\(',
    re.MULTILINE)


def liberty_sequential_cells(liberty_text: str,
                             include_latches: bool = False) -> set:
    """Return the set of cell names a Liberty declares SEQUENTIAL, by reading
    each `cell (NAME) { … }` group and asking whether it contains an `ff` /
    `ff_bank` group (with `include_latches`, also `latch` / `latch_bank`).

    This is the AUTHORITATIVE, PDK-agnostic answer to "is this cell a flop?" —
    it consults the library's own declaration instead of guessing from the
    spelling of the name. Pure; no I/O.

    Single linear token walk (a std-cell Liberty is tens of megabytes, so
    per-cell brace matching would be quadratic). A sequential group is
    attributed to the innermost OPEN cell, which is why a scan flop declaring
    its `ff` inside a nested `test_cell` group is still recognised.

    Degrades in the SAFE direction: if the structure is damaged (e.g. a lossy
    reduction), groups over-attribute, so a combinational cell may be called
    sequential. That can only turn a would-be self-skip into a refusal to
    self-skip — never the reverse."""
    text = _LIB_COMMENT_RE.sub(" ", liberty_text or "")
    out, stack, depth, pending = set(), [], 0, None
    for m in _LIB_TOKEN_RE.finditer(text):
        if m.group("name"):
            pending = m.group("name")
        elif m.group("open"):
            depth += 1
            if pending is not None:
                stack.append([pending, depth])
                pending = None
        elif m.group("close"):
            if stack and stack[-1][1] == depth:
                stack.pop()
            depth = max(0, depth - 1)
        elif stack and (m.group("ff") or (include_latches and m.group("latch"))):
            out.add(stack[-1][0])
    return out


# A std-cell Liberty is often only reachable inside the tool container. Reading
# it whole across that boundary is wasteful and unnecessary: only the group
# headers and the brace structure are load-bearing. This reduces a 20 MB Liberty
# to something small that `liberty_sequential_cells` parses identically.
LIBERTY_STRUCTURE_GREP = (
    r"grep -aE '(^|[^A-Za-z0-9_])(cell|ff|ff_bank|latch|latch_bank)[[:space:]]*\(|[{}]'")


def instantiated_modules(netlist_text: str) -> set:
    """Every module name instantiated in a (gate-level) netlist. Intentionally
    over-inclusive — see `_INST_RE`. Pure."""
    return {m.group(1).lstrip("\\")
            for m in _INST_RE.finditer(netlist_text or "")}


def detect_dff_cells(netlist_text: str,
                     liberty_sequential: "set | None" = None) -> str:
    """Scan a gate-level netlist for instantiated flip-flop cells and return
    them sorted, comma-separated, de-duped — suitable for `fault cut --dff`.
    Chip- and PDK-AGNOSTIC. Returns "" when none are found (caller keeps the
    PDK-config seed).

    `liberty_sequential` — the AUTHORITATIVE cell set from
    `liberty_sequential_cells()`. When supplied, any instantiated module the
    Liberty declares to have an `ff` group is detected REGARDLESS of how it is
    spelled; the name pattern is unioned in on top as a superset safety net (it
    still catches the pre-techmap `\\$_DFF_P_` vocabulary, which appears in no
    Liberty). Omitting it falls back to name matching alone — the historical
    behaviour, and a guess.

    This closes the failure mode where a PDK config seeds the WRONG flop cell
    (e.g. seed DFFRQD1,DFFSQD1 but the netlist actually uses DFFHQD1): the
    detected set is UNIONED with the seed so cut always sees the real flop
    cell and does not leave 64 un-cut sequential elements (which would tank
    the measured stuck-at coverage or make ATPG meaningless)."""
    found = {m.group(1) for m in _DFF_INST_RE.finditer(netlist_text or "")}
    if liberty_sequential:
        found |= (instantiated_modules(netlist_text) & set(liberty_sequential))
    return ",".join(sorted(found))


# Three-valued outcome of "does this design contain sequential elements?".
SEQ_PRESENT = "HAS_SEQUENTIAL"
SEQ_ABSENT = "NO_SEQUENTIAL"
SEQ_UNKNOWN = "UNKNOWN"


def sequential_evidence(netlist_text: str,
                        liberty_text: "str | None" = None) -> dict:
    """Decide, WITH ITS PROVENANCE, whether a netlist contains sequential
    elements. Returns a dict carrying the verdict, the method that produced it,
    and the counts behind it — the evidence a downstream gate needs in order to
    judge a `scan_flops: 0` result instead of taking it on trust.

    The three outcomes are deliberately asymmetric, because the two claims carry
    different weight:

      HAS_SEQUENTIAL — flops were found. EITHER source may establish this; both
        are unioned, so the answer is a superset and a flop is never missed.

      NO_SEQUENTIAL — the design genuinely has no sequential elements. This is
        the claim that licenses a NOT_APPLICABLE self-skip for every at-speed
        step, so it may ONLY be made from the authoritative source: a Liberty
        that declares sequential cells, none of which the netlist instantiates.
        `authoritative` is True exactly here.

      UNKNOWN — no Liberty was available to enumerate sequential cells, and the
        name pattern (a guess) matched nothing. That is not evidence of absence;
        it is absence of evidence. Saying so is the entire point: the previous
        code could not express it and silently emitted NOT_APPLICABLE, which
        read downstream as a clean self-skip.

    Pure; no I/O. chip- and PDK-AGNOSTIC."""
    lib_cells = liberty_sequential_cells(liberty_text) if liberty_text else set()
    name_hits = {m.group(1) for m in _DFF_INST_RE.finditer(netlist_text or "")}
    lib_hits = (instantiated_modules(netlist_text) & lib_cells
                if lib_cells else set())

    out = {
        "liberty_consulted": bool(lib_cells),
        "liberty_sequential_cells_declared": len(lib_cells),
        "sequential_cells_instantiated": sorted(lib_hits | name_hits),
        "liberty_matched_cells": sorted(lib_hits),
        "name_pattern_matched_cells": sorted(name_hits),
    }

    if lib_hits or name_hits:
        out.update({
            "verdict": SEQ_PRESENT,
            "authoritative": bool(lib_hits),
            "method": "liberty_ff_group" if lib_hits else "cell_name_pattern",
            "reasons": [
                f"{len(lib_hits | name_hits)} distinct sequential cell type(s) "
                f"instantiated: {', '.join(sorted(lib_hits | name_hits)[:8])}"],
        })
    elif lib_cells:
        out.update({
            "verdict": SEQ_ABSENT,
            "authoritative": True,
            "method": "liberty_ff_group",
            "reasons": [
                f"the design's own Liberty declares {len(lib_cells)} cell(s) "
                "with an `ff` group and the netlist instantiates none of them "
                "— genuinely combinational"],
        })
    else:
        out.update({
            "verdict": SEQ_UNKNOWN,
            "authoritative": False,
            "method": "none",
            "reasons": [
                "no Liberty was available to enumerate sequential cells, so "
                "'this design has no flops' could not be checked — only a "
                "cell-NAME pattern was consulted and it matched nothing, which "
                "is absence of evidence, not evidence of absence"],
        })
    return out


def adjudicate_zero_flop_claim(blob: dict) -> "dict | None":
    """Gate-side adjudication of a DFT/ATPG result that reports ZERO scan flops.

    A producer saying "0 flops, therefore not applicable" is a claim, and the
    gate's job is to ask what it rests on. Returns a verdict dict when the claim
    must be overridden, or None when the result may be evaluated normally.

      * evidence says the design HAS sequential elements  -> FAIL. A scan
        insertion that inserted nothing into a sequential design is a failed
        gate, not an inapplicable one. This is the measured case: 0 of 65 flops
        detected, no chain cut, `scan_flops: 0` scored PASS.
      * evidence authoritatively says it has NONE          -> None (a genuinely
        combinational design is legitimately NOT_APPLICABLE and must not
        false-FAIL).
      * no evidence, or non-authoritative evidence         -> BLOCKED. The
        producer never established that the design is combinational, so neither
        a coverage number nor a self-skip is supported. Not a pass, and
        deliberately not silence either.

    Pure; no I/O. chip- and PDK-AGNOSTIC — the caller supplies the artefact."""
    ev = blob.get("sequential_evidence")
    scan_flops = blob.get("scan_flops")
    if isinstance(scan_flops, int) and scan_flops > 0:
        return None

    if isinstance(ev, dict) and ev.get("verdict") == SEQ_PRESENT:
        cells = ev.get("sequential_cells_instantiated") or []
        return {
            "verdict": "FAIL", "status": "FAIL",
            "scan_flops": scan_flops,
            "sequential_evidence": ev,
            "reasons": [
                f"scan_flops={scan_flops} on a design that HAS sequential "
                f"elements ({len(cells)} sequential cell type(s) instantiated: "
                f"{', '.join(cells[:8])}) — scan insertion reported success "
                "having inserted nothing; a zero-flop scan result is only "
                "legitimate on a design with no sequential elements"],
        }

    if isinstance(ev, dict) and ev.get("verdict") == SEQ_ABSENT \
            and ev.get("authoritative"):
        return None

    detail = ("no `sequential_evidence` was recorded at all"
              if not isinstance(ev, dict)
              else "; ".join(ev.get("reasons") or [ev.get("verdict", "?")]))
    return {
        "verdict": "BLOCKED", "status": "BLOCKED",
        "scan_flops": scan_flops,
        "sequential_evidence": ev if isinstance(ev, dict) else None,
        "reasons": [
            f"scan_flops={scan_flops} but whether the design has sequential "
            f"elements was never established ({detail}) — a zero-flop result "
            "is only legitimate on a genuinely flop-free design, and that was "
            "not checked. Reporting BLOCKED rather than passing an unverified "
            "self-skip"],
    }


def merge_dff_cells(seed: str | None, detected: str) -> str:
    """Union a PDK-config seed dff-cell list with the auto-detected set,
    preserving a stable sorted order. Pure — unit-tested. An empty/None seed
    yields just the detected set and vice-versa."""
    parts = set()
    for chunk in (seed or "", detected or ""):
        for tok in chunk.split(","):
            tok = tok.strip()
            if tok:
                parts.add(tok)
    return ",".join(sorted(parts))


def resolve_cell_model(cell_model_override: str | None,
                       pdk_cfg: dict | None) -> str | None:
    """Resolve the Verilog cell-model path as seen INSIDE the container.

    Priority: explicit --cell-model-path > PDK config. A container-absolute
    override (starts with '/', e.g. /pdk/... or /foss/...) is used as-is; a
    relative override is a project-relative path resolved under the /work mount
    (so the model can live inside the run dir → single mount, reproducible).
    Returns None when neither is available."""
    if cell_model_override:
        if cell_model_override.startswith("/"):
            return cell_model_override
        return "/work/" + cell_model_override.lstrip("./")
    if pdk_cfg is not None:
        return pdk_cfg.get("cell_model")
    return None


# ── Tech-mapped netlist resolution ─────────────────────────────────────
# ATPG must run on a TECH-MAPPED (std-cell) netlist: iverilog cannot
# elaborate the generic Yosys gate vocabulary ($_NAND_/$_NOR_/$_DFF_…),
# so a generic-unmapped netlist yields `Unknown module type: $_NAND_` and
# ZERO fault sites. The flow writes BOTH a generic `netlist.v` (kept for
# LEC/equivalence, where the abstract gate view is wanted) AND a mapped
# `<top>_synth.v` (what PnR/streamout consume). The DFT step historically
# handed ATPG the generic one. Detect that and switch to the mapped
# sibling, mirroring phase3_one_shot_runner's netlist-resolver order
# (`<top>_synth.v` first, then any `*_synth.v`). chip-AGNOSTIC: keyed only
# on the generic-primitive vocabulary and the design's own top-module
# name — no chip/PDK literal.
_GENERIC_PRIM_RE = re.compile(r"\$_[A-Z][A-Z0-9]*_")
_MODULE_DECL_RE = re.compile(r"(?m)^\s*module\s+([A-Za-z_]\w*)")


def is_generic_unmapped(netlist_text: str) -> bool:
    """True iff the netlist contains Yosys generic gate primitives
    ($_NAND_, $_DFF_P_, $_NOR_, $_MUX_, …) — these appear ONLY pre-techmap
    and cannot be simulated (no cell model declares them)."""
    return bool(_GENERIC_PRIM_RE.search(netlist_text or ""))


# Language keywords and Verilog PRIMITIVE gates. `instantiated_modules` is
# deliberately over-inclusive (see `_INST_RE`), so the caller must subtract the
# non-cell vocabulary itself. This is a LANGUAGE fact, not a library one — no
# cell/vendor/PDK name appears here, and adding a PDK never touches this set.
# The primitive gates (`and`/`nor`/`buf`/…) are excluded ON PURPOSE: a netlist
# built from them is gate-level but NOT library-mapped.
_NON_CELL_IDENTIFIERS = frozenset("""
module endmodule input output inout wire reg assign always initial begin end
if else case casex casez endcase for while repeat forever function endfunction
task endtask generate endgenerate parameter localparam defparam integer real
genvar supply0 supply1 tri triand trior wand wor time realtime event signed
unsigned logic bit byte shortint int longint specify endspecify primitive
endprimitive table endtable posedge negedge disable force release fork join
and or not nand nor xor xnor buf bufif0 bufif1 notif0 notif1 pmos nmos cmos
rpmos rnmos rcmos tran tranif0 tranif1 rtran rtranif0 rtranif1 pullup pulldown
""".split())


def netlist_is_library_mapped(netlist_text: str) -> bool:
    """True iff `netlist_text` positively shows TECHNOLOGY-MAPPED cells —
    i.e. instantiations of named library cells rather than Yosys generic
    primitives or Verilog primitive gates.

    This is the POSITIVE complement of `is_generic_unmapped`, and it exists
    because callers were using "I could not NAME the PDK" as though it were
    "there are no library-mapped cells". Those are different questions:
    a netlist mapped to a library that is simply absent from `PDK_CONFIG`
    (NanGate45, any foundry library the container does not ship) answers NO to
    the first and YES to the second. Publishing the first as the second tells a
    reader the netlist is unmapped when it is fully mapped, and — worse — that
    label is an ATTESTATION downstream (`transition_coverage_check` grants the
    ENGINE_LIMITED skip only on `pdk_detected == "generic_unmapped"`, precisely
    so a MAPPED netlist cannot claim it).

    The rule here is the one `transition_fault_atpg_run` already applies for
    the same decision: require POSITIVE structural evidence, never infer from
    the absence of a name.

    FAIL-SAFE in the only direction that matters: every unclear case returns
    False, which leaves the pre-existing `generic_unmapped` label in place and
    moves no verdict. A False positive can only cause a self-skip to be
    REFUSED, never granted — it can never fabricate a pass.

    Pure; no I/O. chip/PDK-AGNOSTIC: no cell-name vocabulary.
    """
    if not netlist_text:
        return False
    if is_generic_unmapped(netlist_text):
        return False
    return bool(instantiated_modules(netlist_text) - _NON_CELL_IDENTIFIERS)


def _first_module_name(netlist_text: str) -> str | None:
    m = _MODULE_DECL_RE.search(netlist_text or "")
    return m.group(1) if m else None


_ATPG_NO_RESET_BYPASS = "__vibeic_atpg_no_reset_bypass__"


def _atpg_liberty_container_path(project: "Path", cell_model: str,
                                 pdk_dir: "Path | None") -> str:
    """Container path of a std-cell Liberty for the SAME library as
    `cell_model`, or "" if none resolves.

    chip/PDK-AGNOSTIC: every PDK we ship lays a std-cell library out as
    ``<lib_root>/verilog/<x>.v`` beside ``<lib_root>/lib/<x>.lib`` (open_pdks
    sky130A/gf180mcuD and IHP-Open-PDK sg13g2 all do). Swap the leaf directory
    and glob for a typical corner, then any corner. No cell/vendor literal."""
    cm = (cell_model or "").split()[0] if cell_model else ""
    if not cm or "/verilog/" not in cm:
        return ""
    root = cm.rsplit("/verilog/", 1)[0]
    for pat in (f"{root}/lib/*typ*.lib", f"{root}/lib/*tt*.lib",
                f"{root}/lib/*.lib"):
        try:
            # NB: _run_docker " ".join()s argv into ONE string handed to an
            # outer `bash -c`, so the glob must be left UNQUOTED for that shell
            # to expand — and an inner `bash -lc` would swallow the arguments.
            ec, out, _ = _run_docker(project, ["ls", pat, "2>/dev/null"],
                                     timeout=60, pdk_dir=pdk_dir)
        except Exception:
            continue
        for ln in (out or "").splitlines():
            ln = ln.strip()
            if ln.endswith(".lib"):
                return ln
    return ""


def cut_netlist_load_count(cut_text: str, name: str) -> int:
    """Number of places `name` is CONSUMED (driven into something) in a cut
    netlist: instance pin connections ``.PIN(name)`` and continuous-assignment
    right-hand sides. Port/wire DECLARATIONS are deliberately not counted — a
    declared-but-unloaded signal is exactly the "no loads" case this feeds.

    chip/PDK-AGNOSTIC: pure structural text analysis, no cell/vendor literal."""
    if not name:
        return 0
    esc = re.escape(name)
    n = len(re.findall(r"\.\s*[A-Za-z_$][\w$]*\s*\(\s*\\?" + esc + r"\s*\)",
                       cut_text))
    for m in re.finditer(r"^\s*assign\b[^=]*=([^;]*);", cut_text, re.M):
        if re.search(r"(?<![\w$\\.])\\?" + esc + r"(?![\w$.])", m.group(1)):
            n += 1
    return n


def _atpg_reset_bypass_name(cut_path: "Path", reset: str | None,
                            clock: str) -> tuple[str, str]:
    """Decide which name to give ``fault atpg --reset`` — i.e. which port the
    ATPG engine will BYPASS and hold at a constant for every simulation.

    `fault atpg` bypasses a reset BY NAME and defaults to the literal "rst".
    A design whose reset port is called `rst` therefore had that input frozen
    even though nothing asked for it, making its entire fanout cone untestable.

    The cut netlist is a purely COMBINATIONAL full-scan model (every flop became
    a pseudo-PI/pseudo-PO pair), so each of its primary inputs is scan-
    controllable and none should be frozen. Decide structurally:

      * candidate HAS loads in the cut netlist -> it is live combinational logic
        (a SYNCHRONOUS reset, or a reset that also feeds datapath) -> return the
        sentinel so NOTHING is bypassed and the cone stays testable.
      * candidate has NO loads -> it only drove flop async pins, which the cut
        removed -> bypassing is a no-op; keep the caller's/tool's behaviour.

    Returns ``(name_to_pass, human_readable_note)``."""
    candidate = (reset or "rst").strip()
    try:
        cut_text = Path(cut_path).read_text(errors="replace")
    except Exception as exc:                                   # unreadable cut
        return _ATPG_NO_RESET_BYPASS, (
            f"cut netlist unreadable ({exc}); passed sentinel --reset so no "
            f"data input is frozen by the tool's name-based default")
    loads = cut_netlist_load_count(cut_text, candidate)
    if loads > 0:
        return _ATPG_NO_RESET_BYPASS, (
            f"reset candidate '{candidate}' has {loads} load(s) in the cut "
            f"netlist -> SYNCHRONOUS/datapath reset, kept ATPG-CONTROLLABLE "
            f"(not bypassed); freezing it would make its whole fanout cone "
            f"untestable")
    return candidate, (
        f"reset candidate '{candidate}' has no loads in the cut netlist "
        f"(async-only: its flop pins were removed by the cut) -> bypassing is "
        f"a no-op; passed through")


def _read_netlist_text(project: Path, netlist_rel: str, limit: int = 200000) -> str:
    try:
        return (project / netlist_rel).read_text(errors="ignore")[:limit]
    except OSError:
        return ""


def sniff_pdk_over_whole_netlist(project: Path, netlist_rel: str) -> str | None:
    """Which configured PDK this netlist is mapped to, scanned over ALL of it.

    Its only caller used to hand `sniff_pdk_from_netlist` a `[:200000]` head,
    which made a WHOLE-FILE classification out of a fixed-size window. A
    netlist's first standard-cell token can sit anywhere: a design that emits
    its hard macros and generic primitives first pushes that token past any
    fixed window, and the LARGER the design the likelier that is. So the
    truncation failed hardest on exactly the designs it matters most for, and
    it failed SILENTLY — `sniff_pdk_from_netlist` returns None both for a
    genuinely unmapped netlist and for one we simply stopped reading, and its
    own docstring tells the caller to "surface the honest error" on that None.
    Downstream that None became `pdk=generic`, which the run then published as
    "OSS ATPG coverage engine-limited" — blaming the open-source engine for a
    read that stopped early.

    Reproduced on two synthetic netlists identical but for token position:
    first std-cell token at 61,689 resolved sky130; at 430,005 resolved
    nothing.

    Read in chunks with an overlap, so a very large netlist is never resident
    and a prefix straddling a chunk boundary is still found. All matches are
    collected before choosing, so the PDK precedence stays exactly what it was
    on untruncated text (first in `pdk_cell_prefixes()` order) rather than
    becoming "whichever chunk happened to match first".
    """
    prefixes = pdk_cell_prefixes()
    if not prefixes:
        return None
    longest = max(len(p) for ps in prefixes.values() for p in ps)
    found: set = set()
    try:
        with (project / netlist_rel).open("r", errors="ignore") as fh:
            tail = ""
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                window = tail + chunk
                for name, ps in prefixes.items():
                    if name not in found and any(p in window for p in ps):
                        found.add(name)
                if len(found) == len(prefixes):
                    break
                tail = window[-(longest - 1):] if longest > 1 else ""
    except OSError:
        return None
    for name in prefixes:                      # config order decides, as before
        if name in found:
            return name
    return None


def pdk_cell_prefixes() -> dict:
    """Library prefix(es) each CONFIGURED PDK's flop cells carry.

    Derived from `PDK_CONFIG[*]["dff_cells"]` rather than a second hardcoded
    table, so adding a PDK to the config teaches the sniff about it and the
    two can never drift apart:

        sky130_fd_sc_hd__dfxtp_1  ->  sky130_fd_sc_hd__
        sg13g2_dfrbp_1            ->  sg13g2_

    chip-AGNOSTIC: keyed on standard-cell naming grammar, not on any design,
    vendor part or PDK SKU literal.
    """
    out: dict = {}
    for name, cfg in PDK_CONFIG.items():
        prefixes = set()
        for cell in str(cfg.get("dff_cells") or "").split(","):
            cell = cell.strip()
            if not cell:
                continue
            if "__" in cell:                     # <lib>__<cell>
                prefixes.add(cell.split("__", 1)[0] + "__")
            elif (dsm := re.match(r"(.+_[A-Za-z]+)\d+$", cell)):
                # FLAT DRIVE-STRENGTH naming `<root>_X<drive>` (NanGate45 /
                # FreePDK45: DFF_X1, SDFFRS_X2, NAND2_X1). The trailing integer
                # is a DRIVE STRENGTH, not a cell instance, and there is no
                # `<lib>_` separator. The plain `<lib>_<cell>` split below would
                # yield the over-broad `DFF_`, which is a SUBSTRING of the Yosys
                # generic primitive `$_DFF_P_` — so an UNMAPPED netlist would be
                # misread as this PDK (a false pass of the sniff). Keep the
                # drive-strength FAMILY root incl. the `_X` (`DFF_X`, `SDFFRS_X`):
                # specific to the mapped library, never a substring of `$_DFF_`.
                # No configured `__`-style PDK reaches here (they take the branch
                # above); only genuine `_X<n>` families do. Still derived purely
                # from `dff_cells` — no second table, no vendor/SKU literal.
                prefixes.add(dsm.group(1))
            elif "_" in cell:                    # <lib>_<cell>
                prefixes.add(cell.split("_", 1)[0] + "_")
            else:
                # A FLAT-NAMED library carries no `<lib>_` prefix at all —
                # its flops are just `DFF...`-style names. Deriving nothing
                # dropped such a PDK out of the sniff table entirely, so
                # `sniff_pdk_from_netlist` returned None for a netlist mapped
                # to a library that IS configured, and the drift assertion in
                # the accompanying test failed. Caught only where such a PDK
                # is configured, which is why it passed on the author's host
                # and failed here. Match the whole cell name instead; still
                # derived from `dff_cells`, so there is still no second table
                # to drift, and no literal enters this source.
                prefixes.add(cell)
        if prefixes:
            out[name] = tuple(sorted(prefixes))
    return out


def sniff_pdk_from_netlist(netlist_text: str) -> str | None:
    """Which configured PDK this netlist is MAPPED to, or None.

    Returns None for a generic/unmapped netlist and for one mapped to a
    library this build has no config for — in both cases the caller must
    surface the honest error rather than pick something.
    """
    if not netlist_text:
        return None
    for name, prefixes in pdk_cell_prefixes().items():
        if any(p in netlist_text for p in prefixes):
            return name
    return None


def _count_yaml_block_items(text: str, key: str) -> int:
    """DFT_FCC / 11-d3 — count the `- item` entries of ONE top-level block
    sequence in Fault's flat coverage-metadata YAML.

    Fault writes `ratio:` followed by several sibling top-level sequences
    (`faultPoints:`, `sa0Covered:`, `sa1Covered:`, `sa0Uncovered:`,
    `sa1Uncovered:`).  A naive `grep -c '^- '` sums ALL of them; this walks
    from the requested key to the next top-level key so the count belongs to
    that block only.  Returns 0 when the key is absent — the caller must then
    keep faults_total at 0 rather than invent one.
    """
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines)
                     if ln.strip() == f"{key}:")
    except StopIteration:
        return 0
    n = 0
    for ln in lines[start + 1:]:
        if ln.startswith("- "):
            n += 1
            continue
        if not ln.strip():
            continue
        # any other non-indented, non-item line ends the block
        if not ln[:1].isspace():
            break
    return n


# ── A HIGH EXIT CODE IS NOT A DEATH CERTIFICATE ────────────────────────────
#
# `128+N means death by signal N` is the convention a SHELL uses to REPORT a
# child's signal death. It says nothing about a process that calls exit(N)
# itself with N >= 128, and the elaborator inside the ATPG engine does exactly
# that: Icarus Verilog exits with its ERROR COUNT.
#
#   MEASURED (public, no PDK, no vendor, no design — 153 instantiations of an
#   undeclared module; see the reproduction shipped with this fix):
#       $ iverilog -o /dev/null probe.v > log 2>&1 ; echo $?
#       154
#       $ tail -3 log
#       *** These modules were missing:
#               MISSING_CELL referenced 153 times.
#
# So an ATPG input that is missing >= 128 cell models was being classified
# "killed by signal N", retried _ATPG_MAX_ATTEMPTS times (a deterministic
# failure retried three times fails three times), and then written up as an
# engine crash that "must be re-driven, not waived" — while the true cause,
# `Unknown module type: <cell>`, sat in the log this very function captured.
#
# THE DISCRIMINATOR: a process killed by a signal did not live long enough to
# print a structured diagnosis. When the engine's own error grammar IS present,
# the exit code is the engine's considered answer, not a death certificate.
#
# Deliberately NARROW. Anything ambiguous stays classified as signal death, so
# a genuine SIGSEGV keeps its retry — see the reverse case in the test.
# chip-AGNOSTIC and PDK-AGNOSTIC: keyed only on compiler diagnostic grammar.
_ATPG_SIGNAL_DEATH_FLOOR = 128
_ATPG_ENGINE_DIAGNOSTIC_RE = re.compile(
    r"^\s*\d+\s+error\(s\)\s+during\s+elaboration"
    r"|These modules were missing"
    r"|Unknown module type",
    re.MULTILINE,
)


def atpg_exit_is_signal_death(exit_code: int, engine_log: str) -> bool:
    """True iff `exit_code` should be read as death by signal.

    Below the floor it never is. At or above the floor it is — UNLESS the
    engine printed its own error diagnosis, which a signal-killed process
    cannot have done. Pure; no I/O."""
    if exit_code < _ATPG_SIGNAL_DEATH_FLOOR:
        return False
    return not _ATPG_ENGINE_DIAGNOSTIC_RE.search(engine_log or "")


def parse_atpg_coverage(cov_text: str, atpg_log: str, atpg_exit: int) -> dict:
    """DFT_FCC / 11-d3 — parse a stuck-at ATPG result and DISCLOSE its sources.

    Fault 0.9 reports a run through two channels: its machine-readable
    coverage metadata (``ratio:`` plus the ``faultPoints:`` enumeration, the
    ``--output-coverage-metadata`` file) and its container stdout
    (``Found N fault sites`` / ``Final coverage: Y%``).

    The pre-existing parser read ``coverage_pct`` from EITHER channel but read
    ``faults_total`` from the stdout scrape ONLY. That asymmetry is the defect:
    ``design_one_shot_runner``'s step 11 decided "did the engine measure?" from
    ``faults_total > 0``, so a clean run whose metadata file held a real ratio
    was still classified as an OSS capability gap the moment that one stdout
    line was absent — and the caller then DELETED the coverage artefacts, so
    nothing downstream could contradict the claim.

    Two changes, both source-disclosing rather than value-inventing:

      * ``faults_total`` falls back to a COUNT of the ``faultPoints:`` entries
        in Fault's own metadata. That is a count of the TOOL's output, not an
        estimate of ours. Verified against the reference run
        (spm × ihp-sg13g2): ``len(faultPoints) == 1000`` == the value the
        stdout scrape reports, so the two channels agree exactly.
      * ``coverage_measured`` is stated explicitly, and requires ALL of
        rc==0, a coverage number from a NAMED source, a non-zero coverage and
        a non-empty fault universe — so an engine that could not elaborate the
        netlist (no cell model, generic netlist, DFF-detect failure) still
        reports False and keeps its honest disclosed capability gap. A 0% from
        a non-run is NOT a measurement.

    ``coverage_source`` / ``faults_total_source`` name the channel each number
    came from so a reviewer can tell a parsed number from a counted one.
    """
    coverage_ratio = 0.0
    faults_total = 0
    coverage_source: str | None = None
    faults_total_source: str | None = None

    if cov_text:
        m_ratio = re.search(r"^ratio\s*:\s*([0-9.eE+\-]+)", cov_text,
                            re.MULTILINE)
        if m_ratio:
            val = float(m_ratio.group(1))
            coverage_ratio = val * 100.0 if val <= 1.0 else val
            coverage_source = "fault_coverage_metadata_yaml:ratio"

    # Fallbacks from stdout log
    if coverage_ratio == 0.0:
        m = re.search(r"Final coverage:\s*([0-9.]+)\s*%", atpg_log)
        if m:
            coverage_ratio = float(m.group(1))
            coverage_source = "atpg_stdout:Final coverage"
    if coverage_ratio == 0.0:
        m = re.search(r"[Cc]overage[^0-9]*([0-9.]+)\s*%", atpg_log)
        if m:
            coverage_ratio = float(m.group(1))
            coverage_source = "atpg_stdout:coverage"

    m_total = re.search(r"Found\s+(\d+)\s+fault\s+sites", atpg_log)
    if m_total:
        faults_total = int(m_total.group(1))
        faults_total_source = "atpg_stdout:Found N fault sites"
    elif cov_text:
        n_points = _count_yaml_block_items(cov_text, "faultPoints")
        if n_points > 0:
            faults_total = n_points
            faults_total_source = "fault_coverage_metadata_yaml:faultPoints"

    # Derive covered count rather than counting YAML "-" lines (which also
    # match testVectors etc. and over-counts).
    faults_covered = int(round(faults_total * coverage_ratio / 100.0))

    return {
        "coverage_pct": coverage_ratio,
        "faults_total": faults_total,
        "faults_covered": faults_covered,
        "coverage_source": coverage_source,
        "faults_total_source": faults_total_source,
        "coverage_measured": bool(
            atpg_exit == 0 and coverage_source is not None
            and coverage_ratio > 0.0 and faults_total > 0),
    }


def resolve_mapped_netlist(project: Path, netlist_rel: str) -> tuple[str, str | None]:
    """If `netlist_rel` is generic-unmapped, resolve to a tech-mapped sibling
    in the same synth dir. Returns (resolved_rel, switch_note|None). When the
    given netlist is already mapped (or unreadable, or no mapped sibling
    exists) the original is returned unchanged so a genuine gap fails honestly
    downstream rather than being papered over."""
    nl = project / netlist_rel
    try:
        text = nl.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return netlist_rel, None
    if not is_generic_unmapped(text):
        return netlist_rel, None
    top = _first_module_name(text)
    synth_dir = nl.parent
    candidates: list[Path] = []
    if top:
        candidates.append(synth_dir / f"{top}_synth.v")
    candidates.extend(sorted(synth_dir.glob("*_synth.v")))
    seen: set = set()
    for cand in candidates:
        rp = cand.resolve()
        if cand == nl or rp in seen or not cand.is_file():
            continue
        seen.add(rp)
        try:
            ctext = cand.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if is_generic_unmapped(ctext):
            continue  # also pre-techmap — skip
        resolved_rel = str(cand.relative_to(project))
        return resolved_rel, (
            f"requested netlist '{netlist_rel}' is generic-unmapped "
            f"(Yosys $_…_ primitives — not simulatable by iverilog); "
            f"switched to tech-mapped '{resolved_rel}' for ATPG")
    return netlist_rel, None


# ── Std-cell model + UDP primitives ────────────────────────────────────
# The sky130 std-cell Verilog model (sky130_fd_sc_hd.v) instantiates
# Verilog UDP primitives (e.g. sky130_fd_sc_hd__udp_mux_4to2) that are
# defined in a SIBLING primitives.v which the model does NOT `include`.
# Handed the model alone, iverilog dies with
# `Unknown module type: sky130_fd_sc_hd__udp_mux_4to2`. When a primitives.v
# sits next to the cell model, build a COMBINED model (primitives + cells)
# for `fault atpg`'s iverilog elaboration. chip-AGNOSTIC: keyed only on a
# co-located primitives.v; PDKs whose model is self-contained just get a
# verbatim copy (harmless).
_COMBINED_CELL_MODEL = "phase2/stage2/dft/cell_model_combined.v"


def _cell_model_prep(cell_model: str) -> tuple[str, str]:
    """Return (effective_cell_model_container_path, prep_shell_snippet).

    `cell_model` is a CONTAINER path, so the combine happens inside the
    container. prep concatenates a co-located primitives.v (if present)
    ahead of the model; otherwise copies the model verbatim.

    A cell model may legitimately be MORE THAN ONE FILE. `PDK_CONFIG`'s
    `ihp-sg13g2` entry is the organic case: its own comment states that
    `sg13g2_udp.v` "holds the UDP primitives the stdcell models reference and
    must be read alongside `sg13g2_stdcell.v`", so the configured value is two
    space-separated paths. This function used to treat the whole string as ONE
    path, which made `os.path.dirname` compute a nonsense primitives.v sibling
    and, worse, emit `cp "<pathA> <pathB>" "<combined>"` — a single quoted
    argument naming no file. Measured on spm x ihp-sg13g2 (plugin 1.6.71,
    image sha256:4182c63b10d1) the container answered

        cp: cannot stat '.../sg13g2_udp.v .../sg13g2_stdcell.v':
            No such file or directory

    so no combined model was ever written, `fault atpg` elaborated against
    nothing, and the run reported `faults_total=0` -> `stuck-at coverage=0.00%`
    — a TOOLING gap that reads exactly like an untestable design.

    So the value is split into its component paths and ALL of them are
    concatenated (primitives.v first when a co-located one exists, resolved
    against the FIRST component's directory). A single-path config keeps
    its previous behaviour VERBATIM — including the bare `cp` on the
    no-primitives.v fallback — so nothing about the sky130 / gf180 path
    changes; only the >1-component case is new."""
    parts = shlex.split(cell_model) or [cell_model]
    prim = os.path.dirname(parts[0].rstrip("/")) + "/primitives.v"
    combined = f"/work/{_COMBINED_CELL_MODEL}"
    quoted = " ".join(f'"{p}"' for p in parts)
    # One component -> `cp` (unchanged). Several -> `cat` them together, since
    # `cp` cannot merge and would need a directory destination.
    fallback = (f'cp {quoted} "{combined}"' if len(parts) == 1
                else f'cat {quoted} > "{combined}"')
    # v1.8.43 — IDEMPOTENT. The implicit "prepend a co-located primitives.v"
    # is a convenience for configs that do not name it; a config that DOES name
    # it explicitly must not get it twice, or the combined model redefines every
    # UDP and iverilog rejects it. This became reachable when the sky130 entry
    # was made explicit so that `pdk_cell_models` (Step 29's consumer, which has
    # no such implicit prepend) could see the file at all — the two consumers
    # are held identical by
    # test_sdf_gate_sim_oss_pdk_models::test_pdk_model_table_agrees_with_fault_atpg_run,
    # so making one explicit forces the other.
    if os.path.normpath(prim) in {os.path.normpath(p) for p in parts}:
        return combined, (f'mkdir -p "$(dirname {combined})" && {fallback}')
    prep = (
        f'mkdir -p "$(dirname {combined})" && '
        f'if [ -f "{prim}" ]; then cat "{prim}" {quoted} > "{combined}"; '
        f'else {fallback}; fi'
    )
    return combined, prep


# Iverilog lives in iic-osic-tools but isn't in default PATH; set the env var
# Fault expects, and also prepend to PATH and LD_LIBRARY_PATH so sub-tools
# find the iverilog `vvp` simulator and its shared library (libvvp.so).
IVERILOG_ROOT = "/foss/tools/iverilog"
YOSYS_BIN = "/foss/tools/bin"
ENV_PREAMBLE = (
    f"export FAULT_IVERILOG={IVERILOG_ROOT}/bin/iverilog && "
    f"export FAULT_YOSYS={YOSYS_BIN}/yosys && "
    f"export PATH={IVERILOG_ROOT}/bin:{YOSYS_BIN}:$PATH && "
    f"export LD_LIBRARY_PATH={IVERILOG_ROOT}/lib:${{LD_LIBRARY_PATH:-}} && "
)


#: vibe-ic#623 — how much longer than the caller's budget the CONTAINER-SIDE
#: deadline allows, so an engine that is nearly finished can flush its result
#: instead of having it thrown away.
#:
#: A CAP ON FLUSH TIME, NOT AN ESTIMATE OF HOW LONG ATPG NEEDS — #581 declined
#: to invent the latter and that stands. MEASURED overshoots, same design, two
#: plugin versions and two images, off artefact mtimes alone:
#:
#:     v1.9.27 / 0.2.51   not_run.json 18:58:49   coverage.yml 19:04:20   +331 s
#:     v1.9.8  / 0.2.48   not_run.json 06:28:45   coverage.yml 06:33:57   +312 s
#:
#: both carrying a byte-identical `ratio: 9.16633307933807e-1`. 600 covers both
#: with headroom. The cost is paid ONLY when the engine is still working, and it
#: is bounded: at budget + this, the container kills its own process.
ATPG_FLUSH_GRACE_S = 600


def atpg_container_deadline(timeout: int,
                            flush_grace_s: int = ATPG_FLUSH_GRACE_S) -> int:
    """Seconds the CONTAINER-SIDE deadline allows: the caller's budget plus the
    bounded flush grace, never below 1.

    A pure function so the arithmetic is testable without handing a
    production-sized budget to a launcher — `timeout=1800` in a test is a
    1800-second bound the harness can outlive, and asserting on the number is
    what the test is actually for.

    NEVER 0: coreutils `timeout 0` means NO deadline, which is precisely the
    state this change exists to remove, so it is the one value the arithmetic
    must not be able to produce.
    """
    return max(1, int(timeout) + max(0, int(flush_grace_s)))


#: The two mount points `_run_docker` establishes, and what they are mounts OF.
#: Callers all over this file build container-absolute strings ("/work/<rel>",
#: "/pdk/..."), so a LOCAL run has to say the same thing about the same files.
_WORK_MOUNT = "/work"
_PDK_MOUNT = "/pdk"

#: Announced ONCE per process, so a transcript records which route was taken
#: without one line per tool call.
_LOCAL_ATPG_ROUTE_ANNOUNCED = False


def _localise_mounted_paths(shell: str, project: Path,
                            pdk_dir: "Path | None") -> str:
    """Rewrite the container-absolute paths in `shell` to this filesystem.

    `_run_docker` mounts the project at /work and (optionally) the PDK at /pdk;
    every command it is handed is written against those mount points. Running
    the same command locally means the same files under their REAL paths, so
    the two prefixes are substituted and nothing else is touched.

    Anchored on the mount point followed by `/` or by a word boundary, so a
    token that merely CONTAINS "/work" (a design named `network`, a path like
    `/opt/workspace`) is not rewritten. Substitution is longest-prefix-first
    for the same reason `_to_container_path` sorts its mounts."""
    subs = [(_WORK_MOUNT, str(project))]
    if pdk_dir is not None:
        subs.append((_PDK_MOUNT, str(pdk_dir)))
    subs.sort(key=lambda t: len(t[0]), reverse=True)
    for mount, real in subs:
        shell = re.sub(re.escape(mount) + r"(?=/|\b)", real.rstrip("/"), shell)
    return shell


def _announce_local_atpg_route(project: Path) -> None:
    global _LOCAL_ATPG_ROUTE_ANNOUNCED
    if _LOCAL_ATPG_ROUTE_ANNOUNCED:
        return
    _LOCAL_ATPG_ROUTE_ANNOUNCED = True
    print("[dft] EXEC ROUTE = LOCAL: no docker client on PATH, so the ATPG "
          "engine runs on THIS filesystem instead of in a sibling container "
          "of %s. The project is read at %s, not at %s."
          % (DOCKER_IMAGE, project, _WORK_MOUNT), file=sys.stderr)


def _run_docker(
    project: Path,
    cmd: list[str],
    timeout: int = 600,
    pdk_dir: Path | None = None,
    flush_grace_s: int = ATPG_FLUSH_GRACE_S,
) -> tuple[int, str, str]:
    """Run a command inside iic-osic-tools.
    - project mounted at /work
    - pdk_dir (shared_pdk) mounted at /pdk (optional, for custom PDKs)

    THE DEADLINE IS ENFORCED INSIDE THE CONTAINER (vibe-ic#623), which is this
    repo's own landed doctrine — see `_container_exec`. The client-side
    `timeout=` used to be the only bound, and it bounds the docker CLIENT: on
    expiry Python killed the client while the container carried on, because the
    engine is not a child of the client and no signal crosses the boundary. Two
    separate harms followed from that one fact:

      * THE COMPLETED MEASUREMENT WAS DISCARDED. The engine kept running,
        finished, wrote `coverage.yml` into the mounted project — 331 s and
        312 s after the caller had already recorded "no measurement" — and
        nothing ever looked again. `--rm` then removed the evidence that it had
        run at all.
      * THE CONTAINER WAS NEVER REAPED. It self-removes only when the engine
        finishes on its own; one was recorded still burning a core after the
        flow had ended. `--rm` makes it look self-cleaning, which is why this
        stayed invisible.

    Both are the same defect and coreutils `timeout`, running INSIDE the
    container as the engine's own parent, fixes both: the engine is signalled
    where it lives, so nothing orphans, and expiry becomes an ordinary rc 124
    rather than an exception thrown past callers.

    The container-side deadline is `timeout + flush_grace_s` on purpose. Killing
    an engine that is minutes from finishing, because a size-independent
    constant expired, discards work the run exists to produce; the grace is a
    bounded extension for exactly that, and the caller's own budget still
    governs when the extension starts. `-k` escalates to SIGKILL for an engine
    that ignores SIGTERM while writing.

    The client-side wait is RETAINED, strictly larger, as a backstop for the
    container itself being wedged — which no container-side deadline can cover.
    Because it is larger the container-side deadline always fires first in the
    normal case.

    DEGRADES LOUDLY: an image without `timeout` returns 127 from the shell, so
    the caller learns the deadline could NOT be enforced instead of running
    unbounded behind a deadline that exists only in the caller's belief.
    """
    deadline = atpg_container_deadline(timeout, flush_grace_s)
    _inner = ENV_PREAMBLE + " ".join(cmd)
    _pdk = pdk_dir if (pdk_dir is not None and pdk_dir.exists()) else None

    # LOCAL ROUTE — see `_container_exec.no_container_route`. With no docker
    # client there is no route to ANY container, so the sibling container this
    # would otherwise start cannot be started and every ATPG call returned
    # `127 docker binary not found in PATH`. MEASURED 2026-09-06 in-image:
    # `reports/phase2/dft/scan_chain.json` recorded exactly that, and the step
    # disclosed-skipped, so the run routed the PRE-SCAN netlist while the same
    # tree run host-side routed the SCAN netlist.
    #
    # THE IMAGE IT WOULD START IS THE IMAGE IT IS ALREADY IN. `DOCKER_IMAGE`
    # resolves to ghcr.io/vibeic/vibeic-eda, whose local id
    # (sha256:891063f1…, label version 0.3.46) is the digest a host-side run
    # records as the ATPG tool's provenance — so running locally is the SAME
    # build, not a substitute for it. `ENV_PREAMBLE` exports absolute
    # FAULT_IVERILOG / FAULT_YOSYS paths that resolve on that same filesystem.
    #
    # The deadline is UNCHANGED: coreutils `timeout` is still the engine's own
    # parent, so it is still signalled where it lives; it simply lives here.
    # A host WITH a docker client takes the branch below and the argv is
    # byte-identical to what it has always been.
    if _CE.no_container_route():
        _announce_local_atpg_route(project)
        local_cmd = [
            "bash", "-c",
            (f"timeout -k {_CE.DEFAULT_KILL_GRACE_S} {deadline} bash -c "
             + shlex.quote(_localise_mounted_paths(_inner, project, _pdk))),
        ]
        try:
            r = subprocess.run(local_cmd, capture_output=True, text=True,
                               timeout=deadline + _CE.CLIENT_GRACE_S)
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return 124, "", (
                f"local backstop fired after {deadline + _CE.CLIENT_GRACE_S}s: "
                f"the in-process deadline ({deadline}s) did not fire first")
        except FileNotFoundError:
            return 127, "", (
                "no docker client and no `bash` on PATH — the ATPG engine "
                "could not be reached by either route")

    docker_cmd = [
        "docker", "run", "--rm",
        *_dmem.docker_memory_flags(),
        "--entrypoint", "bash",
        "-v", f"{project}:/work",
    ]
    if _pdk is not None:
        docker_cmd += ["-v", f"{_pdk}:/pdk"]
    docker_cmd += [
        DOCKER_IMAGE,
        "-c", (f"timeout -k {_CE.DEFAULT_KILL_GRACE_S} {deadline} bash -c "
               + shlex.quote(_inner)),
    ]
    try:
        r = subprocess.run(docker_cmd, capture_output=True, text=True,
                           timeout=deadline + _CE.CLIENT_GRACE_S)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        # The BACKSTOP fired, which now means the container itself is wedged —
        # the container-side deadline is strictly earlier, so a merely-slow
        # engine can no longer reach this branch.
        return 124, "", (
            f"docker client backstop fired after "
            f"{deadline + _CE.CLIENT_GRACE_S}s: the container-side deadline "
            f"({deadline}s) did not fire first, so the container — not the "
            f"engine — is unresponsive")
    except FileNotFoundError:
        return 127, "", "docker binary not found in PATH"


# ── Transition (at-speed) fault model ──────────────────────────────────
# A SECOND fault model alongside stuck-at. The mechanism (launch-off-capture
# two-pattern at-speed test) is always emitted as a plan; the coverage NUMBER
# is only reported if the OSS engine can actually run transition ATPG.

_TRANSITION_PLAN_TEMPLATE = """\
# Transition (at-speed) ATPG plan — launch-off-capture

Design clock : {clock}
Cut netlist  : {cut_rel}
Cell model   : {cell_model}
Target       : stuck-at-independent transition-fault coverage >= {target:.2f}%

## Fault model
Transition (a.k.a. delay / at-speed) faults model a node that is
functionally correct but too SLOW: a slow-to-rise (STR) or slow-to-fall
(STF) fault at each gate terminal. Detecting them requires a TWO-PATTERN
test (an initialization vector V1 then a launch vector V2) applied so the
transition is launched and captured at the rated (at-speed) clock period.

## Launch-off-capture (LOC) mechanism
1. Scan-in the initialization pattern V1 through the scan chain
   (scan_enable = 1) — the same scan chain inserted for stuck-at.
2. De-assert scan_enable (functional mode).
3. Pulse the functional clock at the rated period to LAUNCH the transition
   (V1 -> V2 combinational evolution) and CAPTURE the response one at-speed
   cycle later.
4. Scan-out the captured response and compare against the fault-free
   expected value.
(An alternative, launch-off-shift/LOS, launches from the last scan-shift
edge; LOC is preferred because it needs no at-speed scan-enable.)

## Engine capability
Engine probed : Fault (cloudv-io/fault) `fault atpg`
Supported     : {supported}
{capability_line}

## Honesty note
{honesty_note}
"""


def _fault_supports_transition(project: Path,
                               pdk_dir: Path | None = None
                               ) -> tuple[bool, str]:
    """Probe whether the Fault ATPG engine advertises a transition / at-speed
    capability by grepping `fault atpg --help`. Returns (supported, reason).

    Fault is a single-pattern combinational stuck-at engine and exposes no
    transition flag, so this returns (False, <reason>) in practice. The probe
    is honest — it never assumes support; it reads the tool's own help text.
    """
    ec, out, err = _run_docker(
        project, ["fault", "atpg", "--help"], timeout=120, pdk_dir=pdk_dir)
    help_text = (out + "\n" + err).lower()
    if ec not in (0, 1, 2) or not help_text.strip():
        # Could not run the probe (no docker / image). Report honestly as
        # "unknown -> treated as unsupported" rather than faking capability.
        return False, (
            "could not probe `fault atpg --help` (engine/docker unavailable, "
            f"exit={ec}); transition capability UNKNOWN — treated as "
            "unsupported (no fabricated transition number)")
    for kw in _TRANSITION_CAPABILITY_KEYWORDS:
        if kw in help_text:
            return True, (
                f"`fault atpg --help` advertises a '{kw}' flag — transition "
                "ATPG appears supported")
    return False, (
        "`fault atpg --help` exposes only single-pattern combinational "
        "stuck-at ATPG (no transition / at-speed / launch-off-capture / "
        "delay-fault / two-pattern flag) — the Fault engine cannot generate "
        "at-speed patterns")


def build_transition_report(supported: bool,
                            reason: str,
                            transition_target: float,
                            plan_rel: str,
                            measured_pct: float | None = None) -> dict:
    """Pure assembler for the transition fault-model block. NEVER fabricates
    a coverage number: if the engine is unsupported, coverage_pct stays None
    and engine_limited=True with a documented reason.

    chip-AGNOSTIC."""
    if supported and measured_pct is not None:
        ge = measured_pct >= transition_target
        return {
            "fault_model": "transition",
            "supported": True,
            "engine_limited": False,
            "coverage_pct": round(measured_pct, 4),
            "target_pct": transition_target,
            "ge_target": ge,
            "reason": reason,
            "plan_file": plan_rel,
        }
    # Unsupported (or supported-but-no-number): honest engine-limited record.
    return {
        "fault_model": "transition",
        "supported": bool(supported),
        "engine_limited": True,
        "coverage_pct": None,
        "target_pct": transition_target,
        "ge_target": None,
        "reason": reason,
        "plan_file": plan_rel,
    }


def run_transition_atpg(project: Path,
                        cut_rel: str,
                        cell_model: str,
                        clock: str,
                        transition_target: float,
                        pdk_dir: Path | None = None,
                        probe_fn=None) -> dict:
    """Emit the launch-off-capture at-speed mechanism plan and (if the engine
    supports it) a real transition-coverage number. Fault does not, so this
    writes the plan + an honest engine_limited record.

    `probe_fn(project, pdk_dir) -> (supported, reason)` is injectable for
    testing; defaults to the real `fault atpg --help` probe.
    """
    probe = probe_fn or _fault_supports_transition
    supported, reason = probe(project, pdk_dir)

    plan_rel = "phase2/stage2/dft/transition_atpg_plan.md"
    if supported:
        capability_line = f"Capability     : {reason}"
        honesty_note = (
            "Engine reports transition capability. Coverage NUMBER below is a "
            "real measurement from the at-speed ATPG run.")
    else:
        capability_line = f"Limitation     : {reason}"
        honesty_note = (
            "The at-speed pattern set is NOT generated because the open-source "
            "Fault engine cannot do transition ATPG. Per DFT-honesty doctrine "
            "we emit the mechanism/plan and record the engine limitation "
            "rather than fabricate a transition-coverage number. A commercial "
            "at-speed ATPG tool (or an OSS engine that gains delay-fault "
            "support) is required to close this coverage.")

    plan_text = _TRANSITION_PLAN_TEMPLATE.format(
        clock=clock,
        cut_rel=cut_rel,
        cell_model=cell_model,
        target=transition_target,
        supported=str(supported),
        capability_line=capability_line,
        honesty_note=honesty_note,
    )
    try:
        (project / plan_rel).parent.mkdir(parents=True, exist_ok=True)
        (project / plan_rel).write_text(plan_text)
    except OSError:
        pass

    # Fault has no transition mode, so we never obtain a measured number here.
    measured = None
    return build_transition_report(
        supported, reason, transition_target, plan_rel, measured)


def _write_coverage_rpt(path: Path, *, clock: str, netlist_rel: str, pdk: str,
                        coverage_ratio: float, faults_covered: int,
                        faults_total: int, min_coverage: float,
                        trans_line: str, cov_out: str, tv_out: str) -> None:
    """Write the human-readable stuck-at coverage report (atpg_coverage.rpt).

    Factored out of run_fault so the CONTRACT-NAMED report can be written twice:
    a durable stuck-at snapshot the moment stuck-at is measured, then a final
    version once the (independent, long-running) transition pass has resolved.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "Fault ATPG Coverage Report\n"
        "==========================\n"
        f"Clock         : {clock}\n"
        f"Netlist       : {netlist_rel}\n"
        f"PDK           : {pdk}\n"
        f"Stuck-at %    : {coverage_ratio:.2f}\n"
        f"Covered / Total: {faults_covered} / {faults_total}\n"
        f"Target (min)  : {min_coverage:.2f}\n"
        f"Result        : {'PASS' if coverage_ratio >= min_coverage else 'FAIL'}\n"
        f"{trans_line}"
        "\n"
        f"(coverage metadata: {cov_out})\n"
        f"(test vectors    : {tv_out})\n"
    )


def _write_coverage_json(path: Path, report: dict) -> None:
    """Write the machine-readable coverage report (reports/dft/coverage.json).

    This is the artefact `dft_signoff_check` / `dft_atpg_coverage_check` read.
    Written by run_fault ITSELF (not deferred to the CLI wrapper) so an
    in-process caller gets the contract-named artefact too.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))


def run_fault(
    project: Path,
    netlist_rel: str,
    clock: str,
    pdk: str,
    min_coverage: float,
    tv_count: int,
    pdk_dir: Path | None = None,
    reset: str | None = None,
    reset_active_low: bool = False,
    transition_target: float = FOUNDRY_TRANSITION_DEFAULT,
    run_transition: bool = True,
    transition_probe_fn=None,
    cell_model_override: str | None = None,
    dff_cells_override: str | None = None,
    json_out: "Path | str | None" = None,
) -> tuple[int, dict]:
    """Run Fault cut+atpg in the Docker container. Returns (exit, report_dict).

    cell_model_override : explicit Verilog cell-model path (container-absolute
        or project-relative → /work/...). Wins over the PDK config; lets the
        commercial-PDK model live inside the run dir for reproducibility.
    dff_cells_override  : explicit `fault cut --dff` list. When None, the flop
        cells are auto-detected from the netlist and unioned with the PDK-config
        seed (detect_dff_cells + merge_dff_cells)."""
    # ATPG needs the TECH-MAPPED netlist — self-heal a generic-unmapped one
    # to the mapped `<top>_synth.v` sibling (fixes the DFT step handing over
    # phase2/stage2/synth/netlist.v, which is the generic LEC netlist).
    #
    # THIS MUST PRECEDE THE PDK CHECK. It used to sit after it, which made the
    # self-heal unreachable in exactly the case it exists for: the caller
    # sniffs the PDK from the GENERIC netlist, that netlist names no library
    # cells, so the caller passes an unsupported value, and `run_fault`
    # returned `unsupported pdk` before ever resolving the mapped sibling that
    # would have identified the PDK. Measured on a real converged cell — the
    # orchestrator sent `--pdk unmapped` for a design whose mapped netlist
    # carries 285 sky130 cells, ATPG never started, and the step recorded a
    # disclosed "OSS engine cannot handle this netlist" capability gap whose
    # every clause was false.
    netlist_rel, netlist_switch_note = resolve_mapped_netlist(project, netlist_rel)

    pdk_cfg = PDK_CONFIG.get(pdk)
    pdk_sniff_note = None
    if pdk_cfg is None and not cell_model_override:
        # Derive the PDK from the netlist ATPG will ACTUALLY run on. This is
        # not the "callee substitutes its own default" behaviour ORGANIC #410
        # removed — nothing is assumed; the library is read off the cell names
        # in the resolved artefact, and if they name no configured library the
        # honest error below still stands.
        sniffed = sniff_pdk_over_whole_netlist(project, netlist_rel)
        if sniffed:
            pdk_sniff_note = (
                f"caller passed unsupported pdk {pdk!r}; derived {sniffed!r} "
                f"from the cell names in the resolved netlist "
                f"{netlist_rel!r}")
            pdk, pdk_cfg = sniffed, PDK_CONFIG[sniffed]
    if pdk_cfg is None and not cell_model_override:
        return 2, {"error": f"unsupported pdk: {pdk}. "
                            f"Supported: {list(PDK_CONFIG.keys())} "
                            f"(or pass --cell-model-path for a custom library)",
                   "netlist_used": netlist_rel,
                   "pdk_sniff": "no configured library's cells found in the "
                                "resolved netlist"}
    cell_model = resolve_cell_model(cell_model_override, pdk_cfg)
    if not cell_model:
        return 2, {"error": "no Verilog cell model resolved: pass "
                            "--cell-model-path or use a PDK with a configured "
                            "cell_model"}
    if pdk == "gf180" and not cell_model_override:
        # ciel's gf180mcu path is content-addressed (versions/<hash>/...) and
        # the hash PDK_CONFIG carries is a point-in-time fallback that goes
        # stale whenever vibeic-eda's gf180mcu pin advances — see
        # pdk_cell_models.GF180_CIEL_HASH_FALLBACK. Re-resolve it live against
        # THIS run's own image/container before trusting it.
        _parts = cell_model.split(" ")
        _resolved = _pcm.materialize_gf180_paths(
            _parts, lambda argv, t: _run_docker(project, argv, timeout=t,
                                                pdk_dir=pdk_dir))
        cell_model = " ".join(_resolved)
    # Flop-cell resolution: explicit override wins; else auto-detect from the
    # netlist and union with the PDK-config seed so cut never misses the real
    # flop cell (fixes seed/netlist mismatch, e.g. DFFHQD1 vs seed DFFRQD1).
    if dff_cells_override:
        dff_cells = dff_cells_override
    else:
        try:
            netlist_text = (project / netlist_rel).read_text(
                encoding="utf-8", errors="replace")
        except OSError:
            netlist_text = ""
        detected = detect_dff_cells(netlist_text)
        seed = pdk_cfg.get("dff_cells") if pdk_cfg else None
        dff_cells = merge_dff_cells(seed, detected) or (seed or "DFF")

    # Prepare output paths (relative to project / /work)
    dft_dir = _pl.dft_dir(project)
    reports_dft = (_pl.reports_phase2_dir(project) / "dft")
    dft_dir.mkdir(parents=True, exist_ok=True)
    reports_dft.mkdir(parents=True, exist_ok=True)

    cut_out = "phase2/stage2/dft/cut_netlist.v"
    tv_out = "phase2/stage2/dft/tv.json"
    cov_out = "phase2/stage2/dft/coverage.yml"
    rpt_out = "phase2/stage2/dft/atpg_coverage.rpt"

    netlist_abs = f"/work/{netlist_rel}"
    cut_abs = f"/work/{cut_out}"

    # `fault cut`/`fault atpg` abort on any `inout` port — AUCOHL/Fault's
    # Module.Port.extract has no bidirectional polarity (see _dft_netlist_ports).
    # `fault cut` sometimes SURVIVES an inout and passes it through into the cut
    # netlist, and then `fault atpg` dies on it with exit 70 / faults_total=0 —
    # which reads exactly like an "engine-limited" coverage gap. Measured on
    # caravel_user_project x sky130A: `inout [28:0] analog_io;` made ATPG exit 70
    # while the engine measures 60.5% once it is gone. Strip UNCONNECTED inout
    # ports from the netlist the cut reads; the cut netlist is a fault-sim
    # intermediate that is never built, so no restore is needed (an inout with no
    # scannable logic — an analog pass-through / unbonded pad — contributes no
    # fault the coverage number depends on, and is not part of the testable
    # logic). A CONNECTED inout is left in place (it carries real nets) and the
    # honest failure is reported rather than a wrong netlist produced.
    try:
        import _dft_netlist_ports as _dnp        # sibling module; no import cycle
        _nl_txt = (project / netlist_rel).read_text(errors="replace")
        _unconn = [n for n in _dnp.find_inout_ports(_nl_txt)
                   if not _dnp.port_is_connected(_nl_txt, n)]
        if _unconn:
            _stripped = _dnp.strip_inout_ports(_nl_txt, _unconn)
            if not (set(_dnp.find_inout_ports(_stripped)) & set(_unconn)):
                _atpg_in_rel = "phase2/stage2/dft/atpg_input.v"
                (project / _atpg_in_rel).write_text(_stripped, encoding="utf-8")
                netlist_abs = f"/work/{_atpg_in_rel}"
    except Exception:
        pass    # fall back to the original netlist; fault then reports honestly

    # Step A: fault cut (DFF-flattening). Note: fault cut does NOT take --top.
    cut_cmd = [
        "fault", "cut",
        "--output", cut_abs,
        "--dff", dff_cells,
        "--clock", clock,
    ]
    if reset:
        cut_cmd += ["--reset", reset]
        if reset_active_low:
            cut_cmd += ["--reset-active-low"]
    cut_cmd.append(netlist_abs)

    ec, out, err = _run_docker(project, cut_cmd, timeout=120, pdk_dir=pdk_dir)
    cut_log = (out + "\n" + err)[-1000:]
    if ec != 0 or not (project / cut_out).exists():
        return 1, {
            "stage": "cut",
            "exit": ec,
            "log_tail": cut_log,
        }

    # Step B: fault atpg. iverilog (which Fault drives to simulate the
    # cell model) cannot resolve the model's UDP primitives on its own, so
    # build a combined model (primitives + cells) first and point atpg at it.
    eff_cell_model, cell_prep = _cell_model_prep(cell_model)
    # RESTORED 2026-07-31. v1.8.48 — a commit whose message is entirely about a
    # spare-net filter in signoff_spef_repair.tcl and mentions ATPG zero times —
    # deleted 166 lines from this file as collateral: the reset-bypass decision,
    # its load counter, the --reset flags, and this async set/reset observability
    # integration. Nine tests named for those properties went red and stayed red.
    # The augmented model is written to its OWN file and `cut_netlist.v` is left
    # BYTE-FOR-BYTE ALONE: the transition/path-delay/SDD ATPG producers all
    # re-read that same cut netlist, so mutating it in place would silently
    # change THEIR fault sets and miters (it broke DT1 outright when tried).
    # One producer must never rewrite a shared upstream artefact.
    async_obs: dict | None = None
    try:
        import fault_cut_async_observe as _fcao      # local import: no cycle
        lib_ctr = _atpg_liberty_container_path(project, cell_model, pdk_dir)
        if lib_ctr:
            ec_l, lib_text, _ = _run_docker(
                project, ["cat", lib_ctr], timeout=180, pdk_dir=pdk_dir)
            if ec_l == 0 and lib_text.strip():
                cut_text = (project / cut_out).read_text(errors="replace")
                adds, async_obs = _fcao.build_additions(
                    (project / netlist_rel).read_text(errors="replace"),
                    cut_text, lib_text)
                async_obs["liberty"] = lib_ctr
                if adds:
                    obs_rel = str(Path(cut_out).with_name(
                        Path(cut_out).stem + "_asyncobs.v"))
                    (project / obs_rel).write_text(
                        _fcao.augment_cut(cut_text, adds))
                    cut_abs = f"/work/{obs_rel}"      # ATPG reads the augmented one
                    async_obs["atpg_netlist"] = obs_rel
                    async_obs["shared_cut_netlist_untouched"] = cut_out
            else:
                async_obs = {"skipped": f"liberty unreadable in container: {lib_ctr}"}
        else:
            async_obs = {"skipped": "no std-cell liberty resolved from cell model"}
    except Exception as exc:                          # never fail the ATPG on this
        async_obs = {"error": f"{type(exc).__name__}: {exc}"}

    atpg_cmd = [
        "fault", "atpg",
        "--cell-model", eff_cell_model,
        "--clock", clock,
    ]
    # `fault atpg` takes the SAME BypassOptions group as `fault cut`
    # (Entries/atpg.swift `@OptionGroup var bypass: BypassOptions`), and that
    # group declares `var resetName: String = "rst"`. So omitting --reset does
    # not mean "this design has no reset" — it means the tool silently adopts
    # the name `rst`. On a design whose reset is called anything else, the real
    # reset is never bypassed, stays ASSERTED through the ATPG simulation, and
    # the flops it drives are frozen: the coverage number that comes back is
    # measured on a design held in reset.
    #
    # `fault cut` was already passing it; the pattern-generating invocation was
    # not. Restored 2026-07-31 — the guard test named for exactly this property
    # (test_atpg_always_passes_reset_explicitly) had been RED at origin/main and
    # was reporting it correctly the whole time; nobody was reading it.
    # WHICH name to pass is a structural question, not a config one. The cut
    # netlist is a purely COMBINATIONAL full-scan model — every flop became a
    # pseudo-PI/pseudo-PO pair — so every primary input is scan-controllable and
    # none should be frozen. `_atpg_reset_bypass_name` decides by counting loads:
    # a candidate WITH loads is live combinational logic (a synchronous reset, or
    # one that also feeds datapath), and bypassing it would freeze its whole
    # fanout cone and make a testable design read as untestable; a candidate with
    # NO loads only drove flop async pins the cut already removed, so bypassing
    # is a no-op.
    #
    # v1.8.91 passed `reset` unconditionally. That restored the flag but not this
    # decision, and unconditional is WRONG in the synchronous case — it is the
    # exact defect v1.8.43 fixed. Corrected here.
    _bypass_name, _bypass_note = _atpg_reset_bypass_name(Path(cut_abs), reset, clock)
    atpg_cmd += ["--reset", _bypass_name]
    if reset_active_low and _bypass_name != _ATPG_NO_RESET_BYPASS:
        atpg_cmd += ["--reset-active-low"]
    atpg_cmd += [
        "-o", f"/work/{tv_out}",
        "--output-coverage-metadata", f"/work/{cov_out}",
        "-m", str(min_coverage),
        "-v", str(tv_count),
        cut_abs,
    ]
    atpg_shell = cell_prep + " && " + " ".join(atpg_cmd)
    # ── A SIGNAL-DEATH EXIT IS A CRASH, NOT A CAPABILITY LIMIT ─────────────
    #
    # MEASURED (spm x sky130A, plugin v1.8.50, image 0.2.45). On a clean
    # single-pass run `fault atpg` came back `exit 139` (= 128 + SIGSEGV 11)
    # with `faults_total=0`, and the step disclosed "OSS Fault ATPG could not
    # measure ... Sign-off ATPG coverage is a disclosed OSS capability gap".
    # The input was not at fault and the failure is not deterministic:
    #
    #   md5 spm_synth.v (the ATPG input) IDENTICAL to the tree where it worked
    #     a703d073d3305951f63869adec55c3a0   both trees
    #   cut_netlist.v differed ONLY in its "Generated on:" timestamp comment
    #   3 retries of the identical call on the identical tree:
    #     rc=0 atpg_exit=0 cov=96.7129647731781 faults=1080   (x3, byte-equal)
    #   host had 113 GB free and load 3.84 -- not a resource shortage
    #
    # So the engine intermittently dies of a signal on work it otherwise
    # completes deterministically. Two consequences, both handled here:
    #
    #  1. RETRY. A signal death is transient by the measurement above, so it is
    #     retried rather than converted into a permanent verdict on the first
    #     sample. Bounded, and only on signal death (>= 128): a clean non-zero
    #     exit is the engine's own considered answer and is NEVER retried, so a
    #     design that genuinely fails its coverage target still fails on the
    #     first try, at the same speed, with the same number.
    #  2. NAME IT. The exit code and the retry history are recorded so a
    #     consumer can tell a crash from a capability limit instead of having
    #     both collapse into "the artefact is absent". Reporting a SIGSEGV as
    #     "the OSS tool cannot do this" is a false capability gap.
    #
    # chip-AGNOSTIC and PDK-AGNOSTIC: keyed only on the POSIX convention that
    # 128+N means death by signal N -- AND, since this fix, on the engine's own
    # diagnostic grammar, because that convention is a shell's reporting
    # convention and not a property of the exit code. See
    # atpg_exit_is_signal_death() above.
    # ── SIZE-SCALED WALL ────────────────────────────────────────────────────
    # This was a fixed `timeout=1800`. A fixed wall asks "has 30 minutes
    # passed", and is read as "can this engine grade this design" — two
    # different questions that agree only on designs small enough for the
    # answer not to matter.
    #
    # MEASURED (ibex x sky130A, 2026-08-05). `fault` ATPG on the sky130-mapped
    # 31k-cell netlist RUNS: `fault chain` built a real scan chain from
    # `ibex_core_synth.v` against the PDK liberty, with real scan DFFs, and the
    # engine was mid-grade when the wall expired. Its own record says so —
    # "the engine was running, not unable ... a BUDGET outcome, not a
    # capability gap". A fixed 1800 s turned a large design's honest partial
    # coverage into an absent measurement.
    #
    # The sibling at-speed engine already fixed this and its comment names
    # "the old 1800 s" as the defect; the same constant was still live here.
    # `_scaled_wall_budget` and `parse_cut_ports` are imported rather than
    # copied, so the two engines cannot drift apart, and the size signal is the
    # SAME quantity the coefficient was measured against: the pseudo-PI/PO
    # pairs the cut exposed, i.e. the flop count.
    #
    # The caller's 1800 stays the FLOOR — a small design's wall is unchanged to
    # the second. NOT MEASURED, and stated rather than hidden: the per-flop
    # coefficient was measured for the 2-frame LOC miter of the at-speed
    # engine, not for stuck-at. It is used here as a floor-RAISING term with
    # the same campaign ceiling, which can only ever give a large design more
    # room; the budget actually used is recorded below so the next round can
    # measure the real stuck-at curve instead of inheriting this one.
    _atpg_wall = 1800
    _atpg_scan_flops = 0
    try:
        import transition_fault_atpg_run as _tdf
        _cut_for_wall = project / cut_out
        if _cut_for_wall.is_file():
            _, _, _, _pairs = _tdf.parse_cut_ports(
                _cut_for_wall.read_text(errors="replace"))
            _atpg_scan_flops = len(_pairs)
            _atpg_wall = _tdf._scaled_wall_budget(1800, _atpg_scan_flops)
    except Exception:
        pass          # unreadable cut -> the floor, never a guess

    _ATPG_MAX_ATTEMPTS = 3
    atpg_attempts: list[int] = []
    ec, out, err = -1, "", ""
    for _attempt in range(1, _ATPG_MAX_ATTEMPTS + 1):
        # Clear the metadata BEFORE each attempt so its presence afterwards is
        # evidence about THIS attempt. Without this, a partial file left by a
        # crashed attempt would be read as that attempt's result and suppress
        # the retry — the exact "stale artefact read as fresh" failure mode.
        try:
            (project / cov_out).unlink()
        except OSError:
            pass
        ec, out, err = _run_docker(project, [atpg_shell], timeout=_atpg_wall,
                                   pdk_dir=pdk_dir)
        atpg_attempts.append(ec)
        if not atpg_exit_is_signal_death(ec, out + "\n" + err):
            break            # clean exit (0 or a considered non-zero) — done
        if (project / cov_out).exists():
            break            # died late but the metadata landed — keep it
    atpg_log = (out + "\n" + err)[-2000:]
    atpg_signal_death = atpg_exit_is_signal_death(ec, out + "\n" + err)

    cov_file = project / cov_out
    cov_text = cov_file.read_text() if cov_file.exists() else ""
    parsed = parse_atpg_coverage(cov_text, atpg_log, ec)
    coverage_ratio = parsed["coverage_pct"]
    faults_total = parsed["faults_total"]
    faults_covered = parsed["faults_covered"]
    coverage_source = parsed["coverage_source"]
    faults_total_source = parsed["faults_total_source"]
    coverage_measured = parsed["coverage_measured"]

    # ── DURABLE STUCK-AT SNAPSHOT — emit the CONTRACT-NAMED artefacts NOW ──
    #
    # The `fault atpg` engine has written coverage.yml (its native
    # machine-readable metadata) and the stuck-at ratio is parsed. Emit the two
    # artefacts the sign-off gate actually reads — atpg_coverage.rpt and
    # reports/dft/coverage.json — RIGHT HERE, before the expensive,
    # timeout-prone transition (at-speed) pass below and independent of the CLI
    # wrapper's own json write.
    #
    # WHY (measured, opentitan_aes × sky130A, r5→r8): stuck-at ATPG completed
    # and left coverage.yml carrying a real ratio (0.507), but the
    # machine-readable coverage.json / atpg_coverage.rpt the gate NAMES were
    # written only AFTER the transition pass — and coverage.json only in
    # main(). When the transition pass ran long and the run was interrupted (or
    # a library caller used run_fault() directly), the completed stuck-at
    # measurement survived only in coverage.yml, which `dft_signoff_check` does
    # not read, so it reported "no DFT/ATPG coverage evidence found" on a design
    # that HAD been measured — a measurement that exists reading identically to
    # a tool that never ran. A completed measurement must not become invisible
    # to the gate because a SECOND, independent fault model ran long afterwards.
    #
    # This is NOT a second file written only to be found: it is the producer's
    # OWN declared output (see this module's docstring — "reports/dft/
    # coverage.json … machine-readable"), emitted at the point in its lifecycle
    # where the real data first exists. chip-AGNOSTIC and PDK-AGNOSTIC: no
    # design/PDK literal; keyed only on the fixed two-fault-model ordering.
    scan_netlist_present = (
        project / "phase2/stage2/dft/scan_netlist.v").is_file()
    json_out_path = (Path(json_out) if json_out is not None
                     else _pl.report_path(project, "dft/coverage.json"))

    # ── TEST coverage (vibe-ic#603): raw FAULT coverage is what Fault reports;
    # sign-off TEST coverage removes the ATPG-UNTESTABLE faults (the unused pad
    # frame: unobservable inputs / constant-driven outputs) from the denominator.
    # Both numbers are kept distinct so neither stands in for the other. The
    # std-cell Liberty (pin directions) lives in the EDA container, so it is read
    # out host-side, exactly as fault_cut_async_observe does. SOUND-only: the
    # excluded set is UNCOVERED ∩ structurally-untestable, so a detected fault is
    # never removed and test coverage can never exceed 100 %.
    test_coverage = None
    try:
        import dft_test_coverage as _dtc            # sibling; no import cycle
        import atpg_untestable_fault_classify as _auc
        if cov_file.exists() and (project / cut_out).exists():
            _lib_ctr = _atpg_liberty_container_path(project, cell_model, pdk_dir)
            if _lib_ctr:
                _ec_l, _lib_text, _ = _run_docker(
                    project, ["cat", _lib_ctr], timeout=120, pdk_dir=pdk_dir)
                if _ec_l == 0 and _lib_text:
                    _dirs = _auc.parse_liberty_pin_directions(_lib_text)
                    test_coverage = _dtc.compute(
                        project / cut_out, cov_file, directions=_dirs)
                    (project / "phase2/stage2/dft/test_coverage.json").write_text(
                        json.dumps(test_coverage, indent=2))
    except Exception as _tc_exc:   # measurement-only: never fail the run on it
        test_coverage = {"computed": False, "reason": f"exception: {_tc_exc}"}

    def _assemble_report(transition_block):
        rep = {
            "tool": "fault",
            "clock": clock,
            "pdk": pdk,
            "netlist": netlist_rel,
            # DECLARED, so no consumer has to infer this program's outputs.
            # `cut_netlist.v` is the combinational ATPG view; the scan-INSERTED
            # implementation netlist is a different artefact, different owner.
            "cut_netlist": cut_out,
            "writes_scan_netlist": False,
            "scan_netlist_present": scan_netlist_present,
            "scan_netlist_owner": "fault_scan_chain_insert.py (`fault chain`)",
            "netlist_switch_note": netlist_switch_note,
            # Disclosed so a reader can see the PDK was DERIVED, and from what.
            "pdk_sniff_note": pdk_sniff_note,
            "pdk_used": pdk,
            # vibe-ic#603 (PR #615) folded into PR #610's durable snapshot:
            # raw FAULT coverage and sign-off TEST coverage are kept DISTINCT
            # so neither stands in for the other, and the snapshot carries
            # both from the moment stuck-at is first measured.
            "test_coverage": test_coverage,
            # THE COMPLETE #615 FIELD SET, taken from that PR verbatim
            # rather than retyped: `dft_atpg_coverage_check` reads
            # `test_coverage_pct` by NAME, and a hand-copied subset had
            # already dropped two of them — a merge that compiles and
            # leaves the consumer blind.
            # vibe-ic#603 — RAW fault coverage above (coverage_pct) is Fault's ratio;
            # TEST coverage below is detected / (total − ATPG-untestable). Distinct on
            # purpose: the gate judges TEST coverage, the report keeps RAW visible.
            "test_coverage_pct": (test_coverage.get("test_coverage_pct")
                                  if test_coverage and test_coverage.get("computed")
                                  else None),
            "test_coverage_measured": bool(
                test_coverage and test_coverage.get("computed")),
            "test_coverage_untestable_excluded": (
                test_coverage.get("untestable_faults_excluded")
                if test_coverage and test_coverage.get("computed") else None),
            "test_coverage_source": (
                "dft_test_coverage: (unobservable|uncontrollable) \u2229 uncovered"
                if test_coverage and test_coverage.get("computed")
                else (test_coverage.get("reason") if test_coverage else
                      "not computed (no liberty / no cut netlist / no "
                      "coverage.yml)")),
            "coverage_pct": coverage_ratio,
            "faults_covered": faults_covered,
            "faults_total": faults_total,
            # DFT_FCC / 11-d3 — the producer DECLARES whether this is a real
            # measurement, and names the artefact each number came from.
            "coverage_measured": coverage_measured,
            "coverage_source": coverage_source,
            "faults_total_source": faults_total_source,
            "cell_model": cell_model,
            "dff_cells": dff_cells,
            "target_pct": min_coverage,
            "stuck_at_ge_target": coverage_ratio >= min_coverage,
            "atpg_exit": ec,
            # Retry history + crash classification, so a consumer can tell "the
            # engine crashed" from "the engine answered".
            "atpg_attempt_exits": atpg_attempts,
            # The budget this run actually had, and the design size it was
            # sized from. "exceeded its wall budget" without the number is a
            # verdict nobody downstream can check or re-plan against.
            "atpg_wall_budget_s": _atpg_wall,
            "atpg_wall_budget_basis": (
                f"floor 1800 s + per-flop term on {_atpg_scan_flops} scan flop(s)"
                if _atpg_scan_flops else "floor 1800 s (no cut flops resolved)"),
            "atpg_signal_death": atpg_signal_death,
            "log_tail": atpg_log[-500:],
        }
        if transition_block is not None:
            rep["transition"] = transition_block
            # Flat mirror fields so a simple consumer can read them without
            # descending into the nested block.
            rep["transition_coverage_pct"] = transition_block.get("coverage_pct")
            rep["transition_target_pct"] = transition_block.get("target_pct")
            rep["transition_ge_target"] = transition_block.get("ge_target")
            rep["transition_supported"] = transition_block.get("supported")
            rep["transition_engine_limited"] = transition_block.get(
                "engine_limited")
        return rep

    # Durable stuck-at-only snapshot: the at-speed pass has not run yet.
    _pending_trans = (
        "Transition     : PENDING (at-speed pass not yet run)\n"
        if run_transition else "Transition     : SKIPPED (--no-transition)\n")
    _write_coverage_rpt(
        project / rpt_out, clock=clock, netlist_rel=netlist_rel, pdk=pdk,
        coverage_ratio=coverage_ratio, faults_covered=faults_covered,
        faults_total=faults_total, min_coverage=min_coverage,
        trans_line=_pending_trans, cov_out=cov_out, tv_out=tv_out)
    _write_coverage_json(json_out_path, _assemble_report(None))

    # ── Transition (at-speed) fault model — SECOND model, own target ──
    transition = None
    if run_transition:
        transition = run_transition_atpg(
            project,
            cut_rel=cut_out,
            cell_model=cell_model,
            clock=clock,
            transition_target=transition_target,
            pdk_dir=pdk_dir,
            probe_fn=transition_probe_fn,
        )

    # Human-readable transition summary line for the rpt.
    if transition is None:
        trans_line = "Transition     : SKIPPED (--no-transition)\n"
    elif transition.get("engine_limited"):
        trans_line = (
            f"Transition %   : ENGINE-LIMITED (target >= "
            f"{transition_target:.2f}%; see transition_atpg_plan.md)\n")
    else:
        tc = transition.get("coverage_pct")
        trans_line = (
            f"Transition %   : {tc:.2f} "
            f"(target {transition_target:.2f}%, "
            f"{'PASS' if transition.get('ge_target') else 'FAIL'})\n")

    # Re-write both contract-named artefacts with the COMPLETE result now that
    # the transition pass has resolved. The snapshot above already guaranteed
    # the gate can read a real stuck-at measurement even if this second pass
    # never returned.
    _write_coverage_rpt(
        project / rpt_out, clock=clock, netlist_rel=netlist_rel, pdk=pdk,
        coverage_ratio=coverage_ratio, faults_covered=faults_covered,
        faults_total=faults_total, min_coverage=min_coverage,
        trans_line=trans_line, cov_out=cov_out, tv_out=tv_out)

    # ── `scan_netlist.v` IS NOT THIS PROGRAM'S TO WRITE ────────────────────
    # This used to be:
    #     scan_netlist = _pl.dft_dir(project) / "scan_netlist.v"
    #     if not scan_netlist.exists() and (project / cut_out).exists():
    #         scan_netlist.write_bytes((project / cut_out).read_bytes())
    # under the comment "Fault's cut output is the scan-ready netlist in the
    # open flow". That claim was FALSE and it was the root of the scan-chain
    # defect: `cut_netlist.v` is the ATPG *cut* view — every flip-flop replaced
    # by a `<inst>.d` pseudo-PI/PO pair, a combinational transform for fault
    # simulation. It has zero flops and cannot be built. Because step 12
    # `opt_clean`ed it into `post_dft_netlist.v`, the artefact the flow calls
    # the post-DFT netlist had no sequential elements and step 13 (RTL ==
    # post-DFT netlist) could not compare anything; and because place-and-route
    # read `<top>_synth.v` instead, the tape-out-bound design carried no chain
    # at all while this program reported coverage on a netlist that never
    # becomes silicon.
    #
    # A REAL scan netlist is produced by `fault_scan_chain_insert.py` (`fault
    # chain`), which stitches the flops sin→sout and publishes only after
    # MEASURING that the chain covers every flop in the input. This program now
    # writes only the ATPG artefacts it actually measures, and DECLARES what
    # its own view is so no consumer has to infer it.

    # Final report — includes the transition (at-speed) block now that it has
    # resolved. Re-write the machine-readable coverage.json so the complete
    # result supersedes the durable stuck-at-only snapshot written above.
    report = _assemble_report(transition)
    _write_coverage_json(json_out_path, report)

    return (0 if report["stuck_at_ge_target"] else 1), report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir")
    p.add_argument("--netlist", default="phase2/stage2/synth/netlist.v",
                   help="Path (relative to project_dir) to synth netlist (default: synth/netlist.v)")
    p.add_argument("--clock", required=True, help="Clock signal name (e.g. clk_i)")
    p.add_argument("--reset", help="Reset signal name (optional)")
    p.add_argument("--reset-active-low", action="store_true", help="Reset is active low")
    # ORGANIC #410 — the default used to be a REAL PDK
    # (`COMMERCIAL_PDK_ID or "sky130"`). A caller that could not attribute its
    # netlist simply omitted the flag, and this default then resolved ANOTHER
    # library's Verilog cell model while the caller's artefact recorded
    # `generic_unmapped`. Neither the PDK the design was built on nor the one
    # actually used appeared anywhere — #389's sentence, reached through a
    # second table.
    #
    # There is no safe default here. `unmapped` is not a PDK, so
    # `PDK_CONFIG.get()` misses and the run REFUSES with the supported list —
    # which is what a caller that does not know its PDK should get. Passing
    # `--cell-model-path` still works for a library this table does not carry.
    p.add_argument("--pdk", default="unmapped",
                   help=f"PDK name (REQUIRED — there is no safe default; an "
                        f"unnamed PDK refuses rather than substituting "
                        f"another library). Supported: "
                        f"{', '.join(PDK_CONFIG.keys())}")
    p.add_argument("--pdk-dir", help="Path to PDK dir (mounted at /pdk for custom PDKs)")
    p.add_argument("--cell-model-path", default=None,
                   help="Explicit Verilog cell-model path for the std-cell "
                        "library. Container-absolute (/pdk/..., /foss/...) is "
                        "used as-is; a relative path is project-relative "
                        "(resolved under the /work mount) so a commercial PDK "
                        "model copied into the run dir is fully reproducible. "
                        "Wins over the PDK config's cell_model.")
    p.add_argument("--dff-cells", default=None,
                   help="Explicit comma-separated flip-flop cell names for "
                        "`fault cut --dff`. When omitted, the flop cells are "
                        "auto-detected from the netlist (DFF/SDFF families) and "
                        "unioned with the PDK-config seed.")
    p.add_argument("--min-coverage", type=float, default=FOUNDRY_STUCK_AT_DEFAULT,
                   help="Minimum stuck-at coverage %% required — FOUNDRY-GRADE "
                        f"default {FOUNDRY_STUCK_AT_DEFAULT:.0f}%% "
                        "(set 98 for the aggressive target). Below the target "
                        "the run FAILs (exit 1).")
    p.add_argument("--transition-target", type=float,
                   default=FOUNDRY_TRANSITION_DEFAULT,
                   help="Minimum transition (at-speed) coverage %% target "
                        f"(default {FOUNDRY_TRANSITION_DEFAULT:.0f}%%). Reported "
                        "only if the OSS engine supports transition ATPG; "
                        "otherwise honestly recorded as engine-limited.")
    p.add_argument("--no-transition", action="store_true",
                   help="Skip the transition (at-speed) fault-model pass "
                        "entirely (stuck-at only).")
    p.add_argument("--tv-count", type=int, default=100,
                   help="Initial test-vector batch size (default 100)")
    p.add_argument("--json", help="Write report JSON to this path "
                                  "(default: reports/dft/coverage.json under project)")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"fault_atpg_run: not a directory: {project}", file=sys.stderr)
        return 2

    netlist = project / args.netlist
    if not netlist.exists():
        print(f"fault_atpg_run: netlist not found: {netlist}", file=sys.stderr)
        return 2

    # For the commercial PDK the default PDK dir is ../../shared_pdk relative to project,
    # matching benchmark/phase2+3_v046 convention
    pdk_dir = None
    if args.pdk_dir:
        pdk_dir = Path(args.pdk_dir).resolve()
    elif _cpdk.COMMERCIAL_PDK_ID and args.pdk == _cpdk.COMMERCIAL_PDK_ID:
        candidate = project.parent / "shared_pdk"
        if candidate.exists():
            pdk_dir = candidate

    # coverage.json is now written by run_fault ITSELF (durably, at the moment
    # the stuck-at measurement exists — see the DURABLE STUCK-AT SNAPSHOT block)
    # so an interruption of the later transition pass, or an in-process caller
    # that never reaches this wrapper, still leaves the gate its contract-named
    # artefact. Pass the resolved path through so --json still honours a custom
    # destination.
    json_path = Path(args.json) if args.json else (_pl.report_path(project, "dft/coverage.json"))

    exit_code, report = run_fault(
        project,
        netlist_rel=args.netlist,
        clock=args.clock,
        pdk=args.pdk,
        min_coverage=args.min_coverage,
        tv_count=args.tv_count,
        pdk_dir=pdk_dir,
        reset=args.reset,
        reset_active_low=args.reset_active_low,
        transition_target=args.transition_target,
        run_transition=not args.no_transition,
        cell_model_override=args.cell_model_path,
        dff_cells_override=args.dff_cells,
        json_out=json_path,
    )

    # Idempotent safety net: run_fault writes coverage.json itself on every path
    # that reaches the stuck-at measurement, but its EARLY-return error stubs
    # (cut failure, no resolvable cell model) return before that write. Preserve
    # the prior contract that a CLI invocation always leaves a coverage.json —
    # on the normal path this re-writes the identical final report.
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2))

    cov = report.get("coverage_pct", 0.0)
    target = report.get("target_pct", 0.0)
    print(f"fault_atpg_run: stuck-at coverage={cov:.2f}%  target={target:.2f}%  "
          f"stuck_at_ge_target={report.get('stuck_at_ge_target', False)}")
    tr = report.get("transition")
    if tr is not None:
        if tr.get("engine_limited"):
            print(f"fault_atpg_run: transition=ENGINE-LIMITED "
                  f"(target={tr.get('target_pct')}%) — {tr.get('reason')}")
        else:
            print(f"fault_atpg_run: transition coverage={tr.get('coverage_pct')}%  "
                  f"target={tr.get('target_pct')}%  "
                  f"transition_ge_target={tr.get('ge_target')}")
    if exit_code != 0:
        print(f"  (see: {json_path})", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
