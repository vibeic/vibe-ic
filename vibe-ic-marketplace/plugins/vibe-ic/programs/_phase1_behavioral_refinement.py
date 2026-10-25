"""Bounded L6 projection of an independently authored FactGraph v1 proposal.

L6 owns the behavioral contract consumed by the RTL author. Validation here
proves vocabulary and coverage, never functional correctness. Independent D1
review must compare proposed choices with the original source requirements.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path
import re
import sys
import yaml

from _phase1_producer_identity import BEHAVIORAL_REFINEMENT_INPUT
from phase1_expert_parse_track import input_text_report, SKIP_ORACLE_PATH
import phase1_port_extract


def _owned_ports(extracted: dict, machine: dict, refuse, state_catalog) -> dict:
    """Use the FSM's source document, never a corpus-wide module union.

    Existing lexical scopes identify a single subject. This optional producer
    refuses ambiguous sibling interfaces rather than selecting one by name.
    """
    sources = [text for name, text in extracted.items()
               if machine["source"] in (name, "input/docs/" + name)]
    if len(sources) != 1:
        refuse("FSM interface owner cannot be located in current extracted source")
    text = sources[0]
    narrative = list(text)
    code_spans = phase1_port_extract._verilog_region_spans(text)
    for start, end in code_spans:
        narrative[start:end] = ["\n" if c == "\n" else " " for c in text[start:end]]
    narrative = "".join(narrative)
    scopes = phase1_port_extract._prose_module_scopes(narrative)
    owners = [owner for _, _, owner in scopes if owner is not None]
    if len(owners) > 1:
        refuse("FSM source has multiple interface owners")
    if owners:
        prefix = narrative[:scopes[0][0]]
        if (phase1_port_extract.extract_ports(prefix)
                or set(machine["states"]) & {name for name, _ in state_catalog(prefix)}):
            refuse("FSM or interface precedes the only declared module owner")
    clean = phase1_port_extract.strip_hdl_comments_and_strings(text)
    # Count headers even when a source snippet has no endmodule. The existing
    # complete-module grammar additionally recognizes non-ANSI declarations.
    modules = {m.start(): m for m in phase1_port_extract._MODULE_SPAN.finditer(clean)}
    modules.update({m.start(): m for m in phase1_port_extract._VERILOG_MODULE_HDR.finditer(clean)})
    if len(modules) > 1:
        refuse("FSM source has multiple HDL module owners")
    if modules and owners:
        module_name = re.match(r"module\s+(\w+)", next(iter(modules.values())).group())[1]
        if module_name != owners[0]:
            refuse("prose and HDL interface owners disagree")
    if owners:
        # Compare actual declaration rows with the same catalog the source
        # producer used. A number in an introductory range is not a state.
        owned_states = {name for name, _ in state_catalog(text[scopes[0][0]:])}
        if (not set(machine["states"]).issubset(owned_states)
                and not (machine.get("closed") and len(modules) == 1)):
            refuse("FSM declarations cannot be attributed to the interface owner")
    prose_ports = phase1_port_extract.extract_ports(narrative)
    if code_spans and prose_ports:
        # A sibling HDL header cannot shadow the source's prose interface.
        code_ports = [dict(name=p.name, dir=p.direction, width=p.width)
                      for start, end in code_spans
                      for p in phase1_port_extract.parse_verilog_ports(
                          text[start:end], phase1_port_extract._parse_module_params(text[start:end]))]
        signature = lambda ps: {(p["name"], p["dir"], p["width"]) for p in ps}
        if signature(prose_ports) != signature(code_ports):
            refuse("source has distinct prose and HDL interfaces with ambiguous ownership")
    ports = {}
    for port in phase1_port_extract.extract_ports(text):
        name, width = port.get("name"), port.get("width")
        if name in ports and ports[name] != width:
            refuse("conflicting source port widths")
        if port.get("dir") in ("input", "output", "inout"):
            ports[name] = width
    if not ports:
        refuse("FSM source has no confirmed owned interface")
    return ports


def project(project: Path, content: dict, explicit_edges: list, extracted: dict,
            state_catalog) -> None:
    """Validate all choices, then attach them without replacing source fields."""
    path = project / BEHAVIORAL_REFINEMENT_INPUT
    if not path.exists() and not path.is_symlink():
        return

    def refuse(message):
        raise ValueError("BEHAVIORAL_REFINEMENT_REFUSED: " + message)

    parent = project
    for part in Path(BEHAVIORAL_REFINEMENT_INPUT).parts:
        parent = parent / part
        if parent.is_symlink():
            refuse("author input must not be a symlink")
    # Load this plugin's existing schema without changing process import paths.
    key = "_phase1_behavioral_fact_schema"
    schema = sys.modules.get(key)
    if schema is None:
        spec = importlib.util.spec_from_file_location(
            key, Path(__file__).resolve().parent.parent /
            "tools/phase1_engine/schema.py")
        schema = importlib.util.module_from_spec(spec)
        sys.modules[key] = schema
        spec.loader.exec_module(schema)
    try:
        raw = path.read_bytes()
        graph = schema.FactGraph.from_dict(yaml.safe_load(raw.decode("utf-8")))
    except Exception as exc:
        refuse(f"invalid FactGraph v1: {exc}")
    if len(graph.facts) != 1:
        refuse("exactly one L6.fsm_transitions fact is required")
    fact = graph.facts[0]
    if fact.path != "L6.fsm_transitions" or fact.views != ["L6"]:
        refuse("only the L6.fsm_transitions projection is supported")
    prov = fact.provenance
    if (prov.source != "inferred" or not isinstance(prov.origin, str)
            or not prov.origin.strip() or not isinstance(prov.reasoning, str)
            or not prov.reasoning.strip()
            or prov.reasoning == "extracted from user's natural-language description"):
        refuse("inferred author provenance and explicit reasoning are required")
    meta = graph.metadata
    assumptions = meta.get("assumptions")
    if (meta.get("status") != "proposed" or not isinstance(assumptions, list)
            or not assumptions or any(not isinstance(a, str) or not a.strip()
                                      for a in assumptions)):
        refuse("proposed status and nonempty assumptions are required")
    report = input_text_report(project)
    if (not report["text"] or report["truncated"]
            or any(s["reason"] != SKIP_ORACLE_PATH for s in report["files_skipped"])):
        refuse("a complete readable design-input text corpus is required")
    source_sha = hashlib.sha256(report["text"].encode()).hexdigest()
    if meta.get("source_text_sha256") != source_sha:
        refuse("source_text_sha256 does not match current raw design input")
    machines = content["fsm_machines"]
    states = content["fsm_states"]
    if len(machines) != 1 or len(states) < 2:
        refuse("one source-declared FSM with at least two states is required")
    machine = machines[0]
    names = [s["name"] for s in states]
    if (len(set(names)) != len(names) or set(names) != set(machine["states"])
            or meta.get("fsm_machine") != machine["machine_id"]
            or graph.ic_name != content["ic_name"]):
        refuse("proposal must address the exact current source machine and states")
    if explicit_edges or any(s.get("transitions") for s in states):
        refuse("explicit source transitions cannot be supplemented or overwritten")
    ports = _owned_ports(extracted, machine, refuse, state_catalog)
    rows = fact.value
    if not isinstance(rows, list) or not rows:
        refuse("transitions must be a nonempty typed row list")
    by_state = {name: [] for name in names}
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            refuse("transition must be an object")
        src, dst = row.get("from"), row.get("to")
        if not isinstance(src, str) or not isinstance(dst, str) \
                or src not in by_state or dst not in by_state:
            refuse("unknown or dangling state")
        if row.get("default") is True and set(row) == {"from", "to", "default"}:
            signature = (src, "default")
            trigger = "default"
        elif set(row) == {"from", "to", "guard"}:
            guard = row["guard"]
            if not isinstance(guard, dict) or set(guard) != {"port", "op", "value"}:
                refuse("guard must contain only port, op and value")
            port, op, value = guard["port"], guard["op"], guard["value"]
            if not isinstance(port, str) or port not in ports or op not in ("==", "!="):
                refuse("guard requires a known source port and == or !=")
            width = ports[port]
            if (type(width) is not int or width < 1 or type(value) is not int
                    or value < 0 or value.bit_length() > width):
                refuse("guard value must be an in-range unsigned port integer")
            signature = (src, port, op, value)
            trigger = f"{port} {op} {value}"
        else:
            refuse("unsupported transition fields or foreign machine")
        if signature in seen:
            refuse("duplicate guard or default")
        seen.add(signature)
        edge = copy.deepcopy(row)
        edge.update(trigger=trigger, provenance={
            "source": "inferred", "status": "proposed", "fact_uuid": fact.uuid})
        by_state[src].append(edge)
    for name, edges in by_state.items():
        if not edges or edges[-1].get("default") is not True \
                or sum(e.get("default") is True for e in edges) != 1:
            refuse(f"state {name!r} needs exactly one final default")
    # Commit only after all checks. No source_literal or extraction evidence
    # is fabricated, and no original state, encoding or explicit field changes.
    for state in states:
        state["transitions"] = by_state[state["name"]]
    content["fsm_transitions"] = [edge for name in names for edge in by_state[name]]
    content["behavioral_refinement"] = {
        "status": "proposed", "source": "inferred",
        "author_input": BEHAVIORAL_REFINEMENT_INPUT,
        "author_input_sha256": hashlib.sha256(raw).hexdigest(),
        "source_text_sha256": source_sha, "fsm_machine": machine["machine_id"],
        "fact_uuid": fact.uuid, "origin": prov.origin, "reasoning": prov.reasoning,
        "assumptions": list(assumptions),
        "guard_evaluation": "per-state ordered first match; final default otherwise",
        "validation_scope": "typed guards and complete state defaults only",
        "behavioral_implementation": "NOT_MEASURED",
    }
