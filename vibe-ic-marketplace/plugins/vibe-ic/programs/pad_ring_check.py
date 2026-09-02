#!/usr/bin/env python3
"""pad_ring_check — step 15.5ic's gate: the pad ring is re-measured from the
artefacts, the ring is checked for ABUTMENT, and a skip must name what it
skipped over.

ENFORCEMENT: blocking — ``phase3_one_shot_runner.step_pad_ring_gen`` invokes
this independent checker inline before routing. Any nonzero rc makes that step
non-PASS; ``_prepare_padring_for_route`` then returns no routing consumer and
the PnR step fails with ``PADRING_PREROUTE_BLOCKED``. Canonical step 15.5ic
also consumes the same rc through a blocking ``program_exit_zero`` clause.
This token names the measured runner/flow control path, not finding severity.
Kept in the first 4 kB because ``declared_intent`` reads only ``text[:4000]``.

WHAT THIS REFUSES
=================
Three failure shapes.

  A CLAIM THAT IS NOT CORROBORATED. `pad_ring_gen` reports a placed ring; this
  gate re-derives every claim from `padring.def`, from `floorplan.def` and
  from the PDK's own IO cell library — the instance is there, it is PLACED,
  its master is the one claimed AND the one the block instantiates, its
  footprint is the one the library gives that master, its centre is nearest
  the die edge it claims, it is inside the die, and it does not overlap its
  neighbour. The report is the thing under audit, never the evidence for it.

  A RING THAT DOES NOT ABUT. Upstream's placer ends with `connect_by_abutment`:
  THE RING'S POWER AND GROUND ARE NOT ROUTED, they are formed by cells
  touching. A ring that places perfectly and does not abut is electrically
  nothing, and a placement check does not notice. So this gate walks each side
  corner -> filler/pad -> ... -> corner and requires every adjacent extent to
  touch with exactly zero residual gap. A declaration that a gap *could* be
  tiled is not evidence that filler instances were placed; every filler is
  independently re-read from the DEF and the PDK IO library.

  A SKIP THAT SAYS NOTHING. A report may legitimately say "the pad ring config
  was not declared, so no ring was generated" — that is the honest state of
  this flow today. What it may NOT do is say so without naming what it went
  without, VARIABLE BY VARIABLE. So a SKIP is accepted only when it carries a
  reason of at least the length the flow demands of an
  `absent_condition_reason`, a non-empty `missing_inputs`, and a reason that
  names every input AND every absent config variable in it. A skip that
  discloses nothing exits 1, exactly like a wrong answer.

AND NOTHING-TO-CHECK IS NEVER A PASS. An absent report is not a skip: it means
the step's producer never ran, and that is exit 1. Only a report that STATES a
disclosed absence earns exit 2 — the flow's "could not measure" tier — and
even then `padring.def` is a declared output of the step that was not
produced, so the flow reports the step MISSING. This gate is not the thing
that turns an ungenerated pad ring into a green step.

WHY `--json` IS BOTH READ AND WRITTEN
=====================================
The step declares `reports/phase3/padring.json` as a required output AND the
flow declares this gate with `--json` pointing at that same path. The gate
therefore READS the producer's report from there and writes back a document
carrying the producer's payload VERBATIM under `producer`, with the gate's own
verdict beside it. Overwriting the producer's claim with the auditor's would
leave the audit standing on a file the audit itself authored — the
self-certification the flow's compliance checker refuses by name. Re-running
is idempotent: a merged document is recognised and its `producer` half is what
gets audited.

EXIT
    0  PASS — a ring is claimed, every claim was corroborated, and it abuts.
    2  SKIP — the report discloses an absent input, by name, with a reason.
    1  FAIL — no report, an unreadable one, an undisclosed skip, a producer
       FAIL, or a claim the artefacts do not bear out.

chip-AGNOSTIC: no chip, vendor, SKU, foundry or process-node literal.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _atomic_artefact import write_json as atomic_write_json

import _pad_ring as PR

GATE = "pad_ring_check"


def _finding(rule: str, message: str, severity: str = "ERROR") -> Dict[str, str]:
    return {"severity": severity, "rule": rule, "message": message}


def _unwrap(doc: Any) -> Tuple[Any, bool]:
    """Return (producer report, was_already_merged)."""
    if isinstance(doc, dict) and doc.get("gate") == GATE and "producer" in doc:
        return doc["producer"], True
    return doc, False


# ── the SKIP branch ─────────────────────────────────────────────────────────
def _audit_skip(project: Path, rep: Dict[str, Any]) -> List[Dict[str, str]]:
    """A skip is accepted only when it says what it skipped over."""
    out: List[Dict[str, str]] = []
    missing = rep.get("missing_inputs")
    if not isinstance(missing, list) or not missing:
        return [_finding(
            "PADRING_SKIP_UNDISCLOSED",
            "the report skips this step and names no absent input. A skip "
            "that discloses nothing is indistinguishable from a step that "
            "was never attempted")]
    reason = str(rep.get("reason") or "")
    if len(reason.strip()) < PR.MIN_REASON_CHARS:
        out.append(_finding(
            "PADRING_SKIP_REASON_TOO_SHORT",
            f"the skip reason is {len(reason.strip())} character(s); the flow "
            f"refuses an absent-condition reason shorter than "
            f"{PR.MIN_REASON_CHARS}, and a skip a program writes is the same "
            f"promise"))
    for m in missing:
        tokens: List[str] = []
        if isinstance(m, dict):
            tokens.append(str(m.get("path") or m.get("input") or ""))
            tokens += [str(v) for v in (m.get("variables_absent") or [])]
        elif isinstance(m, str):
            tokens.append(m)
        if not any(tokens):
            out.append(_finding("PADRING_SKIP_UNDISCLOSED",
                                "an entry of `missing_inputs` names nothing"))
            continue
        for token in tokens:
            if not token:
                continue
            if token not in reason:
                out.append(_finding(
                    "PADRING_SKIP_DOES_NOT_NAME_INPUT",
                    f"`missing_inputs` lists {token!r} but the stated reason "
                    f"never names it — the reason a reader sees must name "
                    f"every input, and every config variable, that was gone"))
    if (project / PR.PADRING_DEF_REL).is_file():
        out.append(_finding(
            "PADRING_SKIP_CONTRADICTED",
            f"the report skips this step, yet {PR.PADRING_DEF_REL} exists — "
            f"a ring is on disk that this report does not account for"))
    return out


# ── the PASS branch ─────────────────────────────────────────────────────────
def _audit_ring(project: Path, rep: Dict[str, Any],
                lib: PR.IoLibrary,
                library_declined: str = "") -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []

    def_rel = str(rep.get("padring_def") or PR.PADRING_DEF_REL)
    def_path = project / def_rel
    if not def_path.is_file():
        return [_finding("PADRING_DEF_ABSENT",
                         f"the report claims a placed ring but {def_rel} does "
                         f"not exist — a PASS with no layout behind it")]
    try:
        ring = PR.read_def(def_path)
    except (PR.DefError, OSError) as exc:
        return [_finding("PADRING_DEF_UNREADABLE", f"{def_rel}: {exc}")]

    pads = rep.get("pads")
    corners = rep.get("corners")
    fillers = rep.get("fillers")
    if not isinstance(pads, list) or not pads:
        return [_finding(
            "PADRING_EMPTY",
            "the report claims PASS and declares no pad — a ring of zero pads "
            "is an empty set, and a green over an empty set is the defect "
            "this gate exists to refuse")]
    if not isinstance(corners, list):
        corners = []
    if not isinstance(fillers, list):
        fillers = []
        out.append(_finding(
            "PADRING_FILLER_POPULATION_UNDECLARED",
            "the producer report carries no filler instance population; "
            "a list of masters or fillable-gap arithmetic is not placement"))

    box = ring.box
    llx, lly, urx, ury = box
    cfg = rep.get("config") if isinstance(rep.get("config"), dict) else {}

    # ── the pads must be FOUND cells, not drawn ones ───────────────────────
    if not lib.resolved:
        out.append(_finding(
            "PADRING_MASTERS_UNCORROBORATED",
            "no PDK IO cell library resolved, so no declared master could be "
            "shown to be a PDK cell rather than a drawn shape. That is the "
            "central claim of this step and it is unverified — set PDK_ROOT / "
            "PDK or pass --io-lef. An unverifiable claim is not a pass"
            + (f". The run's own record was consulted and declined: "
               f"{library_declined}" if library_declined else "")))

    # ── upstream's two site lookups, re-run against the library ────────────
    for var in ("PAD_SITE_NAME", "PAD_CORNER_SITE_NAME"):
        name = str(cfg.get(var) or "")
        if not name:
            out.append(_finding(
                "PAD_CONFIG_VARIABLE_ABSENT",
                f"the report records no {var}; the ring's spacing arithmetic "
                f"rounds to that site's width and cannot be re-derived "
                f"without it"))
            continue
        if not lib.resolved:
            continue
        site = lib.resolve_site(name)
        if site is None:
            out.append(_finding(
                "PAD_SITE_NOT_FOUND",
                f"{var}={name!r} is declared by neither PDK view this run "
                f"resolved — not as a LEF SITE record and not as a tech-view "
                f"pad site declaration (PAD-class sites available: "
                f"{lib.pad_class_site_names()})"))
        elif site["class"] != "PAD":
            out.append(_finding(
                "PAD_SITE_CLASS_NOT_PAD",
                f"{var}={name!r} has CLASS {site['class'] or '(none)'!r}, "
                f"expected PAD"))

    for name, recs in sorted(lib.site_declaration_conflicts.items()):
        out.append(_finding(
            "PAD_SITE_DECLARATION_AMBIGUOUS",
            f"pad site {name!r} is declared at {len(recs)} different sizes by "
            f"the PDK tech views this run resolved "
            f"({[dict(r, size=list(r['size'])) for r in recs]}) — the site "
            f"width is what the ring's spacing arithmetic rounds to, so it is "
            f"not re-derivable and this gate does not pick one"))

    declared_fillers = set(str(x) for x in
                           (cfg.get("PAD_FILLERS") or []))
    placed_count = rep.get("fillers_placed")
    if not isinstance(placed_count, int) or placed_count != len(fillers):
        out.append(_finding(
            "PADRING_FILLER_COUNT_MISMATCH",
            f"fillers_placed={placed_count!r}, but the report declares "
            f"{len(fillers)} concrete filler instance record(s)"))
    unperformed = (rep.get("unperformed")
                   if isinstance(rep.get("unperformed"), dict) else {})
    if unperformed.get("io_filler_placement"):
        out.append(_finding(
            "PADRING_FILLER_PLACEMENT_UNPERFORMED",
            "the producer declares IO filler placement unperformed; a ring "
            "whose supply cells do not touch is not a PASS"))

    # ── per-cell corroboration ─────────────────────────────────────────────
    extent: Dict[str, Tuple[int, int]] = {}
    seen: Dict[str, Dict[str, Any]] = {}
    for cell, kind in ([(p, "pad") for p in pads] +
                       [(c, "corner") for c in corners] +
                       [(f, "filler") for f in fillers]):
        if not isinstance(cell, dict):
            out.append(_finding("PADRING_ENTRY_MALFORMED",
                                f"a {kind} entry is not an object"))
            continue
        inst = str(cell.get("instance") or "")
        if not inst:
            out.append(_finding("PADRING_ENTRY_MALFORMED",
                                f"a {kind} entry declares no instance"))
            continue
        if inst in seen:
            out.append(_finding("PADRING_INSTANCE_DUPLICATED",
                                f"{inst!r} is declared twice in the report"))
        seen[inst] = cell

        comp = ring.components.get(inst)
        if comp is None:
            out.append(_finding(
                "PAD_INSTANCE_ABSENT_FROM_DEF",
                f"the report declares {kind} {inst!r} but {def_rel} has no "
                f"such COMPONENT"))
            continue
        if not comp.placed:
            out.append(_finding(
                "PAD_INSTANCE_UNPLACED",
                f"{inst!r} is {comp.status} in {def_rel} — an unplaced pad "
                f"has no position in the ring"))
            continue
        if comp.master != str(cell.get("master") or ""):
            out.append(_finding(
                "PAD_MASTER_MISMATCH",
                f"{inst!r}: the report claims master "
                f"{cell.get('master')!r}, {def_rel} instantiates "
                f"{comp.master!r}"))

        # ── the DEF's orientation IS the report's, exactly ────────────────
        # NOT re-derived from the footprint. A MIRROR and a ROTATION share a
        # bounding box -- FS against S on a north pad, FN against E on a
        # square corner -- so every extent, fit, abutment and spacing check in
        # this file agrees either way, and a DEF reader deriving pin positions
        # does not. MEASURED on this gate before the check existed: flipping a
        # north pad FS -> S and a corner FN -> E in `padring.def` each left it
        # rc 0 with ZERO findings. That is the whole defect class this step was
        # corrected for, unguarded in the artefact a downstream tool parses.
        rep_orient = PR.normalise_orient(cell.get("orient"))
        def_orient = PR.normalise_orient(comp.orient)
        if rep_orient is None:
            out.append(_finding(
                "PAD_ORIENT_UNDECLARED",
                f"{inst!r} declares orientation {cell.get('orient')!r}, "
                f"which is not one of {list(PR.DEF_ORIENTS)} — an orientation "
                f"that cannot be read cannot be corroborated"))
        elif def_orient is None:
            out.append(_finding(
                "PAD_ORIENT_UNREADABLE_IN_DEF",
                f"{inst!r} is placed in {def_rel} with orientation "
                f"{comp.orient!r}, which is not one of "
                f"{list(PR.DEF_ORIENTS)}"))
        elif def_orient != rep_orient:
            out.append(_finding(
                "PAD_ORIENT_DISAGREES_WITH_DEF",
                f"{inst!r}: the report declares orientation {rep_orient!r} "
                f"and {def_rel} places it {def_orient!r}. These may share a "
                f"bounding box — a mirror is not a rotation — so no extent or "
                f"spacing check can see the difference, and a reader deriving "
                f"pin positions from the footprint gets a different cell"))

        w, h = cell.get("width_dbu"), cell.get("height_dbu")
        if not isinstance(w, int) or not isinstance(h, int) or w <= 0 or h <= 0:
            out.append(_finding(
                "PAD_FOOTPRINT_UNDECLARED",
                f"{inst!r} declares no positive footprint "
                f"(width_dbu={w!r}, height_dbu={h!r}), so neither its side "
                f"nor its extent can be corroborated"))
            continue

        if lib.resolved:
            size = lib.masters.get(comp.master)
            if size is None:
                out.append(_finding(
                    "PAD_MASTER_NOT_IN_PDK_IO_LIBRARY",
                    f"{inst!r}: master {comp.master!r} is not in the IO cell "
                    f"library this run resolved ({len(lib.masters)} "
                    f"master(s)) — the ring must be built from PDK IO cells, "
                    f"not drawn ones"))
            else:
                lw, lh = PR.footprint(size, comp.orient or "N", ring.units)
                if (w, h) != (lw, lh):
                    out.append(_finding(
                        "PAD_FOOTPRINT_DISAGREES_WITH_LIBRARY",
                        f"{inst!r}: the report declares {w}x{h} DEF unit(s), "
                        f"and {comp.master!r} oriented {comp.orient} is "
                        f"{lw}x{lh} in the IO library"))
                w, h = lw, lh
        extent[inst] = (w, h)

        if comp.x < llx or comp.y < lly or comp.x + w > urx or comp.y + h > ury:
            out.append(_finding(
                "PAD_OUTSIDE_DIE",
                f"{inst!r} occupies ({comp.x},{comp.y})..({comp.x + w},"
                f"{comp.y + h}) and the die is {box} — a pad off the die "
                f"reaches no package pin"))

        cx, cy = comp.x + w / 2.0, comp.y + h / 2.0
        if kind in ("pad", "filler"):
            side = str(cell.get("side") or "")
            got = PR.nearest_side(cx, cy, box)
            if side not in PR.SIDES:
                out.append(_finding(
                    "PAD_SIDE_UNDECLARED",
                    f"{inst!r} declares side {side!r}, not one of "
                    f"{list(PR.SIDES)}"))
            elif got != side:
                out.append(_finding(
                    "PAD_SIDE_MISMATCH",
                    f"{kind} {inst!r} is declared on side {side!r} but its centre in "
                    f"{def_rel} is nearest the {got!r} die edge"))
            if kind == "filler" and comp.master not in declared_fillers:
                out.append(_finding(
                    "PADRING_FILLER_MASTER_UNDECLARED",
                    f"filler {inst!r} uses master {comp.master!r}, which is "
                    f"not one of PAD_FILLERS={sorted(declared_fillers)}"))
        elif kind == "corner":
            pos = str(cell.get("position") or "")
            if pos not in PR.CORNER_POSITIONS:
                out.append(_finding(
                    "PADRING_CORNERS_INCOMPLETE",
                    f"{inst!r} declares corner position {pos!r}, not one of "
                    f"{list(PR.CORNER_POSITIONS)}"))
            else:
                want = ("S" if cy < (lly + ury) / 2.0 else "N") + \
                       ("W" if cx < (llx + urx) / 2.0 else "E")
                if want != pos:
                    out.append(_finding(
                        "PADRING_CORNER_POSITION_MISMATCH",
                        f"{inst!r} is declared at the {pos} die corner but "
                        f"sits in the {want} quadrant of {def_rel}"))

    # ── one corner cell per die corner ─────────────────────────────────────
    need = ring.n_die_corners
    positions = [str(c.get("position") or "") for c in corners
                 if isinstance(c, dict)]
    good = [p for p in positions if p in PR.CORNER_POSITIONS]
    if len(set(good)) != need or len(good) != len(positions):
        out.append(_finding(
            "PADRING_CORNERS_INCOMPLETE",
            f"the die declared by {def_rel} has {need} corner(s); the report "
            f"binds {len(set(good))} distinct declared position(s) out of "
            f"{len(positions)} corner entr(y/ies): {sorted(set(positions))} — "
            f"a ring with an unfilled corner does not abut"))

    # ── no two cells on a side may overlap, and every actual gap is zero ───
    by_pos = {str(c.get("position")): c for c in corners
              if isinstance(c, dict)}
    filler_widths = sorted({
        PR.footprint(lib.masters[f], "N", ring.units)[0]
        for f in declared_fillers if f in lib.masters})
    if lib.resolved and not filler_widths:
        out.append(_finding(
            "PADRING_FILLER_UNRESOLVED",
            f"none of the declared filler master(s) "
            f"{cfg.get('PAD_FILLERS')!r} is in the IO cell library, so no gap "
            f"in the ring can be shown to be closable — abutment is what "
            f"carries the ring's supply and it is unverified"))

    ends = {"S": ("SW", "SE"), "N": ("NW", "NE"),
            "W": ("SW", "NW"), "E": ("SE", "NE")}
    for side in PR.SIDES:
        axis = "x" if side in PR.HORIZONTAL_SIDES else "y"
        chain: List[Tuple[int, int, str]] = []
        for pos in ends[side]:
            c = by_pos.get(pos)
            comp = ring.components.get(str(c.get("instance"))) if c else None
            if comp is None or not comp.placed or \
                    comp.instance not in extent:
                chain = []
                break
            e = extent[comp.instance]
            lo = comp.x if axis == "x" else comp.y
            chain.append((lo, lo + (e[0] if axis == "x" else e[1]),
                          comp.instance))
        if not chain:
            continue                       # already reported above
        for p in pads:
            if not isinstance(p, dict) or str(p.get("side")) != side:
                continue
            comp = ring.components.get(str(p.get("instance") or ""))
            if comp is None or not comp.placed or \
                    comp.instance not in extent:
                continue
            e = extent[comp.instance]
            lo = comp.x if axis == "x" else comp.y
            chain.append((lo, lo + (e[0] if axis == "x" else e[1]),
                          comp.instance))
        for filler in fillers:
            if not isinstance(filler, dict) or \
                    str(filler.get("side")) != side:
                continue
            comp = ring.components.get(str(filler.get("instance") or ""))
            if comp is None or not comp.placed or \
                    comp.instance not in extent:
                continue
            e = extent[comp.instance]
            lo = comp.x if axis == "x" else comp.y
            chain.append((lo, lo + (e[0] if axis == "x" else e[1]),
                          comp.instance))
        chain.sort()
        for (a0, a1, an), (b0, _b1, bn) in zip(chain, chain[1:]):
            gap = b0 - a1
            if gap < 0:
                out.append(_finding(
                    "PAD_OVERLAP",
                    f"side {side!r}: {an!r} spans {a0}..{a1} and {bn!r} "
                    f"starts at {b0} — the two cells overlap by {-gap} DEF "
                    f"unit(s)"))
            elif gap > 0:
                out.append(_finding(
                    "PADRING_DOES_NOT_ABUT",
                    f"side {side!r}: an actual {gap} DEF unit gap remains "
                    f"between {an!r} and {bn!r}. Declared filler widths "
                    f"{filler_widths} do not count until instances occupy "
                    f"the gap; ring power and ground require cells TOUCHING"))

    # ── the pads ARE the BTerms, and they are instances of the block ───────
    fp = project / PR.FLOORPLAN_DEF_REL
    if not fp.is_file():
        out.append(_finding(
            "PADRING_BTERM_COVERAGE_UNCORROBORATED",
            f"{PR.FLOORPLAN_DEF_REL} is absent, so neither the claim that "
            f"every top-level port reaches a pad nor the claim that every pad "
            f"instance exists in the block could be checked against anything. "
            f"Not checked is not clean"))
    else:
        try:
            floor = PR.read_def(fp)
        except (PR.DefError, OSError) as exc:
            out.append(_finding("FLOORPLAN_DEF_UNREADABLE",
                                f"{PR.FLOORPLAN_DEF_REL}: {exc}"))
        else:
            covered = {str(p.get("signal") or "") for p in pads
                       if isinstance(p, dict)}
            uncovered = sorted(set(floor.pins) - covered)
            if uncovered:
                out.append(_finding(
                    "BTERM_WITHOUT_PAD",
                    f"{len(uncovered)} of {len(floor.pins)} floorplan "
                    f"BTerm(s) reach no pad: {uncovered[:8]} — once a pad "
                    f"ring exists the pads ARE the BTerms"))
            orphan = sorted(str(p.get("instance")) for p in pads
                            if isinstance(p, dict)
                            and str(p.get("instance")) not in floor.components)
            if orphan:
                out.append(_finding(
                    "PAD_INSTANCE_NOT_IN_BLOCK",
                    f"{len(orphan)} pad instance(s) are not COMPONENTS of "
                    f"{PR.FLOORPLAN_DEF_REL}: {orphan[:8]} — the ring names "
                    f"instances the netlist must already carry, and this step "
                    f"does not create them"))
    return out


# ── main ────────────────────────────────────────────────────────────────────
#: What `io_pad_chip_top_gen` writes. The same record `pad_assignment_gen`
#: reads, for the same reason: it is this RUN's own account of which files it
#: physically opened.
DERIVED_CHIP_TOP_REL = "reports/phase3/io_pad_chip_top.json"


def declared_masters(producer: Dict[str, Any]) -> List[str]:
    """Every IO master the producer's report CLAIMS, pads + corners + fillers.

    The names are read out of the placed-instance records, not out of the
    config, because the config declares a filler FAMILY and the ring places
    from it; a library that carries the family name and not the instance's
    master would corroborate nothing.
    """
    names: List[str] = []
    for key in ("pads", "corners", "fillers"):
        for rec in producer.get(key) or []:
            if isinstance(rec, dict) and rec.get("master"):
                names.append(str(rec["master"]))
    return sorted(set(names))


def io_lefs_this_run_recorded(project: Path, producer: Dict[str, Any]
                              ) -> Tuple[List[Path], List[Path], str]:
    """The IO views THIS RUN opened, from its own producer record.

    WHY THIS EXISTS, MEASURED. The flow declares step 15.5ic's gate as
    `pad_ring_check . --json reports/phase3/padring.json` with no PDK
    argument; `phase3_one_shot_runner` dispatches the same program with
    `--pdk-root/--pdk`. On one tree (spm, an open 5 V PDK, plugin 1.15.99) the
    flow's shape returned FAIL/`PADRING_MASTERS_UNCORROBORATED` and the
    runner's returned PASS — the same ring, the same disk, two verdicts. The
    root is a per-host, per-container path and the clause is a static string,
    so it cannot be written into the yaml.

    WHAT IS AND IS NOT ADOPTED. `io_pad_chip_top_gen` records the ABSOLUTE
    paths of the IO LEFs it read. Those files are re-opened and parsed HERE —
    the corroboration is still LEF CONTENT, never the producer's word for it.
    And the list is adopted ONLY IF the files it names carry EVERY master the
    ring claims. A record whose LEFs do not is not a library this gate
    resolved: reporting `PAD_MASTER_NOT_IN_PDK_IO_LIBRARY` off it would be a
    claim about the PDK that nothing here measured, so the fallback is
    declined and `PADRING_MASTERS_UNCORROBORATED` stands, exactly as it does
    with no record at all.

    Returns (lefs, site_declaration_views, why) — `why` is "" when adopted.
    """
    rec_path = project / DERIVED_CHIP_TOP_REL
    if not rec_path.is_file():
        return [], [], f"{DERIVED_CHIP_TOP_REL} is absent"
    try:
        doc = json.loads(rec_path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        return [], [], f"{DERIVED_CHIP_TOP_REL} is not readable JSON: {exc}"
    if doc.get("verdict") != "WROTE":
        return [], [], (f"{DERIVED_CHIP_TOP_REL} verdict is "
                        f"{doc.get('verdict')!r}, so it opened no library")
    lefs = [Path(x) for x in (doc.get("io_library_lefs") or [])
            if isinstance(x, str)]
    lefs = [p for p in lefs if p.is_file()]
    if not lefs:
        return [], [], (f"{DERIVED_CHIP_TOP_REL} names no IO LEF that exists "
                        f"on this host")
    claimed = declared_masters(producer)
    carried = PR.IoLibrary(lefs).masters
    absent = [m for m in claimed if m not in carried]
    if absent:
        return [], [], (
            f"the {len(lefs)} IO LEF(s) {DERIVED_CHIP_TOP_REL} names do not "
            f"carry {len(absent)} of the {len(claimed)} master(s) the ring "
            f"claims ({', '.join(absent[:4])}"
            f"{'…' if len(absent) > 4 else ''}), so they corroborate nothing")
    # The tech view lives beside the reference view: <tree>/libs.ref/<lib>/lef
    # -> <tree>. Derived from the path this run actually read, so no root is
    # assumed and no tree is named here.
    decls: List[Path] = []
    for lef in lefs:
        for parent in lef.parents:
            if parent.name == PR._LIBS_REF:
                tree = parent.parent
                decls.extend(PR.discover_io_site_declarations(
                    str(tree.parent), tree.name))
                break
    seen: Dict[str, Path] = {}
    for d in decls:
        seen.setdefault(str(d), d)
    return lefs, list(seen.values()), ""


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None,
                    help=("the step's pad-ring report: READ as the producer's "
                          "claim, then written back with this gate's verdict "
                          "beside it (default %s)" % PR.REPORT_REL))
    ap.add_argument("--io-lef", action="append", default=None)
    ap.add_argument("--pdk-root", default=None)
    ap.add_argument("--pdk", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{GATE}] project dir not found: {project}", file=sys.stderr)
        return 1

    rep_path = Path(args.json) if args.json else (project / PR.REPORT_REL)
    if not rep_path.is_absolute():
        rep_path = (Path.cwd() / rep_path).resolve()

    findings: List[Dict[str, str]] = []
    producer: Any = None
    verdict, rc, reason = "FAIL", 1, ""

    if not rep_path.is_file():
        reason = (f"no pad-ring report at {rep_path} — `pad_ring_gen` did not "
                  f"run. An absent report is not a disclosed skip: nothing "
                  f"stated why there is no ring, so nothing was measured")
        findings.append(_finding("PADRING_REPORT_ABSENT", reason))
    else:
        try:
            doc = json.loads(rep_path.read_text(errors="replace"))
        except (ValueError, OSError) as exc:
            reason = f"{rep_path} is not readable JSON: {exc}"
            findings.append(_finding("PADRING_REPORT_UNREADABLE", reason))
            doc = None
        if doc is not None:
            producer, _merged = _unwrap(doc)
            if not isinstance(producer, dict):
                reason = "the pad-ring report is not a JSON object"
                findings.append(_finding("PADRING_REPORT_UNREADABLE", reason))
            elif producer.get("schema") != PR.SCHEMA:
                reason = (f"report schema {producer.get('schema')!r} is not "
                          f"{PR.SCHEMA!r} — this gate will not interpret an "
                          f"unrecognised payload as this step's evidence")
                findings.append(
                    _finding("PADRING_REPORT_SCHEMA_UNKNOWN", reason))
            else:
                v = producer.get("verdict")
                if v not in PR.VERDICTS:
                    reason = (f"report verdict {v!r} is not one of "
                              f"{list(PR.VERDICTS)}")
                    findings.append(
                        _finding("PADRING_VERDICT_UNRECOGNISED", reason))
                elif v == "FAIL":
                    reason = (f"the producer refused to generate a ring: "
                              f"{producer.get('reason') or '(no reason stated)'}")
                    findings.append(
                        _finding("PADRING_GENERATION_FAILED", reason))
                elif v == "SKIP":
                    findings.extend(_audit_skip(project, producer))
                    if not findings:
                        verdict, rc = "SKIP", 2
                        reason = (
                            "the producer disclosed its absent inputs by "
                            "name; no pad ring exists. This is exit 2 — the "
                            "flow's 'could not measure' tier — and the step's "
                            "declared padring.def is still absent, so the "
                            "step is not done")
                    else:
                        reason = findings[0]["message"]
                else:
                    library_source = ""
                    library_declined = ""
                    lefs = ([Path(p) for p in args.io_lef] if args.io_lef
                            else PR.discover_io_lefs(args.pdk_root, args.pdk))
                    # Both PDK views, the same two the producer reads. An
                    # auditor that consulted only the LEF would report
                    # PAD_SITE_NOT_FOUND against a ring the PDK had in fact
                    # declared the site for.
                    decls = PR.discover_io_site_declarations(
                        args.pdk_root, args.pdk)
                    if not lefs:
                        # NOTHING was passed and nothing resolved from the
                        # environment. Before reporting that no library could
                        # be corroborated, ask the run what IT opened.
                        lefs, run_decls, why = io_lefs_this_run_recorded(
                            project, producer)
                        if lefs:
                            decls = decls or run_decls
                            library_source = (
                                f"{len(lefs)} IO LEF(s) recorded by this run "
                                f"in {DERIVED_CHIP_TOP_REL}")
                        else:
                            library_declined = why
                    findings.extend(
                        _audit_ring(project, producer,
                                    PR.IoLibrary(lefs, decls),
                                    library_declined))
                    if not findings:
                        verdict, rc = "PASS", 0
                        reason = (
                            f"every claim in the report was re-derived from "
                            f"{producer.get('padring_def')}, from "
                            f"{PR.FLOORPLAN_DEF_REL} and from the PDK IO cell "
                            f"library; every declared filler instance exists "
                            f"in the DEF and every adjacent ring cell "
                            f"physically touches with zero residual gap"
                            + (f"; IO library: {library_source}"
                               if library_source else ""))
                    else:
                        reason = findings[0]["message"]

    audit = {
        "schema": PR.SCHEMA,
        "gate": GATE,
        "verdict": verdict,
        "rc": rc,
        "reason": reason,
        "report_path": str(rep_path),
        "findings": findings,
        "producer": producer,
    }
    try:
        rep_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(rep_path, audit)
    except OSError as exc:                                # pragma: no cover
        print(f"[{GATE}] could not write {rep_path}: {exc}", file=sys.stderr)

    print(f"=== {GATE} ({project.name}) ===")
    print(f"  verdict: {verdict}  (rc={rc})")
    if reason:
        print(f"  {reason}")
    for f in findings[:12]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    if len(findings) > 12:
        print(f"  ... and {len(findings) - 12} more finding(s)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
