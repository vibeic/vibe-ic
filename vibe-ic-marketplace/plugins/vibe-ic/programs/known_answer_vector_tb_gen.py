#!/usr/bin/env python3
"""known_answer_vector_tb_gen.py — a SELF-CHECKING TB for a declared vector.

NOT A GATE. This module is a schema / producer imported by the L10 emitter, the
unit-TB producer and `l10_tb_conformance_check`; it declares no `ENFORCEMENT:`
intent because it is not wired into the flow definition as a clause and
`flow_gate_enforcement_audit` would correctly call such a declaration orphaned.
Its siblings `arith_oracle_tb_gen` and `cpu_boot_latency_oracle_tb_gen` declare
none either.

The defect this closes, in one line from `testbench_gen.emit_unit_tb`:

    lines.append(f"    // expected: {expected}")
    lines.append("    // Drive the case's inputs and compare against `expected` here.")

A reference output carried into a comment verifies nothing. What this emits
instead DRIVES the vector's typed inputs onto the DUT's own ports, samples the
declared outputs, compares them against the typed expected value, increments
`errors` on mismatch and ends `$fatal(1)` when `errors != 0` — so a wrong DUT
makes the simulator exit non-zero.

FAIL-CLOSED, and this is the load-bearing property. A vector binds only when
EVERY one of its input fields and EVERY one of its expected fields resolves to a
port of this DUT whose width matches the value's own width. Anything else
returns None and the caller falls back to the substance floor, so a case nobody
can actually drive still fails the Step-4 gate honestly. Nothing is padded,
truncated, or assumed.

chip-AGNOSTIC: the field->port map is open cryptographic-datapath vocabulary
(`key`, `plaintext`, `ciphertext`, `message`, `digest`) plus the universal
direction/clock/reset shapes; no chip, vendor or SKU literal takes part.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import known_answer_vector as _kav
except Exception:  # pragma: no cover — importable standalone
    _kav = None  # type: ignore

#: Vector field -> the port-name tokens a design may expose it under. Ordered:
#: an exact match wins over a token match, so `data_in` is preferred to `data`.
FIELD_PORT_TOKENS: Dict[str, Tuple[str, ...]] = {
    "key":        ("key", "key_i", "cipher_key", "aes_key"),
    "iv":         ("iv", "iv_i", "init_vector", "nonce", "ctr", "counter"),
    "plaintext":  ("plaintext", "data_in", "din", "data_i", "pt", "text_in"),
    "message":    ("message", "block", "msg", "data_in", "din", "data_i",
                   "block_i"),
    "ciphertext": ("ciphertext", "data_out", "dout", "data_o", "ct",
                   "text_out"),
    "digest":     ("digest", "hash", "digest_o", "data_out", "dout", "hash_o"),
}

_CLK = ("clk", "clock", "clk_i", "i_clk", "clk_in")
_RST = ("rst", "reset", "rst_n", "rst_ni", "resetn", "i_rst", "rst_i",
        "reset_n")

_ID_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")


def _width_of(decl: str) -> int:
    """Bit width from a port's declared range, 1 when scalar."""
    m = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", str(decl or ""))
    if not m:
        return 1
    hi, lo = int(m.group(1)), int(m.group(2))
    return abs(hi - lo) + 1


def _bind_field(field: str, value_bits: int,
                candidates: Sequence[Tuple[str, str]]
                ) -> Optional[Tuple[str, int]]:
    """`(port, width)` for `field`, or None. Width must MATCH the value: a
    vector driven onto a port of the wrong width is not the vector."""
    tokens = FIELD_PORT_TOKENS.get(field)
    if not tokens:
        return None
    for tok in tokens:
        for name, decl in candidates:
            n = _norm(name)
            if n == tok or n.rstrip("_io") == tok or n == tok + "_i" \
                    or n == tok + "_o":
                if _width_of(decl) == value_bits:
                    return name, _width_of(decl)
    for tok in tokens:
        for name, decl in candidates:
            if tok in _norm(name) and _width_of(decl) == value_bits:
                return name, _width_of(decl)
    return None


def bind_vector(case: dict,
                ports: Sequence[Tuple[str, str, str]]
                ) -> Tuple[Optional[dict], str]:
    """`(binding, reason)` — how this vector maps onto this DUT's ports.

    `ports` is the `(name, decl, direction)` triple list `testbench_gen`
    already resolves. Returns `(None, why)` for anything that does not bind
    completely: partial binding is the failure mode that would emit a TB
    comparing a value against a port it never drove."""
    if _kav is None:
        return None, "known_answer_vector schema unavailable"
    if not _kav.is_known_answer_vector(case):
        return None, "not a valid known_answer_vector record"
    # `testbench_gen.resolve_dut` yields (DIRECTION, WIDTH, NAME) — see
    # `_classify`, which is the authority. This module read it as
    # (name, width, direction) and its unit fixtures repeated the same wrong
    # order, so every test passed while every REAL port surface bound nothing.
    ins = [(n, w) for d, w, n in ports if str(d).startswith("input")]
    outs = [(n, w) for d, w, n in ports if str(d).startswith("output")]
    drive: Dict[str, Tuple[str, str, int]] = {}
    check: Dict[str, Tuple[str, str, int]] = {}
    for field, raw in (case.get("inputs") or {}).items():
        val = _kav.normalise_hex(raw)
        if val is None:
            return None, f"input {field} is not a typed value"
        bits = len(val) * 4
        b = _bind_field(_norm(field), bits, ins)
        if b is None:
            return None, (f"input field {field!r} ({bits} bits) binds to no "
                          f"input port of this DUT at that width")
        drive[field] = (b[0], val, bits)
    for field, raw in (case.get("expected_outputs") or {}).items():
        val = _kav.normalise_hex(raw)
        if val is None:
            return None, f"expected {field} is not a typed value"
        bits = len(val) * 4
        b = _bind_field(_norm(field), bits, outs)
        if b is None:
            return None, (f"expected field {field!r} ({bits} bits) binds to no "
                          f"output port of this DUT at that width")
        check[field] = (b[0], val, bits)
    if not drive or not check:
        return None, "a vector with no drivable input or no checkable output"
    clk = next((n for n, _w in ins if _norm(n) in _CLK), None)
    rst = next((n for n, _w in ins if _norm(n) in _RST), None)
    return {"drive": drive, "check": check, "clk": clk, "rst": rst}, ""


def emit_case_oracle_from_ports(case: dict, dut_module: str,
                                ports: Sequence[Tuple[str, str, str]],
                                settle_cycles: int = 64
                                ) -> Tuple[Optional[str], str]:
    """`(verilog, reason)` for ONE vector, or `(None, why)` — fail-closed."""
    binding, why = bind_vector(case, ports)
    if binding is None:
        return None, why
    name = str(case.get("name"))
    if not _ID_RE.match(name):
        return None, f"case name {name!r} is not a legal identifier"
    clk, rst = binding["clk"], binding["rst"]
    rst_low = bool(rst) and _norm(rst).endswith(("n", "ni"))
    L: List[str] = []
    L.append("// AUTO-GENERATED self-checking known-answer-vector testbench.")
    L.append(f"// case      : {name}")
    L.append(f"// citation  : {case.get('citation')}")
    L.append(f"// source    : {case.get('source')}  ({case.get('evidence')})")
    L.append(f"// transport : {(case.get('transport') or {}).get('kind')}")
    L.append("// The expected value below is a TYPED LITERAL compared against")
    L.append("// the DUT's own output. A mismatch increments `errors` and the")
    L.append("// run ends $fatal(1) — this file cannot print a PASS it did not")
    L.append("// verify.")
    L.append(f"module {name};")
    L.append("  integer errors = 0;")
    if clk:
        L.append(f"  reg {clk} = 1'b0;")
        L.append(f"  always #5 {clk} = ~{clk};")
    if rst:
        L.append(f"  reg {rst} = 1'b{'0' if rst_low else '1'};")
    for _f, (port, val, bits) in binding["drive"].items():
        L.append(f"  reg [{bits-1}:0] {port} = {bits}'h{val};")
    for _f, (port, val, bits) in binding["check"].items():
        L.append(f"  wire [{bits-1}:0] {port};")
        L.append(f"  localparam [{bits-1}:0] EXPECTED_{port.upper()} = "
                 f"{bits}'h{val};")
    conns = []
    if clk:
        conns.append(f".{clk}({clk})")
    if rst:
        conns.append(f".{rst}({rst})")
    for _f, (port, _v, _b) in list(binding["drive"].items()) + \
            list(binding["check"].items()):
        conns.append(f".{port}({port})")
    L.append(f"  {dut_module} dut (" + ", ".join(conns) + ");")
    L.append("  initial begin")
    if rst:
        L.append(f"    #20 {rst} = 1'b{'1' if rst_low else '0'};")
    L.append(f"    repeat ({settle_cycles}) @(posedge {clk});" if clk
             else f"    #{settle_cycles * 10};")
    for _f, (port, _v, _b) in binding["check"].items():
        L.append(f"    if ({port} !== EXPECTED_{port.upper()}) begin")
        L.append("      errors = errors + 1;")
        L.append(f'      $display("[TB {name}] FAIL: {port} = %h, expected '
                 f'%h", {port}, EXPECTED_{port.upper()});')
        L.append("    end")
    L.append("    if (errors != 0) begin")
    L.append(f'      $display("[TB {name}] FAIL: %0d mismatch(es) against '
             f'{case.get("citation")}", errors);')
    L.append("      $fatal(1);")
    L.append("    end")
    L.append(f'    $display("[TB {name}] PASS: known-answer vector matched '
             f'({case.get("citation")})");')
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n", ""


# --------------------------------------------------------------------------
# THE SECOND ROUTE — the bus the design SAYS the vector is driven over
# --------------------------------------------------------------------------
def _staged_bus_packages(project) -> "List[Tuple[str, str]]":
    """`(path, text)` for every staged package that declares a bus struct pair.

    Read out of the design's OWN staged RTL, never out of an oracle tree."""
    from pathlib import Path as _P
    out = []
    root = _P(project)
    for sub in ("input/vendor_rtl", "input/design_src", "phase2/stage1/rtl"):
        d = root / sub
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*pkg*.sv")):
            try:
                t = p.read_text(errors="replace")
            except OSError:
                continue
            if "h2d" in t.lower() and "d2h" in t.lower():
                out.append((str(p.relative_to(root)), t))
    return out


def emit_case_register_bus(project, case: dict, dut_module: str,
                           ports: "Sequence[Tuple[str, str, str]]"
                           ) -> Tuple[Optional[str], str]:
    """`(verilog, reason)` for a vector driven over the design's register bus.

    Used when the vector's fields do not appear as DUT ports — which is the
    normal case for a peripheral whose interface is a bus. Fail-closed at every
    step: the register map, the encoding tables, the status bit, the byte order
    and the bus field names all come from the design's own input, and any one
    of them missing is a refusal with a reason."""
    from pathlib import Path as _P
    import json as _json
    try:
        import register_bus_driver_gen as _rbd
    except Exception as e:
        return None, f"register-bus driver unavailable: {e}"
    root = _P(project)
    gd = root / "phase1" / "generated_docs"

    def _load(n):
        p = gd / n
        try:
            return _json.loads(p.read_text(errors="ignore")) if p.is_file() else {}
        except Exception:
            return {}

    corpus = {}
    for sub in ("phase1/input_doc", "input/docs"):
        d = root / sub
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in (".txt", ".md", ".rst"):
                try:
                    corpus[p.name] = p.read_text(errors="replace")
                except OSError:
                    pass
    plan, why = _rbd.resolve_register_plan(
        case, _load("L4_REGMAP.json"), _load("L15_ENCODING_TABLES.json"),
        corpus)
    if plan is None:
        return None, why
    reasons = []
    for path, text in _staged_bus_packages(root):
        bus, bwhy = _rbd.bus_contract(text)
        if bus is None:
            reasons.append(f"{path}: {bwhy}")
            continue
        h2d_t = bus["h2d_type"].split("::")[-1]
        d2h_t = bus["d2h_type"].split("::")[-1]
        # The parsed port surface carries no type for a struct-typed port, so
        # the pairing is read off the design's OWN module declaration.
        h2d_port, d2h_port = _bus_ports_from_rtl(root, dut_module, h2d_t, d2h_t)
        if bus["h2d"].get("user") and not bus.get("user_default"):
            reasons.append(
                f"{path}: the bus carries a user/sideband field "
                f"({bus['h2d']['user']}) and the package names no default "
                f"constant for it — leaving it at 0 is an invalid encoding the "
                f"design's own error check rejects, so this refuses rather "
                f"than driving a transaction the DUT will error")
            continue
        if not h2d_port or not d2h_port:
            reasons.append(f"{path}: the DUT exposes no {h2d_t}/{d2h_t} port "
                           f"pair")
            continue
        clk = next((n for d, _w, n in ports
                    if str(d).startswith("input") and _norm(n) in _CLK), None)
        rst = next((n for d, _w, n in ports
                    if str(d).startswith("input") and _norm(n) in _RST), None)
        if not clk or not rst:
            reasons.append(f"{path}: the DUT exposes no clock/reset pair")
            continue
        # A device that CHECKS request integrity rejects a host that does not
        # generate it. Look for the design's own generator; when it ships one,
        # the sequence drives through it and the extra source is reported so a
        # caller knows what to compile.
        gen, gwhy = _rbd.find_host_intg_gen(
            _staged_bus_packages(root) + _staged_rtl_sources(root),
            bus["h2d_type"])
        text_out = _rbd.emit_sequence_tb(
            case, plan, bus, dut_module, h2d_port, d2h_port, clk, rst,
            rst_active_low=_norm(rst).endswith(("n", "ni")),
            ports=ports, intg_gen=gen)
        return text_out, (f"host integrity generator: {gen['file']}"
                          if gen else f"no integrity generator ({gwhy})")
    if not reasons:
        return None, ("no staged package declares a host->device / "
                      "device->host bus struct pair")
    return None, "; ".join(reasons[:3])


def _bus_ports_from_rtl(root, dut_module: str, h2d_t: str, d2h_t: str
                        ) -> Tuple[Optional[str], Optional[str]]:
    """`(h2d_port, d2h_port)` read off the DUT's own module declaration.

    A struct-typed port survives the generic port parser as a bare name with no
    width, so the type has to come from the RTL itself."""
    from pathlib import Path as _P
    root = _P(root)
    # Anchored on the DIRECTION keyword: a module header is not delimited by
    # the first `;` (an `import pkg::*;` line sits inside it), and the same
    # type name also appears on the instantiation below. Direction + type +
    # identifier is the port declaration and nothing else.
    pat_h = re.compile(r"\binput\s+[\w:]*\b" + re.escape(h2d_t)
                       + r"\s+(\w+)")
    pat_d = re.compile(r"\boutput\s+[\w:]*\b" + re.escape(d2h_t)
                       + r"\s+(\w+)")
    for sub in ("phase2/stage1/rtl", "input/vendor_rtl", "input/design_src"):
        d = root / sub
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.sv")) + sorted(d.rglob("*.v")):
            try:
                t = p.read_text(errors="replace")
            except OSError:
                continue
            m = re.search(r"\bmodule\s+" + re.escape(dut_module)
                          + r"\b(?P<hdr>.*?)\bendmodule\b", t, re.S)
            if not m:
                continue
            hdr = m.group("hdr")
            mh, md = pat_h.search(hdr), pat_d.search(hdr)
            if mh and md:
                return mh.group(1), md.group(1)
    return None, None


def _staged_rtl_sources(project) -> "List[Tuple[str, str]]":
    """`(path, text)` for every SystemVerilog source the design staged.

    Includes `input/vendor_rtl/**`, which holds the HOST-side helpers a device
    closure legitimately does not: a request-integrity generator is not part of
    the DUT and would never be staged into `phase2/stage1/rtl`."""
    from pathlib import Path as _P
    out = []
    root = _P(project)
    for sub in ("phase2/stage1/rtl", "input/vendor_rtl", "input/design_src"):
        d = root / sub
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.sv")):
            try:
                out.append((str(p), p.read_text(errors="replace")))
            except OSError:
                pass
    return out
