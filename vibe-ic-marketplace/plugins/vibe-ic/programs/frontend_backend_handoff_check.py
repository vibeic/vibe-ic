#!/usr/bin/env python3
"""frontend_backend_handoff_check.py — Verify all frontend deliverables are
present before entering backend PnR flow (Step 14 Floorplan).

THE PROBLEM
-----------
Backend Place & Route requires several frontend deliverables:
  - Synthesized gate-level netlist (.v with standard cell instances)
  - Timing constraints (SDC)
  - Floorplan configuration (DEF or config)
  - Analog hardmacro LEF (if analog blocks exist)

If any are missing, PnR fails silently or produces garbage.  This gate
ensures the frontend-backend handoff is complete before Step 14 begins.

HEURISTIC
---------
1. Synthesized netlist: ``synth/*.v`` or ``synth/output/*.v`` or
   ``results/*.v`` containing standard-cell instance patterns.
2. Timing constraints: ``*.sdc`` anywhere in the project.
3. Floorplan config: ``*.def`` or ``floorplan.cfg`` or ``config.mk``
   with die-area definition.
4. If ``analog/analog_block_list.json`` exists, require
   ``hardmacro/*/*.lef`` files.
5. DFT evidence (WARN only, not ERROR).

SELF-SKIP
---------
If no ``synth/`` directory and no ``*.sdc`` files exist, the project has not
reached backend stage yet — there is no handoff to audit, so the gate examined
nothing and exits 2 (#515). This is the gate's dominant outcome: 279 of 327
tracked project roots.

WHY ``NO_DFT_EVIDENCE`` IS **NOT** PART OF THAT (#515 judgement)
---------------------------------------------------------------
See the comment at the ``NO_DFT_EVIDENCE`` finding in ``audit()``. In short:
it fires only on the path where every required deliverable WAS examined, so it
is an advisory on a real pass, not a skip — and the "should this design have
scan at all?" question is owned by ``l20_dft_scan_topology_actionable_check``,
which derives it from the design's own requirement documents.

USAGE
-----
    python3 frontend_backend_handoff_check.py <project_dir> [--json report.json]

EXIT CODES
----------
    0 — PASS: the handoff was examined and every required deliverable is
        present (possibly with non-blocking WARN advisories)
    1 — FAIL (missing deliverables)
    2 — VACUOUS: nothing was examined — the project has not reached backend
        stage (no synth dir and no SDC), so no handoff exists yet
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Set, Tuple
import _hdl_code_text  # offset-preserving comment/string blanker (#731)
import _path_layout as _pl
import _vacuous_exit as _vx


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "frontend_backend_handoff_check"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


#: KEPT only as a fast pre-filter for the English gate words; the VERDICT is
#: `netlist_cell_kinds` below. MEASURED, and it is why: two of this pattern's
#: alternatives were vendor cell-name prefixes, so a chip-AGNOSTIC gate carried
#: a two-vendor allow-list. On a third open PDK it answered NO to a correctly
#: technology-mapped netlist (46 standard cells, zero generic primitives) AND
#: NO to the unmapped one that preceded it — it could not see either, and could
#: not tell them apart. The design was told "run synthesis (Step 10)" after it
#: had synthesised.
STDCELL_RE = re.compile(
    r"\b(AND|OR|NAND|NOR|XOR|XNOR|DFF|DFFR|BUF|INV|MUX|AOI|OAI|TIEH|TIEL"
    r"|sky130_fd_sc_\w+|gf180mcu_fd_sc_\w+)\b",
    re.I,
)

#: Yosys writes its technology-generic primitives as escaped identifiers
#: (`\$_NAND_`, `\$_DFF_P_`). A netlist made of these is a SIMULATION netlist:
#: no placer has a master for any of them.
_MODULE_DECL_RE = re.compile(r"(?m)^\s*module\s+(\\?[A-Za-z_$][\w$]*)")


def netlist_cell_kinds(text: str) -> Tuple[Set[str], Set[str]]:
    """(technology cell types, yosys-generic types) instantiated in a netlist.

    Technology-AGNOSTIC by construction: a technology cell is an instantiated
    type that is neither a yosys-generic primitive nor a module DEFINED in the
    same file (that would be the design's own hierarchy, or an analog macro's
    blackbox). No vendor prefix appears here, so a PDK nobody anticipated is
    recognised on the same evidence as one that was.
    """
    try:
        import pdk_consistency_check as _pcc
    except Exception:                                        # pragma: no cover
        return set(), set()
    # The `module` declaration scan runs over COMMENT-BLANKED text (vibe-ic
    # #2010, item 3). `_MODULE_DECL_RE` is anchored at line start, and a block
    # comment quoting a retired module — `/* the old\nmodule ghost ...*/` —
    # puts `module ghost` at a line start too. Scanned raw, `ghost` joined
    # `defined`, and an INSTANTIATED cell of that name was then read as the
    # design's own hierarchy rather than as a technology cell: a phantom
    # module that changes the verdict. The blanker keeps offsets.
    code = _hdl_code_text.strip_hdl_comments_and_strings(text)
    defined = {m.group(1).lstrip("\\") for m in _MODULE_DECL_RE.finditer(code)}
    tech: Set[str] = set()
    generic: Set[str] = set()
    for c in _pcc.extract_netlist_cells(text):
        name = str(c.get("cell_name", ""))
        if not name:
            continue
        if _pcc.is_yosys_technology_generic(name):
            generic.add(name)
        elif name.lstrip("\\") not in defined:
            tech.add(name)
    return tech, generic

DIE_AREA_RE = re.compile(
    r"(DIE_AREA|die_area|DIEAREA|FP_DIE_AREA|set_die_area)", re.I,
)


def _has_gate_netlist(project: Path) -> List[Path]:
    """Return list of gate-level netlist files found.
    Probes the canonical synth output dir plus its `output/` subdir
    (some synth tools write into a sub-folder) and the OpenROAD-style
    `results/` alternative."""
    candidates: List[Path] = []
    for d in [_pl.synth_dir(project),
              _pl.synth_dir(project) / "output",
              project / "results"]:
        if d.is_dir():
            candidates.extend(d.glob("*.v"))
    found = []
    for f in candidates:
        try:
            txt = f.read_text(errors="replace")
        except OSError:
            continue
        tech, generic = netlist_cell_kinds(txt)
        # ANY generic primitive disqualifies the file, even beside real cells:
        # the placer stops at the first master it does not have, so a mixed
        # netlist is no more placeable than an all-generic one. And the
        # design's own blackboxes (an analog macro) are "not defined here"
        # too, so `tech` alone would have accepted the all-generic netlist on
        # the strength of the two macros it instantiates.
        if generic:
            continue
        if tech or STDCELL_RE.search(txt):
            found.append(f)
    return found


def netlists_carrying_generic_cells(project: Path
                                    ) -> List[Tuple[Path, Set[str]]]:
    """Candidate netlists that instantiate ANY yosys-generic primitive.

    A netlist like that is not a handoff: `ORD-2013 LEF master $_NOT_ not
    found` is the first thing the placer says about it. Reported by name so
    the refusal points at the synthesis command, not at the placer.
    """
    out: List[Tuple[Path, Set[str]]] = []
    for d in [_pl.synth_dir(project), _pl.synth_dir(project) / "output",
              project / "results"]:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.v")):
            try:
                txt = f.read_text(errors="replace")
            except OSError:
                continue
            _tech, generic = netlist_cell_kinds(txt)
            if generic:
                out.append((f, generic))
    return out


def _find_sdc(project: Path) -> List[Path]:
    """Find SDC timing constraint files."""
    return sorted(project.rglob("*.sdc"))


def _find_floorplan(project: Path) -> List[Path]:
    """Find DEF or floorplan config files."""
    found: List[Path] = []
    found.extend(project.rglob("*.def"))
    for name in ["floorplan.cfg", "config.mk"]:
        for p in project.rglob(name):
            try:
                txt = p.read_text(errors="replace")
            except OSError:
                continue
            if DIE_AREA_RE.search(txt):
                found.append(p)
    return sorted(set(found))


def _has_analog_blocks(project: Path) -> bool:
    return (_pl.analog_dir(project) / "analog_block_list.json").is_file()


def _find_hardmacro_lef(project: Path) -> List[Path]:
    hm = _pl.hardmacro_dir(project)
    if not hm.is_dir():
        return []
    return sorted(hm.rglob("*.lef"))


def _find_dft_evidence(project: Path) -> bool:
    for p in project.rglob("*.v"):
        try:
            txt = p.read_text(errors="replace")
        except OSError:
            continue
        if re.search(r"\b(scan_en|scan_in|scan_out|scan_mode)\b", txt):
            return True
    return False


def audit(project: Path) -> AuditResult:
    result = AuditResult()

    if not project.is_dir():
        result.summary = {"skipped": True, "reason": "not_a_directory"}
        return result

    synth_dir = _pl.synth_dir(project)
    sdc_files = _find_sdc(project)

    if not synth_dir.is_dir() and not sdc_files:
        result.summary = {"skipped": True, "reason": "not_backend_stage"}
        result.findings.append(Finding(
            "SKIP", "INFO",
            "Project has not reached backend stage — no frontend/backend "
            "handoff exists yet, so nothing was examined.",
        ))
        return result

    result.summary = {"skipped": False, "checks": {}}

    netlists = _has_gate_netlist(project)
    if netlists:
        result.summary["checks"]["netlist"] = [str(f.name) for f in netlists]
    else:
        result.passed = False
        generic = netlists_carrying_generic_cells(project)
        if generic:
            f, kinds = generic[0]
            result.findings.append(Finding(
                "GENERIC_ONLY_NETLIST", "ERROR",
                f"{f.name} instantiates technology-generic primitives "
                f"({', '.join(sorted(kinds)[:6])}) — a simulation netlist, not "
                f"a handoff. No placer has a master for any of them. Re-run "
                f"synthesis against the design's own PDK liberty "
                f"(dfflibmap + abc -liberty) before entering backend flow.",
            ))
        else:
            result.findings.append(Finding(
                "MISSING_GATE_NETLIST", "ERROR",
                "No synthesized gate-level netlist found in synth/ or "
                "results/. Run synthesis (Step 10) before entering backend "
                "flow.",
            ))

    if sdc_files:
        result.summary["checks"]["sdc"] = [str(f.name) for f in sdc_files]
    else:
        result.passed = False
        result.findings.append(Finding(
            "MISSING_SDC", "ERROR",
            "No SDC timing constraint files found. "
            "Generate constraints (Step 11) before entering backend flow.",
        ))

    floorplan = _find_floorplan(project)
    if floorplan:
        result.summary["checks"]["floorplan"] = [str(f.name) for f in floorplan]
    else:
        result.findings.append(Finding(
            "MISSING_FLOORPLAN", "WARN",
            "No DEF or floorplan config with die area found. "
            "PnR tool may auto-generate, but explicit floorplan is recommended.",
        ))

    if _has_analog_blocks(project):
        lefs = _find_hardmacro_lef(project)
        if lefs:
            result.summary["checks"]["hardmacro_lef"] = [str(f.name) for f in lefs]
        else:
            result.passed = False
            result.findings.append(Finding(
                "MISSING_HARDMACRO_LEF", "ERROR",
                "Analog blocks detected (analog/analog_block_list.json) but no "
                "hardmacro LEF files found. Complete analog track (A1-A7) before "
                "entering backend flow.",
            ))

    # ── #515 JUDGEMENT: NO_DFT_EVIDENCE stays a NON-BLOCKING rc-0 ADVISORY ──
    #
    # #515 asked whether absent DFT is a REAL FINDING (a design that should
    # have scan and does not -> rc 1) or an INAPPLICABLE CHECK (DFT out of
    # scope -> rc 2). Decided deliberately, from evidence, as NEITHER:
    #
    # NOT rc 2. This branch is only reachable with `summary["skipped"] is
    # False` — i.e. the project HAS reached backend stage and the netlist,
    # SDC, floorplan and hardmacro-LEF checks above all ran on real artefacts.
    # Exiting 2 would report "nothing was examined" about a run that examined
    # everything the gate audits, which is the same false claim #515 removes,
    # pointed the other way. Measured: on ic/ibex, ic/caravel_user_project and
    # ic/opentitan_aes this finding co-occurs with a fully-executed check and
    # an "All required frontend deliverables present" PASS.
    #
    # NOT rc 1. To FAIL a design for missing scan, a gate must first know that
    # scan was REQUIRED of it. This gate has no such evidence: _find_dft_
    # evidence is a regex for four literal identifiers over `*.v`. It cannot
    # tell "DFT was required and skipped" from "DFT is legitimately out of
    # scope" (FPGA target, analog block, pre-DFT-insertion stage, an SoC
    # integrator's job) or from "scan exists under names I do not recognise".
    # A FAIL derived from that would be a verdict about this gate's recogniser
    # rather than about the design — a fabricated finding, which is worse than
    # the vacuous PASS #515 is closing.
    #
    # The question DOES have an owner: l20_dft_scan_topology_actionable_check
    # F2 (REQUIREMENT_OUTSIDE_CONSUMING_LAYER) BLOCKS on exactly it, and it
    # derives the requirement from the design's OWN input docs and sibling
    # L-docs, exiting 2 when no DFT requirement is derivable. Duplicating that
    # verdict here with strictly less evidence would make the weaker gate the
    # one that stops the flow.
    #
    # So: advisory, rc 0, worded as an advisory. If a DFT requirement is ever
    # threaded into this gate's inputs, this comment is the tripwire — the
    # promotion to rc 1 becomes justifiable at that point and not before.
    if not _find_dft_evidence(project):
        result.findings.append(Finding(
            "NO_DFT_EVIDENCE", "WARN",
            "ADVISORY (non-blocking): no DFT scan chain signals "
            "(scan_en/scan_in/scan_out/scan_mode) detected. This gate cannot "
            "tell 'DFT required and skipped' from 'DFT out of scope' — "
            "l20_dft_scan_topology_actionable_check owns that verdict. "
            "Consider inserting DFT before backend flow.",
        ))

    if result.passed:
        result.findings.append(Finding(
            "PASS", "INFO",
            "All required frontend deliverables present for backend handoff.",
        ))

    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="PATH")
    args = ap.parse_args(argv)

    target = Path(args.project_dir)
    if not target.exists():
        print(f"error: not found: {target}", file=sys.stderr)
        return _vx.RC_VACUOUS

    result = audit(target)
    report = {
        "program": result.program,
        "passed": result.passed,
        "findings": [asdict(f) for f in result.findings],
        "summary": result.summary,
    }

    if args.json:
        txt = json.dumps(report, indent=2)
        if args.json == "-":
            print(txt)
        else:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(txt + "\n")
    else:
        for f in result.findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line}: {f.message}")
        errors = [f for f in result.findings if f.severity == "ERROR"]
        verdict = ("FAIL" if errors
                   else "VACUOUS (nothing examined)"
                   if _vx.summary_is_skipped(result.summary) else "PASS")
        print(f"\n{len(errors)} error(s); verdict: {verdict}")

    # #515 — routed from the gate's OWN `summary["skipped"]`. Only the
    # `not_backend_stage` / `not_a_directory` branches set it; a run that
    # reached the deliverable checks reports PASS or FAIL on what it found,
    # advisories included (see the NO_DFT_EVIDENCE judgement in `audit`).
    skipped = _vx.summary_is_skipped(result.summary)
    if result.passed and skipped:
        _vx.announce_vacuous(result.program,
                             str(result.summary.get("reason", "unspecified")))
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
