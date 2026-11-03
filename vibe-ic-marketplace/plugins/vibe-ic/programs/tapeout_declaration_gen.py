#!/usr/bin/env python3
"""Write the initial tapeout contract or measure the final GDS with KLayout.

The initial contract is populated only from supplied answers. The explicit
--measure-final-gds mode writes a separate final declaration of native geometry;
it preserves the original contract and never derives acceptance limits.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _submission_template as ST                              # noqa: E402
import _tapeout_declaration as TD                              # noqa: E402
import plugin_manifest_discovery as _pmd                       # noqa: E402
from _atomic_artefact import write_text as atomic_write_text   # noqa: E402

PROGRAM = "tapeout_declaration_gen"
FINAL_REL = "reports/phase3/tapeout_declaration_final.json"


def final_gds(project: Path) -> Path:
    """The final stream this run published, including a relocated run."""
    import librelane_contract as contract
    from librelane_fill_dfm import DEFAULT_STREAM_REL
    from tapeout_readiness_check import discover_layouts
    selected = project / DEFAULT_STREAM_REL
    if selected.is_file():
        record = json.loads(selected.read_text())
        path = contract.project_path(project, record["canonical"])
        if path.is_file():
            return path
        raise ValueError(f"published final GDS is missing: {path}")
    layouts = discover_layouts(project)
    if len(layouts) != 1:
        raise ValueError(f"expected one final layout, found {len(layouts)}")
    return layouts[0]


_FINAL_MEASURE = r'''
import json
import pya
layout = pya.Layout()
layout.read(gds)
tops = layout.top_cells()
if len(tops) != 1:
    raise ValueError("final GDS must have exactly one top cell")
cell = tops[0]
box = cell.bbox()
layers = []
polygons = zero_area = 0
for index in layout.layer_indexes():
    count = bad = 0
    shapes = cell.begin_shapes_rec(index)
    while not shapes.at_end():
        shape = shapes.shape()
        if shape.is_box():
            area = shape.box.area()
        elif shape.is_polygon():
            area = shape.polygon.area()
        elif shape.is_path():
            area = shape.path.polygon().area()
        else:
            shapes.next()
            continue
        count += 1
        bad += int(area <= 0)
        shapes.next()
    if count:
        info = layout.get_info(index)
        layers.append({"layer": info.layer, "datatype": info.datatype,
                       "polygon_count": count, "zero_area_polygon_count": bad})
    polygons += count
    zero_area += bad
bbox = [coordinate * layout.dbu for coordinate in (box.left, box.bottom, box.right, box.top)]
result = {"tool": "KLayout", "tool_version": pya.Application.instance().version(),
          "top_cell": cell.name, "database_unit_um": layout.dbu,
          "bbox_um": bbox, "width_um": box.width() * layout.dbu,
          "height_um": box.height() * layout.dbu, "polygon_count": polygons,
          "zero_area_polygon_count": zero_area, "layers": layers}
with open(out, "w") as stream:
    json.dump(result, stream, indent=2)
'''


def measure_final(project: Path, gds: Optional[Path] = None) -> dict:
    """Measure the shipped GDS with KLayout and write the final declaration.

    The initial declaration remains the design contract. Measured dimensions
    are published separately and never become a new acceptance limit.
    """
    project = Path(project).resolve()
    destination = project / FINAL_REL
    destination.parent.mkdir(parents=True, exist_ok=True)
    script = destination.with_name("tapeout_declaration_measure.py")
    native = destination.with_name("tapeout_declaration_measure.json")
    log = destination.with_name("tapeout_declaration_measure.log")
    result = {"program": PROGRAM, "verdict": "NOT_MEASURED", "measurement": None,
              "scope": "final GDS measurement; original limits are evaluated by tapeout_precheck"}
    try:
        gds = Path(gds) if gds is not None else final_gds(project)
        if not gds.is_absolute():
            gds = project / gds
        result["gds"] = str(gds.relative_to(project)) if gds.is_relative_to(project) else str(gds)
        result["gds_sha256"] = hashlib.sha256(gds.read_bytes()).hexdigest()
        script.write_text(_FINAL_MEASURE)
        native.unlink(missing_ok=True)
        command = ["klayout", "-b", "-r", str(script), "-rd", f"gds={gds}", "-rd", f"out={native}"]
        result["command"] = command
        with log.open("w") as stream:
            completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=False)
        result["exit_code"] = completed.returncode
        if completed.returncode != 0 or not native.is_file():
            raise ValueError(f"KLayout measurement did not complete; see {log.relative_to(project)}")
        measurement = json.loads(native.read_text())
        result["measurement"] = measurement
        result["verdict"] = ("PASS" if measurement["polygon_count"] > 0
                             and measurement["zero_area_polygon_count"] == 0 else "FAIL")
        source = project / TD.DECLARATION_REL
        if source.is_file():
            result["declared_contract"] = json.loads(source.read_text())
            result["declared_contract_path"] = TD.DECLARATION_REL
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["reason"] = str(exc)
    atomic_write_text(destination, json.dumps(result, indent=2) + "\n")
    return result


def _self_tapeout_text(doc: Dict[str, Any]) -> str:
    audit = TD.audit(doc)
    return "\n".join([
        TD.SELF_TAPEOUT_MARKER,
        "",
        "This design declares that it is a DIE and that it targets NO shuttle",
        "operator. It is on the CHIP path, so it runs step 37.5ic and gets that",
        "step's general tape-out precheck; the operator's own container is the",
        "arm it does not get, because there is no operator. It is not an IP",
        "hardmacro (37.5ip).",
        "",
        f"declaration: {TD.DECLARATION_REL}",
        f"answered:    {audit['answered']} of {audit['questions_total']} "
        f"question(s); {audit['unanswered']} still NOT_DETERMINED",
        "",
        "Every unanswered question is reported by the general precheck as",
        "NOT_DETERMINED, which is a non-pass. Nothing is defaulted.",
        "",
    ])


def _retire_own_marker(path: Path, marker: str) -> Optional[str]:
    """Delete `path` iff its first line is `marker`. Returns it if deleted."""
    if not path.exists():
        return None
    try:
        head = path.read_text(errors="replace").splitlines()[:1]
    except OSError:
        return None
    if head and head[0].strip() == marker:
        try:
            path.unlink()
        except OSError:
            return None
        return str(path)
    return None


def build(project: Path, answers_path: Optional[Path]) -> Dict[str, Any]:
    """The declaration, the route, and everything that went into both."""
    doc = TD.blank_declaration()
    source: Dict[str, Any] = {"answers_file": None, "ignored_keys": [],
                              "error": None}
    if answers_path is not None:
        source["answers_file"] = str(answers_path)
        if not answers_path.is_file():
            source["error"] = f"no such answers file: {answers_path}"
        else:
            raw, err = TD.load(answers_path)
            if err is not None:
                source["error"] = err
            elif not isinstance(raw, dict):
                source["error"] = ("the answers file's top level is "
                                   f"{type(raw).__name__}, not a mapping")
            else:
                # Accept either the flat `{key: value}` shape a human writes or
                # a full declaration document. Both, because a caller who
                # copies a previous declaration and edits it should not have to
                # unwrap it first.
                flat = raw.get("answers") if isinstance(
                    raw.get("answers"), dict) else raw
                merged = dict(flat)
                for key in TD.EXTRA_KEYS:
                    if key in raw:
                        merged[key] = raw[key]
                doc, ignored = TD.merge_answers(doc, merged)
                # The area producer replays its owner-attested slot selection
                # against this declaration. Carry the supplied selection along
                # with its provenance; dropping it makes a fresh LIMIT appear
                # stale at the real consumer. No slot is chosen here.
                if "operator_template" in raw:
                    doc["operator_template"] = copy.deepcopy(raw["operator_template"])
                source["ignored_keys"] = ignored
                # #2070 — a transcribed TECHNOLOGY fact answers its question.
                # `merge_answers` carried the provenance record through as an
                # extra key; this is what makes the VALUE land in `answers`
                # where every consumer reads it, from the one record, so a
                # declaration can never carry the provenance of a number it
                # does not publish. Idempotent when the producer already wrote
                # the value (it does), and the single source of the rule when
                # some other producer does not.
                doc = TD.merge_technology(doc, doc.get(TD.TECHNOLOGY_KEY)
                                          if isinstance(
                                              doc.get(TD.TECHNOLOGY_KEY), dict)
                                          else {})

    slots = sorted((project / ST.SLOTS_DIR_REL).glob("*.yaml")) + \
        sorted((project / ST.SLOTS_DIR_REL).glob("*.yml"))
    has_slots = bool(slots)
    route = TD.route_of(doc, has_slots, project)
    return {
        "schema": TD.SCHEMA,
        "program": PROGRAM,
        "project": str(project),
        "declaration": doc,
        "declaration_refusals": TD.validate(doc),
        # KEPT APART FROM THE MALFORMED ONES ON PURPOSE. `validate` answers
        # "can anybody read this?"; these answer "did anybody entitled to
        # answer it actually answer it?". Both are rc 1 below, and a reader
        # sorting a failing run has to be able to tell which of the two it is
        # holding without re-reading the messages.
        "attestation_refusals": TD.owner_attestation_refusals(doc),
        "audit": TD.audit(doc),
        "answers_source": source,
        "operator_slot_files": [str(p) for p in slots],
        "route": route,
        "route_reason": _route_reason(route, has_slots, doc),
    }


def _route_reason(route: str, has_slots: bool, doc: Dict[str, Any]) -> str:
    if route == TD.ROUTE_SHUTTLE:
        return ("an operator template was ingested, so the chip path (step "
                "37.5ic) runs BOTH arms: the general precheck and the "
                "operator's own container. The operator's answer wins over "
                "anything this design declares about itself, and where the two "
                "arms disagree the step refuses rather than preferring one")
    if route == TD.ROUTE_SELF_TAPEOUT:
        return ("no applicable operator binding, and the design declares deliverable="
                f"{TD.DELIVERABLE_DIE}: it is a die doing its own tape-out, so "
                "it takes the chip path (step 37.5ic) and is judged by the "
                "general precheck alone — the operator's arm has no operator")
    if route == TD.ROUTE_IP:
        return ("no applicable operator binding, and the design declares deliverable="
                f"{TD.DELIVERABLE_HARDMACRO}: it is delivered, not fabricated, "
                "so it terminates at the hardmacro kit (step 37.5ip) and needs "
                "no pad ring, seal ring or submission check")
    return ("`deliverable` is NOT_DETERMINED, so no route was selected and no "
            "router file was written. A design that has not said what it is "
            "has not chosen a route and must not be given one")


def write_artefacts(project: Path, rec: Dict[str, Any]) -> Dict[str, Any]:
    written: Dict[str, Any] = {"declaration": None, "self_tapeout": None,
                               "retired_stale": []}
    decl_path = project / TD.DECLARATION_REL
    decl_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        decl_path,
        json.dumps(rec["declaration"], indent=2, ensure_ascii=False) + "\n")
    written["declaration"] = str(decl_path)

    self_path = project / TD.SELF_TAPEOUT_REL
    if rec["route"] == TD.ROUTE_SELF_TAPEOUT:
        atomic_write_text(self_path, _self_tapeout_text(rec["declaration"]))
        written["self_tapeout"] = str(self_path)
        # A die must not also select the IP terminal. Only OUR OWN sibling's
        # marker is retired; anything else is left as evidence.
        gone = _retire_own_marker(project / ST.NO_TEMPLATE_REL,
                                  ST.NO_TEMPLATE_MARKER)
        if gone:
            written["retired_stale"].append(gone)
    else:
        gone = _retire_own_marker(self_path, TD.SELF_TAPEOUT_MARKER)
        if gone:
            written["retired_stale"].append(gone)
    return written


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Write the tape-out declaration (step 0.5ic) and select "
                    "the delivery route. Every unanswered question is "
                    "NOT_DETERMINED; nothing is ever defaulted or inferred.")
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--answers", type=Path, default=None,
                   help="JSON file of answers. Omitting it produces a "
                        "complete, well-formed, entirely unanswered "
                        "declaration — which is a legal and useful result.")
    p.add_argument("--json", type=Path, dest="out_json", default=None,
                   help=f"Report path (default: <project>/{TD.REPORT_REL}).")
    p.add_argument("--print-json", action="store_true")
    p.add_argument("--measure-final-gds", action="store_true",
                   help="Measure this run's final GDS with KLayout and write the final declaration.")
    args = p.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: project directory not found: {project}", file=sys.stderr)
        return 2

    if args.measure_final_gds:
        rec = measure_final(project)
        print(json.dumps(rec, indent=2))
        return 0 if rec["verdict"] == "PASS" else 1 if rec["verdict"] == "FAIL" else 2

    # The direct producer entry point must enforce the same 0.5ic route
    # decision as the runner, before it writes either router file.
    if TD.bought_slot_hardmacro(project):
        print(f"REFUSED: {TD.BOUGHT_SLOT_HARDMACRO_MESSAGE}", file=sys.stderr)
        return 1

    rec = build(project, args.answers)
    try:
        rec["written"] = write_artefacts(project, rec)
    except OSError as exc:
        print(f"[ERROR] {PROGRAM}: could not write the declaration: {exc}",
              file=sys.stderr)
        return 2
    rec["emitted_by"] = _pmd.emitted_by(PROGRAM)

    out = args.out_json or (project / TD.REPORT_REL)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(rec, indent=2,
                                          ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[ERROR] {PROGRAM}: could not write the report: {exc}",
              file=sys.stderr)
        return 2

    if args.print_json:
        print(json.dumps(rec, indent=2, ensure_ascii=False))

    a = rec["audit"]
    print(f"{PROGRAM}: route={rec['route']} "
          f"answered={a['answered']}/{a['questions_total']} "
          f"unanswered={a['unanswered']} not_applicable={a['not_applicable']}")
    for sec, s in a["sections"].items():
        print(f"  {sec}: {s['answered']}/{s['questions']} answered"
              + (f", unanswered: {', '.join(s['unanswered_keys'])}"
                 if s["unanswered_keys"] else ""))
    print(f"  {rec['route_reason']}")
    if rec["answers_source"]["error"]:
        print(f"  answers not read: {rec['answers_source']['error']}",
              file=sys.stderr)
    if rec["answers_source"]["ignored_keys"]:
        print("  IGNORED (not a recognized declaration field): "
              + ", ".join(rec["answers_source"]["ignored_keys"]),
              file=sys.stderr)
    # A malformed declaration is the one thing this program can produce that
    # nobody can read. An UNANSWERED one is the intended output and is rc 0.
    if rec["declaration_refusals"]:
        for r in rec["declaration_refusals"]:
            print(f"  REFUSED {r['rule']}: {r['message']}", file=sys.stderr)
        return 1
    # THE HALT AT STEP 0.5 (R-0915-95). This program is BLOCKING in step
    # 0.5ic's producer chain -- `phase1_one_shot_runner._run_step_0_5ic` fails
    # the whole of Phase 1 on a non-zero rc here -- so this is where an
    # owner-only question that nobody entitled to answer has answered actually
    # STOPS the flow, with the question surfaced. The sibling gate
    # `tapeout_declaration_check` reports the same refusal in the compliance
    # channel; one fix, two consumers, and neither is allowed to be the only
    # one that notices.
    if rec["attestation_refusals"]:
        for r in rec["attestation_refusals"]:
            print(f"  REFUSED {r['rule']}: {r['message']}", file=sys.stderr)
        return 1
    if rec["answers_source"]["error"]:
        return 1
    return 0


if __name__ == "__main__":
    from execution_modes import frontend_producer_main
    sys.exit(frontend_producer_main(main))
