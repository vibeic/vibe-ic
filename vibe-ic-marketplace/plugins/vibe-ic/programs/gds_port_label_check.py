#!/usr/bin/env python3
"""gds_port_label_check — every port the DEF declares must be NAMED in the sign-off GDS.

WHY (vibe-ic#613)
=================
A top-level LVS cannot pin-match a layout whose top cell carries no labels.
Measured on a real run (IHP SG13G2 `u_hawaii_adc`):

    phase3/stage3/pnr/filled.def        PINS 20 ;   all 20 placed, with layers
    phase3/stage4/gds/u_hawaii_adc.gds  0 text labels in the top cell

    .subckt u_hawaii_adc                <- extraction found no ports at all
    Final result: Top level cell failed pin matching.

So that step could never reach PASS no matter how correct the layout was: there
was nothing for the extractor to name a port with, and nothing in the flow
measured it.

THE THING THAT WAS BEING PREDICTED IS DIRECTLY MEASURABLE
=========================================================
The restore pass (`def_gds_port_power_restore`) that injects DEF PINS as GDS
labels already existed; it ran only where a bridge config declared
`port_label_restore`, on the stated premise that "OSS PDKs keep native
streamout". Measured on the tracked corpus, that premise predicts nothing in
EITHER direction:

    sky130A  sha256       77 declared / 77 labelled     native streamout, no restore
    sky130A  subservient  31 declared / 31 labelled     native streamout, no restore
    IHP      u_hawaii_adc 20 declared /  0 labelled     native streamout, no restore

A PDK class does not decide it. Whether the labels are IN THE STREAMED FILE
does, and that is a fact of the artefact, readable after streamout.

WHAT IS COMPARED, AND WHY BY NAME
=================================
Per-STRUCTURE, never library-wide: a chip GDS carries the std cells' own pin
texts, so a GLOBAL text count is comfortably non-zero for a chip whose TOP cell
has not one label. sha256's library has 2,314 TEXT records; the question is only
ever about the 77 in `sha256`.

By NAME, not by count: the count can only say how many are missing, the names
say WHICH port has nothing to name it. Both directions are reported — declared
pins with no label AND labels matching no pin — because a naming-convention
difference (a `VDD!` label for a `VDD` pin) otherwise reads as a missing label
and sends the reader looking for the wrong defect.

THE DEF AND THE GDS ARE PAIRED BY THE DESIGN'S OWN NAME, never by directory
position. sha256's `phase3/stage3/pnr/` holds DEFs for TWO designs — `chip_top`
and `sha256` — and the sign-off GDS is `sha256`. Taking "the routed DEF" would
have compared chip_top's 77 pins against a GDS that does not contain chip_top at
all and called the result zero. A GDS with no DEF naming a structure inside it
is NOT MEASURED and says so; it is not a design finding.

CALIBRATION, measured before it was chosen
==========================================
Blocking on "a placed pin with no label" flips 0 of the 4 real sign-off GDS on
this host (sha256 77/77, sha256_magic 77/77, spm 36/36, subservient 31/31, exact
string match, both streamout engines). A pin DECLARED in the `PINS n ;` header
but carrying no placement can never be labelled — it has no geometry — so it is
counted and disclosed separately and never blocks.

Exit: 0 = every measured GDS names every placeable port
      1 = at least one placed port has no label in the top cell
      2 = nothing could be measured (no GDS, no DEF naming a structure in it,
          or a GDS that is not a valid stream) — the VACUOUS_PASS convention
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from gds_substance_check import (  # noqa: E402
    _CANONICAL_GDS_GLOBS,
    find_canonical_gds,
    parse_gds,
    structure_text_census,
)
from def_gds_port_power_restore import (  # noqa: E402
    pdk_port_label_layers,
    def_declared_pin_count,
    def_design_name,
    def_rank,
    parse_pins,
)

TOOL = "gds_port_label_check"
RC_OK, RC_FINDINGS, RC_CANNOT_MEASURE = 0, 1, 2

#: Where a project's DEFs live. Every one is a candidate; the pairing is by the
#: DEF's own `DESIGN` name, so the glob does not have to guess which is right.
_DEF_GLOB = "phase3/stage3/pnr/*.def"

#: Names reported in full before the list is truncated in the JSON/stderr.
_NAME_CAP = 40



#: vibe-ic#626 — the tie-break among DEFs naming the same design now lives in
#: `def_gds_port_power_restore.def_rank`, because M1's merge needs the SAME
#: answer and had been picking its DEF by alphabetical glob position instead.
#: Behaviour here is unchanged; the rule is simply no longer private to this
#: file. `_def_rank` is kept as the local name so the call sites read the same.
_def_rank = def_rank


def pair_def_with_gds(def_paths: List[Path],
                      structures: List[str]) -> Optional[Tuple[Path, str]]:
    """The DEF whose own `DESIGN <name> ;` names a structure present in this GDS.

    Returns (def_path, design_name) or None when no DEF describes this layout —
    which is a statement about the PAIRING, never about the design.
    """
    present = set(structures)
    cands: List[Tuple[Tuple[int, str], Path, str]] = []
    for p in def_paths:
        try:
            # HEAD ONLY. `DESIGN <name> ;` is in the first few lines, and a
            # routed DEF runs to hundreds of megabytes: reading all nine of
            # sha256's DEFs in full to learn nine names is a cost the answer
            # does not need.
            with open(p, "r", errors="replace") as fh:
                head = fh.read(8192)
        except OSError:
            continue
        name = def_design_name(head)
        if name and name in present:
            cands.append((_def_rank(p, name), p, name))
    if not cands:
        return None
    cands.sort(key=lambda c: c[0])
    return cands[0][1], cands[0][2]


def label_layer_readability(cen, design, pdk_tech=None):
    """(readable, note) — are the top cell's labels on a layer the design's PDK
    declares as a PORT-label layer?

    DISCLOSURE ONLY, DELIBERATELY. vibe-ic#631 is right that presence is not
    readability: a label on a layer the extractor's tech does not map is
    byte-for-byte present and semantically absent, and the measured case is
    20 labels in the file against `Circuits do NOT match uniquely (top-level
    cell has no ports)`.

    But BLOCKING on it is not calibrated yet, and the reason is a measurement
    taken while writing this. The restore writes layer 100; NATIVE KLayout
    streamout writes 10/1 — and sky130A's Magic tech declares neither (its port
    layers are 68/5, 69/5, …). So `subservient`, a shipped cell whose sign-off
    is green, would be flagged by the naive rule. Either its LVS never reads the
    GDS through Magic, or the rule is wrong; until that is established, turning
    this into a FAIL would fail a design on a predicate whose accept case has
    never been run. #613's own calibration rule — measure the blast radius
    before choosing the predicate — applies to its own follow-up.

    THREE STATES, and the gate uses only two of them:

      True   on a declared port layer — the extractor can name the ports.
      False  MEASURED off every declared layer. The GATE does not fail on this
             (see above); the PRODUCER does act on it, because "the labels are
             there but unreadable" is exactly the trigger the restore was
             missing — #613 fixed "is there a label", and this is the same
             argument one level further: presence was the wrong measurement.
      None   could not be established: no tech supplied, or the tech declares
             no port layer at all.
    """
    layers = sorted(set(cen.label_layers_per_structure.get(design, [])))
    if not layers:
        return None, ""
    if not pdk_tech:
        return None, (f"label layer(s) {layers}; the design's PDK tech was not "
                      f"supplied, so whether a Magic-based extractor can READ "
                      f"them is UNKNOWN — not confirmed (vibe-ic#631)")
    try:
        declared = pdk_port_label_layers(Path(pdk_tech).read_text(errors="replace"))
    except OSError as exc:
        return None, f"could not read the PDK tech {pdk_tech}: {exc}"
    want = set(declared.values())
    if not want:
        return None, (f"label layer(s) {layers}; this PDK's tech declares NO "
                      f"port-label layer, so readability cannot be established "
                      f"either way")
    hit = [l for l in layers if l in want]
    if hit:
        return True, (f"label layer(s) {layers} include the PDK-declared port "
                      f"layer(s) {sorted(want)} — an extractor reading through "
                      f"that tech can name the ports")
    return False, (f"ADVISORY (vibe-ic#631): label layer(s) {layers} are NOT "
                  f"among the PDK-declared port-label layer(s) {sorted(want)}, "
                  f"so a Magic-based extractor reading through that tech would "
                  f"DROP them and extract a portless subckt. Reported, not "
                  f"failed: the predicate's accept case is not yet calibrated.")


def census_one(gds_path: Path, def_paths: List[Path],
                pdk_tech=None) -> Dict:
    """Measure one GDS against whichever DEF names a structure inside it."""
    rec: Dict = {"gds_file": str(gds_path), "verdict": "NOT_MEASURED",
                 "def_file": None, "top_cell": None}
    try:
        data = gds_path.read_bytes()
    except OSError as exc:
        rec["reason"] = f"cannot read the GDS: {exc}"
        return rec

    findings, _stats = parse_gds(data)
    errs = [f for f in findings if f.severity == "ERROR"]
    if errs:
        # Counting labels in a stream that does not parse counts an artefact of
        # the damage. `gds_substance_check` owns that verdict; this one declines.
        rec["reason"] = ("the GDS is not a valid stream — "
                         f"{errs[0].category}: {errs[0].message}")
        return rec

    cen = structure_text_census(data)
    paired = pair_def_with_gds(def_paths, cen.structures)
    if not paired:
        rec["reason"] = (
            f"no DEF names a structure present in this GDS "
            f"(structures={len(cen.structures)}, "
            f"tops={', '.join(cen.top_structures()[:4]) or 'none'}; "
            f"DEFs offered={', '.join(p.name for p in def_paths) or 'none'})")
        return rec

    def_path, design = paired
    def_text = def_path.read_text(errors="replace")
    declared = def_declared_pin_count(def_text)
    placed = [n for n, _l, _x, _y in parse_pins(def_text)]
    labels = cen.labels_per_structure.get(design, [])
    # #631 — PRESENCE IS NOT READABILITY. A label on a layer the extractor's
    # PDK tech does not map is byte-for-byte present and semantically absent:
    # measured on a real run, 20 labels in the file and
    # `Circuits do NOT match uniquely (top-level cell has no ports)`. This
    # gate's own argument one level down — that a PDK CLASS predicts nothing
    # and the readable fact is whether the labels are IN THE FILE — turns out
    # to apply to itself: being in the file predicts nothing either.
    readable, unreadable_note = label_layer_readability(cen, design, pdk_tech)

    missing = sorted(set(placed) - set(labels))
    unmatched = sorted(set(labels) - set(placed))
    # A pin in the `PINS n ;` header that carries no placement has no geometry
    # to attach a label to. Disclosed, never blocking.
    unplaceable = (declared - len(placed)) if declared is not None else None

    rec.update({
        "def_file": str(def_path),
        "top_cell": design,
        "pins_declared": declared,
        "pins_placed": len(placed),
        "pins_unplaceable": unplaceable,
        "top_labels": cen.text_per_structure.get(design, 0),
        "labels_total_in_library": sum(cen.text_per_structure.values()),
        "missing_labels": missing[:_NAME_CAP],
        "missing_labels_count": len(missing),
        "labels_matching_no_pin": unmatched[:_NAME_CAP],
        "labels_matching_no_pin_count": len(unmatched),
    })
    # #631 — a False from the predicate is a MEASUREMENT, not a verdict. The
    # gate keeps it advisory (the calibration is on the issue); the runner uses
    # it to decide whether to re-run the restore.
    rec["labels_extractor_readable"] = readable
    if not placed:
        rec["verdict"] = "NO_PLACED_PINS"
        rec["reason"] = (
            f"the DEF declares {declared if declared is not None else 0} pin(s) "
            f"and places none — there is no port geometry to name")
    elif not labels:
        rec["verdict"] = "NO_LABELS"
        rec["reason"] = (
            f"top cell '{design}' carries 0 text labels while the DEF places "
            f"{len(placed)} port(s); extraction can name no port, so a "
            f"top-level LVS cannot pin-match at all")
    elif missing:
        rec["verdict"] = "MISSING_LABELS"
        rec["reason"] = (
            f"{len(missing)} placed port(s) have no label in top cell "
            f"'{design}': {', '.join(missing[:8])}"
            + (" …" if len(missing) > 8 else "")
            + (f" (labels present that match no pin: "
               f"{', '.join(unmatched[:5])} — a naming-convention difference "
               f"rather than an absence?)" if unmatched else ""))
    else:
        rec["verdict"] = "OK"
    if unreadable_note:
        rec["readability"] = unreadable_note
        rec["label_layers"] = sorted(
            set(cen.label_layers_per_structure.get(design, [])))
    return rec


def audit(project: Optional[Path], gds_file: Optional[Path],
          def_file: Optional[Path],
          pdk_tech: Optional[str] = None) -> Tuple[str, List[Dict]]:
    if gds_file is not None:
        defs = [def_file] if def_file else []
        recs = [census_one(gds_file, [d for d in defs if d and d.is_file()],
                           pdk_tech=pdk_tech)]
    else:
        assert project is not None
        defs = sorted(p for p in project.glob(_DEF_GLOB) if p.is_file())
        recs = [census_one(g, defs, pdk_tech=pdk_tech)
                for g in find_canonical_gds(project)]

    if any(r["verdict"] in ("NO_LABELS", "MISSING_LABELS") for r in recs):
        return "FINDINGS", recs
    if any(r["verdict"] == "OK" for r in recs):
        return "PASS", recs
    return "NOTHING_MEASURED", recs


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", nargs="?",
                    help="project directory (scans the canonical chip-GDS paths)")
    ap.add_argument("--gds-file", help="audit a single GDS instead")
    ap.add_argument("--def-file", help="the DEF to pair with it (single-file mode)")
    ap.add_argument("--pdk-tech",
                    help="Magic `*-GDS.tech` for this design's PDK, so the "
                         "record can say whether a Magic-based extractor could "
                         "READ the labels (vibe-ic#631). NOT discovered "
                         "automatically: the PDK root a project's artefacts "
                         "name is a CONTAINER path (`/foss/pdks/...`) that does "
                         "not exist host-side, so a discovery here could only "
                         "ever return nothing — and a code path that cannot "
                         "succeed makes an architectural fact look like a "
                         "lookup failure. The runner, which has the container, "
                         "resolves it and passes it.")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)

    if not a.project_dir and not a.gds_file:
        print("error: give a project_dir or --gds-file", file=sys.stderr)
        return RC_CANNOT_MEASURE

    project = Path(a.project_dir).resolve() if a.project_dir else None
    if project is not None and not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return RC_CANNOT_MEASURE

    verdict, recs = audit(project,
                          Path(a.gds_file) if a.gds_file else None,
                          Path(a.def_file) if a.def_file else None,
                          pdk_tech=a.pdk_tech)
    report = {"tool": TOOL, "verdict": verdict,
              "project": str(project) if project else None,
              "checked_globs": list(_CANONICAL_GDS_GLOBS),
              "files_measured": sum(1 for r in recs if r["verdict"] != "NOT_MEASURED"),
              "files": recs}
    if a.json_out:
        out = Path(a.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "FINDINGS":
        for r in recs:
            if r["verdict"] in ("NO_LABELS", "MISSING_LABELS"):
                print(f"[FAIL] {Path(r['gds_file']).name}: {r['verdict']} — "
                      f"{r['reason']}", file=sys.stderr)
        return RC_FINDINGS

    if verdict == "NOTHING_MEASURED":
        why = "; ".join(f"{Path(r['gds_file']).name}: {r.get('reason', '?')}"
                        for r in recs) or (
            f"no .gds at any canonical chip-GDS path under {project}")
        print(f"VACUOUS_PASS: {TOOL} measured no GDS against a DEF — {why}")
        return RC_CANNOT_MEASURE

    for r in recs:
        if r["verdict"] == "OK":
            print(f"PASS: {Path(r['gds_file']).name} — top cell "
                  f"'{r['top_cell']}' names all {r['pins_placed']} placed "
                  f"port(s) ({r['top_labels']} label(s) in the top cell, "
                  f"{r['labels_total_in_library']} in the library)"
                  + (f"; {r['pins_unplaceable']} declared pin(s) carry no "
                     f"placement and cannot be labelled"
                     if (r.get("pins_unplaceable") or 0) > 0 else "")
                  + (f"; NOTE the DEF's `PINS {r['pins_declared']} ;` header "
                     f"disagrees with its own body ({r['pins_placed']} placed)"
                     if (r.get("pins_unplaceable") or 0) < 0 else ""))
        else:
            print(f"NOTE: {Path(r['gds_file']).name} — {r['verdict']}: "
                  f"{r.get('reason', '')}")
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
