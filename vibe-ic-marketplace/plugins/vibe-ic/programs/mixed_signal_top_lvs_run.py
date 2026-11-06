#!/usr/bin/env python3
"""Merge mixed-signal layouts with KLayout and compare Magic extraction in netgen.

The verdict comes from the native netgen report. Input ambiguity and wrong
macro placement remain errors; a missing tool or PDK remains unmeasured.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402
import lvs_verdict_tokens as _lvt  # noqa: E402  — #524 shared verdict tokens
# #626 — the ONE rule for "which DEF describes this layout", shared with
# `gds_port_label_check` so the two halves cannot pair to different DEFs.
from def_gds_port_power_restore import (  # noqa: E402
    def_design_name,
    def_rank,
)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _container_exec as _ce  # noqa: E402 — the ONE guarded docker-exec argv
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated
import _atomic_artefact as _aa  # noqa: E402  (vibe-ic#1082)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

TOOLS_IN_CONTAINER = "/foss/tools"
PDKS_IN_CONTAINER = os.environ.get("PDK_ROOT", "/foss/pdks")
#: DECIDE PER MACRO, never append (vibe-ic#597).
#:
#: `Layout.read` APPENDS into a cell that already exists under the same name.
#: Once OpenROAD's stream-out has been handed the hardmacro GDS, the digital
#: GDS already carries a REAL body for that macro — so reading the macro file
#: on top of it put every polygon in twice. Measured: `delta_sigma` 45678 ->
#: 91356 own shapes, `ldo` 36887 -> 73774. Exactly double, both blocks.
#:
#: Magic then extracts the duplicated geometry as duplicated devices, so the
#: layout-side device count is 2x the schematic's and LVS can never match — a
#: failure whose report reads like a design defect.
#:
#: PRESENCE OF THE CELL NAME IS NOT EVIDENCE THAT IT IS AN ABSTRACT, and the
#: old merge assumed it was. The branch is now taken on whether the cell
#: actually holds geometry, and BOTH branches are recorded per macro in
#: merge.json with the before/after shape count, so a doubled body can be seen
#: in the artefact rather than inferred from an LVS mismatch.
#: `- u_ds3 delta_sigma + PLACED ( 123000 456000 ) N ;` — DEF COMPONENTS.
_DEF_COMPONENT_RE = re.compile(
    r"^\s*-\s+(?P<inst>\S+)\s+(?P<cell>\S+)\s+\+\s*"
    r"(?:FIXED|PLACED|COVER)\s*\(\s*(?P<x>-?\d+)\s+(?P<y>-?\d+)\s*\)\s*"
    r"(?P<orient>[A-Z]+)", re.MULTILINE)
_DEF_UNITS_RE = re.compile(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)",
                           re.MULTILINE)

#: DEF orientation -> KLayout `Trans(rot, mirrx)`. Only the four unflipped
#: orientations and the two flips this can back are mapped; `FE` / `FW` are
#: DELIBERATELY absent. vibe-ic#612 asks for macros to be placed where the
#: floorplan says, and a placement at the wrong orientation is worse than none:
#: it looks integrated and is not. An unmapped orientation refuses, by name.
_DEF_ORIENT_TO_KLAYOUT = {
    "N": (0, False), "W": (1, False), "S": (2, False), "E": (3, False),
    "FS": (0, True),           # mirror at the x-axis
    "FN": (2, True),           # mirror at the y-axis
}


def def_macro_placements(def_text: str, macro_cells):
    """``({cell: [placement, ...]}, [refusal, ...])`` read from a DEF.

    vibe-ic#612 — M1 read each macro GDS into the layout and never INSTANTIATED
    it, so the design top carried `child_insts = 0`, both macros sat as their
    own top cells at the origin, and `Layout.top_cell()` raised "multiple top
    cells". Reading a GDS adds STRUCTURES to the library; it does not place
    anything. The step is named "... + macro placement" and the placement half
    did not happen.

    The positions are not invented: they are the design's own DEF COMPONENTS
    entries. A macro the DEF does not place, or places at an orientation this
    cannot back, is REFUSED by name rather than dropped at the origin.
    """
    want = {c for c in macro_cells if c}
    um = _DEF_UNITS_RE.search(def_text)
    per_um = float(um.group(1)) if um else None
    out, refusals = {}, []
    if per_um is None or per_um <= 0:
        return {}, ["DEF states no `UNITS DISTANCE MICRONS`, so no placement "
                    "coordinate can be converted"]
    for m in _DEF_COMPONENT_RE.finditer(def_text):
        cell = m.group("cell")
        if cell not in want:
            continue
        orient = m.group("orient")
        if orient not in _DEF_ORIENT_TO_KLAYOUT:
            refusals.append(
                f"{m.group('inst')} ({cell}) is placed {orient}, an "
                f"orientation this merge does not map; placing it at a guessed "
                f"transform would look integrated and be wrong")
            continue
        rot, mirr = _DEF_ORIENT_TO_KLAYOUT[orient]
        out.setdefault(cell, []).append({
            "inst": m.group("inst"), "orient": orient,
            "rot": rot, "mirror": mirr,
            "x_um": int(m.group("x")) / per_um,
            "y_um": int(m.group("y")) / per_um})
    for c in sorted(want - set(out)):
        refusals.append(f"{c} is not placed by any DEF COMPONENTS entry")
    return out, refusals


def _placement_signature(placements):
    """A comparable, order-free statement of WHERE a DEF puts the macros.

    Instance names are deliberately in the key: two DEFs that place the same
    cell the same number of times but attach the positions to different
    instances have not agreed.
    """
    return sorted(
        (p.get("inst"), cell, p.get("orient"),
         round(float(p["x_um"]), 6), round(float(p["y_um"]), 6))
        for cell, pl in placements.items() for p in pl)


def resolve_macro_placements_detailed(project, macro_cells, design_top=None):
    """Where the design's own DEF puts each analog macro, and WHICH DEF said so.

    Returns a dict: ``placements``, ``refusals``, ``def_source`` (the basename
    the placements were read from, or None), ``defs_considered`` and
    ``defs_disagreeing`` (basenames that place the same macros somewhere else).

    vibe-ic#626 — WHICH DEF IS NOT A FREE CHOICE, AND IT WAS BEING MADE BY
    ALPHABETICAL ORDER. This used to walk ``sorted(pnr_dir.glob("*.def"))`` and
    take the first entry that placed anything. A PnR directory holds one DEF per
    stage — floorplan, macro_placed, placed, post_cts, post_hold, routed,
    routed_preantenna, filled, and the design's own — and they do NOT all agree:
    an earlier iteration's DEF is still on disk with the macros somewhere else.
    Measured on a real run (IHP SG13G2 `u_hawaii_adc`), eight of nine DEFs
    agreed and the alphabetical glob returned the ninth:

        u_hawaii_adc.def   u_ds1 delta_sigma + FIXED ( 30080 439350 ) N     <- the
                           DEF the sign-off GDS was streamed from
                           (`stream_tail: file=u_hawaii_adc.def`)
        filled.def         u_ds1 delta_sigma + FIXED ( 15080 760610 ) FS    <- taken,
                           because "f" sorts before everything else

    so M1 instantiated the analog macros 15.0 x 321.3 um from where the digital
    layout they were merged INTO carries them, one of them mirrored, and the
    merged GDS reported one clean top cell while being wrong. `merge.json`
    recorded the coordinates but not the FILE, so nothing in the artefact could
    be audited for it.

    Two things change. The DEF is chosen with `def_rank` — the SAME rule
    `gds_port_label_check` uses to decide which DEF describes a layout, so the
    flow cannot hold two answers — and every OTHER DEF that places these macros
    is still parsed and DISCLOSED when it disagrees. That disagreement is a real
    fact about the project (a stale DEF next to a live one) and it now travels
    in `macro_placements.json` instead of being silently resolved.
    """
    defs = list(_pl.pnr_dir(project).glob("*.def"))
    heads = {}
    for d in defs:
        try:
            with open(d, "r", errors="replace") as fh:
                # HEAD ONLY — `DESIGN <name> ;` is in the first few lines and a
                # routed DEF runs to hundreds of megabytes.
                heads[d] = def_design_name(fh.read(8192))
        except OSError:
            heads[d] = None
    if not design_top:
        # The caller did not say, so ASK THE ARTEFACTS. A ranking that depends
        # on an argument the caller may forget to pass is a defect waiting to
        # come back: without a design name `def_rank` falls through to the
        # preference order and puts `filled.def` first again — the exact file
        # this issue is about. When every DEF here names ONE design, that name
        # IS the design top and nothing has to be guessed; when they name
        # several, the directory holds more than one design and the caller's
        # silence cannot be resolved, so the preference order stands.
        named = {n for n in heads.values() if n}
        design_top = next(iter(named)) if len(named) == 1 else None
    parsed = []                          # [(path, placements, refusals)]
    fallback_refusals = ["no DEF under the PnR directory places any macro"]
    for d in sorted(defs, key=lambda p: def_rank(p, design_top)):
        try:
            txt = d.read_text(errors="replace")
        except OSError:
            continue
        # The design's own statement of its top cell. A PnR directory can hold
        # DEFs for MORE THAN ONE design; a DEF describing a different design
        # says nothing about where THIS design's macros go.
        if design_top and (heads.get(d) or design_top) != design_top:
            continue
        got, ref = def_macro_placements(txt, macro_cells)
        if got:
            parsed.append((d, got, ref))
        else:
            fallback_refusals = ref
    if not parsed:
        return {"placements": {}, "refusals": fallback_refusals,
                "disclosures": [], "def_source": None,
                "defs_considered": [], "defs_disagreeing": []}
    chosen_path, chosen, chosen_ref = parsed[0]
    sig = _placement_signature(chosen)
    disagreeing = [p.name for p, got, _r in parsed[1:]
                   if _placement_signature(got) != sig]
    # DISCLOSURE, NOT REFUSAL — kept in its own list because a refusal means a
    # macro was NOT placed, and reporting "n other DEFs disagree" under that
    # heading would describe a merge that did happen as one that did not.
    disclosures = []
    if disagreeing:
        disclosures.append(
            f"placements read from {chosen_path.name}; "
            f"{len(disagreeing)} other DEF(s) under the same PnR directory "
            f"place these macros somewhere else "
            f"({', '.join(sorted(disagreeing))}) — one of them is stale, and "
            f"which one is a fact about the project, not about this merge")
    return {"placements": chosen, "refusals": list(chosen_ref),
            "disclosures": disclosures,
            "def_source": chosen_path.name,
            "defs_considered": [p.name for p, _g, _r in parsed],
            "defs_disagreeing": sorted(disagreeing)}


def resolve_macro_placements(project, macro_cells, design_top=None):
    """``({cell: [placement, ...]}, [refusal, ...])`` from the project's DEF.

    Split out of the M1 caller so it can be DRIVEN. The first version of this
    lived inline, and the test that was supposed to pin it asserted the string
    `def_macro_placements(` appeared in the source — which a mutation that
    short-circuits the call (`({}, []) or def_macro_placements(...)`) satisfies
    while placing nothing. A property that can only be asserted by looking at
    source text is not being measured.

    The two-value shape is kept for callers that only want the map; the DEF this
    came from is in `resolve_macro_placements_detailed` (vibe-ic#626).
    """
    r = resolve_macro_placements_detailed(project, macro_cells, design_top)
    return r["placements"], r["refusals"]


_KLAYOUT_MERGE_PY = """\
import pya, os, json

def own_shapes(ly, name):
    # `has_cell` / `cell_by_name`, not `cell_name_to_index` — the latter is not
    # on this KLayout's Layout binding and raised AttributeError when this was
    # first run against the real tool.
    if not ly.has_cell(name):
        return None
    # `cell_by_name` returns an INDEX; `cell()` turns it into the object.
    # Both corrections came from running this against the real KLayout, not
    # from reading the API.
    c = ly.cell(ly.cell_by_name(name))
    return sum(c.shapes(li).size() for li in ly.layer_indexes())

ly = pya.Layout()
ly.read(os.environ["DIGITAL_GDS"])
design_top = os.environ["DESIGN_TOP"]
digital_tops = [ly.cell(i).name for i in ly.each_top_cell()]
if digital_tops != [design_top]:
    print("KLAYOUT_MERGE_WRONG_DIGITAL_TOP", digital_tops, design_top)
    raise SystemExit(3)

record = []
for g in os.environ["MACRO_GDS"].split(";"):
    g = g.strip()
    if not g:
        continue
    probe = pya.Layout()
    probe.read(g)
    tops = [probe.cell(i).name for i in probe.each_top_cell()]
    expected = os.path.splitext(os.path.basename(g))[0]
    if tops != [expected] or not any(own_shapes(probe, c.name) for c in probe.each_cell()):
        print("KLAYOUT_MERGE_WRONG_MACRO_CELL", g, tops, expected)
        raise SystemExit(3)
    for name in tops:
        before = own_shapes(ly, name)
        if before is None:
            action = "added"          # not in the digital GDS at all
        elif before == 0:
            action = "filled"         # an abstract placeholder — today's intent
        else:
            action = "replaced_digital"   # replace an older embedded A8 view without appending
        record.append({"macro": name, "file": g, "action": action,
                       "shapes_before": before})
    # Replace the consumed macro hierarchy from the current A8 view. Merely
    # retaining a nonempty digital body can retain an older macro generation.
    # copy_tree preserves existing references to the destination root.
    source = probe.cell(probe.cell_by_name(expected))
    destination = ly.cell(ly.cell_by_name(expected)) if ly.has_cell(expected) else ly.create_cell(expected)
    destination.prune_subcells(-1)
    destination.clear()
    destination.copy_tree(source)
    for r in record:
        if r["file"] == g:
            r["shapes_after"] = own_shapes(ly, r["macro"])

# vibe-ic#612 — READING A GDS ADDS STRUCTURES; IT DOES NOT PLACE ANYTHING.
# Until now the loop above ended here, so the design top carried child_insts=0,
# each macro sat as its OWN top cell at the origin, and `Layout.top_cell()`
# raised "multiple top cells". A merged GDS with more than one top cell is on
# its face not an integrated design: top-level extraction sees no macro devices
# at all, and no overlap / halo / track check means anything about a cell that
# is nowhere.
#
# Positions are the design's OWN DEF COMPONENTS entries, passed in by the
# caller. Nothing is placed at a guessed transform.
placements = {}
pj = os.environ.get("PLACEMENTS_JSON")
if pj and os.path.isfile(pj):
    with open(pj) as f:
        _pj = json.load(f)
    # The caller writes {"placements": {...}, "refusals": [...]} so the
    # refusals travel with the map rather than only to stdout.
    placements = _pj.get("placements", _pj) if isinstance(_pj, dict) else {}

placed = []
design_top = os.environ.get("DESIGN_TOP", "").strip()
if design_top and ly.has_cell(design_top):
    top = ly.cell(ly.cell_by_name(design_top))
    # OpenROAD stream-out may already have instantiated the macros. Validate
    # those transforms, then replace just those references rather than double
    # their placement. Abstract-only stream-outs are populated from the DEF.
    wanted = {r["macro"] for r in record}
    for name in wanted:
        if any(parent != top.cell_index() for parent in ly.cell(name).each_parent_cell()):
            print("KLAYOUT_MERGE_NESTED_MACRO", name)
            raise SystemExit(3)
    existing = {}
    for inst in top.each_inst():
        name = ly.cell(inst.cell_index).name
        if name in wanted:
            if inst.is_regular_array():
                print("KLAYOUT_MERGE_MACRO_ARRAY", name)
                raise SystemExit(3)
            existing.setdefault(name, []).append(inst.trans)
    for name, transforms in existing.items():
        expected = [pya.Trans(int(pl["rot"]), bool(pl["mirror"]),
                             int(round(pl["x_um"] / ly.dbu)),
                             int(round(pl["y_um"] / ly.dbu))) for pl in placements.get(name, [])]
        if sorted(str(t) for t in transforms) != sorted(str(t) for t in expected):
            print("KLAYOUT_MERGE_DEF_MISMATCH", name, transforms, expected)
            raise SystemExit(3)
    for inst in list(top.each_inst()):
        if ly.cell(inst.cell_index).name in wanted:
            inst.delete()
    for r in record:
        for pl in placements.get(r["macro"], []):
            if not ly.has_cell(r["macro"]):
                continue
            ci = ly.cell_by_name(r["macro"])
            t = pya.Trans(int(pl["rot"]), bool(pl["mirror"]),
                          int(round(pl["x_um"] / ly.dbu)),
                          int(round(pl["y_um"] / ly.dbu)))
            top.insert(pya.CellInstArray(ci, t))
            placed.append({"macro": r["macro"], "inst": pl.get("inst"),
                           "orient": pl.get("orient"),
                           "x_um": pl["x_um"], "y_um": pl["y_um"]})
    for r in record:
        r["instances_placed"] = sum(1 for q in placed if q["macro"] == r["macro"])

tops_after = [ly.cell(i).name for i in ly.each_top_cell()]

ly.write(os.environ["MERGED_OUT"])
mj = os.environ.get("MERGE_JSON")
if mj:
    with open(mj, "w") as f:
        json.dump({"merged_out": os.environ["MERGED_OUT"],
                   "digital_gds": os.environ["DIGITAL_GDS"],
                   "design_top": design_top,
                   "placed": placed,
                   "top_cells_after": tops_after,
                   "single_top": len(tops_after) == 1,
                   "macros": record}, f, indent=2)
for r in record:
    print("KLAYOUT_MERGE_MACRO", r["macro"], r["action"],
          r["shapes_before"], "->", r.get("shapes_after"))
for q in placed:
    print("KLAYOUT_MERGE_PLACED", q["macro"], q["inst"], q["orient"],
          q["x_um"], q["y_um"])
print("KLAYOUT_MERGE_TOPS", ",".join(tops_after))
if tops_after != [design_top]:
    # LOUD, not silent. Emitting the file and reporting DONE would let a
    # multi-top GDS travel downstream as an "integrated" design.
    print("KLAYOUT_MERGE_MULTITOP " + ",".join(tops_after))
    raise SystemExit(3)
print("KLAYOUT_MERGE_DONE", os.environ["MERGED_OUT"])
"""

_MAGIC_EXT_TCL = """\
crashbackups stop
gds readonly true
gds rescale false
gds read $env(GDS)
load $env(TOP)
select top cell
extract all
ext2spice lvs
ext2spice -o $env(SPICE_OUT)
puts "MAGIC_EXT2SPICE_DONE $env(SPICE_OUT)"
quit -noprompt
"""


def _docker_exec_raw(container, cmd, timeout=600):
    """Simple bounded wall-clock exec (monkeypatch surface for tests) — for
    short probes. Long tool runs use `_docker_exec(..., marker=...)` → the
    progress-stall watchdog."""
    if container not in ("", "host"):
        # OWN container-side deadline: a host timeout kills only the
        # `docker exec` CLIENT and ORPHANS the tool inside the container
        # (see `_docker_watchdog.wrap_with_container_timeout`).
        import _docker_watchdog as _dw
        full = _ce.docker_exec_argv(container, "bash", "-lc", _dw.wrap_with_container_timeout(cmd, timeout))
    else:
        full = ["bash", "-lc", cmd]
    try:
        r = _pr.run(full, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller
        return 1, "", str(exc)


def _docker_exec(container, cmd, timeout=600, *, marker=None, log_path=None):
    """marker=None → `_docker_exec_raw` (short probes). marker set → the shared
    progress-stall watchdog (`_docker_watchdog.run_docker_supervised`): a long,
    open-ended run (KLayout merge, Magic ext2spice, netgen LVS — hours on a big
    merged GDS) is killed ONLY on NO forward progress, never on a fixed
    estimate. `marker` is a token already in the tool's argv. chip/tool-AGNOSTIC.
    Still a monkeypatch surface for tests (fakes absorb marker via **_)."""
    if marker is None:
        return _docker_exec_raw(container, cmd, timeout)
    import _docker_watchdog as _dw
    return _dw.run_docker_supervised(
        container, cmd, marker, docker_exec_raw=_docker_exec_raw,
        log_path=log_path)


def _to_container_path(p, container):
    return str(p)


def _project_reachable(container, project):
    """True when `project` resolves to a directory INSIDE the container.

    `_to_container_path` hands the tool the HOST path verbatim. When the run
    root is outside the container's mounted tree every `docker exec` below
    fails to find its inputs — and, because each step's success test was
    "does the output file exist on the HOST", a run in which no tool executed
    was indistinguishable from one in which they all did (see the
    `_ran_fresh` note). Ask once, up front, and SKIP by name instead."""
    if container in ("", "host"):
        return True
    rc, _, _ = _docker_exec(
        container, f"test -d {shlex.quote(str(project))}", timeout=15)
    return rc == 0






def _tool_ok(container, tool):
    rc, _, _ = _docker_exec(container, f"command -v {tool} >/dev/null 2>&1",
                            timeout=10)
    return rc == 0


# ── C5 — RESOLVE THE TOP CELL AND THE PDK FROM THE PROJECT, NEVER FROM A
#    DESIGN-SPECIFIC LITERAL. ───────────────────────────────────────────────
# MEASURED DEFECT (2026-07-31): `--top` defaulted to the literal `chip_top` and
# `--pdk` to the literal `sky130A`, and M1's ONLY call site
# (`flow/phase1_phase2_phase3.yaml` advisory_program_exit_zero) passes NEITHER.
# On a design whose top is `u_hawaii_adc` on `ihp-sg13g2` this made Magic run
# `load chip_top` against a merged GDS that does not contain that cell —
#   Reading "u_hawaii_adc". / Cell chip_top couldn't be read / Creating new cell
#   / Warning: There is nothing here to extract.
# — and the program blamed the extraction ("produced no netlist"). Worse, the
# `--pdk` literal survived the tech SKIP-guard because sky130A really IS
# installed in the container, so Magic would have extracted an IHP SG13G2
# layout with SKY130 layer definitions had the top name been right: a presence
# check standing in for a correctness check.
#
# Both are now DERIVED FROM THE DESIGN'S OWN ARTEFACTS, and when they cannot be
# derived the program SKIPs saying so instead of guessing. chip/PDK-AGNOSTIC:
# no design name, cell name or PDK name appears below.
_DEF_DESIGN_RE = re.compile(r"^\s*DESIGN\s+(\S+)\s*;", re.MULTILINE)
_PDK_ROOT_RE = re.compile(re.escape(PDKS_IN_CONTAINER) + r"/([^/\s\"']+)/")


def resolve_top(project: Path, requested: "str | None" = None):
    """Return (top_cell, source). chip-AGNOSTIC.

    The DEF's own `DESIGN <name> ;` line is the authoritative answer: it names
    the cell that was actually floorplanned, placed, routed and streamed out,
    and the merged GDS this program extracts is built from that stream-out. An
    EXPLICIT `--top` still wins (a caller that names one has asserted it), but
    it is reported with its source so a wrong one is visible in the report.
    Returns (None, reason) when nothing in the project answers.
    """
    if requested:
        return requested, "explicit --top"
    names = {}
    for d in sorted(_pl.pnr_dir(project).glob("*.def")):
        try:
            m = _DEF_DESIGN_RE.search(d.read_text(errors="replace"))
        except OSError:
            continue
        if m:
            names.setdefault(m.group(1), []).append(d.name)
    if len(names) == 1:
        name = next(iter(names))
        return name, f"DEF DESIGN line ({', '.join(names[name])})"
    if len(names) > 1:
        return None, "ambiguous DEF DESIGN names: " + ", ".join(sorted(names))
    # Second lane: the synthesis product is named after the top by construction.
    for v in sorted(_pl.synth_dir(project).glob("*_synth.v")):
        return v.stem[: -len("_synth")], f"synth netlist stem ({v.name})"
    return None, ("no DEF carries a DESIGN line and no *_synth.v exists — the "
                  "project does not state its top cell")


def resolve_pdk(project: Path, requested: "str | None" = None):
    """Return (pdk_name, source). chip/PDK-AGNOSTIC.

    The PDK is read back off the design's OWN back-end artefacts — the PnR /
    extraction scripts and logs name their PDK root explicitly in every
    `read_lef` / `-rcfile` path. That is the PDK the layout under test was
    actually built with, so it is the only one whose layer definitions can
    correctly extract it. Returns (None, reason) when nothing answers, and the
    caller SKIPs — it must never fall back to some other design's PDK.
    """
    if requested:
        return requested, "explicit --pdk"
    counts: "dict[str, int]" = {}
    roots = [_pl.pnr_dir(project), _pl.extracted_dir(project),
             project / "phase3" / "stage3", project / "reports" / "phase3"]
    for root in roots:
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in (
                    ".tcl", ".log", ".json", ".rpt", ".sh"):
                continue
            try:
                txt = f.read_text(errors="replace")
            except OSError:
                continue
            for name in _PDK_ROOT_RE.findall(txt):
                counts[name] = counts.get(name, 0) + 1
    if not counts:
        return None, (f"no back-end artefact under this project names a "
                      f"{PDKS_IN_CONTAINER}/<pdk> root — the PDK this layout "
                      f"was built with is not recoverable from the project")
    # Most-cited root wins; ties broken by name so the choice is deterministic.
    best = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return best, (f"back-end artefacts ({counts[best]} reference(s) to "
                  f"{PDKS_IN_CONTAINER}/{best}/)")


def netgen_lvs_script(sch_paths, layout_path, layout_top, sch_top,
                      setup_path, report_path) -> str:
    """The Tcl netgen actually consumes, built so it can be tested without one.

    netgen's `lvs` takes a TWO-element `{filename cellname}` list per side; its
    own source falls back to treating the whole string as ONE filename when the
    list length is not 2. The schematic side here is always the gate netlist
    plus one `.v` per analog hardmacro, i.e. always >= 2 files, so it can never
    be expressed as that pair directly.

    netgen's answer is to read the files into ONE netlist first --
    `readnet <format> <file> <fnum>` forces a file into the netlist already held
    in `fnum` -- and then identify that netlist's top cell as `{<fnum> <cell>}`,
    which `CommonParseCell` accepts precisely because the first element is an
    integer file number.

    The schematic side is `{$fnum <top>}` and NOT a bare cell name. A bare name
    is ambiguous exactly when LVS is doing its job: both sides normally hold a
    cell of the same name, and `lay_top` defaults to `top` whenever the layout
    has no `_flat` subckt. Measured against netgen 1.5.323: the bare name
    resolved to the layout's copy and netgen refused with "Both cells are in the
    same netlist: Cannot compare!" -- while still exiting cleanly and writing no
    report, which is the second reason the caller judges on the report's
    existence rather than on an exit code.

    Words are wrapped in Tcl braces, not shell-quoted: this is a Tcl script, and
    shell quoting would reach netgen verbatim. The layout pair is braced too --
    `lvs` runs `llength` on it, and Tcl's list parser raises "unmatched open
    quote in list" on a word carrying a stray quote.
    """
    def _tcl(word) -> str:
        return "{" + str(word) + "}"

    lines = [f"set fnum [readnet verilog {_tcl(sch_paths[0])}]"]
    lines += [f"readnet verilog {_tcl(p)} $fnum" for p in sch_paths[1:]]
    lines.append(
        f"lvs {_tcl(str(layout_path) + ' ' + str(layout_top))} "
        f"[list $fnum {_tcl(sch_top)}] {_tcl(setup_path)} {_tcl(report_path)}")
    return "\n".join(lines) + "\n"


def lvs_failure_verdict(report_written: bool, rc: int, transcript: str) -> dict:
    """Distinguish "netgen compared and found a mismatch" from "netgen never
    compared anything".

    Both used to return the same sentence: "real compare ran on the merged GDS;
    design/extraction defect". That attributed to the DESIGN a comparison that
    had not happened -- netgen was aborting in ReadNetlist, before either side
    was loaded -- and it pointed the reader at an LVS report the run had never
    written.

    netgen writes its report only after loading both sides and comparing them,
    so the report's existence is the evidence of whether a comparison occurred.
    Either way the verdict stays FAIL: an LVS that cannot run is not a pass.
    What changes is what is claimed about the design, and whether the reader is
    handed the tool output they need instead of a dangling report path.
    """
    if report_written:
        return {"verdict": "FAIL", "rc": 1, "compared": True,
                "reason": ("netgen top-level LVS did not match — real compare "
                           "ran on the merged GDS; design/extraction defect")}
    return {"verdict": "FAIL", "rc": 1, "compared": False,
            "reason": (f"netgen produced NO comparison (rc={rc}): it wrote no "
                       f"report, so neither side was compared. This is a "
                       f"tool/invocation failure, NOT a design or extraction "
                       f"defect — read the transcript before attributing "
                       f"anything to the design."),
            "transcript_tail": (transcript or "")[-800:]}


class InputRefusal(ValueError):
    """The current subject does not provide a unique, matching merge input."""




def _uncomment(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)


def current_merge_inputs(project, top):
    """Resolve canonical OpenROAD delivery files, never a first-file fallback.

    Direct step_gds delivers <top>.gds from <top>.def in pnr/. The stage4
    delivery lane uses the same exact top stem and routed.def. Conflicting
    copies refuse. Earlier stage DEFs are not eligible delivery sources.
    """
    if not top or not re.fullmatch(r"[A-Za-z_][\w$]*", top):
        raise InputRefusal("top is missing, ambiguous or unsupported")
    pnr = _pl.pnr_dir(project)
    # Physical top and delivery filename may differ after top wrapping. Only
    # an exact same-stem DEF declaring this physical top can justify that alias.
    named_defs = [path for path in pnr.glob("*.def")
                  if path.name != "routed.def" and def_design_name(path.read_text()) == top
                  and any((root / (path.stem + ".gds")).is_file()
                          for root in (pnr, _pl.gds_dir(project)))]
    stems = {top, *(path.stem for path in named_defs)}
    candidates = [root / f"{stem}.gds" for root in (pnr, _pl.gds_dir(project)) for stem in sorted(stems)]
    candidates = list(dict.fromkeys(p for p in candidates if p.is_file()))
    if not candidates:
        raise InputRefusal("current digital GDS absent for exact top " + top)
    if len({p.read_bytes() for p in candidates}) != 1:
        raise InputRefusal("ambiguous current digital GDS copies for " + top)
    digital = candidates[0]
    defs = list(dict.fromkeys([*sorted(named_defs), *[p for p in (pnr / f"{top}.def", pnr / "routed.def") if p.is_file()]]))
    if not defs:
        raise InputRefusal("matching routed DEF absent")
    # The named DEF is step_gds's actual source. A routed alias must describe
    # the same design; a different generation cannot silently supply placement.
    for path in defs:
        if def_design_name(path.read_text(errors="strict")) != top:
            raise InputRefusal("wrong top in routed DEF: " + path.name)
    if len({p.read_bytes() for p in defs}) != 1:
        raise InputRefusal("ambiguous routed DEF generations")
    routed = defs[0]
    macros = sorted((project / "phase3/analog/hardmacro").rglob("*.gds"))
    views = sorted((project / "phase3/analog/hardmacro").rglob("*.v"))
    cells = [p.stem for p in macros]
    if not cells or len(set(cells)) != len(cells):
        raise InputRefusal("missing or duplicate A8 hardmacro GDS cells")
    modules = {}
    for path in views:
        names = re.findall(r"\bmodule\s+([A-Za-z_][\w$]*)\b", _uncomment(path.read_text()))
        if len(names) != 1 or names[0] in modules:
            raise InputRefusal("missing, ambiguous or duplicate A8 Verilog module: " + path.name)
        modules[names[0]] = path
    if set(modules) != set(cells):
        raise InputRefusal("A8 GDS cells and Verilog modules disagree")
    netlists = [root / f"{stem}{suffix}" for root, suffix in ((pnr, "_pnr.v"), (_pl.synth_dir(project), "_synth.v"))
                for stem in dict.fromkeys((digital.stem, top))]
    netlist = next((p for p in netlists if p.is_file()), netlists[0])
    if not netlist.is_file():
        raise InputRefusal("matching gate netlist absent")
    source = _uncomment(netlist.read_text())
    body = re.search(r"\bmodule\s+" + re.escape(top) + r"\b(.*?)\bendmodule\b", source, re.S)
    if not body:
        raise InputRefusal("gate netlist does not declare the requested top")
    def_text = routed.read_text()
    section = re.search(r"\bCOMPONENTS\s+(\d+)\s*;(.*?)END COMPONENTS", def_text, re.S)
    if not section:
        raise InputRefusal("routed DEF COMPONENTS section absent")
    rows = [row.strip() for row in section.group(2).split(";") if row.strip()]
    parsed_rows = [re.match(r"-\s+(\S+)\s+(\S+)(?:\s|$)", row) for row in rows]
    if len(rows) != int(section.group(1)) or not all(parsed_rows):
        raise InputRefusal("routed DEF COMPONENTS count/records disagree")
    row_instances = [row.group(1) for row in parsed_rows]
    if len(set(row_instances)) != len(row_instances):
        raise InputRefusal("duplicate COMPONENTS instance in routed DEF")
    placement, refusals = def_macro_placements(def_text, cells)
    if refusals:
        raise InputRefusal("placement did not complete in THIS run: " + "; ".join(refusals))
    instances = [(p["inst"], c) for c, items in placement.items() for p in items]
    if len({inst for inst, _ in instances}) != len(instances):
        raise InputRefusal("duplicate macro instance in routed DEF")
    schematic = []
    for cell in cells:
        expression = r"\b" + re.escape(cell) + r"\s+(?:#\s*\([^;]*?\)\s*)?([A-Za-z_][\w$]*)\s*\("
        schematic.extend((inst, cell) for inst in re.findall(expression, body.group(1)))
    if sorted(schematic) != sorted(instances):
        raise InputRefusal("routed DEF macro instances/types disagree with gate netlist")
    detail = {"placements": placement, "refusals": [], "disclosures": [],
              "def_source": routed.name, "defs_considered": [p.name for p in defs],
              "defs_disagreeing": []}
    paths = [*candidates, *defs, *macros, *views, netlist]
    for path in paths:
        if not path.stat().st_size or not path.resolve().is_relative_to(project.resolve()):
            raise InputRefusal("empty or outside-subject input: " + str(path))
    return digital, macros, views, netlist, detail








def run(project: Path, top: str, container: str, pdk: str,
        *, pdk_source: str = "", top_source: str = "") -> dict:
    # C5: `top`/`pdk` may be None when the project does not state them. That is
    # reported at the tech rung of the SKIP ladder below, NOT by refusing to
    # run — M1's wiring contract requires this producer to stay dispatchable.
    ms_dir = project / "phase3" / "mixed_signal"
    rpt_dir = project / "reports" / "analog" / "mixed_signal"
    merged = ms_dir / "top_merged.gds"

    # The normal caller keeps its shape. Input/tool absence remains a named
    # SKIP; ambiguous or contradictory evidence is a refusal.
    if not any((project / "phase3/analog/hardmacro").rglob("*.gds")):
        return {"verdict": "SKIP", "rc": 2, "reason": "inputs missing: hardmacro GDS (A8)"}
    if not _tool_ok(container, "klayout"):
        return {"verdict": "SKIP", "rc": 2, "reason": "tools missing in container: klayout"}
    if not _project_reachable(container, project):
        return {"verdict": "SKIP", "rc": 2,
                "reason": f"project dir is not reachable inside container '{container}': {project}"}
    try:
        digital_gds, macro_gds, macro_v, netlist, placement = current_merge_inputs(project, top)
    except (InputRefusal, OSError, UnicodeError) as exc:
        return {"verdict": "FAIL", "rc": 1, "compared": False,
                "reason": ("M1 current input did not complete in THIS run: " + str(exc)
                           + ". Nothing was compared — this is NOT an LVS mismatch")}

    ms_dir.mkdir(parents=True, exist_ok=True)
    rpt_dir.mkdir(parents=True, exist_ok=True)
    invocation = uuid.uuid4().hex
    pending = ms_dir / ("top_merged.current-" + invocation + ".gds")
    merge_log = ms_dir / "merge.log"
    merge_log.unlink(missing_ok=True)
    (ms_dir / "merge.json").unlink(missing_ok=True)
    merge_py = ms_dir / "klayout_merge.py"
    merge_py.write_text(_KLAYOUT_MERGE_PY)
    _pl_json = ms_dir / "macro_placements.json"
    _aa.write_text(_pl_json, json.dumps(placement, indent=2) + "\n")
    # Keep the original resolver available for its existing positive callers:
    # resolve_macro_placements(project, cells, top). The producer uses the
    # exact resolved delivery DEF, rather than another independent scan.
    merge_record = ms_dir / "merge.json"
    env = (f"export DESIGN_TOP={top} "
           f"PLACEMENTS_JSON={shlex.quote(_to_container_path(_pl_json, container))} "
           f"DIGITAL_GDS={shlex.quote(_to_container_path(digital_gds, container))} "
           f"MACRO_GDS={shlex.quote(';'.join(_to_container_path(g, container) for g in macro_gds))} "
           f"MERGED_OUT={shlex.quote(_to_container_path(pending, container))} "
           f"MERGE_JSON={shlex.quote(_to_container_path(merge_record, container))} && ")
    cmd = (env + "set -o pipefail && klayout -b -r "
           + shlex.quote(_to_container_path(merge_py, container)) + " 2>&1 | tee "
           + shlex.quote(_to_container_path(merge_log, container)))
    rc, out, err = _docker_exec(container, cmd, marker=_to_container_path(merge_py, container))
    try:
        if rc != 0 or not pending.is_file() or not pending.stat().st_size \
                or (not merge_log.is_file() or "KLAYOUT_MERGE_DONE" not in merge_log.read_text(errors="replace")):
            raise InputRefusal(f"KLayout merge did not complete in THIS run (rc={rc})")
        record = json.loads(merge_record.read_text())
        expected = sorted((p["inst"], c, p["orient"], p["x_um"], p["y_um"])
                          for c, items in placement["placements"].items() for p in items)
        observed = sorted((p["inst"], p["macro"], p["orient"], p["x_um"], p["y_um"])
                          for p in record["placed"])
        if record.get("design_top") != top or record.get("single_top") is not True \
                or record.get("top_cells_after") != [top] or observed != expected:
            raise InputRefusal("KLayout output top/placement mapping disagrees with current DEF")
        pending.replace(merged)
    except (InputRefusal, OSError, ValueError, KeyError, TypeError) as exc:
        pending.unlink(missing_ok=True)
        return {"verdict": "FAIL", "rc": 1, "ran": True, "compared": False,
                "reason": str(exc), "transcript_tail": (out + err)[-600:]}
    merge_provenance = "KLayout merged the supplied digital and macro layouts"

    # M1 can merge with actual KLayout before the PDK-dependent LVS rung.
    missing_tools = [t for t in ("magic", "netgen") if not _tool_ok(container, t)]
    if missing_tools:
        return {"verdict": "SKIP", "rc": 2, "reason": "tools missing in container: " + ", ".join(missing_tools),
                "merge_provenance": merge_provenance}
    if not pdk:
        return {"verdict": "SKIP", "rc": 2, "reason": "cannot identify PDK (" + pdk_source + ")",
                "merge_provenance": merge_provenance}
    magicrc = f"{PDKS_IN_CONTAINER}/{pdk}/libs.tech/magic/{pdk}.magicrc"
    netgen_setup = f"{PDKS_IN_CONTAINER}/{pdk}/libs.tech/netgen/{pdk}_setup.tcl"
    missing_tech = [p for p in (magicrc, netgen_setup)
                    if _docker_exec(container, f"test -f {shlex.quote(p)}", timeout=10)[0] != 0]
    if missing_tech:
        return {"verdict": "SKIP", "rc": 2, "reason": "PDK tech missing: " + ", ".join(missing_tech),
                "merge_provenance": merge_provenance}

    # 2) extract ----------------------------------------------------------
    spice_out = ms_dir / f"{top}_merged_extracted.sp"
    tcl = ms_dir / "ext2spice_merged.tcl"
    tcl.write_text(_MAGIC_EXT_TCL)
    # ── C5 pipefail — MEASURED, in this container, on 2026-07-31: ───────────
    #   $ bash -lc 'bash -c "exit 137" 2>&1 | tee /tmp/x; echo $?'          -> 0
    #   $ bash -lc 'set -o pipefail; bash -c "exit 137" 2>&1 | tee /tmp/x; echo $?' -> 137
    # `<tool> 2>&1 | tee <log>` reports TEE's exit status, so a tool that was
    # KILLED comes back rc=0 and every "was it killed or did it just produce
    # nothing?" branch downstream is unreachable. This is the exact mechanism
    # that made Step 31's sibling report `produced no extracted netlist (rc=0)`
    # about a Magic run that had been killed mid-DEF-read.
    cmd = ("set -o pipefail && "
           f"export GDS={_to_container_path(merged, container)} TOP={top} "
           f"SPICE_OUT={_to_container_path(spice_out, container)} && "
           f"cd {_to_container_path(ms_dir, container)} && "
           f"magic -dnull -noconsole -rcfile {shlex.quote(magicrc)} "
           f"{_to_container_path(tcl, container)} 2>&1 | "
           f"tee {_to_container_path(ms_dir, container)}/ext2spice_merged.log")
    ext_log = ms_dir / "ext2spice_merged.log"
    ext_log.unlink(missing_ok=True)
    spice_out.unlink(missing_ok=True)
    rc, out, err = _docker_exec(
        container, cmd, marker=_to_container_path(tcl, container))
    if not spice_out.is_file() or spice_out.stat().st_size == 0:
        return {"verdict": "FAIL", "rc": 1, "ran": True,
                "reason": (f"Magic ext2spice on the MERGED GDS produced no "
                           f"netlist (rc={rc})"),
                "transcript_tail": (out + err)[-600:]}
    if rc != 0 or (not ext_log.is_file() or "MAGIC_EXT2SPICE_DONE" not in ext_log.read_text(errors="replace")):
        return {"verdict": "FAIL", "rc": 1, "ran": True,
                "reason": (f"Magic ext2spice did not complete in THIS run "
                           f"(rc={rc}): {ext_log.name} carries no "
                           f"MAGIC_EXT2SPICE_DONE from this invocation. The "
                           f"extracted netlist on disk is a carried-forward "
                           f"file and is NOT evidence about this run"),
                "transcript_tail": (out + err)[-600:]}
    lay_top = top
    sub_txt = spice_out.read_text(errors="replace")
    if re.search(rf"^\.subckt\s+{re.escape(top)}_flat\b", sub_txt,
                 re.IGNORECASE | re.MULTILINE):
        lay_top = f"{top}_flat"

    # 3) netgen LVS — schematic side = gate netlist + hardmacro .v stubs
    #
    # netgen's `lvs` takes a TWO-element `{filename cellname}` list per side. It
    # says so in its own source: if `llength` is not 2 it falls back to treating
    # the WHOLE string as one filename. This site used to join every schematic
    # file into one space-separated string and append the top cell, handing
    # netgen four or more elements, so netgen dutifully looked for a file
    # literally named "<netlist>.v <macro1>.v <macro2>.v <top>", failed to open
    # it, and never loaded the schematic side at all.
    #
    # That made M1 unpassable for EVERY design with an analog hardmacro — the
    # only kind of design M1 exists for — because the schematic side is always
    # the gate netlist plus one `.v` per macro, i.e. always >= 2 files.
    #
    # netgen's documented way to compare against several files is to read them
    # into ONE netlist first (`readnet <format> <file> <fnum>` forces a file
    # into the netlist already held in `fnum`) and then name the CELL, which
    # `lvs` resolves through `canonical` because it has already been read:
    # "A single <filename>, or any valid_cellname form if the file has already
    # been read."
    lvs_rpt = rpt_dir / "top_lvs.rpt"
    sch_paths = [_to_container_path(f, container) for f in [netlist] + macro_v]
    lvs_tcl = ms_dir / "top_lvs.tcl"
    lvs_tcl.write_text(netgen_lvs_script(
        sch_paths, _to_container_path(spice_out, container), lay_top, top,
        netgen_setup, _to_container_path(lvs_rpt, container)))
    cmd = (f"export PATH={TOOLS_IN_CONTAINER}/netgen/bin:"
           f"{TOOLS_IN_CONTAINER}/bin:$PATH && "
           f"netgen -batch source {_to_container_path(lvs_tcl, container)}")
    lvs_rpt.unlink(missing_ok=True)
    rc, out, err = _docker_exec(
        container, cmd, marker=_to_container_path(spice_out, container))
    # netgen writes its comparison result to the requested report.
    if not lvs_rpt.is_file() or not lvs_rpt.stat().st_size:
        return {"verdict": "FAIL", "rc": 1, "compared": False,
                "reason": (f"netgen did not write a top-level LVS report in "
                           f"THIS run (rc={rc}): {lvs_rpt.name} was not "
                           f"(re)written by this invocation. Nothing was "
                           f"compared — this is NOT an LVS mismatch"),
                "merge_provenance": merge_provenance,
                "transcript_tail": ((out or "") + (err or ""))[-600:]}
    blob = (out or "") + "\n" + (err or "") + "\n" + (
        lvs_rpt.read_text(errors="replace") if lvs_rpt.is_file() else "")
    # #524 — shared verdict classifier (adds 'failed pin matching', the netgen
    # property-error terminal FAIL, 失配 and the Final-result truncation guard,
    # all missing from the old inline copy) so this site can never drift from
    # the Step-31 gate again.
    lvs_pass = rc == 0 and _lvt.classify(blob) == "MATCH"
    # 4) emit M1/M4 artifacts ----------------------------------------------
    top_lvs = {
        "program": "mixed_signal_top_lvs_run", "version": "1.0.0",
        "verdict": "PASS" if lvs_pass else "FAIL",
        "layout": str(merged.relative_to(project)),
        "layout_top": lay_top,
        "schematic": [str(netlist.relative_to(project))]
                     + [str(v.relative_to(project)) for v in macro_v],
        "extracted_netlist": str(spice_out.relative_to(project)),
        "lvs_report": str(lvs_rpt.relative_to(project)),
        "tool": "magic ext2spice + netgen (PDK setup)",
        "merge_provenance": merge_provenance,
    }
    _aa.write_text(rpt_dir / "top_lvs.json",
        json.dumps(top_lvs, indent=2) + "\n")
    _aa.write_text(rpt_dir / "merge.json", json.dumps({
        "gate": "mixed_signal_merge",
        "verdict": "PASS" if lvs_pass else "FAIL",
        "merged_gds": str(merged.relative_to(project)),
        "macros_merged": [str(g.relative_to(project)) for g in macro_gds],
        "top_lvs": top_lvs["verdict"],
        "note": ("top-level merged-GDS LVS executed (Magic extraction + "
                 "netgen vs gate netlist + hardmacro stubs) — the merge "
                 "claim is LVS-substantiated, not presence-only"),
    }, indent=2) + "\n")

    if lvs_pass:
        return {"verdict": "PASS", "rc": 0, **top_lvs}
    return {**lvs_failure_verdict(
        report_written=lvs_rpt.is_file() and lvs_rpt.stat().st_size > 0,
        rc=rc, transcript=(out or "") + (err or "")), **top_lvs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    # C5: default None, NOT a design-specific literal. An omitted value is
    # resolved from the project; an unresolvable one SKIPs saying so.
    ap.add_argument("--top", default=None)
    ap.add_argument("--container", default=_pin.default_container_name())
    ap.add_argument("--pdk", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project.is_dir():
        print(f"ERROR: not a directory: {args.project}", file=sys.stderr)
        return 1
    project = args.project.resolve()
    top, top_src = resolve_top(project, args.top)
    pdk, pdk_src = resolve_pdk(project, args.pdk)
    # Degrade loudly, never silently: say WHERE these came from, so a wrong one
    # is visible in the transcript instead of surfacing 40 lines later as
    # "Magic produced no netlist".
    #
    # An UNRESOLVED top or PDK must NOT short-circuit here. `run()` owns the
    # SKIP ladder (inputs → tools → tech), and M1's wiring contract is that this
    # producer is always dispatchable and always reports its own state; a
    # pre-emptive return would make it unreachable on a fresh project and break
    # that contract (caught by tests/test_m1_top_lvs_producer_wiring.py). The
    # unresolved case is therefore reported at the tech rung inside `run()`,
    # where "PDK tech missing" already lives — see `_UNRESOLVED_PDK`.
    print(f"TOP_RESOLVED {top or '<unresolved>'} (source: {top_src})")
    print(f"PDK_RESOLVED {pdk or '<unresolved>'} (source: {pdk_src})")
    rep = run(project, top, args.container, pdk, pdk_source=pdk_src,
              top_source=top_src)
    # ── C5: a SKIP is a VERDICT and must leave verdict evidence. ────────────
    # `run()` writes reports/analog/mixed_signal/top_lvs.json only on the
    # completed-compare path, so every SKIP rung (inputs / tools / tech /
    # unresolved-top-or-PDK) previously wrote NOTHING — and M1's gate, which
    # reads that file, then cannot tell "the producer skipped, and here is why"
    # from "the producer never ran at all". Those are different claims. Writing
    # the SKIP verdict here keeps M1's evidence contract intact for every exit
    # (guarded by tests/test_m1_top_lvs_producer_wiring.py, which proves the
    # declared producer really writes its verdict evidence) WITHOUT restoring
    # any guess about which PDK or which top cell the design uses.
    if rep.get("verdict") in ("SKIP", "FAIL"):
        _ev = project / "reports" / "analog" / "mixed_signal" / "top_lvs.json"
        _ev.parent.mkdir(parents=True, exist_ok=True)
        # vibe-ic#614 — C5's reason above is right (a SKIP must leave verdict
        # evidence) and the write was UNCONDITIONAL, so a run that could not
        # compare REPLACED one that did. `flow_compliance_check` invokes this
        # producer with the DEFAULT container, so on any host where the run
        # root is not bind-mounted under that name the audit overwrote a
        # computed FAIL with a capability-gap SKIP — and the gate then
        # published that SKIP as a design mismatch.
        #
        # A NON-RESULT MUST NOT DISPLACE A RESULT. The skip still leaves
        # evidence, beside the comparison rather than on top of it.
        _prior = None
        if _ev.is_file():
            try:
                _prior = json.loads(_ev.read_text(errors="replace"))
            except (OSError, ValueError):
                _prior = None
        _compared = isinstance(_prior, dict) and bool(_prior.get("lvs_report"))
        _payload = {k: v for k, v in rep.items() if k != "rc"}
        if _compared and rep.get("verdict") == "SKIP":
            _alt = _ev.with_name("top_lvs_skipped.json")
            _payload["preserved"] = (
                f"an existing {_ev.name} records a COMPLETED comparison "
                f"(verdict {_prior.get('verdict')!r}, report "
                f"{_prior.get('lvs_report')!r}); this skip is recorded here "
                f"instead of replacing it")
            _alt.write_text(json.dumps(_payload, indent=2,
                                       ensure_ascii=False) + "\n")
            rep["skip_evidence"] = str(_alt.relative_to(project))
            rep["did_not_overwrite"] = str(_ev.relative_to(project))
        else:
            _ev.write_text(json.dumps(_payload, indent=2,
                                       ensure_ascii=False) + "\n")
    rep.setdefault("top", top)
    rep.setdefault("top_source", top_src)
    rep.setdefault("pdk", pdk)
    rep.setdefault("pdk_source", pdk_src)
    rc = rep.pop("rc")
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
