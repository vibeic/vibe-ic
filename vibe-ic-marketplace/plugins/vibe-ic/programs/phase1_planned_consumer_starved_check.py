#!/usr/bin/env python3
"""phase1_planned_consumer_starved_check.py — an empty layer is only allowed
to be empty when NOTHING LATER READS IT.

ENFORCEMENT: advisory

THE DEFECT, AS MEASURED
=======================
Phase 1 emits ``phase1/generated_docs/L*.json``. A layer emitted as an EMPTY
SKELETON — every content collection present and every one of them length 0 —
passes every gate that exists at the point of production:

  * ``phase1_all_l_docs_present_check``  asks only whether the FILE is there.
  * ``phase1_structured_field_substance_check`` compares a fixed list of
    fields against a fixed list of template DEFAULT VALUES; ``[]`` is not one
    of them for most layers, and the list names no consumer.
  * ``phase1_layer_demand_probe`` asks the INPUT-side question — "did the
    design's own documents STATE facts this layer failed to extract?" — and
    stays deliberately silent when the input states nothing.

None of the three asks the consumer-side question:

    is a later step going to READ this layer?

That question is the one that decides whether the emptiness is harmless. And
the flow answers it in writing. Twenty-nine strings in
``flow/phase1_phase2_phase3.yaml`` name a ``phase1/generated_docs/L*.json``
path, and the ones that matter have this exact shape::

    - optional_program_exit_zero:
        command: "<consumer> ... phase1/generated_docs/L<n>_<NAME>.json ..."
        condition_files_exist: ["phase1/generated_docs/L<n>_<NAME>.json"]

The condition is FILE EXISTENCE. So an empty skeleton is strictly WORSE than
no file at all:

    file absent   -> condition false -> the step records a SKIP. Honest.
    file present  -> condition true  -> the consumer runs, reads zero
                     elements, finds nothing to object to, and returns PASS.

Emitting the skeleton converts an honest skip into a green light, five steps
before anyone looks. ``flow_condition_reachability_check`` already classifies
``phase1/generated_docs/`` as a T1 DECLARATION trigger — "a broken analog
block does not delete the declaration that the block exists" — which is
correct for PRESENCE and says nothing about CONTENT. This gate is the content
half of that same trigger.

THE RULE
========
    When a PLANNED downstream step reads a layer, that layer being an empty
    skeleton is a FAILURE at the point the layer is produced, and the failure
    names the consumer that will be starved.

Three conjuncts, each derived, none guessed:

  C1  CONSUMER IS DECLARED.  Read out of the shipped flow YAML, never
      re-spelled here: any step whose gate predicate COMMAND names the layer
      path is a consumer of that layer. The step that lists the layer in its
      own ``required_outputs`` is its PRODUCER and is excluded — derived from
      the YAML, so renaming the producing step cannot break the exclusion.

  C2  CONSUMER IS PLANNED FOR THIS PROJECT.  Every condition between the
      project and that predicate must hold *now*: the stage's
      ``condition.files_exist``, the step's ``condition.files_exist``, the
      predicate's own ``condition_files_exist``, and the step must not be
      waived (via the shared ``_waiver_entries`` reader).
      PLANNEDNESS DELIBERATELY DOES NOT REQUIRE PHASE-2 ARTEFACTS TO EXIST.
      The whole point is to fail at production time, which is before phase2
      has run; a plannedness test that waited for ``phase2/`` would only ever
      speak after the damage.

  C3  THE LAYER IS SILENTLY EMPTY.  It parses, it declares at least one
      content collection, every content collection is empty — AND the layer
      makes no declaration of why. The design already owns three ways to say
      it: a ``no_<field>_in_input: true`` flag, an ``applicability`` of N/A,
      or an ``extraction_status`` in the producer's own FOUND-NOTHING
      vocabulary. Any one of them and this gate stays quiet, because the
      emptiness is then stated rather than silent.

WHY C3's ESCAPE HATCH IS NOT A LOOPHOLE — MEASURED
==================================================
Without C3 this would be the false-positive machine
``phase1_layer_demand_probe``'s docstring warns about. Measured on this
repo's tracked corpus (108 roots carrying ``phase1/generated_docs/L*.json``),
over the five layers the flow declares a consumer for:

    empty skeletons found ................................. 77
    of those, carrying an explicit emptiness declaration ... 72
    remaining (silent) .................................... 5

So the escape hatch is not an invention to make a number go down: it is what
94% of the corpus already does. A design with no command protocol writes
``no_opcodes_in_input: true`` and this gate never speaks. The 5 that stay are
the deviation from the corpus's own norm.

WHAT THE 5 ARE, AND WHY THEY ARE NOT FALSE POSITIVES
====================================================
All five are the same layer (the timing/waveform layer) emitted as three
empty collections with no declaration and no extraction evidence, on projects
whose flow plan includes the SDC-generating step whose validator is
conditioned on that very file. One of the five is independently corroborated
inside this repo: ``l8_sta_clock_period_design_owned_check`` records that the
same project's PUBLISHED SDC carries ``sdc_gen``'s hardcoded default period
verbatim — the fabricated number a starved timing layer produces. The gate
found, from the production side, the cause of a defect an existing gate had
already found from the consumption side.

That is why this gate is wired ADVISORY rather than blocking, and why the
finding was NOT tuned away. Blocking would turn 5 published roots red for a
producer-side defect the corpus shares — the same reason
``l16_compliance_properties_actionable_check``,
``l17_channel_catalog_consumer_contract_check`` and
``l8_sta_clock_period_design_owned_check`` are advisory. Narrowing until the
count reached zero would have required dropping the layer or accepting bare
presence, and either one swallows the real defect underneath.

SCOPE — WHAT THIS GATE DOES NOT CLAIM
=====================================
It judges the LAYER, not the FIELD. A layer that carries one non-empty
collection while the specific key its consumer reads is empty is NOT reported
here: deciding which key a given consumer dereferences is per-consumer
knowledge that the flow YAML does not carry, and guessing it is how a gate
starts inventing requirements. The per-layer contract gates
(``l10_*``, ``l12_*``, ``l17_*`` ...) own that finer question. This gate owns
the coarse one nothing owned: the layer is entirely empty and somebody is
going to read it.

Usage:
    python3 phase1_planned_consumer_starved_check.py <project_dir>
            [--flow <flow.yaml|plugin_dir>] [--json OUT]

Exit codes:
    0 = PASS (no planned consumer is starved) / SKIP (no generated_docs)
    1 = FAIL — at least one silently-empty layer has a planned consumer
    2 = operational (flow YAML missing or unparseable)

Honors waiver ``phase1_planned_consumer_starved_intentional`` (>=40 chars).
chip-AGNOSTIC: no design, PDK, vendor or part literal appears anywhere. The
only literals are the flow's own step vocabulary and the L-doc schema's own
bookkeeping key names.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROGRAM = "phase1_planned_consumer_starved_check"
VERSION = "1.0.0"

WAIVER_KEY = "phase1_planned_consumer_starved_intentional"
WAIVER_MIN = 40

_FLOW_REL = Path("flow") / "phase1_phase2_phase3.yaml"

#: Any string in the flow that names a Phase-1 layer artefact. Group 0 is the
#: PROJECT-RELATIVE PATH and group 1 the layer code.
#:
#: THE PATH IS THE KEY, NOT THE CODE. One layer code can own more than one
#: document — the flow's own comment on the second L8 records that
#: ``phase1_all_l_docs_present_check`` matches by ``L<n>_`` PREFIX, so one
#: sibling satisfied the slot and the other's absence was invisible to every
#: gate. A gate that resolved a consumer's layer by prefix glob would repeat
#: that exactly: it would judge whichever sibling sorts first and report a
#: clean verdict about a file no consumer named.
_LAYER_REF_RE = re.compile(
    r"phase1/generated_docs/(L\d+)[_A-Za-z0-9*]*\.json")

#: Gate-predicate keys that carry a COMMAND. A predicate is either
#: ``{<key>: "<command>"}`` or ``{<key>: {command: ..., condition_files_exist:
#: [...]}}`` — both shapes appear in the shipped flow.
_COMMAND_KEYS = (
    "program_exit_zero",
    "advisory_program_exit_zero",
    "optional_program_exit_zero",
)

# ---------------------------------------------------------------------------
# L-doc bookkeeping vocabulary.
#
# These keys describe the DOCUMENT, not the design. They are excluded from the
# content scan so that a layer holding nothing but its own schema header is
# still recognised as empty. Derived by census over the tracked corpus, not by
# taste: every key here appears on >=100 of the 2610 tracked L-doc JSONs and
# none of them is a content collection in any of them.
# ---------------------------------------------------------------------------
_BOOKKEEPING_KEYS = frozenset({
    "schema_version", "doc_class", "doc_name", "doc_id", "ic_class",
    "class_path", "emitted_by", "extraction_status", "extraction_hints",
    "extraction_strategy", "extraction_evidence", "applicability",
    "provenance", "generated_at", "source", "version", "layer", "l_doc",
    "notes", "rationale", "ic_name", "id",
})

#: ``no_<field>_in_input`` — the design's own "the input said nothing about
#: this" flag. Used across the corpus and already honoured by
#: ``phase1_structured_field_substance_check``.
_NO_FIELD_RE = re.compile(r"^no_.+_in_input$")

#: Applicability values that state the layer does not apply to this design.
_APPLICABILITY_NOT_APPLICABLE = frozenset({
    "N/A", "NA", "NOT_APPLICABLE", "NOT APPLICABLE", "NONE", "ABSENT",
    "NOT_PRESENT",
})


def _found_nothing_vocabulary() -> frozenset:
    """The producer's own FOUND-NOTHING status tokens.

    READ OUT of a gate that already declares the set rather than re-spelled
    here — three copies of this vocabulary already exist (L16/L17/L18) and a
    fourth would be the drift the layer-contract doctrine keeps warning about.
    When the import is unavailable the set is EMPTY, which is the strict
    direction: ``extraction_status`` then grants no exemption and the other
    two declarations still do. Zero tracked corpus documents rely on this
    path, so the strict fallback changes no measured verdict.
    """
    try:
        from l17_channel_catalog_consumer_contract_check import (  # noqa: PLC0415
            _STATUS_FOUND_NOTHING as _v)
        return frozenset(str(x).strip().upper() for x in _v)
    except Exception:                                       # noqa: BLE001
        return frozenset()


# ---------------------------------------------------------------------------
# Flow reading
# ---------------------------------------------------------------------------
def resolve_flow_yaml(arg: Optional[str]) -> Path:
    """Accept a flow YAML path, a PLUGIN DIRECTORY, or nothing.

    Same resolver contract as ``flow_condition_reachability_check``: a guard
    that only accepts a YAML path answers a plugin-directory invocation with
    "cannot find the flow", which is a check disabled by its own caller.
    """
    if not arg:
        return Path(__file__).resolve().parent.parent / _FLOW_REL
    p = Path(arg)
    if p.is_dir():
        cand = p / _FLOW_REL
        if cand.is_file():
            return cand
        for sub in sorted(p.glob("plugins/*/" + str(_FLOW_REL))):
            return sub
        return cand
    return p


def _iter_predicates(node: Any) -> Iterable[Tuple[str, str, List[str]]]:
    """``(predicate_key, command, condition_files_exist)`` for every
    command-bearing predicate anywhere under ``node``."""
    if isinstance(node, dict):
        for key in _COMMAND_KEYS:
            if key not in node:
                continue
            val = node[key]
            if isinstance(val, str):
                yield key, val, []
            elif isinstance(val, dict):
                cmd = val.get("command")
                cond = val.get("condition_files_exist") or []
                if isinstance(cmd, str):
                    yield (key, cmd,
                           [c for c in cond if isinstance(c, str)])
        for v in node.values():
            yield from _iter_predicates(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_predicates(v)


def _files_exist_list(cond: Any) -> List[str]:
    if isinstance(cond, dict):
        v = cond.get("files_exist")
        if isinstance(v, list):
            return [x for x in v if isinstance(x, str)]
    return []


def _layer_refs(text: str) -> Dict[str, str]:
    """``{project_relative_path: layer_code}`` for every layer named in
    ``text``."""
    return {m.group(0): m.group(1) for m in _LAYER_REF_RE.finditer(text)}


def consumers_from_flow(flow: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every DECLARED layer consumer in the flow definition (C1).

    A gate predicate consumes a layer when the layer path appears EITHER in
    its command OR in its ``condition_files_exist``. Both count, and the
    second is the load-bearing one: ``condition_files_exist: [<layer>]`` on a
    program whose argv does not spell the layer out still says "run this
    consumer once that layer exists" — that is the admission rule the empty
    skeleton exploits, and reading only commands would miss the purest
    instance of the defect.

    The step that lists the same layer under ``required_outputs`` is its
    PRODUCER and is excluded. The exclusion is derived from the YAML rather
    than keyed to a step id, so renaming the producing step cannot silently
    turn a producer into a consumer of its own output.
    """
    stages = {s.get("id"): s for s in (flow.get("stages") or [])
              if isinstance(s, dict)}
    out: List[Dict[str, Any]] = []
    for step in (flow.get("steps") or []):
        if not isinstance(step, dict):
            continue
        produced = set()
        for pat in (step.get("required_outputs") or []):
            if isinstance(pat, str):
                produced.update(_layer_refs(pat))
        stage_id = step.get("stage")
        stage = stages.get(stage_id) or {}
        for key, cmd, cond in _iter_predicates(step.get("gate")):
            refs: Dict[str, str] = {}
            refs.update(_layer_refs(cmd))
            for c in cond:
                refs.update(_layer_refs(c))
            for path in sorted(set(refs) - produced):
                out.append({
                    "layer": refs[path],
                    "layer_path": path,
                    "step": step.get("id"),
                    "step_name": step.get("name"),
                    "stage": stage_id,
                    "predicate": key,
                    "command": cmd,
                    "named_in_command": path in _layer_refs(cmd),
                    "condition_files_exist": cond,
                    "step_condition": _files_exist_list(
                        step.get("condition")),
                    "stage_condition": _files_exist_list(
                        stage.get("condition")),
                })
    return out


# ---------------------------------------------------------------------------
# Plannedness (C2)
# ---------------------------------------------------------------------------
def _pattern_matches(project: Path, pattern: str) -> bool:
    if any(ch in pattern for ch in "*?["):
        try:
            return any(True for _ in project.glob(pattern))
        except Exception:                                   # noqa: BLE001
            return False
    return (project / pattern).exists()


def _all_present(project: Path, patterns: Iterable[str]) -> bool:
    return all(_pattern_matches(project, p) for p in patterns)


def waived_step_ids(project: Path) -> set:
    """Flow step ids this project has waived, via the ONE shared reader."""
    ids: set = set()
    try:
        from _waiver_entries import (  # noqa: PLC0415
            dict_entries, read_document, resolve_step_name)
    except Exception:                                       # noqa: BLE001
        return ids
    try:
        doc = read_document(Path(project))
    except Exception:                                       # noqa: BLE001
        return ids
    for entry in dict_entries(doc):
        if "id" in entry:
            ids.add(entry["id"])
        named = resolve_step_name(entry.get("step"))
        if named is not None:
            ids.add(named)
    return ids


def plannedness(project: Path, consumer: Dict[str, Any],
                waived: set) -> Tuple[bool, str]:
    """Is this consumer on the plan for THIS project? ``(planned, reason)``."""
    if consumer["step"] in waived:
        return False, "step waived"
    if not _all_present(project, consumer["stage_condition"]):
        return False, "stage condition not satisfied"
    if not _all_present(project, consumer["step_condition"]):
        return False, "step condition not satisfied"
    if not _all_present(project, consumer["condition_files_exist"]):
        return False, "predicate condition_files_exist not satisfied"
    return True, "planned"


# ---------------------------------------------------------------------------
# Silent emptiness (C3)
# ---------------------------------------------------------------------------
def _payload(doc: Any) -> Dict[str, Any]:
    """The layer's content payload.

    Reuses the shared accessor so this gate and the L20/L22/L23 gates cannot
    disagree about where a layer keeps its fields (nested under ``fields`` vs
    flat). Falls back to an inline equivalent only if the shared module is not
    importable.
    """
    try:
        from l_doc_consumer_contract import l_doc_fields  # noqa: PLC0415
        return l_doc_fields(doc) or {}
    except Exception:                                       # noqa: BLE001
        if not isinstance(doc, dict):
            return {}
        inner = doc.get("fields")
        merged = {k: v for k, v in doc.items() if k != "fields"}
        if isinstance(inner, dict):
            merged.update(inner)
        return merged


def _is_bookkeeping(key: str) -> bool:
    return (key in _BOOKKEEPING_KEYS
            or key.startswith("_")
            or bool(_NO_FIELD_RE.match(key)))


def content_collections(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The layer's enumerable content: every non-bookkeeping list/dict."""
    return {k: v for k, v in payload.items()
            if not _is_bookkeeping(k) and isinstance(v, (list, dict))}


def emptiness_declaration(payload: Dict[str, Any]) -> Optional[str]:
    """How the design SAYS this layer is empty, or None if it says nothing."""
    for k, v in payload.items():
        if _NO_FIELD_RE.match(k) and v is True:
            return k
    app = payload.get("applicability")
    if isinstance(app, str) and app.strip().upper() in \
            _APPLICABILITY_NOT_APPLICABLE:
        return f"applicability={app.strip()}"
    if isinstance(app, dict):
        for probe in ("status", "value", "applicable"):
            raw = app.get(probe)
            if isinstance(raw, str) and raw.strip().upper() in \
                    _APPLICABILITY_NOT_APPLICABLE:
                return f"applicability.{probe}={raw.strip()}"
            if probe == "applicable" and raw is False:
                return "applicability.applicable=false"
    status = str(payload.get("extraction_status") or "").strip().upper()
    if status and status in _found_nothing_vocabulary():
        return f"extraction_status={status}"
    return None


def layer_state(project: Path, code: str, rel_path: str) -> Dict[str, Any]:
    """Classify the ONE document the consumer names.

    ``rel_path`` is the project-relative path AS WRITTEN IN THE FLOW, so a
    layer code owning two documents is judged per document. A wildcard in the
    declared path (the flow spells one layer's suffix as ``L13_*.json``,
    because that suffix is IC-class dependent) is expanded against the
    project; every match is judged and the first non-clean one is reported.

    ``LAYER_ABSENT`` / ``UNPARSEABLE`` / ``NO_CONTENT_SCHEMA`` /
    ``DECLARED_EMPTY`` / ``SILENT_EMPTY`` / ``HAS_CONTENT``.
    Only ``SILENT_EMPTY`` can produce a finding; the other five are the
    business of other gates and are reported so a reader can tell a quiet
    verdict from an unexamined one.
    """
    base = {"layer": code, "declared_path": rel_path}
    if any(ch in rel_path for ch in "*?["):
        try:
            hits = sorted(project.glob(rel_path))
        except Exception:                                   # noqa: BLE001
            hits = []
    else:
        p = project / rel_path
        hits = [p] if p.is_file() else []
    if not hits:
        return {**base, "state": "LAYER_ABSENT", "path": None}

    states = [_one_layer_state(base, h) for h in hits]
    for want in ("SILENT_EMPTY", "UNPARSEABLE", "DECLARED_EMPTY",
                 "NO_CONTENT_SCHEMA"):
        for st in states:
            if st["state"] == want:
                return st
    return states[0]


def _one_layer_state(base: Dict[str, Any], path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:                                       # noqa: BLE001
        return {**base, "state": "UNPARSEABLE", "path": path.name}
    payload = _payload(doc)
    cols = content_collections(payload)
    if not cols:
        return {**base, "state": "NO_CONTENT_SCHEMA", "path": path.name,
                "collections": []}
    nonempty = sorted(k for k, v in cols.items() if len(v) > 0)
    if nonempty:
        return {**base, "state": "HAS_CONTENT", "path": path.name,
                "collections": sorted(cols), "nonempty": nonempty}
    decl = emptiness_declaration(payload)
    if decl:
        return {**base, "state": "DECLARED_EMPTY", "path": path.name,
                "collections": sorted(cols), "declaration": decl}
    return {**base, "state": "SILENT_EMPTY", "path": path.name,
            "collections": sorted(cols)}


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def evaluate(project: Path, flow: Dict[str, Any]) -> Dict[str, Any]:
    project = Path(project)
    consumers = consumers_from_flow(flow)
    waived = waived_step_ids(project)

    states: Dict[str, Dict[str, Any]] = {}
    for c in consumers:
        if c["layer_path"] not in states:
            states[c["layer_path"]] = layer_state(
                project, c["layer"], c["layer_path"])

    findings: List[Dict[str, Any]] = []
    examined: List[Dict[str, Any]] = []
    for c in consumers:
        st = states[c["layer_path"]]
        planned, why = plannedness(project, c, waived)
        rec = {
            "layer": c["layer"],
            "layer_path": c["layer_path"],
            "layer_file": st.get("path"),
            "layer_state": st["state"],
            "planned": planned,
            "plannedness": why,
            "consumer_step": c["step"],
            "consumer_step_name": c["step_name"],
            "consumer_stage": c["stage"],
            "consumer_predicate": c["predicate"],
            "consumer_command": c["command"],
            "admitted_by": c["condition_files_exist"],
        }
        examined.append(rec)
        if planned and st["state"] == "SILENT_EMPTY":
            findings.append({**rec,
                             "empty_collections": st.get("collections") or []})

    return {
        "program": PROGRAM,
        "version": VERSION,
        "project": str(project),
        "declared_consumers": len(consumers),
        "layers_with_a_declared_consumer": sorted(states),
        "layer_states": [states[k] for k in sorted(states)],
        "examined": examined,
        "findings": findings,
    }


def _waiver_text(project: Path) -> Optional[str]:
    p = Path(project) / "waivers.json"
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(errors="replace"))
    except Exception:                                       # noqa: BLE001
        return None
    if not isinstance(d, dict):
        return None
    v = d.get(WAIVER_KEY)
    if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
        return v.strip()
    return None


#: The three states in which this gate reads NOTHING about emptiness. A layer
#: that is missing, that will not parse, or that carries no collection this
#: gate recognises cannot be judged clean — it was never judged at all. They
#: are counted separately from the clean reads so a PASS cannot pass an
#: unexamined layer off as an examined one (vibe-ic#447 denominator rule).
UNEXAMINED_STATES = ("LAYER_ABSENT", "UNPARSEABLE", "NO_CONTENT_SCHEMA")


def unexamined_planned(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The planned reads whose layer this gate could not examine at all."""
    return [e for e in result.get("examined") or []
            if e.get("planned") and e.get("layer_state") in UNEXAMINED_STATES]


def _unexamined_clause(result: Dict[str, Any]) -> str:
    blind = unexamined_planned(result)
    if not blind:
        return ""
    layers = sorted({e["layer"] for e in blind}, key=lambda c: int(c[1:]))
    return (f", {len(blind)} NOT EXAMINED "
            f"(absent / unparseable / no content schema: "
            f"{', '.join(layers)})")


def summary_line(result: Dict[str, Any]) -> str:
    f = result.get("findings") or []
    blind = _unexamined_clause(result)
    if not f:
        planned = sum(1 for e in result.get("examined") or [] if e["planned"])
        return (f"Planned consumers:   {planned} planned layer read(s), "
                f"{planned - len(unexamined_planned(result))} examined and "
                f"0 starved{blind}")
    layers = sorted({x["layer"] for x in f}, key=lambda c: int(c[1:]))
    return ("Planned consumers:   **{n} PLANNED READ(S) OF A SILENTLY EMPTY "
            "LAYER**: {names}{blind}".format(
                n=len(f), names=", ".join(layers), blind=blind))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fail a silently-empty Phase-1 layer that a planned "
                    "downstream step will read, naming the starved consumer.")
    ap.add_argument("project")
    ap.add_argument("--flow", default=None,
                    help="flow YAML path or plugin directory "
                         "(default: the shipped canonical flow)")
    ap.add_argument("--json", default=None, help="write the result JSON here")
    args = ap.parse_args(argv)

    project = Path(args.project).resolve()
    flow_path = resolve_flow_yaml(args.flow)
    if not flow_path.is_file():
        print(f"=== {PROGRAM} === OPERATIONAL: flow YAML not found at "
              f"{flow_path}")
        return 2
    try:
        import yaml
        flow = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    except Exception as exc:                                # noqa: BLE001
        print(f"=== {PROGRAM} === OPERATIONAL: flow YAML unreadable "
              f"({exc.__class__.__name__}: {exc})")
        return 2
    if not isinstance(flow, dict):
        print(f"=== {PROGRAM} === OPERATIONAL: flow YAML is not a mapping")
        return 2

    gd = project / "phase1" / "generated_docs"
    if not gd.is_dir():
        print(f"=== {PROGRAM} === SKIP: no phase1/generated_docs under "
              f"{project}")
        return 0

    res = evaluate(project, flow)
    waiver = _waiver_text(project)
    findings = res["findings"]
    res["waiver"] = waiver
    res["verdict"] = ("PASS" if not findings
                      else ("WAIVED" if waiver else "FAIL"))
    res["verdict_mode"] = "ADVISES"

    print(f"=== {PROGRAM} ===")
    print(f"  declared layer consumers in the flow: "
          f"{res['declared_consumers']}")
    for st in res["layer_states"]:
        print(f"  {st['layer']:>4}  {st['state']:<18} "
              f"{st.get('path') or st['declared_path'] + ' (absent)'}")
    if not findings:
        blind = unexamined_planned(res)
        if blind:
            # An unexamined layer is not a clean one. Saying so on the verdict
            # line is the whole point: the reader must not read "no starved
            # consumer" as "every planned read was checked".
            print("  [PASS] no planned downstream step reads a silently empty "
                  "layer — of the layers this gate DID examine.")
            detail = ", ".join(
                "{0} {1}".format(e["layer"], e["layer_state"]) for e in blind)
            print(f"         NOT EXAMINED: {len(blind)} planned read(s) — "
                  f"{detail}")
        else:
            print("  [PASS] no planned downstream step reads a silently empty "
                  "layer.")
    else:
        for f in findings:
            print("")
            print(f"  [FAIL] {f['layer']} ({f['layer_file']}) is an EMPTY "
                  f"SKELETON and step {f['consumer_step']} will read it.")
            print(f"         empty collections : "
                  f"{', '.join(f['empty_collections']) or '-'}")
            print(f"         starved consumer  : step {f['consumer_step']} "
                  f"— {f['consumer_step_name']}")
            print(f"         it runs           : {f['consumer_command']}")
            if f["admitted_by"]:
                print(f"         admitted by       : file exists — "
                      f"{', '.join(f['admitted_by'])}")
                print("         so the layer's mere presence turns a SKIP "
                      "into a verdict over nothing.")
            print("         fix: give the layer content, or declare the "
                  "emptiness (no_<field>_in_input / applicability / "
                  "extraction_status).")
        if waiver:
            print(f"\n  WAIVED by {WAIVER_KEY} "
                  f"({len(findings)} finding(s) suppressed)")

    print(f"\n  {summary_line(res)}")

    try:
        from l_doc_consumer_contract import write_report  # noqa: PLC0415
        write_report(project, PROGRAM, res)
    except Exception:                                       # noqa: BLE001
        pass
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

    return 1 if (findings and not waiver) else 0


if __name__ == "__main__":
    sys.exit(main())
