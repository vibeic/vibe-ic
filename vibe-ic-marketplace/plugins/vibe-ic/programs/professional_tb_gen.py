#!/usr/bin/env python3
"""professional_tb_gen.py — deterministic PROFESSIONAL testbench generator.

One canonical flow step (Phase-2 "Simulation") that derives a PROFESSIONAL,
high-coverage testbench directly from the Phase-1 design layers (L1/L2/L3/L8/L9/
L16/L17 …). It COMBINES several open-source verification frameworks — cocotb
(TB base), cocotb-coverage (functional coverage + constrained-random),
Verilator/Icarus (sim), + an SVA bind for Verilator/SymbiYosys — rather than
re-inventing them; the plugin's value is the deterministic DERIVATION from the
spec layers.

What it emits (under phase2/stage1/sim_professional/<top>/):
  * tb_<top>.py         — cocotb testbench: clock/reset from L8/L9, a reference
                          model, a SCOREBOARD (incl. a bounded-latency +
                          bit-order-tolerant STREAMING scoreboard that closes the
                          serial/streaming reference-model gap that the legacy
                          arith_oracle_tb_gen DEFERs on — e.g. the spm bit-serial
                          multiplier), functional coverage (cocotb-coverage
                          covergroups derived from the interface + spec), and a
                          constrained-random + directed-corner stimulus loop.
  * <top>_coverage_model.json  — the derived L28 coverage model (covergroups /
                          coverpoints / crosses / code-coverage targets).
  * <top>_assertions.sva       — the derived L29 assertions (reset->known-state,
                          L16 must/shall properties, L17 handshake stability).
  * Makefile            — cocotb Makefile (SIM=icarus default; verilator opt-in).
  * verification_plan.json     — vplan tying coverage goals to spec features.

Reference-model strategy (3-tier, honest): (1) closed-form for arithmetic
primitives (reuses arith_oracle_tb_gen.compute_golden); (2) a streaming
scoreboard that auto-derives latency + bit-order for serial datapaths; (3) a
clearly-marked reference hook for classes with no closed form (dual-track: the
spec-to-refmodel skill / L10 vectors fill it) — never a silent vacuous pass.

chip-AGNOSTIC: no chip / vendor / SKU literal; everything is derived from the
project's own L-docs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _path_layout as _pl  # noqa: E402
import arith_oracle_tb_gen as _aog  # noqa: E402 — reuse port/golden/spec logic


_CLK_NAMES = _aog._CLK_NAMES
_RST_NAMES = _aog._RST_NAMES


def _read_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(errors="ignore"))
    except (OSError, ValueError):
        return None


def _gd(project: Path) -> Path:
    return _pl.generated_docs_dir(project)


def _read_l16(project: Path) -> dict:
    """Load the L16 compliance-properties doc by DISCOVERY, not by one literal.

    SILENT-DEAD-READ FIX. This used to open a single hardcoded
    `L16_COMPLIANCE.json`. Phase 1 writes `L16_COMPLIANCE_PROPERTIES.json`, so
    the read returned {} in every real run and the SVA property-stub
    generator's L16 contribution was ALWAYS empty no matter how good L16 was —
    a dead read that raises no error and shows up in no report. Discovering the
    file means a future rename cannot silently re-open the hole; the
    canonical/longest name wins so `L16_COMPLIANCE_PROPERTIES.json` is
    preferred over any stub alias left behind. Guarded by
    l16_compliance_properties_actionable_check.py (rail 1: CONSUMER_DEAD_READ),
    which parses THIS function's filename literals back out of the source.
    """
    gd = _gd(project)
    d = _read_json(gd / "L16_COMPLIANCE_PROPERTIES.json")
    if d:
        return d
    # Any other L16_*.json, longest (most specific) name first. Discovery, not
    # a second hardcoded alias — a stale alias literal would make the L16 gate
    # warn on every healthy run, and a warning that always fires is noise.
    try:
        cands = sorted(gd.glob("L16_*.json"),
                       key=lambda p: (-len(p.name), p.name))
    except OSError:
        cands = []
    for p in cands:
        d = _read_json(p)
        if d:
            return d
    return {}


def _detect_ic_class(project: Path) -> str:
    for cand in ("ic_class.json",):
        d = _read_json(project / "reports" / cand) or _read_json(project / cand)
        if d:
            c = d.get("ic_class") or d.get("class")
            if c:
                return str(c)
    d = _read_json(_gd(project) / "L9_INTEGRATION_SPEC.json") or {}
    return str((d.get("fields", d) or {}).get("ic_class") or "unknown")


# --------------------------------------------------------------------------
# Interface / clock / reset extraction (L9 primary, L1 pin_table fallback)
# --------------------------------------------------------------------------
def _load_clock_reset(project: Path, ports: List[dict]) -> Dict[str, Any]:
    """Resolve clock (name, edge, period_ns) + reset (name, active_high, sync)
    from L9 (reset_domains/clocks) with an L1/name-heuristic fallback."""
    names = {p["name"].lower(): p["name"] for p in ports}
    clk = next((orig for low, orig in names.items() if low in _CLK_NAMES), None)
    rst = next((orig for low, orig in names.items() if low in _RST_NAMES), None)
    edge = "posedge"
    period_ns = 10.0
    active_high = True
    sync = True
    l9 = _read_json(_gd(project) / "L9_INTEGRATION_SPEC.json") or {}
    f9 = l9.get("fields", l9)
    for c in (f9.get("clocks") or []):
        if isinstance(c, dict) and c.get("name"):
            if not clk:
                clk = c["name"]
            if c.get("edge"):
                edge = str(c["edge"]).lower()
            if c.get("period_ns"):
                try:
                    period_ns = float(c["period_ns"])
                except (TypeError, ValueError):
                    pass
            break
    for r in (f9.get("reset_domains") or f9.get("resets") or []):
        if isinstance(r, dict) and r.get("name"):
            if not rst:
                rst = r["name"]
            pol = str(r.get("polarity") or "").lower()
            if "active_low" in pol or pol == "low" or "n" == str(
                    r.get("name", "")).lower()[-1:]:
                active_high = "active_low" not in pol and not (
                    pol == "low")
            active_high = not ("low" in pol)
            s = str(r.get("sync") or r.get("reset_strategy") or "").lower()
            if "async" in s:
                sync = False
            break
    # name heuristic: *_n / *n reset is active-low
    if rst and re.search(r"(_n|n)$", rst.lower()):
        active_high = False
    return {"clk": clk, "rst": rst, "edge": edge, "period_ns": period_ns,
            "active_high": active_high, "sync": sync}


def _port_width(p: dict) -> int:
    w = p.get("numeric_width")
    if isinstance(w, int) and w >= 1:
        return w
    return 1


_PARAM_DEF_RE = re.compile(
    r"\bparameter\b(?:\s+(?:signed|integer)\b)?(?:\s*\[[^\]]*\])?\s*"
    r"(\w+)\s*=\s*(\d+)", re.IGNORECASE)


def _resolve_tb_width(project: Path, ports: List[dict]) -> int:
    """The DUT is COMPILED at its parameter default, so the TB must drive that
    exact width. Resolve: (1) any concrete numeric port width > 1; else (2) the
    RTL's first `parameter <name> = <int>` default (the parametric operand's
    width, e.g. spm `parameter size = 32`); else (3) 8 (a small default that
    still exercises the datapath)."""
    for p in ports:
        w = p.get("numeric_width")
        if isinstance(w, int) and w > 1:
            return w
    for f in _rtl_files(project, ""):
        try:
            m = _PARAM_DEF_RE.search(Path(f).read_text(errors="ignore"))
        except OSError:
            continue
        if m:
            try:
                v = int(m.group(2))
                if 1 <= v <= 4096:
                    return v
            except ValueError:
                pass
    return 8


# --------------------------------------------------------------------------
# DUT shape classification
# --------------------------------------------------------------------------
def classify_dut(project: Path, ic_class: str
                 ) -> Tuple[Optional[dict], Optional[str]]:
    """Return (shape, reason_if_none). shape kinds:
      * "parallel_arith"  — c = a OP b, all full-width  (closed-form ref)
      * "serial_stream"   — a parallel operand + a 1-bit serial operand + a
                            1-bit serial result (bounded-latency scoreboard)
      * "generic"         — reference hook (dual-track)
    """
    top, ports = _aog._load_top_ports(project)
    if not top or not ports:
        return None, "no usable L9 top ports"
    cr = _load_clock_reset(project, ports)
    data = [p for p in ports
            if p["name"] not in (cr["clk"], cr["rst"])]
    ins = [p for p in data if p["dir"] == "input"]
    outs = [p for p in data if p["dir"] == "output"]
    if not ins or not outs:
        return None, "need >=1 data input and >=1 data output"
    width = _resolve_tb_width(project, ports)

    # arithmetic-primitive family: try the closed-form operator first
    spec, _why = _aog.extract_arith_spec(project, ic_class)
    if spec:
        return ({"kind": "parallel_arith", "top": top, "cr": cr,
                 "spec": spec, "width": width, "ports": ports}, None)

    # serial-streaming multiply/datapath: one parallel operand + a 1-bit serial
    # operand + a 1-bit serial output. This is the shape arith_oracle DEFERs on.
    # A parametric-width operand (e.g. `x [size-1:0]`) is the PARALLEL operand
    # even though its numeric width is unresolved — never mis-read as serial.
    def _is_serial(p: dict) -> bool:
        # explicitly-1-bit port (concrete numeric width == 1)
        return p.get("numeric_width") == 1

    def _is_parallel(p: dict) -> bool:
        # a bus: parametric, OR unresolved width (num_w is None), OR width > 1
        w = p.get("numeric_width")
        return bool(p.get("is_parametric")) or w is None or (
            isinstance(w, int) and w > 1)

    # #140 — a memory-mapped / command-driven register interface (address bus +
    # write/read-data or cs/we) is NOT a serial arithmetic datapath. Route it to
    # the generic dual-track reference hook so a register-file interface is never
    # mis-read as an (x*y) serial-multiply DUT.
    if _is_register_mapped(ins, outs):
        return ({"kind": "generic", "top": top, "cr": cr, "ports": ports,
                 "width": width}, None)

    # #140 width/role sanity: a 1-bit CONTROL/STATUS line (cs/we/error/irq/...)
    # carries no streamed data bits, so it is NEVER a serial data operand or a
    # serial product. Exclude it from the serial candidate sets.
    serial_ins = [p for p in ins
                  if _is_serial(p) and not _is_ctrl_status(p["name"])]
    parallel_ins = [p for p in ins if _is_parallel(p)]
    serial_outs = [p for p in outs
                   if _is_serial(p) and not _is_ctrl_status(p["name"])]
    op = _detect_stream_operator(project, ic_class)
    if (len(parallel_ins) >= 1 and len(serial_ins) >= 1
            and len(serial_outs) >= 1 and op):
        return ({"kind": "serial_stream", "top": top, "cr": cr,
                 "operator": op, "width": width, "ports": ports,
                 "x_port": parallel_ins[0]["name"],
                 "y_port": serial_ins[0]["name"],
                 "p_port": serial_outs[0]["name"]}, None)

    return ({"kind": "generic", "top": top, "cr": cr, "ports": ports,
             "width": width}, None)


# ── #140: register-map / control-status structural guards (chip-AGNOSTIC) ────
def _name_comps(name: str) -> set:
    """Whole-word components of a port name (split on _/digits/non-word)."""
    return {c for c in re.split(r"[_\W0-9]+", name.lower()) if c}


# Control / handshake / status lexicon — a 1-bit port whose name reads as one of
# these lines is a control/status signal, never a serial DATA operand.
_CTRL_STATUS_TOKENS = frozenset({
    # control inputs
    "cs", "csb", "csn", "ncs", "we", "wen", "web", "oe", "oen", "ce", "cen",
    "en", "enable", "start", "go", "req", "request", "stb", "strobe", "sel",
    "select", "wr", "rd", "rw", "wnr", "load", "clear", "clr", "flush",
    "valid", "vld", "ready", "rdy", "ack", "hold", "keep",
    # status outputs
    "error", "err", "fault", "irq", "int", "intr", "done", "busy", "empty",
    "full", "overflow", "underflow", "ovf", "unf", "alert", "warn", "nak",
})

# ic_class families that are register-mapped / command-driven / protocol / crypto
# — never a serial arithmetic datapath, so the stream-operator must not fire.
_NON_DATAPATH_CLASSES = frozenset({
    "crypto_accelerator", "bus_peripheral", "digital_cmd_driven",
    "processor_cpu", "bus_interconnect_protocol", "serial_peripheral_protocol",
    "mixed_signal_otp", "aid_class_half_duplex_single_wire",
})


def _is_ctrl_status(name: str) -> bool:
    """True iff a port name reads as a control/handshake/status line — never a
    serial data operand. Component-aware so `cs_n`, `wr_en`, `parity_err`,
    `data_valid` match while a bare data bus (`din`, `mosi`, `y`) does not."""
    return bool(_name_comps(name) & _CTRL_STATUS_TOKENS)


def _sig_has(ports: List[dict], *tokens: str) -> bool:
    toks = set(tokens)
    return any(_name_comps(p["name"]) & toks for p in ports)


def _sig_has_pair(ports: List[dict], a: str, b: str) -> bool:
    return any({a, b} <= _name_comps(p["name"]) for p in ports)


def _is_register_mapped(ins: List[dict], outs: List[dict]) -> bool:
    """Memory-mapped / command-driven register-file signature: an address bus
    PLUS EITHER a write-data/read-data bus pair OR chip-select + write-enable
    control. Such an interface is a register peripheral, not a serial arithmetic
    datapath (#140). chip-AGNOSTIC / name-based — no chip or vendor literal."""
    allp = ins + outs
    has_addr = _sig_has(allp, "addr", "address", "paddr", "haddr",
                        "awaddr", "araddr")
    if not has_addr:
        return False
    has_wdata = (_sig_has(ins, "wdata", "writedata")
                 or _sig_has_pair(ins, "write", "data"))
    has_rdata = (_sig_has(outs, "rdata", "readdata")
                 or _sig_has_pair(outs, "read", "data"))
    has_cs = _sig_has(ins, "cs", "csb", "csn", "ncs", "chipselect")
    has_we = (_sig_has(ins, "we", "wen", "web", "wr")
              or _sig_has_pair(ins, "write", "enable")
              or _sig_has_pair(ins, "write", "en"))
    return (has_wdata and has_rdata) or (has_cs and has_we)


def _detect_stream_operator(project: Path,
                            ic_class: Optional[str] = None) -> Optional[str]:
    """Operator for a serial datapath from L2/L3 prose (multiply is by far the
    common serial primitive). Returns a python-eval operator token or None.

    §4.05 GENERAL (#140): fires only on genuine arithmetic-datapath evidence — an
    explicit `x*y` / `p = x` datapath equation, a real multiplier / multiply
    (-accumulate) noun-verb (NOT `multiplexer`), or a partial-product term. Bare
    metadata / crypto tokens are EXCLUDED: `product` false-fires on `product_name`
    / `product_family` / "Product & Tapeout Metadata" (L1 metadata), and `mac`
    false-fires on a crypto Message-Authentication-Code — neither is arithmetic.
    Also never fires for a register-mapped / command-driven / crypto ic_class."""
    if ic_class and str(ic_class).strip().lower() in _NON_DATAPATH_CLASSES:
        return None
    txt = _aog._doc_text(project).lower()
    if _STREAM_MUL_RE.search(txt):
        return "*"
    return None


# Genuine arithmetic-datapath evidence (see _detect_stream_operator). The
# `\bmultipl(y|ies|ied|ying)` / `\bmultiplic(and|ation|...)` / `\bmultiplier`
# stems all require a char that `multiplexer` ("multipl"+"e") never has, so a
# clock/data multiplexer never false-fires as a multiply datapath.
_STREAM_MUL_RE = re.compile(
    r"\bx\s*[\*×]\s*y\b"                     # x*y datapath equation
    r"|\by\s*[\*×]\s*x\b"
    r"|\bp\s*=\s*x\b"                             # p = x ...  serial product
    r"|\bpartial\s+products?\b"                   # multiplier micro-arch term
    r"|\bmultiplic(?:and|ation|ations|ative)\b"
    r"|\bmultiplier\b|\bmultipliers\b"
    r"|\bmultipl(?:y|ies|ied|ying)(?:[\s\-‑]*accumulate)?\b",
    re.IGNORECASE)


# --------------------------------------------------------------------------
# L28 coverage model + L29 assertions (derived from the interface + spec)
# --------------------------------------------------------------------------
def _value_bins(width: int) -> List[dict]:
    hi = (1 << width) - 1
    bins = [{"name": "zero", "values": [0]},
            {"name": "one", "values": [1]},
            {"name": "max", "values": [hi]},
            {"name": "mid", "values": [hi >> 1]}]
    if width >= 2:
        bins.append({"name": "msb", "values": [1 << (width - 1)]})
    return bins


def build_coverage_model(shape: dict) -> dict:
    width = int(shape.get("width", 1))
    cps = []
    data_inputs = []
    if shape["kind"] == "parallel_arith":
        sp = shape["spec"]
        for nm in (sp.get("operands") or []):
            data_inputs.append((nm, width))
    elif shape["kind"] == "serial_stream":
        data_inputs.append((shape["x_port"], width))
        data_inputs.append((shape["y_port"], width))  # value fed serially
    else:
        cr = shape["cr"]
        for p in shape["ports"]:
            if p["dir"] == "input" and p["name"] not in (cr["clk"], cr["rst"]):
                data_inputs.append((p["name"], _port_width(p)))
    for nm, w in data_inputs:
        cps.append({"name": f"cp_{nm}", "expr": nm,
                    "bins": _value_bins(w), "at_least": 1})
    crosses = []
    if len(cps) >= 2:
        crosses.append({"name": f"cross_{cps[0]['name']}_{cps[1]['name']}",
                        "points": [cps[0]["name"], cps[1]["name"]]})
    return {
        "doc_id": "L28", "applicability": "APPLICABLE",
        "fields": {
            "covergroups": [{"name": f"cg_{shape['top']}",
                             "coverpoints": cps, "crosses": crosses}],
            "code_coverage_targets": {"line": 100, "toggle": 90, "branch": 100,
                                      "fsm_state": 100, "fsm_transition": 100},
            "closure_policy": {"functional_bins_required_pct": 100},
        },
        "derived_by": "professional_tb_gen",
    }


def build_assertions(project: Path, shape: dict) -> Tuple[str, dict]:
    """Emit an SVA file + an L29 record. Reset->known-output + L16 must/shall
    (best-effort, prose-anchored) + L17 handshake stability."""
    cr = shape["cr"]
    top = shape["top"]
    clk = cr["clk"] or "clk"
    rst = cr["rst"] or "rst"
    rst_expr = rst if cr["active_high"] else f"!{rst}"
    props = []
    lines = [f"// Auto-derived assertions for {top} (professional_tb_gen).",
             f"// clock={clk} edge={cr['edge']} reset={rst} "
             f"active_high={cr['active_high']}",
             f"module {top}_asserts (input {clk}, input {rst});"]
    # reset -> outputs are known (no X) once out of reset
    outs = [p["name"] for p in shape.get("ports", [])
            if p.get("dir") == "output"]
    for o in outs:
        pid = f"A_{o}_known"
        lines.append(
            f"  // {o} must be known (no X) when not in reset")
        # NAMED property + `endproperty`, which is the shape this plugin's
        # OTHER SVA emitter (formal_harness_gen) already produces. The inline
        # form this used to emit —
        #     {pid}: assert property (@(posedge clk) disable iff (r) ...);
        # — is legal SystemVerilog, but `assertion_property_check` looks for a
        # declaration with `\bproperty\s+\w+`, and in `assert property (` the
        # token after `property` is `(`. So the checker could never match this
        # generator's output: EVERY design it wrote assertions for failed
        # NO_PROPERTY_DECL, at any port count, while the same file's
        # ASSERT_COUNT happily reported the assertions it had just refused to
        # see. Two emitters, two shapes, one checker that only knew one.
        lines.append(f"  property {pid}_p;")
        lines.append(f"    @(posedge {clk}) disable iff ({rst_expr}) "
                     f"!$isunknown({o});")
        lines.append(f"  endproperty")
        lines.append(f"  {pid}: assert property ({pid}_p);")
        props.append({"id": pid, "kind": "SVA", "english":
                      f"{o} is known (no X) out of reset",
                      "spec_ref": "L9.reset"})
    # L16 must/shall prose -> advisory property stubs (english kept; formalise
    # via spec-to-assertion skill — never fabricated as a passing SVA)
    l16 = _read_l16(project)
    for pr in (l16.get("properties") or l16.get("fields", {}).get(
            "properties") or [])[:8]:
        if isinstance(pr, dict) and pr.get("english_form"):
            eng = re.sub(r"\s+", " ", str(pr["english_form"]))[:160]
            props.append({"id": f"A_l16_{len(props)}", "kind": "advisory",
                          "english": eng, "spec_ref": "L16"})
            lines.append(f"  // TODO(spec-to-assertion): {eng}")
    lines.append("endmodule")
    l29 = {"doc_id": "L29", "applicability": "APPLICABLE",
           "fields": {"assertions": props}, "derived_by": "professional_tb_gen"}
    return "\n".join(lines) + "\n", l29


# --------------------------------------------------------------------------
# cocotb testbench emission
# --------------------------------------------------------------------------
def _emit_common_header(shape: dict) -> str:
    cr = shape["cr"]
    clk = cr["clk"] or "clk"
    rst = cr["rst"] or "rst"
    half = max(1, int(round(cr["period_ns"] / 2)))
    rst_on = "1" if cr["active_high"] else "0"
    rst_off = "0" if cr["active_high"] else "1"
    # Every DATA input (clk/rst excluded) is driven to a known 0 BEFORE reset is
    # asserted, so the datapath never latches X during power-up. chip-AGNOSTIC:
    # the port list is derived from the project's own interface (L9/L1), not a
    # per-chip literal. (An uninitialised input propagates X through the DUT and
    # mis-calibrates the streaming scoreboard — the spm serial-multiplier fail:
    # 203/208 false mismatches vanish to 208/208 on the SAME RTL once inputs
    # start at 0. A cocotb signal left unset reads X, and X into a
    # bounded-latency/bit-order calibrator locks a wrong (order, latency).)
    in_ports = [p["name"] for p in shape.get("ports", [])
                if p.get("dir") == "input"
                and p["name"] not in (cr["clk"], cr["rst"])]
    inputs_lit = "[" + ", ".join(repr(n) for n in in_ports) + "]"
    return f'''"""Professional cocotb testbench for {shape["top"]} —
GENERATED by professional_tb_gen (deterministic, from the Phase-1 L-docs).
Combines cocotb + cocotb-coverage; run via the emitted Makefile."""
import os
import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

try:
    from cocotb_coverage.coverage import CoverPoint, CoverCross, coverage_db
    _HAVE_COV = True
except Exception:
    _HAVE_COV = False

CLK = "{clk}"
RST = "{rst}"
HALF_NS = {half}
SEED = int(os.environ.get("TB_SEED", "1"))
DUT_INPUTS = {inputs_lit}   # all data inputs (clk/rst excluded); reset drives 0


async def _reset(dut):
    # Initialise every data input to a known 0 BEFORE asserting reset so no X
    # propagates into the datapath / scoreboard during power-up.
    for _sig in DUT_INPUTS:
        try:
            getattr(dut, _sig).value = 0
        except Exception:
            pass
    getattr(dut, RST).value = {rst_on}
    for _ in range(3):
        await RisingEdge(getattr(dut, CLK))
    getattr(dut, RST).value = {rst_off}
    await RisingEdge(getattr(dut, CLK))


def _start_clock(dut):
    cocotb.start_soon(Clock(getattr(dut, CLK), 2 * HALF_NS, units="ns").start())
'''


def emit_serial_stream_tb(shape: dict) -> str:
    """The centerpiece: a bounded-latency + bit-order-tolerant streaming
    scoreboard. Feeds the parallel operand (held) + the serial operand LSB/MSB,
    collects the serial output, and auto-derives (latency, bit_order) from the
    first passing vector, then verifies every vector against the closed-form
    reference — closing the serial-datapath DEFER."""
    x, y, p = shape["x_port"], shape["y_port"], shape["p_port"]
    top = shape["top"]
    N = int(shape["width"])
    cov = build_coverage_model(shape)
    cps = cov["fields"]["covergroups"][0]["coverpoints"]
    hi = (1 << N) - 1
    # coverage decorators (cocotb-coverage) on the sampled operands
    cov_bins_x = str({b["name"]: (lambda v, vals=b["values"]: v in vals)
                      for b in cps[0]["bins"]}) if cps else "{}"
    header = _emit_common_header(shape)
    return header + f'''
N = {N}
MAX_LATENCY = N + 4          # bounded search window for the output alignment
X = "{x}"; Y = "{y}"; P = "{p}"


def _ref(xv, yv):
    """Closed-form reference: product mod 2^N (unsigned & two's-complement share
    the low-N bit pattern)."""
    return (xv * yv) & {hi}


def _bits_lsb(val):
    return [(val >> i) & 1 for i in range(N)]


async def _run_vector(dut, xv, yv, order):
    """Drive one (x,y) vector; return the collected P stream (list of N+ bits)."""
    getattr(dut, X).value = xv
    ybits = _bits_lsb(yv) if order == "lsb" else list(reversed(_bits_lsb(yv)))
    got = []
    for i in range(N + MAX_LATENCY):
        getattr(dut, Y).value = ybits[i] if i < N else 0
        await RisingEdge(getattr(dut, CLK))
        try:
            got.append(int(getattr(dut, P).value))
        except Exception:
            got.append(0)
    return got


def _stream_to_val(stream, latency, order, n):
    seg = stream[latency:latency + n]
    if len(seg) < n:
        return None
    if order == "lsb":
        return sum((b & 1) << i for i, b in enumerate(seg))
    return sum((b & 1) << (n - 1 - i) for i, b in enumerate(seg))


@cocotb.test()
async def professional_stream_test(dut):
    random.seed(SEED)
    _start_clock(dut)

    # ---- calibrate (latency, bit_order) from a known non-trivial vector ----
    calib = [(3, 3), (5, 7), ({hi}, {hi})]
    solved = None
    for order in ("lsb", "msb"):
        await _reset(dut)
        for (xv, yv) in calib:
            got = await _run_vector(dut, xv, yv, order)
            for lat in range(MAX_LATENCY + 1):
                if _stream_to_val(got, lat, order, N) == _ref(xv, yv):
                    solved = (order, lat)
                    break
            if solved:
                break
        if solved:
            break
    assert solved, ("could not derive (latency, bit-order) for the serial "
                    "datapath — the DUT does not implement (x*y) mod 2^N in "
                    "any bounded LSB/MSB alignment")
    order, latency = solved
    dut._log.info(f"streaming scoreboard locked: order={{order}} latency={{latency}}")

    # ---- coverage ----
    def _sample(xv, yv):
        if not _HAVE_COV:
            return
        @CoverPoint("top.{x}", xf=lambda a, b: a, bins=list(range(0, {hi} + 1, max(1, ({hi} + 1) // 8))) or [0], at_least=1)
        @CoverPoint("top.{y}", xf=lambda a, b: b, bins=list(range(0, {hi} + 1, max(1, ({hi} + 1) // 8))) or [0], at_least=1)
        def _s(a, b):
            pass
        _s(xv, yv)

    # ---- directed corners + constrained-random ----
    corners = [(0, 0), (0, {hi}), ({hi}, 0), (1, 1), ({hi}, {hi}),
               (2, {hi}), ({hi}, 2), ({hi} >> 1, 3)]
    rand = [(random.randint(0, {hi}), random.randint(0, {hi})) for _ in range(200)]
    fails = 0
    total = 0
    await _reset(dut)
    for (xv, yv) in corners + rand:
        got = await _run_vector(dut, xv, yv, order)
        exp = _ref(xv, yv)
        act = _stream_to_val(got, latency, order, N)
        _sample(xv, yv)
        total += 1
        if act != exp:
            fails += 1
            dut._log.error(f"MISMATCH x={{xv}} y={{yv}} exp={{exp}} got={{act}}")
        await _reset(dut)
    if _HAVE_COV:
        try:
            coverage_db.report_coverage(dut._log.info, bins=True)
            coverage_db.export_to_xml(filename="coverage_{top}.xml")
        except Exception:
            pass
    assert fails == 0, f"{{fails}}/{{total}} vectors mismatched the reference"
    dut._log.info(f"PROFESSIONAL_TB PASS {{total}}/{{total}} vectors, order={{order}} latency={{latency}}")
'''


def emit_parallel_arith_tb(shape: dict) -> str:
    """Parallel c = a OP b: closed-form reference, directed corners +
    constrained-random, functional coverage on each operand."""
    sp = shape["spec"]
    top = shape["top"]
    N = int(shape["width"])
    op = sp["operator"]
    a, b = (sp.get("operands") + ["a", "b"])[:2]
    res = sp.get("result_port") or "out"
    signed = bool(sp.get("signed"))
    hi = (1 << N) - 1
    header = _emit_common_header(shape)
    return header + f'''
import arith_oracle_tb_gen as _aog  # reference golden (single source of truth)
N = {N}; A = "{a}"; B = "{b}"; R = "{res}"; OP = "{op}"; SIGNED = {signed}


@cocotb.test()
async def professional_arith_test(dut):
    random.seed(SEED)
    _start_clock(dut)
    await _reset(dut)
    corners = [(0, 0), (0, {hi}), ({hi}, 0), (1, 1), ({hi}, {hi}),
               ({hi} >> 1, 3), ({hi}, 2)]
    rand = [(random.randint(0, {hi}), random.randint(0, {hi})) for _ in range(300)]
    fails = 0; total = 0
    for (av, bv) in corners + rand:
        getattr(dut, A).value = av
        getattr(dut, B).value = bv
        await RisingEdge(getattr(dut, CLK))
        await Timer(1, units="ns")
        exp = _aog.compute_golden(OP, av, bv, N, SIGNED)
        try:
            act = int(getattr(dut, R).value)
        except Exception:
            act = None
        total += 1
        if act != exp:
            fails += 1
            dut._log.error(f"MISMATCH a={{av}} b={{bv}} exp={{exp}} got={{act}}")
    assert fails == 0, f"{{fails}}/{{total}} mismatched"
    dut._log.info(f"PROFESSIONAL_TB PASS {{total}}/{{total}}")
'''


def emit_generic_tb(shape: dict) -> str:
    """No closed-form reference: emit a structural + reset TB with a clearly
    marked reference hook (dual-track — filled by L10 vectors / spec-to-refmodel,
    NEVER a silent vacuous pass)."""
    header = _emit_common_header(shape)
    top = shape["top"]
    return header + f'''

@cocotb.test()
async def professional_smoke_test(dut):
    """Structural smoke + reset. Reference model NOT closed-form for this class:
    the scoreboard below is a HOOK — fill `reference_model()` from L10 test
    vectors or the spec-to-refmodel skill. This test asserts reset + no-X only;
    it MUST NOT be treated as functional sign-off until the hook is filled."""
    _start_clock(dut)
    await _reset(dut)
    for _ in range(20):
        await RisingEdge(getattr(dut, CLK))
    # reference_model hook — RAISES until filled (never a vacuous pass)
    raise cocotb.result.TestSkip(
        "reference_model hook unfilled for {top}: supply L10 vectors or a "
        "spec-derived reference before this counts as functional sign-off")
'''


def emit_makefile(shape: dict, rtl_files: List[str]) -> str:
    top = shape["top"]
    verilog = " \\\n\t".join(rtl_files) if rtl_files else f"$(PWD)/{top}.v"
    return f'''# Auto-generated cocotb Makefile (professional_tb_gen)
SIM ?= icarus
TOPLEVEL_LANG ?= verilog
VERILOG_SOURCES = {verilog}
TOPLEVEL = {top}
MODULE = tb_{top}
export PYTHONPATH := $(PWD):$(PYTHONPATH)
include $(shell cocotb-config --makefiles)/Makefile.sim
'''


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def _rtl_files(project: Path, top: str) -> List[str]:
    rtl_dir = _pl.rtl_dir(project)
    out = []
    if rtl_dir.is_dir():
        for f in sorted(rtl_dir.rglob("*")):
            if f.suffix.lower() in (".v", ".sv"):
                out.append(str(f))
    return out


def generate(project: Path, out_dir: Optional[Path] = None) -> dict:
    ic_class = _detect_ic_class(project)
    shape, why = classify_dut(project, ic_class)
    if shape is None:
        return {"status": "SKIP", "reason": why, "ic_class": ic_class}
    top = shape["top"]
    out = out_dir or (_pl.rtl_dir(project).parent / "sim_professional" / top)
    out.mkdir(parents=True, exist_ok=True)

    if shape["kind"] == "serial_stream":
        tb = emit_serial_stream_tb(shape)
        ref_tier = "streaming_bounded_latency"
    elif shape["kind"] == "parallel_arith":
        tb = emit_parallel_arith_tb(shape)
        ref_tier = "closed_form"
    else:
        tb = emit_generic_tb(shape)
        ref_tier = "hook_unfilled"

    cov = build_coverage_model(shape)
    sva, l29 = build_assertions(project, shape)
    rtl = _rtl_files(project, top)
    mk = emit_makefile(shape, rtl)
    vplan = {
        "top": top, "ic_class": ic_class, "dut_kind": shape["kind"],
        "reference_model_tier": ref_tier,
        "coverage_model": "L28 (see <top>_coverage_model.json)",
        "assertions": "L29 (see <top>_assertions.sva)",
        "sim": "cocotb + cocotb-coverage; SIM=icarus|verilator",
        "closure": cov["fields"]["closure_policy"],
    }

    (out / f"tb_{top}.py").write_text(tb)
    (out / f"{top}_coverage_model.json").write_text(
        json.dumps(cov, indent=2) + "\n")
    (out / f"{top}_assertions.sva").write_text(sva)
    (out / "Makefile").write_text(mk)
    (out / "verification_plan.json").write_text(
        json.dumps(vplan, indent=2) + "\n")
    return {"status": "PASS", "ic_class": ic_class, "dut_kind": shape["kind"],
            "reference_model_tier": ref_tier, "out_dir": str(out),
            "files": [f"tb_{top}.py", f"{top}_coverage_model.json",
                      f"{top}_assertions.sva", "Makefile",
                      "verification_plan.json"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    res = generate(a.project.resolve(), a.out_dir)
    txt = json.dumps(res, indent=2)
    if a.json:
        a.json.write_text(txt + "\n")
    print(txt)
    return 0 if res.get("status") in ("PASS", "SKIP") else 1


if __name__ == "__main__":
    raise SystemExit(main())
