#!/usr/bin/env python3
"""serial_parallel_mul_synth.py — deterministic SOLVER for the SERIAL-PARALLEL
integer-multiplier subset of ``digital_arithmetic_primitive`` (spec -> RTL).

THE AUDITED GAP (capture, IC-expert recovery on the spm x sky130A cell):
``digital_arithmetic_primitive`` ships ``rtl_gen=null`` in ic_class_registry.json
and defers the ENTIRE family to ``fallback_skill=spec-to-rtl`` — i.e. a human/AI
hand-authors the RTL every blind run. But the SERIAL-PARALLEL MULTIPLIER shape
(one PARALLEL N-bit operand ``x`` + one 1-bit SERIAL operand ``y`` + one 1-bit
SERIAL result ``p`` + clk + rst, computing ``p = (x * y) mod 2^N``) is
CLOSED-FORM and its functional golden is ALREADY self-calibrated by
``arith_oracle_tb_gen`` (the serial-parallel declared-function oracle). A closed
function whose oracle the plugin can already CHECK is Bucket A: it can also be
GENERATED. This solver fills exactly that hole so the next blind run recovers the
RTL with NO agent.

FIRES only on the unambiguous serial-parallel MULTIPLIER shape:
  * L2/FRS states a MULTIPLY (``*`` / "multiplier" / "product" / "x × y").
  * top_ports resolve to EXACTLY: one clk, one rst, one input of width>1
    (the parallel multiplicand), one 1-bit input (the serial multiplier),
    one 1-bit output (the serial product).
On ANY ambiguity (operator not multiply, >1 wide operand, missing serial
in/out, missing clk/rst) it returns (None, reason) — a FAIL-CLOSED SKIP. A wrong
multiplier is far worse than an honest skip; the spec-to-rtl fallback still
stands for the shapes this solver declines.

Latency + bit-order are Plugin-chosen (the spec grants R3 freedom) and the
oracle self-calibrates them, so the emitted core uses a clean textbook
carry-save shift-add datapath (LSB-first y / LSB-first p; its latency is the
register-stage count of the emitted serial path, `serial_path_latency`: `yr`
then `pr`, i.e. 2 -- R-0929-SPM-LATENCY). Provenance:
authored from the public/textbook carry-save serial-parallel multiplier
algorithm — NOT copied from any benchmark reference RTL.

CLI:
    python3 serial_parallel_mul_synth.py <project_dir> [--emit]
      (default) prints a JSON verdict {emitted|deferred, reason, ...}
      --emit     writes phase2/stage1/rtl/<top>.v when the shape matches

Exit codes: 0 = emitted (or would emit); 2 = deferred (shape not matched);
            1 = error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _specrtl_common import _detect_reset
from parameter_range_contract import minimums

_CLK_NAMES = {"clk", "clock", "clk_i", "i_clk", "sysclk", "clk_in"}
_RST_NAMES = {"rst", "reset", "rst_n", "reset_n", "rstn", "i_rst",
              "rst_ni", "arst_n", "rst_in", "resetn"}
_MUL_TOKENS = ("multiplier", "multiply", "multiplic", "product", "* y",
               "x*y", "x * y", "x×y", "x × y", "乘法", "乘積", "乘積器",
               "序列乘", "mod 2^")


def _load_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _find_doc(gd: Path, *stems: str) -> Dict[str, Any]:
    for stem in stems:
        f = gd / stem
        if f.exists():
            return _load_json(f)
    return {}


def _is_active_low(rst_name: str, ports_blob: str) -> bool:
    if rst_name.lower().endswith("_n") or rst_name.lower().endswith("n") and \
       rst_name.lower() in {"rstn", "resetn"}:
        return True
    return bool(re.search(r"active[\s_-]*low", ports_blob, re.I))


def _reset_style(gd: Path, rst_name: str) -> Tuple[Optional[Tuple[str, bool]], str]:
    """Read a declared reset style from design input; never choose a mode."""
    modes, polarities = set(), set()
    for stem in ("L2_FRS.json", "L2_ARCHITECTURE.json", "L3_DETAIL_SPEC.json",
                 "L9_INTEGRATION_SPEC.json"):
        doc = _find_doc(gd, stem)
        if not doc:
            continue
        # Read values as prose, not a JSON serialization: JSON escaping erases
        # sentence boundaries and unrelated data signals are not reset modes.
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for child in value.values():
                    yield from strings(child)
            elif isinstance(value, list):
                for child in value:
                    yield from strings(child)

        for text in strings(doc):
            for sentence in re.split(r"[.!?;]+", text):
                if not re.search(r"\b(?:reset|rst|" + re.escape(rst_name) + r")\b", sentence, re.I):
                    continue
                # A negative declaration supplies no positive reset mode.
                sentence = re.sub(
                    r"\b(?:no|not|without)\s+(?:an?\s+)?(?:a?synchronous)\s+reset\b",
                    "", sentence, flags=re.I)
                if not re.search(r"\b(?:reset|rst|" + re.escape(rst_name) + r")\b", sentence, re.I):
                    continue
                mode, polarity, _ = _detect_reset(sentence)
                if polarity:
                    polarities.add(polarity)
                explicit_modes = set()
                # Preserve refusal for two explicit reset qualifications in
                # one sentence; a nearby data qualifier is not a reset claim.
                for match in re.finditer(
                        r"\b(a?synchronous)(?:\s+active[ -](?:high|low))?\s+reset\b",
                        sentence, re.I):
                    explicit_modes.add(match.group(1).lower())
                for match in re.finditer(
                        r"\b(?:reset|" + re.escape(rst_name) +
                        r")\s+(?:is\s+)?(a?synchronous)\b", sentence, re.I):
                    explicit_modes.add(match.group(1).lower())
                if explicit_modes:
                    modes.update(explicit_modes)
                elif mode:
                    modes.add(mode)
        declarations = [doc.get("reset")] + list(doc.get("reset_domains") or [])
        for rst in declarations:
            if not isinstance(rst, dict) or rst.get("name", rst_name) != rst_name:
                continue
            mode = rst.get("mode") or rst.get("sync")
            polarity = str(rst.get("polarity") or "").replace("_", "-")
            if mode in ("synchronous", "asynchronous"):
                modes.add(mode)
            if polarity in ("active-high", "active-low"):
                polarities.add(polarity)
    if len(modes) != 1:
        return None, "reset mode is absent or contradictory; defer to spec-to-rtl AI"
    if len(polarities) > 1:
        return None, "reset polarity is contradictory; defer to spec-to-rtl AI"
    name_low = _is_active_low(rst_name, "")
    if polarities:
        active_low = next(iter(polarities)) == "active-low"
        if name_low and not active_low:
            return None, "reset polarity conflicts with reset port name"
    elif name_low:
        active_low = True
    else:
        return None, "reset polarity is absent; defer to spec-to-rtl AI"
    return (next(iter(modes)), active_low), "reset style declared in design input"


def _port_width_is_wide(port: Dict[str, Any]) -> bool:
    """True when a port is a multi-bit bus (the parallel operand)."""
    w = port.get("width")
    if isinstance(w, int):
        return w > 1
    # symbolic widths like 'size-1:0', 'N-bit(...)', or an explicit msb symbol
    sym = str(port.get("width_symbolic") or "") + " " + str(w or "")
    if re.search(r"-\s*1\s*:\s*0", sym):
        return True
    msb = str(port.get("msb") or "")
    return bool(re.search(r"[A-Za-z]", msb))  # msb is a symbol (e.g. 'size-1')


def _size_param_from(port: Dict[str, Any], default_name: str = "size",
                     default_val: int = 32) -> Tuple[str, int]:
    """Resolve the parametric width name + default for the parallel operand."""
    # v1.11.91 — the STRUCTURED answer first. When phase 1 resolved a symbolic
    # width against the parameters of the same document, it wrote the integer
    # into `width`/`msb` and moved the symbol into `width_resolution`. Reading
    # the prose fields alone would then find no identifier and silently fall
    # back to this function's own `default_name` / `default_val` — a real
    # parameter name replaced by a guess with no diagnostic. The provenance
    # record carries both, already parsed, so no regex is involved.
    res = port.get("width_resolution")
    if isinstance(res, dict):
        ident = res.get("identifier")
        dv = res.get("parameter_default_int")
        if isinstance(ident, str) and ident and isinstance(dv, int) \
                and not isinstance(dv, bool):
            return ident, dv
    for src in (port.get("width_symbolic"), port.get("width"), port.get("msb")):
        m = re.search(r"([A-Za-z_]\w*)\s*-\s*1", str(src or ""))
        if m:
            name = m.group(1)
            dv = default_val
            dm = re.search(r"預設\s*(\d+)|default\s*(\d+)|=\s*(\d+)",
                           str(src or ""))
            if dm:
                dv = int(next(g for g in dm.groups() if g))
            return name, dv
    return default_name, default_val


def extract_serial_parallel_mul_spec(
        project_dir: Path, ic_class: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return (spec, reason). spec is None (FAIL-CLOSED) unless the design is an
    unambiguous serial-parallel multiplier."""
    gd = project_dir / "phase1" / "generated_docs"
    if not gd.exists():
        return None, f"no generated_docs at {gd}"

    l9 = _find_doc(gd, "L9_INTEGRATION_SPEC.json")
    ports: List[Dict[str, Any]] = l9.get("top_ports") or []
    top = l9.get("top_module") or l9.get("ic_name") or project_dir.name
    if not ports:
        return None, "L9 has no top_ports"

    # operator must be MULTIPLY, read from L2/FRS prose (token, never a SKU)
    blob = ""
    for stem in ("L2_FRS.json", "L2_ARCHITECTURE.json", "L1_DATASHEET.json"):
        blob += json.dumps(_find_doc(gd, stem), ensure_ascii=False)
    ports_blob = json.dumps(ports, ensure_ascii=False)
    hay = (blob + ports_blob).lower()
    if not any(tok.lower() in hay for tok in _MUL_TOKENS):
        return None, "no MULTIPLY operator token found in L2/FRS/ports"
    # a stated ADD/SUB/bitwise-only core is NOT this solver's shape
    if re.search(r"\b(adder|subtract|加法器|減法器)\b", hay) and \
       "multipl" not in hay and "乘" not in hay:
        return None, "operator resolves to add/sub, not multiply"

    clk = rst = par = ser_in = ser_out = None
    extra = []
    for p in ports:
        name = str(p.get("name", "")).strip()
        d = str(p.get("direction") or p.get("mode") or "").lower()
        lname = name.lower()
        if lname in _CLK_NAMES:
            clk = name
            continue
        if lname in _RST_NAMES:
            rst = name
            continue
        if d.startswith("in"):
            if _port_width_is_wide(p):
                if par is not None:
                    return None, f"more than one wide input operand ({par},{name})"
                par = (name, p)
            else:
                if ser_in is not None:
                    return None, f"more than one 1-bit serial input ({ser_in},{name})"
                ser_in = name
        elif d.startswith("out"):
            if _port_width_is_wide(p):
                return None, f"result port {name} is a bus; serial-parallel needs a 1-bit serial result"
            if ser_out is not None:
                return None, f"more than one 1-bit serial output ({ser_out},{name})"
            ser_out = name
        else:
            extra.append(name)

    miss = [n for n, v in (("clk", clk), ("rst", rst), ("parallel_operand", par),
                           ("serial_in", ser_in), ("serial_out", ser_out)) if not v]
    if miss:
        return None, f"missing required port role(s): {miss}"

    size_name, size_def = _size_param_from(par[1])
    reset_style, reset_reason = _reset_style(gd, rst)
    if reset_style is None:
        return None, reset_reason
    reset_mode, active_low = reset_style
    # CR-11: a declared legal minimum of the size parameter is an elaboration
    # contract -- a default below it is refused, and emit_rtl guards it.
    bounds = {}
    for stem in ("L1_DATASHEET.json", "L2_FRS.json", "L3_DETAIL_SPEC.json",
                 "L9_INTEGRATION_SPEC.json"):
        for name, low in minimums(
                json.dumps(_find_doc(gd, stem), ensure_ascii=False),
                declared_parameters=(size_name,)).items():
            bounds[name] = max(low, bounds.get(name, low))
    size_min = bounds.get(size_name.lower())
    if size_min is not None and size_def < size_min:
        return None, f"default {size_name}={size_def} violates declared minimum {size_min}"
    spec = {
        "topology": "serial_parallel",
        "operator": "*",
        "top": top,
        "clk": clk,
        "rst": rst,
        "rst_active_low": active_low,
        "reset_mode": reset_mode,
        "parallel": par[0],
        "serial_in": ser_in,
        "serial_out": ser_out,
        "size_param": size_name,
        "size_default": size_def,
        "size_min": size_min,
    }
    declaration = _load_json(project_dir / "plugin_output" / "declaration.json")
    decisions = _load_json(project_dir / "input" / "feature-decisions.json")
    if not isinstance(declaration, dict) or not isinstance(decisions, dict):
        return None, "DFT interface decision/declaration must be an object"
    if declaration.get("dft") is not None or decisions.get("dft") is not None:
        from fault_scan_chain_insert import load_d09_dft_contract
        binding, problems = load_d09_dft_contract(
            project_dir, expected_clock=clk, expected_reset=rst,
            reset_active_low=active_low)
        if binding is None or problems:
            return None, "DFT interface authority is unavailable: " + "; ".join(problems)
        if binding["intent"]["requires_scan"]:
            functional = {clk, rst, par[0], ser_in, ser_out}
            reserved = {
                definition["public"]: "output" if role == "scan_out" else "input"
                for role, definition in binding["intent"]["test_port_def"].items()
            }
            if functional.intersection(reserved):
                return None, "reserved test interface aliases a functional port"
            spec["reserved_test_ports"] = reserved
            spec["dft_intent_binding"] = binding
            spec["preinsert_test_observation"] = {
                "port": binding["intent"]["test_port_def"]["scan_out"]["public"],
                "register": "pr",
                "purpose": "pre_insertion_observation",
            }
    return spec, "serial-parallel multiplier shape matched"


def emit_rtl(spec: Dict[str, Any]) -> str:
    top = spec["top"]
    sz = spec["size_param"]
    szd = spec["size_default"]
    clk, rst = spec["clk"], spec["rst"]
    x, y, p = spec["parallel"], spec["serial_in"], spec["serial_out"]
    reserved = spec.get("reserved_test_ports", {})
    observation = spec.get("preinsert_test_observation")
    observation_assignment = ""
    if reserved:
        intent = spec.get("dft_intent_binding", {}).get("intent", {})
        roles = intent.get("test_port_def", {})
        endpoint = roles.get("scan_out", {}).get("public")
        intended = {
            definition["public"]: "output" if role == "scan_out" else "input"
            for role, definition in roles.items()
        }
        if (intent.get("requires_scan") is not True or reserved != intended
                or not endpoint or reserved.get(endpoint) != "output"
                or observation != {"port": endpoint, "register": "pr",
                                   "purpose": "pre_insertion_observation"}):
            raise ValueError("unapproved pre-insertion product observation")
        observation_assignment = f"    assign {endpoint} = pr;\n"
    elif observation is not None:
        raise ValueError("test observation requires the declared test interface")
    test_ports = "".join(
        f",\n    {direction} wire            {name}"
        for name, direction in reserved.items())
    reservation = ("    // D01-declared test interface; scan_out observes the existing product register.\n"
                   "    // Scan replacement/stitching and shift behavior remain pending.\n") if reserved else ""
    rst_expr = f"!{rst}" if spec["rst_active_low"] else rst
    rst_word = "active-low" if spec["rst_active_low"] else "active-high"
    reset_mode = spec["reset_mode"]
    if reset_mode not in ("synchronous", "asynchronous"):
        raise ValueError("reset mode must be declared")
    sensitivity = f"posedge {clk}"
    if reset_mode == "asynchronous":
        sensitivity += f" or {'negedge' if spec['rst_active_low'] else 'posedge'} {rst}"
    size_min = spec.get("size_min")
    guard = (f'    generate if ({sz} < {size_min}) begin : g_illegal_width\n'
             f'        initial $fatal(1, "{sz} must be >= {size_min}");\n'
             f'    end endgenerate\n\n') if size_min is not None else ''
    return f"""`default_nettype none
//============================================================================
// {top} — serial-parallel (carry-save) integer multiplier
//   AUTO-GENERATED by serial_parallel_mul_synth.py (deterministic, Bucket A).
//----------------------------------------------------------------------------
// Function : {p} = ({x} * {y}) mod 2^{sz}
//   {x} : parallel {sz}-bit multiplicand, held stable during a computation
//   {y} : serial multiplier, one bit per clock, LSB-first
//   {p} : serial product,   one bit per clock, LSB-first
// Reset    : {reset_mode}, {rst_word}
// Algorithm: textbook carry-save shift-add serial-parallel multiplier. Latency
//   and bit-order are Plugin-chosen (spec R3 freedom); the flow's serial-
//   parallel oracle self-calibrates them, so any functionally-correct variant
//   verifies. Provenance: public/textbook algorithm, not any reference RTL.
//============================================================================
module {top} #(
    parameter {sz} = {szd}
) (
    input  wire            {clk},
    input  wire            {rst},
    input  wire [{sz}-1:0] {x},
    input  wire            {y},
    output wire            {p}{test_ports}
);
{reservation}    reg  [{sz}-1:0] s;    // carry-save sum column
    reg  [{sz}-1:0] c;    // carry-save carry column
    reg             yr;   // registered serial multiplier bit
    reg             pr;   // registered serial product bit

{guard}

    wire [{sz}-1:0] m  = {x} & {{{sz}{{yr}}}};               // gated partial product
    wire [{sz}-1:0] so = m ^ s ^ c;                    // carry-save sum
    wire [{sz}-1:0] co = (m & s) | (m & c) | (s & c);  // carry-save carry

    always @({sensitivity}) begin
        if ({rst_expr}) begin
            s  <= {{{sz}{{1'b0}}}};
            c  <= {{{sz}{{1'b0}}}};
            yr <= 1'b0;
            pr <= 1'b0;
        end else begin
            yr <= {y};
            s  <= {{1'b0, so[{sz}-1:1]}};  // shift sum toward next (higher) weight
            c  <= co;                    // carry re-added at same column next cycle
            pr <= so[0];                 // stream settled LSB of this column
        end
    end

    assign {p} = pr;
{observation_assignment}endmodule
`default_nettype wire
"""


_REG_DECL_RE = re.compile(r"^\s*reg\b[^;]*?([A-Za-z_]\w*)\s*;", re.M)
_NB_RE = re.compile(r"\b([A-Za-z_]\w*)\s*<=\s*([^;]+);")
_COMB_RE = re.compile(
    r"^\s*(?:assign|wire\b[^=;]*?)\s*([A-Za-z_]\w*)\s*=\s*([^;]+);", re.M)
_IDENT_RE = re.compile(r"\b[A-Za-z_]\w*\b")


def serial_path_latency(rtl: str, serial_in: str, serial_out: str) -> Optional[int]:
    """Clock cycles from a serial input bit to the output bit it reaches: the
    FEWEST registers on any dependency path from `serial_out` back to
    `serial_in` in the emitted RTL (a nonblocking `<=` is one register stage,
    `assign` / `wire x =` is none). Derived from the RTL this solver emits,
    never restated: on `emit_rtl` the path is y -> yr -> m -> so -> pr -> p,
    two registers, which every oracle framing search measured
    (R-0929-SPM-LATENCY; U5). None when no path exists."""
    regs = set(_REG_DECL_RE.findall(rtl))
    edges: Dict[str, List[Tuple[str, int]]] = {}
    for lhs, rhs in _NB_RE.findall(rtl):
        for ident in _IDENT_RE.findall(rhs):
            edges.setdefault(lhs, []).append((ident, 1 if lhs in regs else 0))
    for lhs, rhs in _COMB_RE.findall(rtl):
        for ident in _IDENT_RE.findall(rhs):
            edges.setdefault(lhs, []).append((ident, 0))
    import heapq
    best = {serial_out: 0}
    heap = [(0, serial_out)]
    while heap:
        cost, node = heapq.heappop(heap)
        if node == serial_in:
            return cost
        if cost > best.get(node, cost):
            continue
        for nxt, w in edges.get(node, ()):
            if cost + w < best.get(nxt, 1 << 30):
                best[nxt] = cost + w
                heapq.heappush(heap, (cost + w, nxt))
    return None


def plugin_declaration(spec: Dict[str, Any]) -> Dict[str, Any]:
    """The L7-required ``plugin_output/declaration.json`` payload for *spec*.

    L7_verification_plan's own ``## 7.0 Plugin Declaration Requirements`` table
    states: "Plugin, before starting RTL design, MUST declare {bit_order,
    reset_polarity, latency_cycles, integer_encoding} in
    ``plugin_output/declaration.json``; the L7 comparison procedure reads this
    file to correctly pair reference outputs." Bit order, encoding and reset
    polarity are this solver's FIXED choices, stated in ``emit_rtl``'s comment
    block ("LSB-first y / LSB-first p"); the latency is counted on the RTL that
    block heads (below) -- none of the four is guessed.

    ``bit_order``   : LSB_first — both the serial multiplier input and the
                     serial product output shift LSB-first (see ``emit_rtl``'s
                     header comment; not chosen here).
    ``reset_polarity``: read from ``spec["rst_active_low"]``, which
                     ``extract_serial_parallel_mul_spec`` already derived from
                     the design's own reset port name — never re-derived here.
    ``latency_cycles``: the register stages between a serial input bit and
                     the product bit it reaches, COUNTED on the RTL
                     ``emit_rtl`` returns (``serial_path_latency``): ``yr``
                     then ``pr``, 2. It used to be the literal 1 ("one
                     register stage (``yr``)"), which missed ``pr``; every
                     oracle framing search measured 2 (R-0929-SPM-LATENCY).
    ``integer_encoding``: unsigned — the algorithm computes
                     ``p = (x * y) mod 2^N``; ``emit_rtl`` declares no signed
                     port and applies no two's-complement handling anywhere.
    """
    return {
        "bit_order": "LSB_first",
        "reset_polarity": "active_low" if spec["rst_active_low"] else "active_high",
        "latency_cycles": serial_path_latency(
            emit_rtl(spec), spec["serial_in"], spec["serial_out"]),
        "latency_cycles_origin": "pre_nba_sample_offset",
        "integer_encoding": "unsigned",
        # Fixed properties of emit_rtl(): every independent operation is
        # re-armed by the synchronous reset branch, one asserted edge clears
        # all state, and x is consumed on every product cycle.
        "transaction_rearm": "clocked_reset",
        "rearm_reset_cycles": 1,
        "parallel_hold": "through_final_product_bit",
    }


def _declared_scenario_populations(project: Path, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Producer-owned populations for L10 consecutive arithmetic scenarios.

    The case identifier is read from the current L10 document and the scenario
    family is classified by the same chip-agnostic parser used by the Step-4
    consumer.  A row saying only "multiple/consecutive transactions" therefore
    gets the smallest real population (two); an explicitly stated larger
    population is preserved.  No case name or benchmark identity is special.
    """
    l10 = project / "phase1" / "generated_docs" / "L10_TEST_CASES.json"
    try:
        document = json.loads(l10.read_text())
    except (OSError, ValueError):
        return {}
    cases = document.get("test_cases") if isinstance(document, dict) else None
    if not isinstance(cases, list):
        return {}
    from arith_oracle_tb_gen import (_arithmetic_scenario_intent,
                                     declared_vector_population,
                                     MAX_CASE_VECTORS)
    scenarios: Dict[str, Any] = {}
    operands = (spec["parallel"], spec["serial_in"])
    for case in cases:
        if not isinstance(case, dict):
            continue
        intent = _arithmetic_scenario_intent(case, operands)
        if not intent["consecutive_transactions"]:
            continue
        case_id = case.get("name") or case.get("id")
        if not isinstance(case_id, str) or not case_id:
            continue
        count = declared_vector_population(intent["case"]) or 2
        if type(count) is int and 2 <= count <= MAX_CASE_VECTORS:
            scenarios[case_id] = {"transaction_count": count}
    return ({"verification_stimuli": {"arithmetic_scenarios": scenarios}}
            if scenarios else {})


def _merge_scenario_populations(prior: Dict[str, Any],
                                produced: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Fill producer populations without overwriting compatible author input."""
    if not produced:
        return prior, []
    merged = dict(prior)
    prior_stimuli = prior.get("verification_stimuli", {})
    if not isinstance(prior_stimuli, dict):
        return merged, ["verification_stimuli"]
    stimuli = dict(prior_stimuli)
    prior_scenarios = stimuli.get("arithmetic_scenarios", {})
    if not isinstance(prior_scenarios, dict):
        return merged, ["verification_stimuli.arithmetic_scenarios"]
    scenarios = dict(prior_scenarios)
    conflicts: List[str] = []
    generated = produced["verification_stimuli"]["arithmetic_scenarios"]
    for case_id, choice in generated.items():
        existing = scenarios.get(case_id)
        if existing is None:
            scenarios[case_id] = choice
            continue
        count = existing.get("transaction_count") if isinstance(existing, dict) else None
        if type(count) is not int or count < choice["transaction_count"]:
            conflicts.append(
                f"verification_stimuli.arithmetic_scenarios.{case_id}.transaction_count")
    stimuli["arithmetic_scenarios"] = scenarios
    merged["verification_stimuli"] = stimuli
    return merged, conflicts


def planned_declaration(project: Path, spec: Dict[str, Any]) -> Tuple[dict, Optional[dict]]:
    """Pure author-preserving plan shared with the normal emit/refresh writer."""
    source_decl = project / "plugin_output/declaration.json"
    declaration = plugin_declaration(spec)
    prior_declaration = None
    populations = _declared_scenario_populations(project, spec)
    if source_decl.exists():
        try:
            prior = json.loads(source_decl.read_text())
        except (OSError, ValueError) as exc:
            raise ValueError(f"existing declaration is unreadable: {exc}") from exc
        if not isinstance(prior, dict):
            raise ValueError("existing declaration is not an object")
        prior_declaration = prior
        expected = dict(declaration, size_param=spec["size_default"])
        conflicts = [name for name, value in expected.items()
                     if name not in ("latency_cycles", "latency_cycles_origin")
                     and name in prior and (type(prior[name]) is not type(value)
                                           or prior[name] != value)]
        if "latency_cycles" in prior:
            from arith_oracle_tb_gen import settled_serial_latency, SERIAL_LATENCY_ORIGIN
            before = (settled_serial_latency(prior["latency_cycles"],
                prior.get("latency_cycles_origin", SERIAL_LATENCY_ORIGIN))
                if type(prior["latency_cycles"]) is int else None)
            produced = settled_serial_latency(declaration["latency_cycles"],
                declaration["latency_cycles_origin"])
            if before is None or before != produced:
                conflicts.append("latency_cycles")
            # An equivalent stated window does not authorize rewriting
            # the author's integer or explicitly selected origin.
            declaration["latency_cycles"] = prior["latency_cycles"]
            if "latency_cycles_origin" in prior:
                declaration["latency_cycles_origin"] = prior["latency_cycles_origin"]
            else:
                declaration.pop("latency_cycles_origin", None)
        prior, population_conflicts = _merge_scenario_populations(
            prior, populations)
        conflicts.extend(population_conflicts)
        if conflicts:
            raise ValueError("existing declaration conflicts with serial RTL: "
                                 + ", ".join(conflicts))
        # Compatible author choices outside this solver's four fields
        # remain available to the contract producer and its consumers.
        declaration = dict(prior, **declaration)
    elif populations:
        declaration.update(populations)
    return declaration, prior_declaration


def inspect_current_outputs(project: Path, ic_class: str, *,
                            source_project: Optional[Path] = None) -> Optional[dict]:
    """Read-only current-output plan; no authority, publication or CLI launch.

    Any output needed, conflict or unsupported population declines inspection.
    The owning runner must separately prove D01, provenance and input identity.
    """
    try:
        spec, _reason = extract_serial_parallel_mul_spec(source_project or project, ic_class)
        if spec is None:
            return None
        rtl = project / "phase2/stage1/rtl" / (spec["top"] + ".v")
        import rtl_provenance as provenance
        if provenance.iter_rtl_files(rtl.parent) != [rtl]:
            return None
        if rtl.read_bytes() != emit_rtl(spec).encode("utf-8"):
            return None
        declaration, prior = planned_declaration(project, spec)
        if prior is None or declaration != prior:
            return None
        return {"spec": spec, "rtl": str(rtl.relative_to(project)),
                "declaration": "plugin_output/declaration.json"}
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _d09_requirement_trace(project, body, spec, l9, interface_match, bound):
    """Join reviewed source addresses to existing consuming responsibilities.

    Ownership is determined by L-layer/field contracts, never words in a demand
    ID or sentence. The reviewed expectation's structured fact is matched to
    the exact generator's supported contract; it is not a new prose oracle.
    Later owners remain unmeasured even when their requirements are traceable.
    """
    import hashlib
    import phase1_expert_parse_track as track
    import l_doc_taxonomy as taxonomy
    expectations = body.get("expectations")
    register = body.get("responsibility_register", [])
    if not isinstance(expectations, list) or not isinstance(register, list):
        raise ValueError("D09_EXPECTATION_OWNERSHIP_MISSING: expectations/responsibility_register")
    def index(rows, label):
        result = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in result:
                raise ValueError("D09_OWNERSHIP_POPULATION_INVALID: " + label)
            result[row["id"]] = row
        return result
    expected = index(expectations, "expectations")
    responsibilities = index(register, "responsibility_register")
    demand_ids = {row["id"] for row in body["source_demands"]}
    if (set(expected) | set(responsibilities)) - demand_ids:
        raise ValueError("D09_SOURCE_POPULATION_DIFFERS: expectation/responsibility has no source demand")
    declaration, _ = bound("plugin_output/declaration.json")
    layers = {"L9_INTEGRATION_SPEC": l9}
    layer_hashes = {}
    def layer_doc(name):
        if name not in layers:
            layers[name], layer_hashes[name] = bound("phase1/generated_docs/" + name + ".json")
        return layers[name]
    # These are the current flow's consumer responsibilities (flow109 rows),
    # not claims that any of them ran or that optional work became mandatory.
    later = {
        "L19_CONSTRAINTS_PDK": ("D02", "D03", "D06", "D19", "D21", "D31", "D32", "D49", "D56", "D77", "D80"),
        "L20_DFT_SCAN_TOPOLOGY": ("D23", "D36", "D52"),
        "L21_POWER_INTENT": ("D05", "D15", "D46"),
        "L22_VERIFICATION_PLAN": ("D13", "D14"),
        "L24_SIGNOFF": ("D65", "D66", "D77", "D80", "D81"),
        "L25_RELIABILITY_MISSION_PROFILE": ("D59",),
        "L10_TEST_CASES": ("D13",), "L12_BEHAVIORAL_SEQUENCES": ("D13",),
        "L3_CMD_PROTOCOL": ("D01", "D16"), "L4_REGMAP": ("D01", "D16"),
        "L5_ADI_SPEC": ("A01",), "L11_OTP_CONTENT": ("D01", "D16"),
        "L13_LAB_CALIBRATION": ("D01",), "L23_SECURITY_REQUIREMENTS": ("D17", "D73"),
    }
    registry_path = Path(__file__).resolve().parents[1] / "flow/flow109.json"
    registry = json.loads(registry_path.read_bytes())
    owners = {row["id"]: row["name"] for row in registry["rows"]}
    if any(owner not in owners for group in later.values() for owner in group):
        raise ValueError("D09_OWNER_CONTRACT_UNAVAILABLE")
    polarity = "active-low" if spec["rst_active_low"] else "active-high"
    reset = {"name": spec["rst"], "polarity": polarity, "mode": spec["reset_mode"],
             "clear": "one cycle", "release_value": 0, "ready": "finite N cycle; L7 verification remains D13"}
    # Witnesses contain derived model facts, never copied free-text source
    # descriptions. Otherwise a new RTL demand could prove itself by echo.
    parameters = [{"name": spec["size_param"], "default": spec["size_default"]}]
    ports = [{"name": name, "direction": direction, "width": width} for name, direction, width in (
        (spec["clk"], "input", 1), (spec["rst"], "input", 1),
        (spec["parallel"], "input", spec["size_default"]),
        (spec["serial_in"], "input", 1), (spec["serial_out"], "output", 1))]
    interface = {"top_module": spec["top"], "parameters": parameters,
                 "ports": ports, "roles": {spec["parallel"]: "parallel multiplicand",
                 spec["serial_in"]: "serial multiplier", spec["serial_out"]: "serial product"},
                 "reset": reset}
    parameter = {"parameter": spec["size_param"], "default": spec["size_default"],
                 "minimum": spec.get("size_min")}
    latency = serial_path_latency(emit_rtl(spec), spec["serial_in"], spec["serial_out"])
    # Every witness below is backed by inspect_current_outputs' full byte and
    # population equality, not a token search through arbitrary authored RTL.
    frs_facts = [
        {"operator": "modulo multiplication", "equation": f'{spec["serial_out"]} {spec["parallel"]} {spec["serial_in"]} mod 2 N'},
        {"modulo": "N-bit pattern", "integer_encoding": declaration["integer_encoding"]},
        parameter,
        {"latency": latency, "stream": f'{spec["serial_in"]} bit i to {spec["serial_out"]} cycle'},
        {"bit_order": declaration["bit_order"], "declaration_owner": "L7"},
        {"functional": "selected exact multiplier", "algorithm": "carry-save", "pending": "L9 timing DRC LVS"},
    ]
    architecture = {"selected": "single module with flop state", "top_module": spec["top"],
                    "namespace_check_pending": "PDK std-cell; D10 remains unmeasured", "language": "V"}
    build = {"declaration": {k: v for k, v in declaration.items() if k in set(plugin_declaration(spec)) | {"size_param"}},
             "derived_algorithm": {"multiplier_algorithm": "carry_save_bit_serial"}, "scope": "latency_cycles product cycle size_param",
             "parameters": parameters, "parameter_domain": parameter}
    facts = {("L1_DATASHEET", "ic_name"): [spec["top"]],
             ("L2_FRS", "frs_sections"): frs_facts,
             ("L8_RTL_CONSTANTS", "parameters"): [parameter],
             ("L8_TIMING_WAVEFORM", "clock_and_reset_waveform"): [{"clock": spec["clk"], "edge": "posedge", "reset": reset}],
             ("L9_INTEGRATION_SPEC", "top_module"): [spec["top"]],
             ("L9_INTEGRATION_SPEC", "top_ports"): [interface],
             ("L9_INTEGRATION_SPEC", "parameters"): [parameter],
             ("L9_INTEGRATION_SPEC", "resets"): [reset],
             ("L9_INTEGRATION_SPEC", "integration.reset_boot"): [reset],
             ("L9_INTEGRATION_SPEC", "integration.external_interface"): [interface],
             ("L9_INTEGRATION_SPEC", "integration.architecture"): [architecture],
             ("L9_INTEGRATION_SPEC", "integration.build_declaration"): [build]}
    def contract_relation(leaf, node, scope):
        """Map a source relation to this exact implementation, not every option.

        The caller has already matched the complete emitted RTL and declaration.
        Unknown clauses/tokens remain owed. Mapping records never prove the
        algebra, all parameter values, or the later verifier's result.
        """
        tokens = leaf["expected_tokens"]
        requirement = str(leaf.get("requirement", ""))
        if re.search(r"\b(only|exclusively|must use|shall use)\b", requirement, re.I):
            return None
        def units(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ("content", "evidence", "type") and isinstance(item, str):
                        yield from re.split(r"(?m)^#{1,6} ", item)
                    elif isinstance(item, (dict, list)):
                        yield from units(item)
            elif isinstance(value, list):
                for item in value:
                    yield from units(item)
            elif isinstance(value, str):
                yield from re.split(r"(?m)^#{1,6} ", value)
        contracts = list(units(node))
        contains = lambda text: all(track.phrase_present(t, text) for t in tokens)
        def result(kind, selected, contract, *, verification=False):
            answer = {"relation": kind, "selected": selected,
                "source_contract_sha256": hashlib.sha256(contract.encode()).hexdigest(),
                "source_address": {"layer": leaf["layer"], "field_path": leaf["field_path"]}}
            if verification:
                answer["later_verification"] = {"steps": {k: owners[k] for k in ("D13", "D14")},
                    "status": "NOT_MEASURED", "scope": "mapping is not functional/algebraic/all-width proof"}
            return answer
        choices = re.search(r"\b(?:allow\w*|permit\w*|either|choos\w*|may)\b|可選|任選|自由", requirement, re.I)
        # The existing declaration table separates allowed values from the
        # actual selected build. Compare membership in the same named row.
        if scope == ("L9_INTEGRATION_SPEC", "integration.build_declaration") and (choices or re.search(r"\bprimary\b.*\bor\b.*\bsecondary\b", requirement, re.I)):
            for contract in contracts:
                for line in contract.splitlines():
                    for field in ("bit_order", "integer_encoding", "size_param"):
                        if (re.match(r"\s*\|\s*`?" + field + r"`?\s*\|", line)
                                and field in declaration and contains(line)
                                and track.phrase_present(str(declaration[field]), line)):
                            return result("DECLARED_CHOICE_MEMBERSHIP", {field: declaration[field]}, line)
        if scope == ("L2_FRS", "frs_sections"):
            for contract in contracts:
                if not contains(contract):
                    continue
                # An explicit bit-order choice, not a demand for the opposite
                # order. Both the source and reviewed clause must allow choice.
                if (choices and re.search(r"可選|may choose|either", contract, re.I)
                        and all(t in ("LSB-first", "MSB-first", "LSB_first", "MSB_first", "L7") for t in tokens)
                        and track.phrase_present(declaration["bit_order"].replace("_", "-"), contract)):
                    return result("DECLARED_CHOICE_MEMBERSHIP", {"bit_order": declaration["bit_order"]}, contract, verification=True)
                # The modulo datapath and interpretation declaration are the
                # implementation seam. Signed/unsigned equivalence is left to
                # the real verifier, never asserted as a proof here.
                if (set(tokens) <= {"signed_2c", "unsigned", "modulo"}
                        and "modulo" in tokens and spec["operator"] == "*"
                        and re.search(r"bit.pattern|位元", contract, re.I)
                        and declaration["integer_encoding"] in ("signed_2c", "unsigned")):
                    return result("MODULO_INTERPRETATION_IMPLEMENTATION", {
                        "operator": "*", "width_parameter": spec["size_param"],
                        "integer_encoding": declaration["integer_encoding"]}, contract, verification=True)
                # Parameter domain is mapped to the emitted parameter/guard,
                # not to simultaneous builds of every example width.
                parameters = l9.get("parameters", [])
                for param in parameters:
                    domain = str(param.get("type", ""))
                    minimum = spec.get("size_min")
                    if (param.get("name") == spec["size_param"] and minimum is not None
                            and set(tokens) <= {spec["size_param"], str(spec["size_default"]), str(minimum), *re.findall(r"\d+", domain)}
                            and spec["size_param"] in tokens and re.search(r">=|≥", domain)
                            and re.search(r"every|any|任意", requirement, re.I)):
                        return result("PARAMETERIZED_IMPLEMENTATION_DOMAIN", parameter, domain, verification=True)
        if scope == ("L9_INTEGRATION_SPEC", "integration.architecture"):
            rtl = emit_rtl(spec)
            # The supported generator's exact source population is one module;
            # these conditions are never inferred from an arbitrary RTL prefix.
            module_names = re.findall(r"(?m)^module\s+(\w+)", rtl)
            if module_names != [spec["top"]]:
                return None
            vocabulary = {"single", "module", "sub-module", "FSM", "SV", "V", "port", "input", "stub", "flop", "Top module"}
            if not set(tokens) <= vocabulary:
                return None
            for contract in contracts:
                if not contains(contract):
                    continue
                if (re.search(r"if .*submodule|if .*sub-module|假如.*sub-module", requirement, re.I)
                        and re.search(r"假如.*sub-module|if .*sub-module", contract, re.I)):
                    return result("CONDITIONAL_NONUSE", {"module_names": module_names,
                        "reason": "exact single-module generator has no submodule instances"}, contract)
                if (choices and re.search(r"可選|may choose|permitted", contract, re.I)
                        and (re.search(r"單一.*module|single.*module", contract, re.I)
                             or (set(tokens) <= {"SV", "V"} and re.search(r"SV.*V", contract)))):
                    return result("PERMITTED_IMPLEMENTATION_SELECTION", {"module_names": module_names, "language": "V"}, contract)
        return None

    def address(leaf):
        path = str(leaf.get("field_path") or "").strip('/').replace('/', '.')
        path = '.'.join(part for part in path.split('.') if not part.isdigit())
        return track._normalise_field_path(path, leaf.get("layer"))
    mapped, missing, traces, required = [], [], [], []
    for demand in body["source_demands"]:
        identity = demand["id"]
        parent = expected.get(identity)
        retained = responsibilities.get(identity)
        record = {"id": identity, "source_demand": demand, "targets": [], "verification_status": "NOT_MEASURED"}
        if retained is not None:
            if (retained.get("responsibility_kind") not in ("native_only", "mixed_ic_and_native")
                    or not isinstance(retained.get("normal_owner"), dict)
                    or not retained["normal_owner"].get("role") or not retained["normal_owner"].get("input_authority")):
                missing.append(identity)
                record["reason"] = "existing responsibility_register.normal_owner is missing or malformed"
            else:
                leafs = parent.get("sub_expectations", [parent]) if isinstance(parent, dict) else []
                if not isinstance(leafs, list) or any(not isinstance(leaf, dict) for leaf in leafs):
                    raise ValueError("D09_OWNERSHIP_POPULATION_INVALID: expectation leaves")
                # A field-address spelling cannot turn an RTL-owned layer into
                # native-only. Use the same consuming responsibility as below.
                conflict = any(leaf.get("layer") in {key[0] for key in facts}
                    and not (leaf.get("layer") == "L9_INTEGRATION_SPEC"
                        and address(leaf).startswith("integration.verification"))
                    for leaf in leafs)
                authority = retained["normal_owner"]["input_authority"]
                authority = [authority] if isinstance(authority, str) else authority
                if not isinstance(authority, list) or not authority:
                    raise ValueError("D09_OWNER_AUTHORITY_MISSING: " + identity)
                references = {}
                for relative in authority:
                    if not isinstance(relative, str):
                        raise ValueError("D09_OWNER_AUTHORITY_INVALID: " + identity)
                    path = project / "input" / relative
                    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to((project / "input").resolve()):
                        raise ValueError("D09_OWNER_AUTHORITY_UNAVAILABLE: " + relative)
                    references[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
                flag = retained["normal_owner"].get("selected_flag")
                if flag is not None:
                    manifest, _ = bound("input/flow109-manifest.json")
                    actual = manifest.get("features", {}).get(flag)
                    if flag not in registry["predicate_names"] or type(actual) is not bool or actual is not retained["normal_owner"].get("selection_value"):
                        raise ValueError("D09_OWNER_SELECTION_MISMATCH: " + identity)
                if conflict:
                    required.append(identity)
                    missing.append(identity)
                    record.update(mapping_status="OWNER_CONFLICT", reason="native-only label conflicts with RTL-owned reviewed address")
                else:
                    record.update(normal_owner=retained["normal_owner"], retained_responsibility=retained,
                                  input_authority_sha256=references, mapping_status="RESPONSIBILITY_PRESERVED")
            traces.append(record)
            continue
        if parent is None or parent.get("requirement") != demand["requirement"] or parent.get("evidence") != demand["evidence"]:
            missing.append(identity)
            record["reason"] = "source_demands item lacks identical reviewed expectation ownership"
            traces.append(record)
            continue
        leaves = parent.get("sub_expectations", [parent])
        if not isinstance(leaves, list) or not leaves or any(not isinstance(leaf, dict) for leaf in leaves):
            missing.append(identity); record["reason"] = "empty expectation leaf population"; traces.append(record); continue
        own = False
        complete = True
        for leaf in leaves:
            layer = leaf.get("layer")
            raw_path = leaf.get("field_path")
            path = address(leaf)
            target = {"layer": layer, "field_path": raw_path, "source_expectation": leaf,
                      "verification_status": "NOT_MEASURED"}
            if layer in later or (layer == "L9_INTEGRATION_SPEC" and path.startswith("integration.verification")):
                ids = later.get(layer, ("D13", "D14", "D26", "D65"))
                target.update(normal_owner={"steps": {k: owners[k] for k in ids},
                    "input_authority": layer, "live_consumption": "NOT_CHECKED"},
                    mapping_status="DOWNSTREAM_RESPONSIBILITY_PRESERVED")
                # Read the actual retained layer, bind its bytes, but do not
                # demand that its native tools or unresolved parameters pass.
                layer_doc(layer)
            else:
                own = True
                target["normal_owner"] = {"steps": {"D09": owners["D09"]}, "input_authority": layer}
                tokens = leaf.get("expected_tokens")
                scopes = [key for key in facts if key[0] == layer and
                          (path == key[1] or path.startswith(key[1] + "."))]
                selected = max(scopes, key=lambda key: len(key[1])) if scopes else None
                candidates = facts.get(selected, [])
                node = (track.subtree_at(layer_doc(layer), raw_path, layer)
                        if layer in {key[0] for key in facts} else None)
                if (node is None or not interface_match or not isinstance(tokens, list) or not tokens
                        or track.unaskable_tokens(tokens)):
                    complete = False; target["mapping_status"] = "UNMAPPED_RTL_REQUIREMENT"
                else:
                    witness = next((fact for fact in candidates if all(
                        track.phrase_present(token, json.dumps(node, ensure_ascii=False))
                        and track.phrase_present(token, json.dumps(fact, ensure_ascii=False))
                        for token in tokens)), None)
                    relation = (contract_relation(leaf, node, selected)
                                if witness is None else None)
                    if witness is None and relation is None:
                        complete = False
                        target.update(mapping_status="UNMAPPED_RTL_REQUIREMENT",
                            reason="not established by selected/derived implementation evidence",
                            unestablished_tokens=[token for token in tokens if not any(
                                track.phrase_present(token, json.dumps(fact, ensure_ascii=False)) for fact in candidates)])
                    else:
                        target.update(mapping_status="MAPPED_TO_EXACT_GENERATOR", generator_contract=witness or relation,
                                      rtl={"path": "phase2/stage1/rtl/" + spec["top"] + ".v", "top": spec["top"]})
            record["targets"].append(target)
        if own:
            required.append(identity)
            if complete:
                mapped.append({"id": identity, "targets": record["targets"]})
            else:
                missing.append(identity)
        record["mapping_status"] = ("RTL_MAPPED" if own else "DOWNSTREAM_RESPONSIBILITY_PRESERVED") if complete else "UNMAPPED_RTL_REQUIREMENT"
        traces.append(record)
    if not required:
        raise ValueError("D09_EMPTY_RTL_REQUIREMENT_POPULATION: no validated absence is inferred")
    # Source choices remain available as source contracts. They are deliberately
    # outside `facts`: an allowed alternative is not the implementation chosen.
    option_context = {"used_as_selected_evidence": False,
        "parameter_declarations": l9["parameters"],
        "declaration_contract": l9.get("integration", {}).get("build_declaration", []),
        "architecture_contract": l9.get("integration", {}).get("architecture", [])}
    return {"mapped_items": mapped, "missing_items": missing, "required_rtl_items": required,
            "source_option_context": option_context,
            "responsibility_register": traces, "layer_source_sha256": layer_hashes,
            "ownership_contract": {"registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
                                   "taxonomy_sha256": hashlib.sha256(Path(taxonomy.__file__).read_bytes()).hexdigest()}}


def d09_owned_metrics(project: Path, ic_class: str) -> dict:
    """Check the supported generator's source claims; unknown claims stay owed.

    Every source demand remains in the responsibility trace. Only RTL-owned
    facts enter D09's required set; later execution stays explicitly pending.
    Structured reviewed source addresses bind exact generator witnesses.
    """
    import hashlib
    def bound(relative):
        path = project / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(project.resolve()):
            raise ValueError("D09_SOURCE_UNAVAILABLE: " + relative)
        raw = path.read_bytes()
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("D09_DUPLICATE_SOURCE_KEY: " + key)
                result[key] = value
            return result
        return json.loads(raw, object_pairs_hook=unique), hashlib.sha256(raw).hexdigest()
    body, body_sha = bound("reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json")
    l9, l9_sha = bound("phase1/generated_docs/L9_INTEGRATION_SPEC.json")
    if not isinstance(body, dict) or not isinstance(l9, dict):
        raise ValueError("D09_SOURCE_OBJECT_INVALID")
    demands = body.get("source_demands")
    if (not isinstance(demands, list) or not demands
            or any(not isinstance(d, dict) or not isinstance(d.get("id"), str)
                   or not d["id"] or not isinstance(d.get("requirement"), str)
                   or not d["requirement"].strip() or not isinstance(d.get("evidence"), list)
                   or not d["evidence"] or not all(isinstance(e, str) and e.strip() for e in d["evidence"])
                   for d in demands)
            or len({d["id"] for d in demands}) != len(demands)):
        raise ValueError("D09_REQUIRED_POPULATION_INVALID")
    plan = inspect_current_outputs(project, ic_class)
    if plan is None:
        raise ValueError("D09_SERIAL_SPEC_RTL_OR_DECLARATION_MISMATCH")
    spec = plan["spec"]
    # Complete L9 population, not merely the five roles selected by extraction.
    expected_ports = {spec["clk"]: ("input", 1), spec["rst"]: ("input", 1),
                      spec["parallel"]: ("input", spec["size_default"]),
                      spec["serial_in"]: ("input", 1), spec["serial_out"]: ("output", 1)}
    expected_ports.update({name: (direction, 1) for name, direction in spec.get("reserved_test_ports", {}).items()})
    ports = l9.get("top_ports")
    parameters = l9.get("parameters")
    if not isinstance(ports, list) or not isinstance(parameters, list) or not parameters:
        raise ValueError("D09_L9_INTERFACE_POPULATION_MISSING")
    actual_ports = {}
    for port in ports:
        if not isinstance(port, dict) or port.get("name") in actual_ports:
            raise ValueError("D09_L9_PORT_POPULATION_INVALID")
        name = port.get("name")
        direction = port.get("direction") or port.get("mode")
        width = port.get("width")
        if not isinstance(name, str) or direction not in ("input", "output", "inout") or type(width) is not int or width < 1:
            raise ValueError("D09_L9_PORT_POPULATION_INVALID")
        actual_ports[name] = (direction, width)
    actual_parameters = {}
    for parameter in parameters:
        if not isinstance(parameter, dict) or not isinstance(parameter.get("name"), str) or parameter["name"] in actual_parameters:
            raise ValueError("D09_L9_PARAMETER_POPULATION_INVALID")
        value = parameter.get("default")
        if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
            raise ValueError("D09_L9_PARAMETER_DEFAULT_UNSUPPORTED")
        actual_parameters[parameter["name"]] = int(value)
    interface_match = (actual_ports == expected_ports
                       and actual_parameters == {spec["size_param"]: spec["size_default"]})
    trace = _d09_requirement_trace(project, body, spec, l9, interface_match, bound)
    mapped, missing = trace["mapped_items"], trace["missing_items"]
    return {"schema": "vibeic.d09.owned-metrics.v1",
            "source_demands": demands, **trace,
            "rtl_requirement_mapping": "NOT_MEASURED" if missing else "PASS",
            "declared_ports_parameters": "PASS" if interface_match else "FAIL",
            "reference_ports": {k: list(v) for k, v in actual_ports.items()}, "reference_parameters": actual_parameters,
            "generator_ports": {k: list(v) for k, v in expected_ports.items()},
            "declared_reference": {"ports": {k: list(v) for k, v in actual_ports.items()},
                                   "parameters": actual_parameters},
            "source": {"expectations_sha256": body_sha, "L9_sha256": l9_sha,
                       "rtl_sha256": hashlib.sha256((project / plan["rtl"]).read_bytes()).hexdigest()},
            "scope": "D09 only; no lint, CDC, simulation or whole-IC credit"}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--ic-class", default="digital_arithmetic_primitive")
    action = ap.add_mutually_exclusive_group()
    action.add_argument("--emit", action="store_true",
                        help="write phase2/stage1/rtl/<top>.v when the shape matches")
    action.add_argument(
        "--refresh-contract", action="store_true",
        help=("refresh plugin_output/declaration.json only when the retained "
              "RTL is byte-identical to this producer's current output"))
    ap.add_argument("--output-project", type=Path,
                    help="private output workspace; authority stays with the source project")
    a = ap.parse_args(argv)
    source_project = Path(a.project).resolve()
    proj = a.output_project.resolve() if a.output_project else source_project
    spec, reason = extract_serial_parallel_mul_spec(source_project, a.ic_class)
    if spec is None:
        print(json.dumps({"verdict": "DEFER", "reason": reason}))
        return 2
    rtl = emit_rtl(spec)
    out = {"verdict": "EMIT", "reason": reason, "top": spec["top"],
           "spec": spec}
    if proj != source_project:
        out.update(source_project=str(source_project), output_project=str(proj))
    if a.emit or a.refresh_contract:
        rtl_dir = proj / "phase2" / "stage1" / "rtl"
        rtl_path = rtl_dir / f"{spec['top']}.v"
        if a.refresh_contract:
            try:
                retained = rtl_path.read_bytes()
            except OSError as exc:
                print(json.dumps({"verdict": "DEFER", "reason":
                                  f"retained RTL is unavailable: {exc}"}))
                return 2
            if retained != rtl.encode("utf-8"):
                print(json.dumps({"verdict": "DEFER", "reason":
                                  "retained RTL differs from current deterministic output"}))
                return 2
            if proj != source_project:
                source_rtl = source_project / "phase2/stage1/rtl" / rtl_path.name
                if not source_rtl.is_file() or source_rtl.read_bytes() != retained:
                    print(json.dumps({"verdict": "DEFER", "reason":
                                      "retained source RTL differs from the output workspace"}))
                    return 2
        decl_path = proj / "plugin_output" / "declaration.json"
        source_decl = source_project / "plugin_output" / "declaration.json"
        if proj != source_project:
            from _path_layout import report_path
            source_report = report_path(source_project, "phase1_one_shot.json")
            output_report = report_path(proj, "phase1_one_shot.json")
            if source_report.is_file():
                import ai_signed_judgement as judgement
                current, why = judgement.check(source_project, "D1")
                if not current:
                    print(json.dumps({"verdict": "DEFER", "reason":
                                      "source D01 signed judgement is not current: " + why}))
                    return 2
                out["source_D01_admission"] = {
                    "current": True, "detail": why,
                    "evidence_sha256": judgement.evidence_sha256(source_project, "D1")}
            if output_report.exists() and (not source_report.is_file()
                    or output_report.read_bytes() != source_report.read_bytes()):
                print(json.dumps({"verdict": "DEFER", "reason":
                                  "output workspace has a different D01 owner"}))
                return 2
            if output_report.exists():
                for rel in ("plugin_output/declaration.provenance.json",
                            "reports/audit/ai_judgements/D1.json"):
                    original, copied = source_project / rel, proj / rel
                    if original.is_file() and (not copied.is_file()
                            or original.read_bytes() != copied.read_bytes()):
                        print(json.dumps({"verdict": "DEFER", "reason":
                                          "output authority evidence differs from the source"}))
                        return 2
            if (proj / "phase1/generated_docs").is_dir():
                import ai_signed_judgement as judgement
                source_inputs = {p.relative_to(source_project): p.read_bytes()
                                 for p in judgement.evidence(source_project, "D1")}
                output_inputs = {p.relative_to(proj): p.read_bytes()
                                 for p in judgement.evidence(proj, "D1")}
                for rel in spec.get("dft_intent_binding", {}).get("sources", {}):
                    source_inputs[Path(rel)] = (source_project / rel).read_bytes()
                    target = proj / rel
                    if target.is_file():
                        output_inputs[Path(rel)] = target.read_bytes()
                if source_inputs != output_inputs:
                    print(json.dumps({"verdict": "DEFER", "reason":
                                      "output workspace inputs differ from the source"}))
                    return 2
            if output_report.exists():
                import _delivery_route as route
                if route.report_label(source_project) != route.report_label(proj):
                    print(json.dumps({"verdict": "DEFER", "reason":
                                      "output workspace route differs from the source"}))
                    return 2
            if decl_path.exists() and (not source_decl.is_file()
                    or decl_path.read_bytes() != source_decl.read_bytes()):
                print(json.dumps({"verdict": "DEFER", "reason":
                                  "output declaration differs from the source author"}))
                return 2
        try:
            declaration, prior_declaration = planned_declaration(source_project, spec)
        except ValueError as exc:
            print(json.dumps({"verdict": "DEFER", "reason": str(exc)}))
            return 2
        if a.emit:
            rtl_dir.mkdir(parents=True, exist_ok=True)
            rtl_path.write_text(rtl)
            out["written"] = str(rtl_path)
        else:
            out["validated_rtl"] = str(rtl_path)
        # L7 ## 7.0 requires this declaration BEFORE RTL design starts; written
        # alongside the RTL here because this solver is a single atomic step,
        # not two — a run that crashed between them would leave the design in
        # a state the spec never describes (RTL present, declaration absent).
        decl_dir = proj / "plugin_output"
        decl_dir.mkdir(parents=True, exist_ok=True)
        if prior_declaration == declaration and decl_path.exists():
            # A byte-bound upstream declaration needs no new publication
            # when this producer has no semantic field change to contribute.
            out["declaration_retained"] = str(decl_path)
        elif prior_declaration == declaration:
            decl_path.write_bytes(source_decl.read_bytes())
            out["declaration_written"] = str(decl_path)
        else:
            decl_path.write_text(
                json.dumps(declaration, indent=2, sort_keys=True) + "\n")
            out["declaration_written"] = str(decl_path)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
