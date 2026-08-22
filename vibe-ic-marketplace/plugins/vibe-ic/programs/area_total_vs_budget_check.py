#!/usr/bin/env python3
"""area_total_vs_budget_check.py — the synthesised area figure must reach a
COMPARISON, or the step must REFUSE and name the authority it lacks.

CHIP_AGNOSTIC: strict — no process, vendor or PDK name anywhere in this file,
DOCSTRING INCLUDED. This is STRICTER than the repo-wide `source_chip_agnostic_check`,
which permits open-PDK names and clears 508 programs that carry one legitimately.
That gate's PASS is not this file's verdict; `test_area_total_vs_budget_check::test_the_program_names_no_process_or_vendor_token` is, and it reads the WHOLE file.

MEASURED, which is why this paragraph exists: a docstring paragraph naming two open
PDKs was added to this file, the repo-wide gate returned PASS over 1544 files, and
this file's own test was red. The rule was real and invisible. Identify a library by
its cell count and the registry population it came from, never by its name.

ENFORCEMENT: blocking — `phase3_one_shot_runner.step_synth` spawns this gate
inline and returns `StepResult(..., "FAIL", ...)` on rc 1, so its verdict can
stop the step it guards while that step is running. `flow_gate_enforcement_audit`
measures the wiring as INLINE_BLOCKING.

IT WAS `advisory` UNTIL 2026-08-22, and every word of that declaration was true
when written: no runner spawned it, so it could describe a run and never stop
one. Three things had to change first and all three are recorded below — the
producer had to hand over the library it synthesised against, the figure's unit
had to be ESTABLISHED from evidence rather than assumed, and only then was there
a verdict worth carrying inline. This token now records the wiring that exists,
not an intention.

NO FLOW EDIT WAS MADE OR NEEDED. The clause stays exactly where the flow declares
it, in step 9's `program_exit_zero`. Step 9's declared output IS
`phase2/stage2/synth/stats.json`, and the phase-3 synthesis is what finally
writes an AREA into it: step 9's other producer maps to generic primitives and
yosys prints no area line at all. So the gate is enforced at the point its input
becomes real, which is the same step, not a different one.

ONLY rc 1 STOPS THE STEP, and the bound is deliberate:

  rc 1  the design's synthesised cell area exceeds the die area IT declared.
        A fact about the design, knowable at synthesis rather than at streamout,
        and a FAIL of the step.
  rc 0  compared, and it fits.
  rc 2  INCOMPLETE — most often "no ceiling declared". MEASURED, and this is a
        CORRECTION of the number an earlier version of this block carried: it
        cited 176 of 177 published L19 copies, from a corpus that has since been
        withdrawn and cannot be re-derived. The sound figure is in this
        repository and was swept independently for a different gate —
        `l19_pdk_floorplan_contract_check`: across 136 real converge runs on all
        5 fleet machines, `die_area_budget_um` is null in 118. So roughly ONE RUN
        IN SEVEN does declare a die, and this gate is materially less inert than
        the older number implied.

        AND THE FIELD IS POPULATABLE, so a null is the design's silence rather
        than the flow's: `floorplan_contract` extracts a die WxH from the
        design's OWN documents and phase 1 writes it into L19. Nothing is
        broken; those designs did not state a die size.

        Making rc 2 non-green would therefore turn 118 of 136 runs non-green
        over a requirement they never wrote, so it is DISCLOSED in the step's
        detail and does not stop the step. WHETHER THE FLOW SHOULD DEMAND A
        DECLARED DIE BUDGET IS A PRODUCT DECISION AND IS DELIBERATELY NOT TAKEN
        HERE — it is the one thing still standing between this gate and
        answering on every run, and 118/136 is the number that decision costs.

THE OTHER TWO AXES ARE UNCHANGED, stated so this token can never be read as
permission to move anything: the FLOW SLOT is `program_exit_zero` and stays
there, and the VERDICT SEVERITY is unchanged — rc 1 on a real finding, rc 2 on
INCOMPLETE.

A NOTE ON WHAT DID NOT CATCH THIS. While the wiring existed and this file still
said `advisory`, `flow_gate_enforcement_audit` exited 0. Its `contradiction`
class is one-directional — it fails a gate that DECLARES blocking and is wired
audit-only, and says nothing about one wired blocking that declares advisory.
That asymmetry is disclosed here rather than left for the next reader to
discover, and the test beside this file pins the declaration against the
MEASURED wiring in both directions.

HOW IT GOT HERE, MEASURED AT EVERY STEP
---------------------------------------
The inline wiring this repo uses — `phase3_one_shot_runner.
_DECLARED_SIGNOFF_GATES` / `_run_declared_signoff_gate` — turns rc 0 into PASS
and rc 1 into a FAIL of the run. Through its step-9 clause this gate can reach
NEITHER. MEASURED on this tree, on a project carrying BOTH a declared
`L19.die_area_budget_um` ('1300x1300') and a synth `chip_area`, invoked exactly
as the flow clause invokes it — no `--area-unit-um2`:

    INCOMPLETE: synthesised area was NOT compared against anything — missing
    authority: the area figure's UNIT — phase2/stage2/synth/stats.json states
    chip_area_unit='cell-library area unit (as declared by the library the
    synthesis script loaded)', which does not name um^2            -> rc 2

`synth_area_stats_emit` is the ONLY producer of that figure in this flow
(`design_one_shot_runner.step_yosys_synth` calls its `emit_stats_json`), and it
declines to name the unit ON PURPOSE — its own comment reads "naming a concrete
unit here would be an invention". So rc 2 is the only verdict reachable through
the flow today, and an inline wiring would install a control-flow decision on
rc 1 that no run can arrive at. A wiring that cannot go red on any real project
is not a wiring; it is a subprocess on the hot path of every synthesis.

Making rc 0/1 reachable by adding `--area-unit-um2` to the flow clause is
REFUSED, not overlooked: it asserts a unit the PRODUCING artefact declined to
assert, which is the ART-POWER-FIGURES-X1000 defect this gate exists to remove.

WHAT WOULD HAVE TO CHANGE FOR THIS TO BECOME BLOCKING
-----------------------------------------------------
CORRECTED 2026-08-22. An earlier version of this block said the wiring belonged
in `design_one_shot_runner.step_yosys_synth`, right after the call that writes
the figure. That is the WRONG STEP, and wiring it there would have produced a
gate that refuses on every run forever. Measured on both real log shapes:

    step 9   read_verilog / synth -flatten / abc -g cmos2 / stat
             -> NO `Chip area for module` line at all -> chip_area = None
    phase 3  read_liberty / dfflibmap -liberty / abc -liberty
             / stat -liberty <lib>
             -> Chip area for module '<top>': 5841.196200 -> chip_area set

Step 9 synthesises to GENERIC primitives (`abc -g cmos2`) and never loads a
library, so yosys prints no area at all. The figure this gate reads is written
LATER, by `phase3_one_shot_runner.step_synth` via `synth_area_stats_emit.
emit_for_run` — which overwrites step 9's own `stats.json`, because
`_path_layout.synth_dir` sends both producers to `phase2/stage2/synth/`.

So this gate can see a figure at all ONLY because it is evaluated at
`final_audit`, after phase 3 has run — which is the very AUDIT_ONLY property
the block above describes. An inline wiring at step 9 would run BEFORE the
producer and read `chip_area: None` on every project ever built.

TWO OF THE THREE ARE NOW DONE, and the declaration is re-decided rather than
left standing (2026-08-22):

  1. DONE. `emit_for_run` now accepts the LIBRARY the synthesis loaded, and
     `phase3_one_shot_runner.step_synth` passes it — the same one it
     interpolates into `stat -liberty`, so the figure and the library its unit
     is derived from cannot disagree.
  2. DONE, from evidence rather than assumption. `_area_unit` establishes the
     unit by cross-checking each cell's Liberty `area` against its LEF
     `SIZE w BY h`, which is in microns by the LEF spec. MEASURED over all five
     libraries the registry resolves in the shipped EDA image: every one
     establishes um^2, on 42 to 428 cells apiece, median 1.000000. Two carry a
     single per-cell outlier — a filler at exactly 0.5, one scan flop at
     exactly 10/9 — which are DISCLOSED and do not unmake a library's unit: a
     unit error is a COMMON factor across the population, never one cell.
     A library at a common 1000x is refused, and so is one split between two
     units; both refusals have a reachable test case.
  3. REMAINS, and it is the product decision, not a technical gap. No runner
     spawns this gate inline, so its verdict still cannot stop the step it
     guards, and that is what `ENFORCEMENT: advisory` above records.

WHAT THE GATE CAN NOW DO, measured end to end through the real producer and this
gate, on a library from the shipped image:

    stats.json    chip_area 2.5282e+04, chip_area_unit "um^2"
                  established from 229 cells, median 1.000000, 0 outliers
    die 10x10     rc 1 FAIL  — cell area exceeds the declared die by 252.8x
    die 1000x1000 rc 0 PASS  — compared, and it fits

Before this it could reach neither. That is the whole point of the change, and
it is why this block no longer says the unit is what stands in the way.

WHAT NOW STANDS IN THE WAY IS THE CEILING, NOT THE UNIT. rc 1 additionally needs
`L19.die_area_budget_um`. The figure to use for that is the one swept for
`l19_pdk_floorplan_contract_check` — 118 of 136 real converge runs across all 5
fleet machines carry it null — and NOT the "177 copies, ONE declaring it" a
draft of this block quoted from the withdrawn corpus. The two disagree by more
than an order of magnitude on the part that matters: roughly one run in seven
declares a die, not one in 177. The unit's establishment converts a VACUOUS_PASS
into an honest verdict either way, but it is a REAL verdict on about a seventh
of runs rather than on almost none, so this gate is not "nearly inert" and must
not be described that way to a reviewer.

That precondition is not left as prose. `test_two_gates_declare_where_their_
verdict_is_consumed.py` re-measures it and FAILS when it stops holding, so this
paragraph cannot quietly become false. This is NOT a claim that the gate is
audit-only forever.

THE SIBLING OF `power_total_vs_budget_check`, ONE AXIS OVER
===========================================================
Power got its comparison in #1026 and the flow's power edge in this change's
sibling clause. Area had NEITHER a comparison nor an edge: no step in the
canonical flow gated on area, and no step declared an area metric at all, so
Step 9 emitted `area.rpt` / `stats.json` and nothing on earth read the number.
A figure produced and never compared is the same defect the power gate was
written to remove — `matrix_mutation_ledger.ART-POWER-FIGURES-X1000` is the
worked example, and its lesson is the reason for the unit clause below.

THE DECLARED AUTHORITY, AND IT IS THE ONLY ONE
==============================================
`L19.fields.die_area_budget_um`, written by `phase1_post_process.py` beside
`power_budget_uw`, is the flow's one DECLARED area ceiling. It is a `WxH` string
in micrometres (the shape `l19_pdk_floorplan_contract_check._l19_die` and
`floorplan_contract` already parse), so the declared die area is `W * H` um^2.

MEASURED over the published corpus on 2026-08-20, by CONTENT rather than by
reputation (`benchmark-data` @ 146d665):

    L19*.json copies                                        177
      with die_area_budget_um set                             1   ('1300x1300')
    published runs carrying a synth area figure (chip_area)   2
      of those, with an L19 die area budget                   0

So there is not one published run in which this comparison could have been made
— the same posture power was in, and for the same reason. The honest verdict on
today's corpus is a REFUSAL that NAMES what is missing.

THE ONE BOUND THIS GATE APPLIES IS ARITHMETIC, NOT A CHOSEN RULER
=================================================================
Standard-cell area cannot exceed die area: utilisation is
`cell_area / die_area` and it is `<= 1.0` by definition of the words. A design
whose synthesised cell area already exceeds its DECLARED die cannot be placed on
that die at ANY utilisation. That bound is not a preference and not a number
anybody picked — it is what the two quantities mean.

Every TIGHTER bound would be a ruler fitted to the answer. A real floorplan
targets 40-70% utilisation, and this gate deliberately DOES NOT apply such a
target, because no design in this corpus declares one and deriving it from a
sibling design, from a PDK default, or from what the flow's own floorplanner
happens to choose would turn an unanswered question into an answered one. That
is the rule `ART-POWER-FIGURES-X1000` exists to state, and it binds here.

THE UNIT IS PART OF THE MEASUREMENT, AND THE PRODUCER REFUSES TO NAME IT
========================================================================
`phase2/stage2/synth/stats.json` records, verbatim:

    "chip_area": 2577.472,
    "chip_area_unit": "cell-library area unit (as declared by the library the
                       synthesis script loaded)"

That artefact DELIBERATELY declines to say the figure is in um^2 — it is
whatever unit the Liberty the synthesis loaded declares. The L19 ceiling is in
micrometres. Multiplying `1300 * 1300` and comparing it to `2577.472` without
establishing the unit would be asserting a unit the PRODUCING artefact refused
to assert, and if the library's unit were not um^2 the verdict would be wrong by
whatever factor separates them.

That is EXACTLY the shape of ART-POWER-FIGURES-X1000 — a figure off by 1000x
reading as the same PASS as the true one — one axis over. So an unestablished
unit is its own REFUSAL, distinct from "no ceiling declared" and distinct from
"no area figure": "I could not read it" and "I read it and it was fine" must
never produce the same artefact.

The unit is ESTABLISHED when the producing artefact says so (its
`chip_area_unit` names um^2 in any of the spellings below), or when a caller
carrying the requirement outside the artefact passes `--area-unit-um2`. Nothing
else establishes it, and no default is assumed.

    ceiling + figure + unit, cell_area <= die_area  -> PASS, naming both
    ceiling + figure + unit, cell_area >  die_area  -> FAIL, naming both
    ceiling absent                                  -> INCOMPLETE, naming
                                                       L19.die_area_budget_um
    no area figure readable                         -> INCOMPLETE, naming that
    figure present, unit not established            -> INCOMPLETE, naming
                                                       stats.json chip_area_unit

WHAT THIS GATE DOES NOT DO — stated so a reviewer does not have to find it
=========================================================================
  * It does not apply a utilisation TARGET. See above; that would be a threshold
    nobody declared.
  * It does not compare against the DEF die area, the floorplan, or any
    post-place figure. Step 9 is synthesis and runs before all of them; the
    declared ceiling is the only authority available at that point, which is the
    entire value of gating here rather than at streamout — a design that cannot
    fit is knowable at synthesis, not at GDS.
  * It does not read `cell_count` or wire count. Those are the axes
    `ppa_area_threshold_check` measures, and it measures them as a REDUCTION
    between an original/optimised PAIR against a threshold parsed from a PROMPT.
    That is a different question with a different authority and it is not this
    one; a general design has no "original" to diff against.
  * It does not sum submodule areas. `stats.json` carries
    `includes_submodules` and its own `selection` rationale; this gate reads the
    figure that artefact SELECTED and records the selection rule it reports, so
    the two cannot silently disagree about which number was compared.

INCOMPLETE EXITS 2, NOT 0
-------------------------
This gate is a BLOCKING `program_exit_zero` clause at step 9. rc 2 is this
flow's VACUOUS_PASS tier: `flow_compliance_check` records it as explicitly NOT a
clean result, so an empty tree cannot PASS a blocking clause while this file's
own last line says the area was never compared to anything. That is the repair
`power_total_vs_budget_check` took in vibe-ic#1017 and the shape
`gate_zero_denominator_refuses_check` requires.

chip-AGNOSTIC: it reads an area figure and a WxH micrometre budget. No foundry,
process, chip token or SKU appears anywhere in this file.

Exit codes: 0 = PASS, 1 = the cell area exceeds the declared die area,
2 = the question could not be put — INCOMPLETE — or a bad argument.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082/#1470

TOOL = "area_total_vs_budget_check"
VERSION = "1.0.0"

RC_OK, RC_FINDINGS, RC_ARG = 0, 1, 2
#: INCOMPLETE — the disclosed-skip tier. Named apart from RC_ARG because they
#: mean different things to a reader even though the flow maps both to
#: VACUOUS_PASS today. Same split as `power_total_vs_budget_check`.
RC_NOT_COMPARED = 2

#: Where a synthesis area figure may sit. DISCOVERED from the tree, never
#: enumerated: the corpus carries it at `phase2/stage2/synth/stats.json`, and a
#: phase-3 re-synthesis writes the same schema elsewhere.
_STATS_GLOBS = ("phase2/**/synth/stats.json", "**/synth/stats.json",
                "steps/**/stats.json")
#: Where L19 may sit. Phase 1 publishes the same document into several
#: directories (ai_docs / generated_docs / merged_docs); all are read and the
#: ceiling must not disagree between them.
_L19_GLOBS = ("phase1/**/L19*.json", "generated_docs/L19*.json",
              "**/L19_CONSTRAINTS_PDK.json")

#: The declared ceiling's spelling: `<W>x<H>` in micrometres. Same shape
#: `l19_pdk_floorplan_contract_check._WXH_RE` and `floorplan_contract` accept.
_WXH_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[xX*]\s*(\d+(?:\.\d+)?)\s*$")

#: Spellings that ESTABLISH the area figure as square micrometres. Matched
#: case-insensitively against the producing artefact's own unit string. The
#: corpus's current string ("cell-library area unit (as declared by the library
#: the synthesis script loaded)") matches NONE of these, deliberately.
_UM2_SPELLINGS = ("um^2", "um2", "um²", "µm^2", "µm2", "µm²", "μm^2", "μm2",
                  "μm²", "micron^2", "micron2", "square micron",
                  "square micrometre", "square micrometer")


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # reject NaN


def _rel(p: Path, project: Path) -> str:
    try:
        return str(p.relative_to(project))
    except ValueError:  # pragma: no cover - defensive
        return str(p)


def discover(project: Path, globs: Tuple[str, ...]) -> List[Path]:
    seen: Dict[str, Path] = {}
    for pat in globs:
        for p in project.glob(pat):
            if p.is_file():
                seen[str(p.resolve())] = p
    return [seen[k] for k in sorted(seen)]


def unit_is_um2(unit_text: Any) -> bool:
    """True only when the producing artefact ITSELF names square micrometres.

    PURE. An absent, empty or non-committal unit string is NOT um^2 — the
    default is refusal, never assumption. See the module docstring.
    """
    if not isinstance(unit_text, str) or not unit_text.strip():
        return False
    low = unit_text.lower()
    return any(s in low for s in _UM2_SPELLINGS)


def parse_die_budget_um2(raw: Any) -> Tuple[Optional[float], Optional[str]]:
    """``('WxH' micrometres) -> (area_um2, 'WxH')``; ``(None, None)`` otherwise.

    PURE. A BARE NUMBER IS REFUSED, deliberately: `die_area_budget_um` is named
    in micrometres, so a lone number is ambiguous between a side length and an
    area and there is no way to tell which the author meant. Guessing either
    would be the ruler-fitted-to-the-answer this gate exists to refuse.
    """
    if not isinstance(raw, str):
        return None, None
    m = _WXH_RE.match(raw)
    if not m:
        return None, None
    w, h = float(m.group(1)), float(m.group(2))
    if w <= 0 or h <= 0:
        return None, None
    return w * h, f"{m.group(1)}x{m.group(2)}"


def read_areas(project: Path) -> List[Dict[str, Any]]:
    """Every synthesised area figure the synth-stats family states.

    The figure and its UNIT travel together; a figure whose artefact declines to
    name the unit is carried with ``unit_established: False`` rather than being
    dropped, so the refusal can name it.
    """
    out: List[Dict[str, Any]] = []
    for fp in discover(project, _STATS_GLOBS):
        try:
            doc = json.loads(fp.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        area = _num(doc.get("chip_area"))
        if area is None or area <= 0:
            continue
        unit_text = doc.get("chip_area_unit")
        sel = doc.get("selection")
        out.append({
            "file": _rel(fp, project),
            "chip_area": area,
            "chip_area_unit": unit_text,
            "unit_established": unit_is_um2(unit_text),
            "top_module": doc.get("top_module"),
            "cell_count": doc.get("cell_count"),
            "includes_submodules": doc.get("includes_submodules"),
            "selection_rule": (sel.get("rule") if isinstance(sel, dict)
                               else None),
        })
    return out


def read_ceiling(project: Path) -> Tuple[Optional[float], Optional[str],
                                         List[Dict[str, Any]]]:
    """``(die_area_um2, 'WxH', sources)`` from L19 ``die_area_budget_um``.

    Every published copy is read. When copies DISAGREE the ceiling is treated as
    undeclared and the disagreement is reported: an authority two documents
    state differently is not an authority, and silently taking the first would
    make the verdict depend on glob order. (Same rule as the power gate.)
    """
    sources: List[Dict[str, Any]] = []
    for fp in discover(project, _L19_GLOBS):
        try:
            doc = json.loads(fp.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        fields = doc.get("fields")
        raw = (fields.get("die_area_budget_um")
               if isinstance(fields, dict) else None)
        if raw is None and "die_area_budget_um" in doc:
            raw = doc.get("die_area_budget_um")
        area, wxh = parse_die_budget_um2(raw)
        sources.append({"file": _rel(fp, project),
                        "die_area_budget_um": raw,
                        "die_area_um2": area, "wxh": wxh})
    stated = sorted({(s["die_area_um2"], s["wxh"]) for s in sources
                     if s["die_area_um2"] is not None})
    if len(stated) == 1:
        return stated[0][0], stated[0][1], sources
    return None, None, sources


def evaluate(project: Path, ceiling_override: Optional[str],
             unit_override: bool) -> Tuple[str, Dict[str, Any]]:
    """Return ``(verdict, report)``; verdict in {PASS, FAIL, INCOMPLETE}."""
    rep: Dict[str, Any] = {"program": TOOL, "version": VERSION,
                           "project": str(project), "findings": []}
    areas = read_areas(project)
    if unit_override:
        for a in areas:
            a["unit_established"] = True
            a["unit_established_by"] = "--area-unit-um2"
    rep["areas_read"] = areas

    if ceiling_override is not None:
        die_um2, wxh = parse_die_budget_um2(ceiling_override)
        sources = [{"file": "--die-area-um", "die_area_budget_um":
                    ceiling_override, "die_area_um2": die_um2, "wxh": wxh}]
    else:
        die_um2, wxh, sources = read_ceiling(project)
    rep["ceiling_sources"] = sources
    rep["die_area_um2"] = die_um2
    rep["die_area_wxh_um"] = wxh

    disagreeing = sorted({s["wxh"] for s in sources
                          if s["die_area_um2"] is not None})
    if die_um2 is None and len(disagreeing) > 1:
        rep["ceiling_disagreement"] = disagreeing

    usable = [a for a in areas if a["unit_established"]]
    lacks: List[str] = []
    if die_um2 is None:
        lacks.append(
            "L19_CONSTRAINTS_PDK.json fields.die_area_budget_um"
            + (f" (copies disagree: {disagreeing})" if len(disagreeing) > 1
               else " (unset or not a 'WxH' micrometre string in "
                    f"{len([s for s in sources if s['die_area_um2'] is None])}"
                    f" of {len(sources)} published copy/copies)"))
    if not areas:
        lacks.append("a readable chip_area in any synth stats artefact")
    elif not usable:
        lacks.append(
            "the area figure's UNIT — "
            + "; ".join(f"{a['file']} states chip_area_unit="
                        f"{a['chip_area_unit']!r}, which does not name um^2"
                        for a in areas[:3])
            + ". The producing artefact declines to assert the unit, so this "
              "gate will not assert it either")

    if lacks:
        rep["verdict"] = "INCOMPLETE"
        rep["missing_authority"] = "; ".join(lacks)
        return "INCOMPLETE", rep

    worst = max(usable, key=lambda d: d["chip_area"])
    cell_um2 = worst["chip_area"]
    rep["comparison"] = {"cell_area_um2": cell_um2,
                         "die_area_um2": die_um2,
                         "die_area_wxh_um": wxh,
                         "utilization": cell_um2 / die_um2,
                         "stated_in": worst["file"],
                         "selection_rule": worst["selection_rule"],
                         "limit": 1.0,
                         "limit_basis": ("utilisation <= 1.0 by definition; no "
                                         "tighter target is declared and none "
                                         "is derived"),
                         "over": cell_um2 > die_um2}
    if cell_um2 > die_um2:
        rep["findings"].append({
            "severity": "ERROR", "rule": "AREA_TOTAL_OVER_DECLARED_DIE",
            "message": (f"synthesised cell area {cell_um2:.4e} um^2 "
                        f"({worst['file']}) exceeds the DECLARED die area "
                        f"{die_um2:.4e} um^2 ({wxh} um, "
                        f"L19.die_area_budget_um) by "
                        f"{cell_um2 / die_um2:.4g}x — the design cannot be "
                        f"placed on the declared die at any utilisation")})
        rep["verdict"] = "FAIL"
        return "FAIL", rep
    rep["verdict"] = "PASS"
    return "PASS", rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", nargs="?", default=".",
                    help="project directory (default: cwd)")
    ap.add_argument("--die-area-um", default=None,
                    help="declared die area as 'WxH' in micrometres, "
                         "overriding L19 (for callers that carry the "
                         "requirement outside the L-doc set)")
    ap.add_argument("--area-unit-um2", action="store_true",
                    help="the caller ESTABLISHES that the synth area figure is "
                         "in square micrometres. Use only when the loaded "
                         "library's area unit is known outside the artefact; "
                         "without it an artefact that declines to name its unit "
                         "is an INCOMPLETE, never an assumption")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project = Path(args.project)
    if not project.is_dir():
        print(f"ERROR: {args.project!r} is not a directory", file=sys.stderr)
        return RC_ARG
    if args.die_area_um is not None:
        probe, _ = parse_die_budget_um2(args.die_area_um)
        if probe is None:
            print("ERROR: --die-area-um must be 'WxH' with W,H > 0 "
                  f"(got {args.die_area_um!r})", file=sys.stderr)
            return RC_ARG

    verdict, rep = evaluate(project, args.die_area_um, args.area_unit_um2)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out,
                          json.dumps(rep, indent=2, ensure_ascii=False) + "\n")

    scope = (f"read {len(rep['areas_read'])} synth area figure(s) and "
             f"{len(rep['ceiling_sources'])} L19 copy/copies")

    if verdict == "FAIL":
        print(f"[FAIL] {TOOL}: {scope}")
        for f in rep["findings"]:
            print(f"  - {f.get('rule')}: {f.get('message')}")
        return RC_FINDINGS

    if verdict == "PASS":
        c = rep["comparison"]
        print(f"[PASS] {TOOL}: {scope}. Compared synthesised cell area "
              f"{c['cell_area_um2']:.4e} um^2 ({c['stated_in']}) against the "
              f"DECLARED die area {c['die_area_um2']:.4e} um^2 "
              f"({c['die_area_wxh_um']} um, L19.die_area_budget_um); "
              f"utilization {c['utilization']:.4f}, limit 1.0 "
              f"({c['limit_basis']})")
        return RC_OK

    # The sentinel must START A LINE and survive the consumer's tail cut —
    # `flow_compliance_check.output_snippet` keeps only the LAST 300 characters
    # of stdout, so the detail goes FIRST and the token is the SHORT LAST LINE.
    # (Measured for the power gate; the same consumer reads this one.)
    print(f"{TOOL}: {scope}.")
    print("  An area ceiling is a REQUIREMENT and has to arrive in the "
          "design's own input documents. This gate will not derive one from a "
          "utilisation target, a PDK default or a sibling design, because a "
          "threshold nobody declared would turn an unanswered question into an "
          "answered one.")
    print(f"INCOMPLETE: synthesised area was NOT compared against anything — "
          f"missing authority: {rep['missing_authority']}.")
    return RC_NOT_COMPARED


if __name__ == "__main__":
    sys.exit(main())
