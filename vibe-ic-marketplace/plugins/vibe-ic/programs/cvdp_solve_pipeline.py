#!/usr/bin/env python3
"""cvdp_solve_pipeline.py — the CVDP TIER-1→3 AUTHORING-GATE PIPELINE.

GOAL (owner directive 2026-06-23): make the AI's CVDP solve STABLE by enforcing
the PROGRAM-EXTRACTED spec on every problem. This realizes the owner's 5-tier
model:

  Tier 1  program-solve (DETERMINISTIC). The atomic bridge emits correct RTL with
          no AI in the loop — the score for these is fixed by construction.
  Tier 2  AI-calls-extractor-then-program-emits. (Same machinery as Tier 1 from
          this pipeline's POV — a record the bridge solves is Tier 1; this label
          is reserved for the extractor-assisted emit path the bridge already
          composes internally, so the pipeline never needs to invent a Tier-2
          distinct from Tier-1's deterministic emit.)
  Tier 3  AI-GENERATES + PROGRAM GATE rejects any output that violates the
          extracted spec. The spec the AI must satisfy (exact module name, exact
          interface, every stated param + structure) is BUILT HERE as a
          CONFORMANCE GATE, and `gate_check` REJECTS a drifting AI output so the
          score is stable+high. This is the STABILIZER: a correct AI solve passes;
          a spec-violating one is caught and would be re-authored.
  Tier 4  too-incomplete to gate meaningfully AND no genre convention applies —
          the gate cannot pin the output, so we do NOT pretend to stabilize it.
  Tier 5  genuine FLOOR — the spec is self-contradictory / the harness is broken;
          cited with evidence.

The product is NOT new RTL authoring — it is the COMPOSITION of three shipped,
unmodified programs into ONE classify+gate layer:

  * cvdp_atomic_bridge.solve        — Tier-1 deterministic emit (read-only import)
  * cvdp_complete_extract.extract   — the COMPLETE spec JSON + completeness verdict
  * the 14 cvdp_*_synth family solvers — reached THROUGH the bridge (not here)

and it plugs in alongside benchmark/cvdp_gate.py: the gate handles record IO +
scoring; THIS layer decides, per record, whether the score is deterministic
(Tier 1), AI-but-gated (Tier 3), or honestly un-stabilizable (Tier 4/5), and
supplies the `gate_check` the Tier-3 author is held to.

§4.05 NO-LEAK / NO-CHEAT (binding, the load-bearing rule):
  * The gate ONLY enforces facts that ARE in the extracted spec. It NEVER demands
    an unstated fact — doing so would FALSE-REJECT a correct AI solve (the worst
    possible failure of a stabilizer). Concretely: a port the spec does not carry
    is not required; a width the spec did not resolve is not checked; an enum /
    FSM / register the extractor did not recover is not demanded.
  * The golden/reference RTL is NEVER read. Tier classification + the gate spec
    come ONLY from the prompt + the cocotb harness interface (both submitter-
    visible). `gate_check` parses the CANDIDATE's module HEADER + body structure,
    never the reference.
  * A candidate RTL whose module/interface/param/structure DRIFTS from the
    extracted spec is REJECTED with a concrete, fixable violation reason.

chip-AGNOSTIC: every decision keys on STRUCTURE (the extracted spec shape +
generic Verilog grammar), never on a design name, problem id, or SKU literal.

Public API
    solve(record) -> {tier:int, rtl:str|None, spec:dict, gate:dict}
    gate_check(record, candidate_rtl) -> {pass:bool, violations:[...]}
    build_gate(spec) -> dict          # the conformance-gate spec (also in solve())
    classify(record) -> int           # the tier integer alone (cheap)

CLI
    python3 cvdp_solve_pipeline.py --jsonl FILE [--dist] [--id ID] [--demo]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Reused (import, read — NOT modified) — the three shipped pieces we compose.
import cvdp_atomic_bridge as _bridge        # noqa: E402  Tier-1 deterministic emit
import cvdp_complete_extract as _extract     # noqa: E402  complete spec + verdict
import cvdp_context_interface_recover as _ctx_recover  # noqa: E402  input.context header

TIER_PROGRAM = 1   # deterministic bridge emit (no AI)
TIER_AI_EMIT = 2   # a PROGRAM (cvdp_complete_extract) extracted a COMPLETE spec
                   # JSON; the AI authors from that complete spec + the gate. The
                   # most stable AI tier — every testable fact was program-pinned.
TIER_AI_GATED = 3  # AI authors reading the prose; a MEANINGFUL conformance gate
                   # (interface +/- structure) constrains + stabilizes it, but the
                   # extracted spec was not fully COMPLETE.
TIER_UNGATED = 4   # too-incomplete to gate meaningfully + no convention applies
TIER_FLOOR = 5     # genuine floor (spec self-contradictory / harness broken)


# --------------------------------------------------------------------------- #
# (1) build the CONFORMANCE GATE spec from the extracted spec
# --------------------------------------------------------------------------- #
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

    # parameter NAMES the AI must declare (presence only — the value is the AI's,
    # the harness drives the override). Both the prompt-parameter table and the
    # harness config-param set are presence facts the extractor recovered.
    param_names = sorted(set(spec.get("params", {}).keys())
                         | set((spec.get("harness") or {}).get("params") or []))

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


# --------------------------------------------------------------------------- #
# (2) tier classification
# --------------------------------------------------------------------------- #
def _floor_evidence(record: dict, spec: dict) -> Optional[str]:
    """Return a cited reason iff the record is a GENUINE floor — the spec is
    self-contradictory OR the harness is broken — else None. Conservative: a
    floor is asserted ONLY on a STRUCTURAL contradiction we can point at, never
    on mere incompleteness (that is Tier 4)."""
    files = _bridge._harness_files(record)
    tb = _bridge._cocotb_test_text(files)
    env = _bridge._env_text(files)
    # (a) harness broken: a .env that names a MODULE/TOPLEVEL but ships NO cocotb
    #     test for the scorer to run — nothing can ever score.
    if env.strip() and not tb.strip():
        # only a floor if there is genuinely no test file at all in the harness.
        if not any(re.search(r"test_.*\.py$", k) for k in files):
            return "harness broken: .env present but no cocotb test_*.py to score against"
    # (b) self-contradictory interface: the SAME signal is declared with two
    #     DIFFERENT non-control widths in the prompt prose (the AI cannot satisfy
    #     both; the spec contradicts itself).
    prompt = (record.get("input") or {}).get("prompt") or ""
    for name in {p.get("name") for p in ((spec or {}).get("interface") or [])}:
        if not name:
            continue
        widths = set()
        # ONLY count a width that comes from an ACTUAL HDL PORT DECLARATION of
        # `name` — the `input/output/inout` keyword precedes the packed `[hi:lo]`
        # width and the name (optionally separated by a type word like `logic`/
        # `wire`/`reg`/`signed`). A bare `name[hi:lo]` ANYWHERE ELSE is a
        # BIT-SELECT / SLICE of the port, a concatenation literal, or a worked
        # example — NEVER a width declaration — and must not be read as a
        # conflicting width. Counting slices was a false-FLOOR generator: a
        # legitimate 66-bit port sliced as `name[65:64]` (2) and `name[63:0]`
        # (64) looked like "conflicting widths [2, 64]"; an `RRRGGGBB` port
        # sliced `name[7:5]`/`name[1:0]` looked like "[2, 3]". A floor (the
        # spec genuinely contradicts itself) requires TWO real declarations
        # disagreeing — slices/literals/examples cannot manufacture one.
        decl_re = re.compile(
            rf"\b(?:input|output|inout)\b[^;\n,]*?"
            rf"\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*(?:\b\w+\s+)*?{re.escape(name)}\b")
        for m in decl_re.finditer(prompt):
            widths.add(abs(int(m.group(1)) - int(m.group(2))) + 1)
        if len(widths) > 1:
            return (f"self-contradictory spec: port `{name}` declared with "
                    f"conflicting widths {sorted(widths)} in TWO HDL declarations")
    return None


def _augment_gate_with_context(record: dict, gate: dict) -> dict:
    """CONVERGE lever (Tier4 -> Tier3): when prose extraction placed NO interface
    ports, recover the TARGET module's port header from the PROVIDED input.context
    RTL (interface = spec, header-only — see cvdp_context_interface_recover). A
    meaningful interface gate is what separates a stabilizable Tier-3 author from
    an ungated Tier-4 one: it pins port names/dirs/widths so the AI output cannot
    drift on the contract the cocotb harness binds. Returns the gate unchanged
    when it already has ports or nothing is recoverable (§4.05 SKIP)."""
    if gate.get("ports"):
        return gate
    target = gate.get("module_name") or _bridge.toplevel_name(record)
    try:
        recovered = _ctx_recover.recover_interface(record, target)
    except Exception:
        recovered = []
    if not recovered:
        return gate
    gate = dict(gate)
    gate["ports"] = recovered
    gate["ports_source"] = "input_context_header"
    return gate


def classify(record: dict, spec: Optional[dict] = None,
             rtl: Optional[str] = None) -> int:
    """The tier integer for this record (cheap; does not build the full result).
    Pass a pre-computed `spec`/`rtl` to avoid recomputation."""
    if not isinstance(record, dict):
        return TIER_UNGATED
    # Tier 1 — the bridge program-solves it deterministically.
    if rtl is None:
        try:
            rtl = _bridge.solve(record)
        except Exception:
            rtl = None
    if rtl:
        return TIER_PROGRAM

    if spec is None:
        try:
            spec = _extract.extract(record)
        except Exception:
            spec = {}

    # Tier 5 — a genuine floor (cited).
    if _floor_evidence(record, spec):
        return TIER_FLOOR

    gate = _augment_gate_with_context(record, build_gate(spec))
    # A gate is MEANINGFUL when it carries the module name AND a non-empty port
    # set — something the AI output is held to. The interface may come from prose
    # extraction or from the provided input.context header; either way it pins the
    # contract the cocotb harness binds, so the AI cannot drift on it.
    gate_meaningful = bool(gate.get("module_name")) and bool(gate.get("ports"))
    if gate_meaningful:
        # Tier 2 — a PROGRAM extracted a COMPLETE spec (every testable fact
        # pinned). The AI authors from the complete structured spec + gate: the
        # most stable AI tier.
        if (spec or {}).get("completeness") == "COMPLETE":
            return TIER_AI_EMIT
        # Tier 3 — the gate constrains a meaningful interface but the extracted
        # spec was not fully COMPLETE; the AI fills the remaining function from
        # the prose. Stability depends on gate coverage.
        return TIER_AI_GATED

    # Tier 4 — nothing to gate: no interface from prose, no target header in the
    # provided context, and no genre convention pinned a width.
    return TIER_UNGATED


def solve(record: dict) -> dict:
    """The pipeline entry point.

    Returns {tier, rtl, spec, gate}:
      tier=1  rtl is the DETERMINISTIC bridge emit (no AI). gate still supplied.
      tier=2  reserved (the bridge's extractor-assisted emit is folded into t1).
      tier=3  rtl=None — the AI authors; `gate` constrains it and `gate_check`
              REJECTS a drifting output (the stabilizer).
      tier=4  rtl=None — too-incomplete to gate meaningfully; honest non-stable.
      tier=5  rtl=None — genuine floor; gate['floor_reason'] cites the evidence.
    """
    if not isinstance(record, dict):
        return {"tier": TIER_UNGATED, "rtl": None, "spec": {}, "gate": {}}

    # Tier 1 first — deterministic emit short-circuits everything.
    try:
        rtl = _bridge.solve(record)
    except Exception:
        rtl = None

    try:
        spec = _extract.extract(record)
    except Exception:
        spec = {}
    gate = _augment_gate_with_context(record, build_gate(spec))

    if rtl:
        return {"tier": TIER_PROGRAM, "rtl": rtl, "spec": spec, "gate": gate}

    floor = _floor_evidence(record, spec)
    if floor:
        gate = dict(gate)
        gate["floor_reason"] = floor
        return {"tier": TIER_FLOOR, "rtl": None, "spec": spec, "gate": gate}

    tier = classify(record, spec=spec, rtl=None)
    return {"tier": tier, "rtl": None, "spec": spec, "gate": gate}


# --------------------------------------------------------------------------- #
# (3) gate_check — the PROGRAM gate the Tier-3 author is held to
# --------------------------------------------------------------------------- #
# Verilog header parse — module name + its port declarations (ANSI header style,
# the CVDP dataset's form). Header ONLY for the interface; the body is parsed
# separately for structural representation (enum/fsm/register tokens).
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
        return None  # parameter-expression width — width unknown, not a mismatch


def gate_check(record: dict, candidate_rtl: str) -> dict:
    """The Tier-3 PROGRAM GATE. Parse the candidate RTL's module header + body and
    assert it CONFORMS to the extracted spec's conformance gate. A violation is a
    CONCRETE, fixable reason; an AI output that drifts from the spec is REJECTED
    (so re-authoring converges the score). Returns {pass:bool, violations:[...]}.

    §4.05: ONLY enforces facts the extractor recovered. An unstated fact is never
    demanded — a parameterized-width port is not required to match a literal
    width; a structure the extractor did not recover is not required to appear.
    """
    spec = None
    try:
        spec = _extract.extract(record)
    except Exception:
        spec = {}
    gate = build_gate(spec)
    return gate_check_spec(gate, candidate_rtl)


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


# --------------------------------------------------------------------------- #
# CLI — measure the tier distribution over a jsonl
# --------------------------------------------------------------------------- #
def _tier_label(t: int) -> str:
    return {1: "Tier1 (program-solved)", 2: "Tier2 (program COMPLETE-spec + gate)",
            3: "Tier3 (gate-able)", 4: "Tier4 (too-incomplete)",
            5: "Tier5 (floor)"}.get(t, f"Tier{t}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", required=True, help="CVDP code-generation jsonl")
    ap.add_argument("--id", help="classify only this record id (prints tier+gate)")
    ap.add_argument("--dist", action="store_true", help="print the tier distribution")
    ap.add_argument("--demo", action="store_true",
                    help="for the first 3 Tier-3 records, show the gate + a "
                         "reject/accept demo")
    a = ap.parse_args(argv)

    recs = [json.loads(l) for l in open(a.jsonl)]
    if a.id:
        for r in recs:
            if r.get("id") == a.id:
                res = solve(r)
                print(json.dumps({"id": r.get("id"), "tier": res["tier"],
                                  "tier_label": _tier_label(res["tier"]),
                                  "gate": res["gate"]}, indent=2, ensure_ascii=False))
                return 0
        print(f"id not found: {a.id}", file=sys.stderr)
        return 2

    counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    tier_ids: Dict[int, List[str]] = {1: [], 2: [], 3: [], 4: [], 5: []}
    floor_reasons: List[Tuple[str, str]] = []
    for r in recs:
        res = solve(r)
        t = res["tier"]
        counts[t] = counts.get(t, 0) + 1
        tier_ids.setdefault(t, []).append(r.get("id"))
        if t == TIER_FLOOR:
            floor_reasons.append((r.get("id"), res["gate"].get("floor_reason", "")))

    total = len(recs)
    stable = counts[1] + counts[2] + counts[3]
    print(f"TOTAL = {total}")
    for t in (1, 2, 3, 4, 5):
        print(f"  {_tier_label(t):30s} = {counts[t]}")
    print(f"\nSTABLE BASELINE (Tier1 + Tier2 + Tier3) = {stable}  "
          f"({100.0*stable/total:.1f}%)")
    if floor_reasons:
        print("\nTier5 floor evidence:")
        for i, why in floor_reasons:
            print(f"  {i}: {why}")
    if a.demo:
        _print_demos(recs, tier_ids[3][:3])
    return 0


def _print_demos(recs: List[dict], ids: List[str]) -> None:
    by_id = {r.get("id"): r for r in recs}
    for rid in ids:
        rec = by_id.get(rid)
        if not rec:
            continue
        res = solve(rec)
        gate = res["gate"]
        print(f"\n=== Tier-3 demo: {rid} ===")
        print("gate.module_name =", gate.get("module_name"))
        print("gate.ports       =", gate.get("ports"))
        print("gate.params      =", gate.get("params"))
        # build a CORRECT candidate from the gate, and a WRONG one (perturbed).
        good = _synthesize_conformant_rtl(gate)
        bad = _perturb_rtl(good, gate)
        gr = gate_check(rec, good)
        br = gate_check(rec, bad)
        print("ACCEPT conformant RTL :", gr["pass"], gr["violations"][:2])
        print("REJECT wrong RTL      :", br["pass"], [v["detail"] for v in br["violations"][:3]])


def _synthesize_conformant_rtl(gate: dict) -> str:
    """A minimal module header that CONFORMS to the gate (for the demo only — this
    is NOT a solver; it builds a header that satisfies the conformance gate so the
    demo can show ACCEPT)."""
    name = gate.get("module_name") or "TopModule"
    lines = []
    for p in gate.get("ports", []):
        w = p.get("width")
        rng = f"[{w-1}:0] " if isinstance(w, int) and w > 1 else ""
        lines.append(f"  {p['dir']} {rng}{p['name']}")
    params = gate.get("params", [])
    phdr = ""
    if params:
        phdr = " #(" + ", ".join(f"parameter {p} = 1" for p in params) + ")"
    body_struct = []
    for tok in (gate.get("structures", {}).get("enum_modes", [])
                + gate.get("structures", {}).get("fsm_states", [])
                + gate.get("structures", {}).get("register_names", [])):
        body_struct.append(f"  localparam {tok} = 0;")
    return (f"module {name}{phdr} (\n" + ",\n".join(lines) + "\n);\n"
            + "\n".join(body_struct) + "\nendmodule\n")


def _perturb_rtl(good: str, gate: dict) -> str:
    """Deliberately break ONE gate fact (the demo's WRONG candidate): widen the
    first multi-bit port if any, else drop the first structural token, else drop
    a port. Guarantees a concrete violation the gate catches."""
    bad = good
    for p in gate.get("ports", []):
        if isinstance(p.get("width"), int) and p["width"] > 1:
            bad = bad.replace(f"[{p['width']-1}:0] {p['name']}",
                              f"[{p['width']}:0] {p['name']}", 1)  # off-by-one width
            return bad
    # no multi-bit port — drop the first structural token instead.
    for key in ("enum_modes", "fsm_states", "register_names"):
        toks = gate.get("structures", {}).get(key, [])
        if toks:
            return bad.replace(f"  localparam {toks[0]} = 0;\n", "", 1)
    # else drop the first port line.
    for p in gate.get("ports", []):
        w = p.get("width")
        rng = f"[{w-1}:0] " if isinstance(w, int) and w > 1 else ""
        return bad.replace(f"  {p['dir']} {rng}{p['name']}", "  // dropped", 1)
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
