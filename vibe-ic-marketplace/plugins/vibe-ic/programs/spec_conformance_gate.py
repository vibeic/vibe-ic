#!/usr/bin/env python3
r"""spec_conformance_gate.py — does this RTL conform to the spec we extracted?

THE PROGRAM GATE, general. Given a spec (whatever produced it) and a candidate
RTL, build the set of facts the RTL MUST satisfy and check it. A violation is a
CONCRETE, fixable reason, which is what lets a re-author converge instead of
guess.

§ 4.05 IS THE LOAD-BEARING PART. The gate enforces ONLY facts the extractor
actually recovered. A field the extractor did not recover is OMITTED from the
gate, not defaulted — so a parameterised-width port is never required to match a
literal width, and a structure nobody extracted is never required to appear.
A gate that demands what was never stated rejects correct work.

WHY IT LIVES HERE. This was inside `cvdp_solve_pipeline`, reachable only by
importing a benchmark's pipeline, and its record-shaped entry point
(`gate_check(record, rtl)`) is two lines: extract the spec from a record, then
call this. Everything else — six functions, none of which touches a record field
— is general conformance checking that any spec-bearing caller wants. The
benchmark keeps the two lines; the machinery moves here.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


_MODULE_HEADER_RE = re.compile(
    r"\bmodule\s+(\w+)\s*(?:#\s*\((?P<params>.*?)\)\s*)?\((?P<ports>.*?)\)\s*;",
    re.S)


def _parse_candidate_header(rtl: str) -> Optional[Tuple[str, List[dict], str, str]]:
    """(module_name, ports[{name,dir,width}], params_text, ports_text) from the
    candidate's FIRST module header, or None if no parseable header. Header-only
    interface parse; widths from a `[hi:lo]` range (else 1)."""
    m = _MODULE_HEADER_RE.search(rtl or "")
    if not m:
        return None
    name = m.group(1)
    params_text = m.group("params") or ""
    ports_text = m.group("ports") or ""
    ports: List[dict] = []
    for pm in re.finditer(
            # the type keyword needs a trailing \b so `reg`/`wire`/`logic` match
            # ONLY the standalone keyword and never the prefix of a port NAME like
            # `registers` / `wire_sel` / `logic_out` (a §4.05 false-reject bug:
            # `(?:reg)?` greedily ate the `reg` of `registers`, leaving `isters`).
            r"\b(input|output|inout)\b\s+(?:(?:wire|reg|logic)\b\s*)?(?:signed\b\s*)?"
            r"(?:\[\s*([^\]:]+)\s*:\s*([^\]]+)\s*\]\s*)?(\w+)", ports_text):
        d, hi, lo, pname = pm.groups()
        w = _range_width(hi, lo)
        ports.append({"name": pname, "dir": d, "width": w})
    return name, ports, params_text, ports_text


def _range_width(hi: Optional[str], lo: Optional[str]) -> Optional[int]:
    """Bit-width of a `[hi:lo]` range when BOTH bounds are integer literals; None
    for a parameter-expression range (`[N-1:0]`) — an unknown-but-present width,
    which the gate treats as 'do not enforce an exact width' (§4.05: never reject
    a parameterized port for not matching a literal width)."""
    if hi is None or lo is None:
        return 1
    try:
        return abs(int(hi.strip()) - int(lo.strip())) + 1
    except ValueError:
        return None


def _struct_key(item) -> Optional[str]:
    """A structural item's identifying name/symbol token, for representation
    checks. Tolerant of the various extractor item shapes (dict with name/symbol/
    state/mode/label, or a bare string)."""
    if isinstance(item, str):
        return item.strip() or None
    if isinstance(item, dict):
        for k in ("name", "symbol", "state", "mode", "label", "field", "reg"):
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _token_represented(rtl: str, tok: str) -> bool:
    """True iff `tok` appears as a Verilog identifier (word-boundary, case-
    sensitive) in the candidate. A structural name the extractor recovered (a
    mode/state/register) must surface as an identifier — a localparam, an enum
    label, a state constant, a reg name. We do NOT require a particular role, only
    that the AI represented the named structure (§4.05: representation, not a
    prescribed encoding)."""
    if not tok:
        return True
    return re.search(rf"\b{re.escape(tok)}\b", rtl) is not None


def build_gate(spec: dict) -> dict:
    """Distill the extracted spec into the CONFORMANCE GATE — the set of facts an
    AI output MUST satisfy. Every entry is anchored to a fact the extractor
    RECOVERED; nothing un-extracted is demanded (§4.05).

    Gate shape:
      module_name : str|None                  the harness TOPLEVEL the TB binds
      ports       : [{name,dir,width}]         every placed interface port
      params      : [PARAM, ...]               stated config parameters (presence)
      structures  : {register_names, enum_modes, fsm_states, fsm_transitions,
                     worked_examples}          counts/keys the AI must REPRESENT
    A field is OMITTED (→ not enforced) when the extractor did not recover it.
    """
    spec = spec or {}
    iface = spec.get("interface") or []
    # A port whose width was resolved from a PARAMETER EXPRESSION (`[DATA_WIDTH-1:0]`,
    # `N*IN_WIDTH`, `$clog2(D)`) has a width that DEPENDS ON THE HARNESS PARAMETER
    # OVERRIDE — its resolved default is for completeness/display only and must NOT
    # be enforced as a hard literal: a correct candidate that writes the
    # harness-driven width (or the param-expression itself) would otherwise be
    # false-rejected (§4.05, Step-2.7). We carry width=None for such ports so the
    # gate enforces presence + direction but skips the literal-width check.
    _PARAM_EXPR_SOURCES = {"param_expression_width", "param_override_width"}
    ports = [{"name": p.get("name"), "dir": p.get("dir"),
              "width": None if p.get("source") in _PARAM_EXPR_SOURCES else p.get("width")}
             for p in iface if p.get("name")]

    structures = spec.get("structures") or {}
    reg = structures.get("register_map") or []
    enums = structures.get("enum_modes") or []
    fsm = structures.get("fsm") or {}
    fsm_states = fsm.get("states") or []
    fsm_trans = fsm.get("transitions") or []
    worked = structures.get("worked_examples") or []

    # parameter NAMES the AI must declare (presence only — the value is the AI's).
    # PROMPT-declared parameters ONLY (§4.05 compliance): the hidden cocotb config-
    # param set is OFF-LIMITS oracle and is never unioned in. (params is carried for
    # DIAGNOSIS only — gate_check_spec never produces a param violation.)
    param_names = sorted(set(spec.get("params", {}).keys()))

    return {
        "module_name": spec.get("module_name"),
        "ports": ports,
        "params": param_names,
        "structures": {
            "register_names": [_struct_key(r) for r in reg if _struct_key(r)],
            "enum_modes": [_struct_key(e) for e in enums if _struct_key(e)],
            "fsm_states": [_struct_key(s) for s in fsm_states if _struct_key(s)],
            "fsm_transitions": len(fsm_trans),
            "worked_examples": len(worked),
        },
        # carried for diagnosis only; gate_check enforces the fields above.
        "completeness": spec.get("completeness"),
    }


def gate_check_spec(gate: dict, candidate_rtl: str) -> dict:
    """gate_check against an ALREADY-built gate (lets a caller reuse solve()'s
    gate without re-extracting). Same conformance rules + §4.05 guarantees."""
    violations: List[dict] = []
    gate = gate or {}

    parsed = _parse_candidate_header(candidate_rtl or "")
    if parsed is None:
        return {"pass": False, "violations": [{
            "kind": "no_module", "detail": "candidate has no parseable module header"}]}
    mod_name, cand_ports, params_text, _ports_text = parsed

    # (a) module name — must equal the harness TOPLEVEL (only when the spec has one)
    want_name = gate.get("module_name")
    if want_name and mod_name != want_name:
        violations.append({
            "kind": "module_name", "detail":
            f"module name `{mod_name}` != required TOPLEVEL `{want_name}`"})

    cand_by_name = {p["name"]: p for p in cand_ports}

    # (b) interface — every SPEC port must be present, same direction, and (when
    #     the spec resolved a literal width) the same width. §4.05: a port the
    #     spec did NOT carry is NOT required (no false-reject for extra ports the
    #     AI legitimately adds, e.g. an unlisted clk the harness also drives).
    for sp in gate.get("ports", []):
        nm = sp.get("name")
        cp = cand_by_name.get(nm)
        if cp is None:
            violations.append({
                "kind": "missing_port",
                "detail": f"required port `{nm}` ({sp.get('dir')}) absent from candidate"})
            continue
        if sp.get("dir") and cp.get("dir") and sp["dir"] != cp["dir"]:
            violations.append({
                "kind": "port_dir",
                "detail": f"port `{nm}` dir `{cp['dir']}` != spec `{sp['dir']}`"})
        sw, cw = sp.get("width"), cp.get("width")
        # enforce width ONLY when BOTH sides are known integer widths. If the spec
        # width is unknown (param-expression) OR the candidate width is a param
        # expression, the width is NOT enforced (§4.05 — no false-reject).
        if isinstance(sw, int) and isinstance(cw, int) and sw != cw:
            violations.append({
                "kind": "port_width",
                "detail": f"port `{nm}` width {cw} != spec width {sw}"})

    # (c) params — NOT a hard conformance check. Parameter PRESENCE cannot be
    #     reliably enforced without false-rejecting a correct answer (§4.05,
    #     Step-2.7): the extracted `params` list mixes genuine harness-driven
    #     parameters (DATA_WIDTH) with prose nouns that are NOT module parameters
    #     (`latency` = a cycle count, `poly` = a CRC polynomial value, lowercase
    #     `width`/`depth`) and even bus PORTS (PADDR/HRDATA) — and even a real
    #     parameter may legitimately be a localparam, hardcoded, or renamed. The
    #     harness binds parameter overrides at elaboration time; the load-bearing
    #     gate is the interface (ports) + structures. `gate["params"]` is therefore
    #     carried for DIAGNOSIS only and never produces a violation.

    # (d) structures — each enumerated mode / FSM state / register the extractor
    #     recovered must be REPRESENTED as a token somewhere in the candidate RTL
    #     (a localparam/enum name, a state label, a register identifier). §4.05:
    #     ONLY structures the extractor recovered are demanded; a representation is
    #     satisfied by the token appearing as a Verilog identifier anywhere.
    structures = gate.get("structures") or {}
    body = candidate_rtl or ""
    for kind, key in (("enum_mode", "enum_modes"),
                      ("fsm_state", "fsm_states"),
                      ("register", "register_names")):
        for tok in structures.get(key, []):
            if not _token_represented(body, tok):
                violations.append({
                    "kind": f"missing_{kind}",
                    "detail": f"{kind} `{tok}` from the spec is not represented in the candidate"})

    return {"pass": not violations, "violations": violations}
