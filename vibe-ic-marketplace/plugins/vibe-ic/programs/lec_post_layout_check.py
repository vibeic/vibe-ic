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
import itertools
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


_NETLIST_MODULE_RE = re.compile(
    r"(?P<head>\bmodule\s+(?P<name>\\?[^\s(]+)\s*"
    r"(?P<ports>\((?P<portlist>[^;]*?)\))?\s*;)"
    r"(?P<body>.*?)"
    r"(?P<end>\bendmodule\b)",
    re.DOTALL,
)


def restore_named_instance_connections(
        text: str, top: str,
        connections: List[Tuple[str, str, str]],
        internal_wires: Optional[List[str]] = None,
        ) -> Tuple[str, Dict[str, object]]:
    """Restore DEF-proven connections elided by ``write_verilog``.

    OpenROAD's default writer omits nets typed POWER/GROUND, even when an IO
    macro's *functional* control pin (OE/IE/pull control) is connected to one.
    The post-layout Boolean view then contains a floating pad control and can
    either go vacuous or stop at ``$tribuf``.  The caller supplies only triples
    independently verified against the final DEF SPECIALNETS; this pure helper
    adds those named connections to a proof-only netlist and declares the
    corresponding internal rail wires.  An absent instance, conflicting
    existing pin, duplicate request or malformed instance refuses: no guessed
    connection can enter the miter.

    ``connections`` is ``[(instance, pin, net), ...]``.  All names come from
    producer/DEF authority; this function applies no naming convention.
    """
    modules = [m for m in _NETLIST_MODULE_RE.finditer(text)
               if (m.group("name") or "").lstrip("\\") == top.lstrip("\\")]
    if len(modules) != 1:
        raise ValueError(
            f"expected exactly one module {top!r}, found {len(modules)}")
    module = modules[0]
    body = module.group("body")
    requests: Dict[Tuple[str, str], str] = {}
    for inst, pin, net in connections:
        key = (str(inst), str(pin))
        value = str(net)
        if not all((*key, value)):
            raise ValueError(f"empty instance/pin/net in connection {key!r}")
        if key in requests and requests[key] != value:
            raise ValueError(
                f"conflicting restoration for {key[0]}/{key[1]}: "
                f"{requests[key]!r} vs {value!r}")
        requests[key] = value

    edits: List[Tuple[int, int, str, int]] = []
    already = 0
    by_instance: Dict[str, List[Tuple[str, str]]] = {}
    for (inst, pin), net in sorted(requests.items()):
        by_instance.setdefault(inst, []).append((pin, net))
    for inst, pin_nets in sorted(by_instance.items()):
        inst_token = (re.escape(inst) + r"\s+" if inst.startswith("\\")
                      else r"\b" + re.escape(inst) + r"\b\s*")
        opener = re.compile(
            r"(?P<cell>\\?[^\s();]+)\s+" + inst_token + r"\(")
        hits = list(opener.finditer(body))
        if len(hits) != 1:
            raise ValueError(
                f"expected exactly one instance {inst!r} in {top!r}, "
                f"found {len(hits)}")
        open_idx = hits[0].end() - 1
        depth = 0
        close_idx = -1
        for idx in range(open_idx, len(body)):
            if body[idx] == "(":
                depth += 1
            elif body[idx] == ")":
                depth -= 1
                if depth == 0:
                    close_idx = idx
                    break
        if close_idx < 0:
            raise ValueError(f"unterminated connection list for {inst!r}")
        current = body[open_idx + 1:close_idx]
        missing: List[Tuple[str, str]] = []
        for pin, net in pin_nets:
            pin_hits = list(re.finditer(
                r"\.\s*" + re.escape(pin) + r"\s*\(\s*([^()]*)\s*\)",
                current))
            if pin_hits:
                if len(pin_hits) != 1 or pin_hits[0].group(1).strip() != net:
                    observed = [x.group(1).strip() for x in pin_hits]
                    raise ValueError(
                        f"existing {inst}/{pin} connection {observed!r} does "
                        f"not equal DEF-proven net {net!r}")
                already += 1
            else:
                missing.append((pin, net))
        if missing:
            prefix = ", " if current.strip() else ""
            replacement = prefix + ", ".join(
                f".{pin}({net})" for pin, net in missing)
            edits.append((close_idx, close_idx, replacement, len(missing)))

    for start, end, replacement, _count in sorted(edits, reverse=True):
        body = body[:start] + replacement + body[end:]

    header_ports = set(re.findall(r"\\?[A-Za-z_$][\w$]*",
                                  module.group("portlist") or ""))
    added_wires: List[str] = []
    declarations: List[str] = []
    for wire in dict.fromkeys(str(x) for x in (internal_wires or [])):
        bare = wire.lstrip("\\")
        if wire in header_ports or bare in header_ports:
            continue
        declared = re.search(
            r"\b(?:input|output|inout|wire)\b[^;]*"
            r"(?:^|[\s,])" + re.escape(wire) + r"(?:[\s,;]|$)",
            body, re.MULTILINE)
        if not declared:
            declarations.append(f"\n  wire {wire};")
            added_wires.append(wire)
    body = "".join(declarations) + body
    new_module = module.group("head") + body + module.group("end")
    out = text[:module.start()] + new_module + text[module.end():]
    return out, {
        "top": top,
        "requested": len(requests),
        "restored": sum(edit[3] for edit in edits),
        "already_present": already,
        "internal_wires_added": added_wires,
    }


def build_yosys_equiv_script(gold_v: str, gate_v: str, lib: str, top: str,
                             blackbox_v: Optional[List[str]] = None,
                             seq_depths: Optional[List[int]] = None,
                             strip_gate_ports: Optional[List[str]] = None,
                             strip_gold_ports: Optional[List[str]] = None,
                             extra_libs: Optional[List[str]] = None,
                             constant_gate_wires: Optional[Dict[str, int]] = None,
                             constant_gold_wires: Optional[Dict[str, int]] = None,
                             functional_lib: bool = False,
                             blacklist: Optional[str] = None) -> str:
    """Emit the Yosys .ys that structurally proves gold_v == gate_v.

    blacklist : optional path (already in the tool's own filesystem view) of a
                 file naming wires `equiv_make` must NOT pair. Used ONLY by the
                 pin-permutation re-proof (see `classify_pin_permutation_points`)
                 and only for points that check proved to be a naming artefact;
                 never for a top-level port or a register pin. Absent -> the
                 recipe is byte-identical to the one without this argument.

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
    strip_gold_ports / strip_gate_ports : supply-only unmatched top ports selected
                 by the caller from the exact two interfaces.  Removing a rail
                 absent from the other side is necessary because functional
                 Liberty logic models omit PG pins; functional ports are never
                 eligible and still make the proof fail closed.
    extra_libs : additional exact-library views whose functional cells occur in
                 the physical wrapper (for example an IO library matched to the
                 standard-cell Liberty PVT). They are read with the same sound
                 functional-vs-blackbox mode as ``lib`` on both arms.
    constant_gold_wires / constant_gate_wires : exact rail nets mapped to 0/1
                 by the caller from producer authority.  They model the powered
                 operating condition before unmatched rail ports are deleted;
                 no functional signal is inferred or eligible.
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
    libraries = [lib] + [x for x in (extra_libs or []) if x != lib]

    def _read_liberties(functional: bool) -> str:
        option = "" if functional else "-lib "
        return "".join(f"read_liberty {option}{path}\n" for path in libraries)

    def _constant_block(values: Optional[Dict[str, int]]) -> str:
        lines: List[str] = []
        if values:
            # `prep` leaves the whole design selected.  `connect -set VDD`
            # against that selection is ambiguous when library modules also
            # expose a VDD wire.  Scope the producer-owned rail constants to
            # the exact comparison top, then restore the full selection for
            # the subsequent flatten/optimization passes.
            lines.append(f"select -module {top}")
        for wire, level in sorted((values or {}).items()):
            if level not in (0, 1, False, True):
                raise ValueError(
                    f"constant rail {wire!r} has non-Boolean level {level!r}")
            lines.append(f"connect -set {wire} 1'b{int(level)}")
        if values:
            lines.append("select -clear")
        return ("\n".join(lines) + "\nopt\n") if lines else ""
    # The physical wrapper and routed Verilog can put supply-only ports on
    # opposite sides (for example the wrapper GOLD declares VDD/VSS while
    # OpenROAD omits them from GATE). Delete ONLY caller-classified unmatched
    # supply ports. They carry no logic in the functional Liberty models.
    # A functional port difference is never stripped and remains a real error.
    gold_strip = "".join(
        f"delete {top}/w:{p}\n" for p in (strip_gold_ports or []))
    gate_strip = "".join(
        f"delete {top}/w:{p}\n" for p in (strip_gate_ports or []))
    gold_strip_block = (gold_strip + "opt_clean\n") if gold_strip else ""
    gate_strip_block = (gate_strip + "opt_clean\n") if gate_strip else ""
    depths = list(seq_depths) if seq_depths else list(DEFAULT_SEQ_DEPTHS)
    # Ascending, de-duplicated, positive; each pass only works the still-unproven
    # cells, so the shallow-first order keeps the common case cheap.
    depths = sorted({int(d) for d in depths if int(d) > 0})
    induct = "\n".join(f"equiv_induct -seq {d}" for d in depths) or "equiv_induct"
    em = ("equiv_make"
          + (f" -blacklist {blacklist}" if blacklist else "")
          + " gold gate equiv")

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
        def _func_side(read_v: str, stash: str, extra_strip: str = "",
                       constants: Optional[Dict[str, int]] = None) -> str:
            return (f"{_read_liberties(True)}"
                    f"{bb_block}{read_v}\n"
                    f"prep -top {top}\n"
                    f"{_constant_block(constants)}"
                    f"{extra_strip}"
                    f"tribuf -formal\n"
                    f"flatten\n"
                    f"async2sync\n"
                    f"opt -purge\n"
                    f"opt_clean -purge\n"
                    f"splitnets -ports\n"
                    f"design -stash {stash}\n")
        gold_block = _func_side(
            f"read_verilog -sv {gold_v}", "gold", gold_strip_block,
            constant_gold_wires)
        gate_block = _func_side(
            f"read_verilog -sv {gate_v}", "gate", gate_strip_block,
            constant_gate_wires)
        return (
            "# Vibe-IC post-layout LEC — FUNCTIONAL (sound) Liberty cell models.\n"
            f"{gold_block}\n{gate_block}\n"
            f"design -copy-from gold -as gold {top}\n"
            f"design -copy-from gate -as gate {top}\n"
            f"{em}\n"
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
{_read_liberties(False).rstrip()}
{bb_block}read_verilog -sv {gold_v}
prep -top {top}
{_constant_block(constant_gold_wires)}
{gold_strip_block}splitnets -ports
design -stash gold

{_read_liberties(False).rstrip()}
{bb_block}read_verilog -sv {gate_v}
prep -top {top}
{_constant_block(constant_gate_wires)}
{gate_strip_block}splitnets -ports
design -stash gate

design -copy-from gold -as gold {top}
design -copy-from gate -as gate {top}
{em}
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
# (1c) Pin-permutation re-proof.
#
# ROUND-3 (subservient x gf180mcuD, 2026-09-02). The post-route real-SPEF
# repair swapped the two symmetric inputs of ONE OAI21 (`repair_timing`'s
# SwapPinsMove: gold A1=_1032_/A2=_1033_, gate A1=_1033_/A2=_1032_, the cell
# also upsized _1 -> _2). The functional recipe FLATTENS each Liberty cell, so
# every cell pin becomes a wire named `<instance>.<pin>`, and `equiv_make`
# pairs those by NAME: `_1428_.A1_gold` was asked to equal `_1428_.A1_gate`,
# which now carry different (swapped) nets. Two points UNPROVEN, the whole
# step FAIL (LEC_POST_UNPROVEN) — on a netlist whose every output and every
# register was proven, while the cell's own output `_1428_.ZN` was among the
# 1923 proven points.
#
# That is a false negative, and it is ALSO a soundness problem the other way:
# equiv_induct assumes every $equiv held in the previous frames, and a point
# that can never hold makes the induction premise unsatisfiable on the real
# traces. So the remedy is NOT "ignore two unproven points": it is to REMOVE
# the mis-paired points from the match set and prove everything else again
# WITHOUT them. MEASURED on the run's own netlists: 1925 points / 2 unproven
# / 152 s  ->  1923 points / 0 unproven / 4.3 s.
#
# The removal is granted only on evidence, all of it read from the artefacts:
#   * the point is `<instance>.<pin>` and the instance exists on BOTH sides;
#   * `<pin>` is an INPUT of the cell on both sides (Liberty direction);
#   * both cells expose the same input and output pin sets (a drive-strength
#     resize is fine, a different logic cell is not);
#   * the gate instance's input NETS are a permutation of the gold instance's
#     input nets, and its output nets are unchanged;
#   * for EVERY assignment of those nets, EVERY output function of the cell
#     (the Liberty `function`, evaluated) gives the same value under the gold
#     wiring and under the gate wiring — i.e. the permutation is a symmetry of
#     the cell, not a rewire.
# A sequential cell fails the last test by construction (its function names a
# state variable this evaluator does not know), so a register pin is never
# blacklisted. A point that fails ANY test is REJECTED with the reason, the
# re-proof does not run, and the original UNPROVEN verdict stands.
# ---------------------------------------------------------------------------
_UNPROVEN_POINT_RE = re.compile(
    r"Unproven\s+\$equiv\s+\S+:\s+\\?(\S+?)_gold\s+\\?(\S+?)_gate", re.M)


def parse_unproven_points(text: str) -> List[str]:
    """Distinct names of the $equiv points the FINAL `equiv_status` listed as
    UNPROVEN, without the `\\` escape and the `_gold`/`_gate` suffixes, in log
    order. `equiv_make` pairs same-named wires, so a line whose two names differ
    is not one of its points and is skipped."""
    names: List[str] = []
    seen = set()
    for m in _UNPROVEN_POINT_RE.finditer(text or ""):
        g, a = m.group(1), m.group(2)
        if g != a or g in seen:
            continue
        seen.add(g)
        names.append(g)
    return names


_VERILOG_KEYWORDS = {
    "module", "endmodule", "input", "output", "inout", "wire", "reg", "assign",
    "supply0", "supply1", "tri", "parameter", "localparam", "specify",
    "endspecify", "always", "initial", "function", "endfunction", "defparam",
}
_INST_RE = re.compile(
    r"^[ \t]*(?P<cell>[A-Za-z_][\w$]*)[ \t]+(?P<inst>\\\S+|[A-Za-z_][\w$]*)\s*"
    r"\(\s*(?P<body>(?:\.[A-Za-z_][\w$]*\s*\([^()]*\)\s*,?\s*)+)\)\s*;",
    re.M)
_PORT_RE = re.compile(r"\.([A-Za-z_][\w$]*)\s*\(\s*([^()]*?)\s*\)")


def _vid(s: str) -> str:
    """A Verilog identifier as written -> its bare name (escaped `\\x ` -> `x`)."""
    s = (s or "").strip()
    if s.startswith("\\"):
        s = s[1:]
    return s.strip()


def _parse_netlist_instances(text: str) -> Dict[str, Tuple[str, Dict[str, str]]]:
    """{instance: (cell_type, {pin: net})} over a structural gate netlist
    (yosys or OpenROAD `write_verilog` shape; escaped identifiers honoured)."""
    out: Dict[str, Tuple[str, Dict[str, str]]] = {}
    for m in _INST_RE.finditer(text or ""):
        cell = m.group("cell")
        if cell in _VERILOG_KEYWORDS:
            continue
        pins = {pm.group(1): _vid(pm.group(2))
                for pm in _PORT_RE.finditer(m.group("body"))}
        out[_vid(m.group("inst"))] = (cell, pins)
    return out


def _brace_block(text: str, start: int) -> Tuple[str, int]:
    """Body of the `{ ... }` block whose opening brace precedes `start`."""
    depth, i, n = 1, start, len(text)
    while i < n and depth:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return text[start:i - 1 if depth == 0 else i], i


_LIB_CELL_RE = re.compile(r"\bcell\s*\(\s*\"?([\w$.]+)\"?\s*\)\s*\{")
_LIB_PIN_RE = re.compile(r"\bpin\s*\(\s*\"?([\w$\[\]]+)\"?\s*\)\s*\{")


def _parse_liberty_pins(text: str) -> Dict[str, Dict[str, object]]:
    """{cell: {"inputs": [pin, ...], "outputs": {pin: function_or_None}}}."""
    cells: Dict[str, Dict[str, object]] = {}
    for m in _LIB_CELL_RE.finditer(text or ""):
        body, _ = _brace_block(text, m.end())
        inputs: List[str] = []
        outputs: Dict[str, Optional[str]] = {}
        for pm in _LIB_PIN_RE.finditer(body):
            pbody, _ = _brace_block(body, pm.end())
            dm = re.search(r"\bdirection\s*:\s*\"?(\w+)", pbody)
            d = dm.group(1).lower() if dm else ""
            if d == "input":
                inputs.append(pm.group(1))
            elif d == "output":
                fm = re.search(r"\bfunction\s*:\s*\"([^\"]*)\"", pbody)
                outputs[pm.group(1)] = fm.group(1) if fm else None
        cells[m.group(1)] = {"inputs": inputs, "outputs": outputs}
    return cells


class _LibertyFn:
    """Evaluate a Liberty boolean `function` string under a pin->bool env.
    Precedence (low -> high): `|`/`+`, `&`/`*`/juxtaposition, `^`, `!`/`'`.
    Any name outside the env (a state variable such as IQ) raises KeyError."""
    _TOK = re.compile(r"[A-Za-z_][\w\[\]]*|[01]|[()!'&*|+^]")

    def __init__(self, expr: str):
        self.toks = self._TOK.findall(expr or "")

    def __call__(self, env: Dict[str, bool]) -> bool:
        self.i = 0
        v = self._or(env)
        if self.i != len(self.toks):
            raise ValueError(f"trailing tokens in function: {self.toks[self.i:]}")
        return bool(v)

    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _take(self):
        t = self._peek()
        self.i += 1
        return t

    def _or(self, env):
        v = self._and(env)
        while self._peek() in ("|", "+"):
            self._take()
            v = v | self._and(env)
        return v

    def _and(self, env):
        v = self._xor(env)
        while True:
            t = self._peek()
            if t in ("&", "*"):
                self._take()
                v = v & self._xor(env)
            elif t is not None and (t == "(" or t == "!" or t[0].isalnum()
                                    or t[0] == "_"):
                v = v & self._xor(env)          # juxtaposition == AND
            else:
                return v

    def _xor(self, env):
        v = self._unary(env)
        while self._peek() == "^":
            self._take()
            v = v ^ self._unary(env)
        return v

    def _unary(self, env):
        if self._peek() == "!":
            self._take()
            v = not self._unary(env)
        else:
            v = self._primary(env)
        while self._peek() == "'":
            self._take()
            v = not v
        return bool(v)

    def _primary(self, env):
        t = self._take()
        if t == "(":
            v = self._or(env)
            if self._take() != ")":
                raise ValueError("unbalanced parenthesis in function")
            return v
        if t in ("0", "1"):
            return t == "1"
        if t is None or not (t[0].isalpha() or t[0] == "_"):
            raise ValueError(f"unexpected token {t!r} in function")
        return bool(env[t])                      # KeyError on a state variable


def classify_pin_permutation_points(names: List[str], gold_text: str,
                                    gate_text: str, liberty_text: str
                                    ) -> Dict[str, List[Dict[str, object]]]:
    """Split UNPROVEN point names into `accepted` (a proven symmetry of the
    cell — a naming artefact of the flattened recipe) and `rejected` (with the
    failing test named). See the block comment above for the tests; every one
    must hold or the point is rejected, and an exception inside the evaluator
    (a sequential cell's state variable, a malformed function) rejects too."""
    gold_i = _parse_netlist_instances(gold_text)
    gate_i = _parse_netlist_instances(gate_text)
    lib = _parse_liberty_pins(liberty_text)
    accepted: List[Dict[str, object]] = []
    rejected: List[Dict[str, object]] = []

    def _no(rec, why):
        rejected.append({**rec, "reason": why})

    for name in names:
        inst, _, pin = name.rpartition(".")
        rec: Dict[str, object] = {"point": name, "instance": inst, "pin": pin}
        if not inst or not pin:
            _no(rec, "not an <instance>.<pin> wire")
            continue
        g, t = gold_i.get(inst), gate_i.get(inst)
        if g is None or t is None:
            _no(rec, "instance absent from the "
                + ("gold" if g is None else "gate") + " netlist")
            continue
        gcell, gpins = g
        tcell, tpins = t
        rec.update({"gold_cell": gcell, "gate_cell": tcell})
        gl, tl = lib.get(gcell), lib.get(tcell)
        if gl is None or tl is None:
            _no(rec, "cell "
                + (gcell if gl is None else tcell) + " has no Liberty model")
            continue
        if pin not in gl["inputs"] or pin not in tl["inputs"]:
            _no(rec, f"pin {pin} is not an INPUT of the cell on both sides")
            continue
        if (set(gl["inputs"]) != set(tl["inputs"])
                or set(gl["outputs"]) != set(tl["outputs"])):
            _no(rec, f"input/output pin sets differ between {gcell} and {tcell}")
            continue
        gin = {p: gpins.get(p, "") for p in gl["inputs"]}
        tin = {p: tpins.get(p, "") for p in tl["inputs"]}
        rec.update({"gold_input_nets": gin, "gate_input_nets": tin})
        if sorted(gin.values()) != sorted(tin.values()) or "" in gin.values():
            _no(rec, "the gate instance's input nets are not a permutation of "
                     "the gold instance's input nets (a rewire, not a swap)")
            continue
        if any(gpins.get(o) != tpins.get(o) for o in gl["outputs"]):
            _no(rec, "an output net of the instance differs between gold and gate")
            continue
        if gin.get(pin) == tin.get(pin):
            # NEGATIVE CONTROL that found this test missing: a pin the
            # permutation did NOT move carries the same-named net on both
            # sides, so a point there that yosys still could not prove is a
            # genuinely different SIGNAL under the same name — never an
            # artefact of the pairing.
            _no(rec, f"pin {pin} carries the SAME net on both sides "
                     f"({gin.get(pin)}); an unproven point there is not a "
                     "permutation artefact")
            continue
        nets = sorted(set(gin.values()))
        same = True
        why = ""
        for o in gl["outputs"]:
            fexpr, texpr = gl["outputs"][o], tl["outputs"][o]
            if not fexpr or not texpr:
                same, why = False, f"output {o} carries no Liberty function"
                break
            try:
                fg, ft = _LibertyFn(fexpr), _LibertyFn(texpr)
                for bits in itertools.product((False, True), repeat=len(nets)):
                    nv = dict(zip(nets, bits))
                    if (fg({p: nv[n] for p, n in gin.items()})
                            != ft({p: nv[n] for p, n in tin.items()})):
                        same, why = False, (
                            f"output {o}: the permuted wiring computes a "
                            f"DIFFERENT function of the same nets ({fexpr})")
                        break
            except (KeyError, ValueError) as exc:
                same, why = False, (f"output {o}: function {fexpr!r} could not "
                                    f"be evaluated over the pins ({exc!r}) — "
                                    "a sequential/stateful cell is never "
                                    "blacklisted")
            if not same:
                break
        if not same:
            _no(rec, why)
            continue
        rec["outputs"] = sorted(gl["outputs"])
        rec["evidence"] = ("cell symmetry proven by truth table over "
                          f"{len(nets)} net(s); output nets unchanged")
        accepted.append(rec)
    return {"accepted": accepted, "rejected": rejected}


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
