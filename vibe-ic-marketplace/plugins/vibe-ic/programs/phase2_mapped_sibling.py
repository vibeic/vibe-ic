#!/usr/bin/env python3
"""Phase-2 technology-MAPPED netlist SIBLING emitter (decision + recipe).

WHY THIS EXISTS
---------------
``design_one_shot_runner.step_yosys_synth`` synthesises with a deliberately
technology-INDEPENDENT recipe --- ``techmap; opt; dffunmap; abc -g cmos2`` ---
whose in-code rationale (v1.6.193 / #80 P0) is, verbatim:

    "To force every cell to a counted primitive without depending on a PDK
     liberty file ... chip-AGNOSTIC: yosys built-in passes only."

That is the right call for the chip-agnostic consumers, and this module does
NOT change it. But it leaves ``phase2/stage2/synth/netlist.v`` containing only
``$_NAND_`` / ``$_NOR_`` / ``$_NOT_`` / ``$_DFF_P_`` primitives, and the Phase-2
DFT/ATPG step cannot measure stuck-at coverage on such a netlist --- iverilog
rejects it with ``Unknown module type: $_NAND_`` and the run records
``pdk_detected=generic_unmapped, atpg_exit=1, faults_total=0``.

The recovery already exists in the plugin, in three separate pieces that were
never joined:

  1. ``fault_atpg_run.resolve_mapped_netlist()`` already switches a generic
     netlist to a ``<top>_synth.v`` SIBLING in the same synth dir when one
     exists (and returns the original unchanged when one does not, so a
     genuine gap still fails honestly).
  2. ``phase3_one_shot_runner.step_synth`` already produces exactly that file,
     with ``dfflibmap -liberty`` + ``abc -liberty`` + ``hilomap``.
  3. The Liberty itself is already resolvable --- ``_detect_pdk`` ->
     ``PdkConfig.liberty`` --- and demonstrably reachable at Phase-2 time.

The only thing missing is ORDER. Phase 3 writes the sibling AFTER Phase-2 DFT
has already given up on the generic netlist. This module closes that ordering
gap ADDITIVELY: ``netlist.v`` / ``netlist_yosys.v`` are never touched, so every
existing generic-netlist consumer sees byte-identical input. The only change is
that a technology-mapped sibling now also EXISTS at Phase-2 time, which is
precisely the precondition ``resolve_mapped_netlist`` is already written to
detect.

CONFORMANCE NOTE (this is load-bearing, not decoration)
------------------------------------------------------
``_yosys_inline_mode_detect`` classifies any yosys command that binds a Liberty
as ``real_pdk``, and a ``real_pdk`` command that lacks ``hilomap`` is a FAIL
(``check_inline_command_conformance``) which ``flow_compliance_check`` turns
into a Step-14 failure. A liberty-mapped recipe that forgot ``hilomap`` would
therefore convert a passing step into a failing one. ``build_mapped_sibling_
command`` REFUSES to build a Liberty-binding command without a hilomap
directive, so that class of regression cannot be introduced by construction.

CHIP-AGNOSTIC
-------------
No PDK name, cell name, or chip class appears in this module. The Liberty path
and the hilomap directive are both supplied by the caller, which resolves them
through the existing registry-driven helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence

__all__ = [
    "mapped_sibling_name",
    "should_emit_mapped_sibling",
    "build_mapped_sibling_command",
    "MappedSiblingRefused",
]


class MappedSiblingRefused(ValueError):
    """Raised when a mapped-sibling recipe was requested but the inputs would
    produce a command that the plugin's own conformance gate rejects.

    Refusing loudly here is deliberate: silently emitting a Liberty-binding
    command without ``hilomap`` would flip Step 14 from PASS to FAIL at a
    distance, which is far harder to diagnose than a refusal at the call site.
    """


def mapped_sibling_name(top: str) -> str:
    """Filename of the technology-mapped sibling for module ``top``.

    This MUST stay in lockstep with the name ``fault_atpg_run.
    resolve_mapped_netlist`` searches for --- it probes ``<top>_synth.v``
    first and then globs ``*_synth.v`` in the same directory. The whole point
    of this module is to place a file where that resolver already looks.
    """
    return f"{top}_synth.v"


def should_emit_mapped_sibling(liberty: Optional[str]) -> bool:
    """True when a technology-mapped sibling can and should be emitted.

    The single precondition is a resolvable Liberty. When there is none the
    answer is False and the caller keeps the generic netlist as the only
    artefact --- which preserves the #80 invariant that Phase 2 has no HARD
    dependency on a PDK Liberty. Degradation is silent-but-recorded at the
    call site, never fatal.
    """
    return bool(liberty) and str(liberty).strip() != ""


def build_mapped_sibling_command(
    rtl_files: Sequence[str],
    top: str,
    liberty: str,
    out_path: str,
    hilomap_directive: str,
    dont_use: Iterable[str] = (),
    latch_map: Optional[str] = None,
) -> str:
    """Build the yosys ``-p`` script that writes the technology-mapped sibling.

    The recipe mirrors ``phase3_one_shot_runner.step_synth`` so that Phase 2
    and Phase 3 cannot disagree about what "the mapped netlist" means:

        read_verilog -sv <rtl>...
        hierarchy -check -top <top>; proc; flatten
        synth -top <top> -flatten
        dfflibmap [-dont_use ...] -liberty <lib>
        [techmap -map <latch_map>]
        abc -liberty <lib> [-dont_use ...]
        <hilomap directive>
        clean
        stat -liberty <lib>
        write_verilog -noattr <out>

    ``hilomap_directive`` is REQUIRED and must be non-empty --- see the
    conformance note in the module docstring. ``MappedSiblingRefused`` is
    raised rather than returning a command that would fail the gate.

    Note the absence of ``-DSIMULATION``: that define marks the sim-only
    lowering path and would be actively misleading on a Liberty-bound
    command.
    """
    if not rtl_files:
        raise MappedSiblingRefused("no RTL sources given for mapped sibling")
    if not should_emit_mapped_sibling(liberty):
        raise MappedSiblingRefused(
            "mapped sibling requested with no resolvable Liberty")
    if not hilomap_directive or not hilomap_directive.strip():
        raise MappedSiblingRefused(
            "a Liberty-binding yosys command MUST carry a hilomap directive "
            "(check_inline_command_conformance classifies it as real_pdk and "
            "FAILs a real_pdk command with no tie-cell mapping); refusing to "
            "emit a command that would flip Step 14 to FAIL")

    du = " ".join(f"-dont_use {c}" for c in dont_use)
    du_sp = f" {du}" if du else ""

    parts = [f"read_verilog -sv {f}" for f in rtl_files]
    parts.append(f"hierarchy -check -top {top}")
    parts.append("proc")
    parts.append("flatten")
    parts.append(f"synth -top {top} -flatten")
    parts.append(f"dfflibmap{du_sp} -liberty {liberty}")
    if latch_map:
        parts.append(f"techmap -map {latch_map}")
    parts.append(f"abc -liberty {liberty}{du_sp}")
    parts.append(hilomap_directive.rstrip("; "))
    parts.append("clean")
    parts.append(f"stat -liberty {liberty}")
    parts.append(f"write_verilog -noattr {out_path}")
    return "; ".join(parts)


def mapped_sibling_path(synth_dir: Path, top: str) -> Path:
    """Absolute path the mapped sibling should be written to."""
    return Path(synth_dir) / mapped_sibling_name(top)
