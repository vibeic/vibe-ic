#!/usr/bin/env python3
"""register_bus_driver_gen.py — drive a known-answer vector over the bus the
design SAYS it is driven over.

NOT A GATE. A producer imported by `known_answer_vector_tb_gen`; it declares no
`ENFORCEMENT:` intent because it is wired into no flow clause.

WHY THIS EXISTS. `opentitan_aes` states its own transport, in its own brief:

    NIST FIPS-197 / SP 800-38A 標準測試向量（ECB/CBC/CFB/OFB/CTR），
    經自建 TB 由 TL-UL register interface 驅動完整 encrypt/decrypt round-trip。

So the register-write sequence is not one of two options a tool may choose
between — it is the transport the design DECLARED. Binding the vectors to a
submodule's data ports instead would be faster and would be going around the
design's own statement. The port-level emitter in `known_answer_vector_tb_gen`
correctly refused every one of the 8 vectors on `chip_top` (`input field 'key'
(128 bits) binds to no input port of this DUT at that width`), because chip_top
exposes struct-typed bus ports and nothing else. This module is the other half.

EVERYTHING IS DERIVED FROM THE DESIGN'S OWN INPUT, and every derivation has a
refusal beside it:

  * register OFFSETS          L4_REGMAP (the summary table the design ships)
  * the CONTROL encoding      L15_ENCODING_TABLES (mode / key length / operation
                              value tables the design ships)
  * the START trigger and     L4 field bit positions, by role vocabulary
    the DONE status bit
  * register byte ORDER       a sentence in the design's documents whose SUBJECT
                              is the registers
  * the BUS field names       the bus package staged in the design's own RTL

Nothing is hard-coded: no address, no bit index, no opcode value, no width. Any
one of them missing returns `(None, reason)` and the caller falls through, so a
design that declares a transport it does not describe gets an honest refusal
rather than a driver that guesses.

MULTI-CYCLE IS REAL. A settle-and-compare would be wrong here: the sequence
waits on the design's own status bit (`STATUS.OUTPUT_VALID` on this design,
resolved by role, never by name literal) with a bounded timeout that FAILS.
There is no fixed cycle count anywhere.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import known_answer_vector as _kav
except Exception:  # pragma: no cover
    _kav = None  # type: ignore

# --------------------------------------------------------------------------
# ROLE VOCABULARY — open bus / register vocabulary, never a chip or vendor name
# --------------------------------------------------------------------------
#: Host->device struct field roles.
_H2D_ROLES = {
    "req_valid": ("a_valid", "valid", "req_valid", "cmd_valid"),
    "addr":      ("a_address", "a_addr", "address", "addr", "paddr"),
    "wdata":     ("a_data", "wdata", "write_data", "pwdata"),
    "opcode":    ("a_opcode", "opcode", "cmd", "a_op"),
    "mask":      ("a_mask", "mask", "byte_enable", "wstrb", "pstrb"),
    "size":      ("a_size", "size", "a_len"),
    "source":    ("a_source", "source", "a_id"),
    "rsp_ready": ("d_ready", "rready", "ready"),
    # A sideband/user field. Leaving it at 0 is NOT neutral: measured on
    # opentitan_aes, `tlul_err` computes
    # `instr_type_err = mubi4_test_invalid(tl_i.a_user.instr_type)`, so an
    # all-zero user field is an INVALID multi-bit encoding and every read came
    # back `ffffffff` (the package's own `DataWhenError`). The design ships the
    # value a host is supposed to send; the driver uses that and refuses when
    # the field exists and the constant does not.
    "user": ("a_user", "user", "auser", "awuser"),
}
#: Device->host struct field roles.
_D2H_ROLES = {
    "req_ready": ("a_ready", "ready", "cmd_ready"),
    "rsp_valid": ("d_valid", "valid", "rsp_valid", "rvalid"),
    "rdata":     ("d_data", "rdata", "read_data", "prdata"),
    "error":     ("d_error", "error", "slverr", "resp"),
}
#: Register roles, by the name a register map gives them.
# The index is OPTIONAL because a register map that lists `DATA_OUT_0 0x64` in
# its summary table is routinely collapsed to a `DATA_OUT` base record at the
# same address. Element 0 and the base are the same row of the same document,
# so reading the un-indexed name as index 0 is the document's own arithmetic —
# and when BOTH appear at DIFFERENT addresses that is a contradiction, which
# `resolve_register_plan` refuses rather than picking a winner.
_REG_ROLES = {
    "key":      re.compile(r"(?i)^key(?:_?share0)?(?:_(?P<i>\d+))?$"),
    "iv":       re.compile(r"(?i)^iv(?:_(?P<i>\d+))?$"),
    "data_in":  re.compile(r"(?i)^(?:data_in|din|input_data)(?:_(?P<i>\d+))?$"),
    "data_out": re.compile(r"(?i)^(?:data_out|dout|output_data)(?:_(?P<i>\d+))?$"),
}
#: Reset-shaped port names, for the tie-off pass in `emit_sequence_tb`.
_RST_TOKENS = frozenset({"rst", "reset", "rst_n", "rst_ni", "resetn",
                         "i_rst", "rst_i", "reset_n"})
_CTRL_RE = re.compile(r"(?i)^ctrl(_shadowed)?$")
_TRIGGER_RE = re.compile(r"(?i)^(trigger|command|cmd)$")
_STATUS_RE = re.compile(r"(?i)^(status|state)$")
#: The trigger field that STARTS a transaction, and the status field that says
#: a result is available. Role words, resolved against the design's own fields.
_START_FIELD = ("start", "go", "run", "launch", "kick")
_DONE_FIELD = ("output_valid", "out_valid", "done", "valid", "ready",
               "data_valid", "complete")
#: Sentence shape whose SUBJECT is the registers. "the increment of the IV in
#: CTR mode is big-endian" has a different subject and must not be read as a
#: register byte order.
_REG_ENDIAN_RE = re.compile(
    r"(?i)\b(?:all\s+|these\s+|the\s+)?registers?\s+(?:are|is)\s+"
    r"(?P<order>little|big)[\s-]endian\b")


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")


def bus_contract(package_text: str) -> Tuple[Optional[dict], str]:
    """`(contract, reason)` for a staged bus package.

    Parses `typedef struct packed { ... } <name>_t;` and the opcode enum out of
    the design's OWN staged package, then assigns roles by field name. Refuses
    unless every role a register access needs is present."""
    if not isinstance(package_text, str) or not package_text.strip():
        return None, "no bus package text"
    structs: Dict[str, List[str]] = {}
    for m in re.finditer(
            r"typedef\s+struct\s+packed\s*\{(?P<body>.*?)\}\s*"
            r"(?P<name>\w+)\s*;", package_text, re.S):
        fields = re.findall(r"^\s*[\w:\[\]\s\-\+']*?(\w+)\s*;\s*$",
                            m.group("body"), re.M)
        structs[m.group("name")] = fields
    # A package may declare several structs whose name contains `h2d` (an
    # integrity-command subset, for instance). Take the widest — the one that
    # carries the whole channel — and prefer an exact `*h2d_t` spelling.
    def _pick(tag: str) -> Optional[str]:
        cands = [n for n in structs if tag in n.lower()]
        if not cands:
            return None
        exact = [n for n in cands if n.lower().rstrip("_t").endswith(tag)]
        return max(exact or cands, key=lambda n: len(structs[n]))

    h2d = _pick("h2d")
    d2h = _pick("d2h")
    if not h2d or not d2h:
        return None, ("the staged bus package declares no host->device / "
                      f"device->host struct pair (saw {sorted(structs)})")

    def _roles(fields: Sequence[str], table: Dict[str, tuple]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        norm = {_norm(f): f for f in fields}
        for role, tokens in table.items():
            for tok in tokens:
                if tok in norm:
                    out[role] = norm[tok]
                    break
        return out

    hr = _roles(structs[h2d], _H2D_ROLES)
    dr = _roles(structs[d2h], _D2H_ROLES)
    need_h = ("req_valid", "addr", "wdata", "opcode", "rsp_ready")
    need_d = ("req_ready", "rsp_valid", "rdata")
    missing = [r for r in need_h if r not in hr] + \
              [r for r in need_d if r not in dr]
    if missing:
        return None, (f"the staged bus package binds no field for {missing} "
                      f"(h2d={sorted(hr)}, d2h={sorted(dr)})")
    # The named default for the user/sideband field, taken from the package
    # that declares the field.
    user_default = ""
    if "user" in hr:
        m_ud = re.search(r"parameter\s+\w*user\w*_t\s+(\w+)\s*=", package_text,
                         re.I)
        if m_ud:
            user_default = m_ud.group(1)
    ops: Dict[str, str] = {}
    op_type = ""
    for m in re.finditer(
            r"typedef\s+enum[^{]*\{(?P<body>.*?)\}\s*(?P<tname>\w+)\s*;",
            package_text, re.S):
        for nm, val in re.findall(r"(\w+)\s*=\s*([0-9]+'\s*[hbdo]\s*[0-9a-fA-F_]+)",
                                  m.group("body")):
            n = _norm(nm)
            if n.startswith("put") and "write" not in ops:
                ops["write"] = val.replace(" ", "")
                op_type = m.group("tname")
            if n == "get" and "read" not in ops:
                ops["read"] = val.replace(" ", "")
                op_type = op_type or m.group("tname")
    if "write" not in ops or "read" not in ops:
        return None, ("the staged bus package declares no write/read opcode "
                      f"enumeration (saw {sorted(ops)})")
    # The struct types are declared inside a package, so a testbench that
    # names them bare does not compile. Carry the scope.
    pkg_m = re.search(r"^\s*package\s+(\w+)\s*;", package_text, re.M)
    pkg = pkg_m.group(1) if pkg_m else ""
    scope = f"{pkg}::" if pkg else ""
    return {"h2d_type": scope + h2d, "d2h_type": scope + d2h,
            "package": pkg, "h2d": hr, "d2h": dr, "opcodes": ops,
            # The opcode field is enum-typed, so a bare literal does not
            # assign to it. Carry the type so the driver can cast.
            "opcode_type": (scope + op_type) if op_type else "",
            "user_default": (scope + user_default) if user_default else ""}, ""


def register_endianness(corpus: Dict[str, str]) -> Tuple[Optional[str], str]:
    """The byte order the design states FOR ITS REGISTERS, or a refusal.

    Subject-anchored on purpose. opentitan_aes says "Note that all registers
    are little-endian." and, one paragraph later, "the increment of the IV in
    CTR mode is big-endian" — a statement about an ARITHMETIC operation, not
    about register byte order. L1 harvests both substrings and therefore cannot
    settle it; this asks the narrower question. Two DIFFERENT orders stated of
    the registers is a genuine contradiction and refuses."""
    seen: Dict[str, List[str]] = {}
    for fname, text in (corpus or {}).items():
        if not isinstance(text, str):
            continue
        for m in _REG_ENDIAN_RE.finditer(text):
            seen.setdefault(m.group("order").lower(), []).append(
                f"{fname}: {m.group(0)}")
    if not seen:
        return None, ("no sentence in the design's documents states a byte "
                      "order OF THE REGISTERS")
    if len(seen) > 1:
        return None, ("the design states BOTH byte orders of its registers: "
                      + "; ".join(v[0] for v in seen.values()))
    order = next(iter(seen))
    return order, seen[order][0]


def _field_bit(reg: dict, tokens: Sequence[str]) -> Optional[Tuple[str, int]]:
    for f in reg.get("fields") or []:
        n = _norm(f.get("field_name") or f.get("name"))
        if n in tokens:
            try:
                return str(f.get("field_name") or f.get("name")), int(f["lsb"])
            except (KeyError, TypeError, ValueError):
                return None
    return None


def _encoding_value(l15: dict, field: str, mnemonic: str) -> Optional[int]:
    """The value the design's own encoding table gives `mnemonic`."""
    want = _norm(mnemonic)
    for t in ((l15 or {}).get("fields") or {}).get("tables") or []:
        if _norm(field) not in _norm(t.get("name")):
            continue
        for row in t.get("rows") or []:
            cells = [c.strip() for c in str(row).split("|")]
            if len(cells) >= 2 and _norm(cells[1]) == want:
                try:
                    return int(cells[0], 16)
                except ValueError:
                    return None
    return None


def resolve_register_plan(case: dict, l4: dict, l15: dict,
                          corpus: Dict[str, str]) -> Tuple[Optional[dict], str]:
    """`(plan, reason)` — every address, bit and value this vector needs."""
    regs = [r for r in (l4 or {}).get("registers") or [] if isinstance(r, dict)]
    if not regs:
        return None, "L4 declares no registers"
    by_role: Dict[str, Dict[int, int]] = {k: {} for k in _REG_ROLES}
    ctrl = trig = stat = None
    conflicts: List[str] = []
    for r in regs:
        name = str(r.get("name") or "")
        addr = r.get("address")
        if _CTRL_RE.match(name):
            ctrl = r
        elif _TRIGGER_RE.match(name):
            trig = r
        elif _STATUS_RE.match(name):
            stat = r
        for role, rx in _REG_ROLES.items():
            m = rx.match(name)
            if not (m and addr):
                continue
            idx = int(m.group("i")) if m.group("i") is not None else 0
            val = int(str(addr), 16)
            prev = by_role[role].get(idx)
            if prev is not None and prev != val:
                conflicts.append(f"{role}[{idx}] is stated at both "
                                 f"0x{prev:x} and 0x{val:x}")
            by_role[role][idx] = val
    if conflicts:
        return None, ("the register map contradicts itself: "
                      + "; ".join(conflicts))
    order, endian_why = register_endianness(corpus)
    if order is None:
        return None, endian_why
    params = case.get("parameters") or {}
    inputs = case.get("inputs") or {}
    outs = case.get("expected_outputs") or {}
    if "plaintext" not in inputs or "ciphertext" not in outs:
        return None, ("this driver drives a (plaintext -> ciphertext) block "
                      f"vector; got inputs={sorted(inputs)} "
                      f"outputs={sorted(outs)}")
    for role in ("key", "data_in", "data_out"):
        if not by_role[role]:
            return None, (f"no {role} register carries an address in L4 — the "
                          f"design's register map does not state where to "
                          f"write it")
    if "iv" in inputs and not by_role["iv"]:
        return None, "the vector states an IV and L4 addresses no IV register"
    if ctrl is None or trig is None or stat is None:
        return None, ("L4 declares no "
                      + ", ".join(n for n, v in (("control", ctrl),
                                                 ("trigger", trig),
                                                 ("status", stat)) if v is None)
                      + " register")
    start = _field_bit(trig, _START_FIELD)
    done = _field_bit(stat, _DONE_FIELD)
    if start is None or done is None:
        return None, ("the design's trigger/status registers declare no "
                      f"start/done bit (start={start}, done={done}) — a fixed "
                      f"wait would be a guess, so this refuses")
    ctrl_val = 0
    ctrl_parts = []
    for field_role, mnemonic in (
            ("MODE", f"AES_{params.get('mode')}"),
            ("KEY_LEN", f"AES_{params.get('key_len')}"),
            ("OPERATION", f"AES_{str(params.get('operation', ''))[:3].upper()}")):
        fb = _field_bit(ctrl, (_norm(field_role),))
        if fb is None:
            return None, (f"the control register declares no {field_role} "
                          f"field")
        val = _encoding_value(l15, field_role, mnemonic)
        if val is None:
            return None, (f"the design's encoding tables give no value for "
                          f"{field_role}={mnemonic}")
        ctrl_val |= val << fb[1]
        ctrl_parts.append(f"{field_role}={mnemonic}(0x{val:x})<<{fb[1]}")
    return {
        "endianness": order, "endianness_evidence": endian_why,
        "key": by_role["key"], "iv": by_role["iv"],
        "data_in": by_role["data_in"], "data_out": by_role["data_out"],
        "ctrl_addr": int(str(ctrl.get("address")), 16),
        # A SHADOWED control register takes effect only after TWO identical
        # writes — the design says so in the register's own NAME, which is the
        # convention its documents use. Measured on opentitan_aes: with one
        # write the control register never updated, so the mode stayed at its
        # invalid-mapped default and STATUS.OUTPUT_VALID was never asserted.
        "ctrl_shadowed": "shadow" in _norm(ctrl.get("name")),
        "ctrl_value": ctrl_val, "ctrl_parts": ctrl_parts,
        "trigger_addr": int(str(trig.get("address")), 16),
        "start_bit": start[1], "start_field": start[0],
        "status_addr": int(str(stat.get("address")), 16),
        "done_bit": done[1], "done_field": done[0],
    }, ""


def _words(hexval: str, order: str) -> List[int]:
    """A hex value as 32-bit register words, in the order the design states."""
    b = bytes.fromhex(hexval)
    out = []
    for i in range(0, len(b), 4):
        chunk = b[i:i + 4]
        out.append(int.from_bytes(chunk, "little" if order == "little" else "big"))
    return out


def find_host_intg_gen(sources: Sequence[Tuple[str, str]], h2d_t: str
                       ) -> Tuple[Optional[dict], str]:
    """`(module, file, why)` for the design's OWN host-side integrity generator.

    A device that checks command integrity rejects every transaction a host
    sends without it. Measured on opentitan_aes: `aes_reg_top` instantiates
    `tlul_cmd_intg_chk` unconditionally and folds its verdict into
    `reg_error`, so every read came back `ffffffff` — the bus package's own
    `DataWhenError` — with `d_error=1`. The design ships the generator that
    makes a legal request (`tlul_cmd_intg_gen`); using it is using the design's
    own RTL, and it is the only way a testbench can talk to that device at all.

    Shape, not name: a module whose port list is `input <h2d> .., output <h2d>
    ..` — a pass-through on the request channel. That is what an integrity
    generator is."""
    bare = h2d_t.split("::")[-1]
    pat = re.compile(
        r"\bmodule\s+(\w+)\b(?P<hdr>.*?)\bendmodule\b", re.S)
    for path, text in sources:
        for m in pat.finditer(text):
            hdr = m.group("hdr")
            mi = re.search(r"\binput\s+[\w:]*\b" + re.escape(bare)
                           + r"\s+(\w+)", hdr)
            mo = re.search(r"\boutput\s+[\w:]*\b" + re.escape(bare)
                           + r"\s+(\w+)", hdr)
            if not (mi and mo):
                continue
            # A pass-through ALONE is not enough: `tlul_adapter_racl` has the
            # same port shape and filters access, it does not generate
            # integrity. What makes this the generator is that its body
            # instantiates an error-correcting-code ENCODER — that is the thing
            # that computes the checksum the device's checker recomputes.
            if not re.search(r"\b\w*secded\w*_enc\b|\b\w*_enc\s+u_\w+\s*\(",
                             hdr):
                continue
            return ({"module": m.group(1), "in": mi.group(1),
                     "out": mo.group(1), "file": path}, "")
    return None, (f"no staged source declares a {bare} -> {bare} "
                  f"pass-through (a host-side integrity generator)")


def emit_sequence_tb(case: dict, plan: dict, bus: dict, dut_module: str,
                     h2d_port: str, d2h_port: str, clk: str, rst: str,
                     rst_active_low: bool = True,
                     timeout_cycles: int = 20000,
                     ports: Optional[Sequence[Tuple[str, str, str]]] = None,
                     intg_gen: Optional[str] = None
                     ) -> str:
    """The SystemVerilog testbench for one vector, driven over the design's own
    register bus.

    Every address, bit index, opcode and control word below came out of
    `resolve_register_plan` / `bus_contract`, i.e. out of the design's own
    register map, encoding tables and staged bus package. The wait is on the
    design's DONE bit with a bounded timeout that FAILS — there is no fixed
    settle time, because a multi-cycle block does not have one."""
    name = str(case.get("name"))
    order = plan["endianness"]
    key_w = _words(_kav.normalise_hex(case["inputs"]["key"]), order)
    pt_w = _words(_kav.normalise_hex(case["inputs"]["plaintext"]), order)
    ct_w = _words(_kav.normalise_hex(case["expected_outputs"]["ciphertext"]),
                  order)
    iv_hex = case["inputs"].get("iv")
    iv_w = _words(_kav.normalise_hex(iv_hex), order) if iv_hex else []
    h, d, ops = bus["h2d"], bus["d2h"], bus["opcodes"]
    _ot = bus.get("opcode_type") or ""

    def _op(v: str) -> str:
        return f"{_ot}'({v})" if _ot else v

    A, W, V, OP, RR = (h["addr"], h["wdata"], h["req_valid"], h["opcode"],
                       h["rsp_ready"])
    AR, DV, RD = d["req_ready"], d["rsp_valid"], d["rdata"]
    mask = h.get("mask")
    size = h.get("size")
    user = h.get("user")
    user_default = bus.get("user_default") or ""
    L: List[str] = []
    L.append("// AUTO-GENERATED known-answer-vector testbench, driven over the")
    L.append("// REGISTER BUS THE DESIGN DECLARES. Nothing below is hard-coded:")
    L.append(f"// case        : {name}")
    L.append(f"// citation    : {case.get('citation')}")
    L.append(f"// transport   : {(case.get('transport') or {}).get('kind')}"
             f"  (bus struct {bus['h2d_type']} / {bus['d2h_type']})")
    L.append(f"// byte order  : {order}-endian — {plan['endianness_evidence']}")
    L.append(f"// control word: 0x{plan['ctrl_value']:x} = "
             + " | ".join(plan["ctrl_parts"]))
    L.append(f"// done bit    : {plan['done_field']} @ bit {plan['done_bit']} "
             f"of the status register (0x{plan['status_addr']:x})")
    L.append(f"module {name};")
    L.append("  integer errors = 0;")
    L.append("  integer wait_cycles = 0;")
    L.append("  integer stall = 0;")
    L.append(f"  reg {clk} = 1'b0;")
    L.append(f"  always #5 {clk} = ~{clk};")
    L.append(f"  reg {rst} = 1'b{'0' if rst_active_low else '1'};")
    # The signal the sequence DRIVES. When the design ships a host-side
    # integrity generator, the driven signal goes through it and the DUT sees
    # its output — otherwise the device's own checker rejects every request.
    drive_sig = f"{h2d_port}_raw" if intg_gen else h2d_port
    L.append(f"  {bus['h2d_type']} {drive_sig};")
    if intg_gen:
        L.append(f"  {bus['h2d_type']} {h2d_port};")
        L.append(f"  {intg_gen['module']} u_intg "
                 f"(.{intg_gen['in']}({drive_sig}), "
                 f".{intg_gen['out']}({h2d_port}));"
                 f"   // the design's own request-integrity generator")
    L.append(f"  {bus['d2h_type']} {d2h_port};")
    L.append("  reg [31:0] rdata;")
    # EVERY port of the DUT is connected. Measured on opentitan_aes: connecting
    # only clock, reset and the bus pair left `rst_shadowed_ni` unconnected,
    # which a simulator reads as 0 — a SECOND reset held asserted forever, so
    # the design never left reset and the run hung rather than failing. An
    # unconnected input is not a neutral default; it is a value nobody chose.
    #
    # Reset-shaped inputs are driven with the SAME polarity as the primary
    # reset (a design that names two resets means both of them); everything
    # else is tied to 0 and SAID so, because a tie is a decision the reader has
    # to be able to see. Outputs are left open.
    extra_in = []
    for _d, _w, _n in (ports or []):
        if not str(_d).startswith("input"):
            continue
        if _n in (clk, rst, h2d_port, d2h_port):
            continue
        nn = _norm(_n)
        is_rst = nn in _RST_TOKENS or "rst" in nn or "reset" in nn
        # A second CLOCK that is tied to 0 does not tick, and everything behind
        # it stops. Measured on opentitan_aes: `clk_edn_i` tied off left the
        # entropy interface frozen. A clock-shaped input is driven by the same
        # clock this testbench already generates — that is what a testbench
        # does with a clock, and it invents no value.
        is_clk = (not is_rst) and ("clk" in nn or "clock" in nn)
        extra_in.append((_n, _w, is_rst, is_clk))
    # A reset gets a driven variable (it has to be RELEASED). Everything else
    # is connected to a literal `'0` at the instantiation rather than through a
    # declared reg: those ports are struct- or parameter-typed
    # (`edn_pkg::edn_rsp_t`, `[NumAlerts-1:0]`) and a `reg` declaration in the
    # testbench would have to know a type and a parameter that live inside the
    # DUT. `'0` is width- and type-agnostic and says what it is.
    for _n, _w, _is_rst, _is_clk in extra_in:
        if _is_rst:
            L.append(f"  reg {_n} = 1'b{'0' if rst_active_low else '1'};"
                     f"   // second reset, released with the primary one")
    conn = [f".{clk}({clk})", f".{rst}({rst})",
            f".{h2d_port}({h2d_port})", f".{d2h_port}({d2h_port})"]
    conn += [(f".{_n}({_n})" if _r else (f".{_n}({clk})" if _c
                                         else f".{_n}('0)"))
             for _n, _w, _r, _c in extra_in]
    L.append(f"  {dut_module} dut (" + ", ".join(conn) + ");")
    L.append("")
    L.append("  task automatic bus_write(input [31:0] addr,")
    L.append("                           input [31:0] data);")
    L.append("    begin")
    L.append(f"      @(posedge {clk});")
    L.append(f"      {drive_sig}.{V}   <= 1'b1;")
    L.append(f"      {drive_sig}.{OP}  <= {_op(ops['write'])};")
    if user and user_default:
        L.append(f"      {drive_sig}.{user} <= {user_default};")
    L.append(f"      {drive_sig}.{A}   <= addr;")
    L.append(f"      {drive_sig}.{W}   <= data;")
    if mask:
        L.append(f"      {drive_sig}.{mask} <= 4'hF;")
    if size:
        L.append(f"      {drive_sig}.{size} <= 2'h2;")
    L.append(f"      {drive_sig}.{RR}  <= 1'b1;")
    L.append(f"      @(posedge {clk});")
    L.append(f"      stall = 0;")
    L.append(f"      while (!{d2h_port}.{AR}) begin")
    L.append(f"        @(posedge {clk});")
    L.append("        stall = stall + 1;")
    L.append(f"        if (stall > {timeout_cycles}) begin")
    L.append(f'          $display("[TB {name}] FAIL: the bus never accepted a '
             f'write to %h after %0d cycles", addr, stall);')
    L.append("          $fatal(1);")
    L.append("        end")
    L.append("      end")
    L.append(f"      {drive_sig}.{V}   <= 1'b0;")
    L.append("    end")
    L.append("  endtask")
    L.append("")
    L.append("  task automatic bus_read(input [31:0] addr,")
    L.append("                          output [31:0] data);")
    L.append("    begin")
    L.append(f"      @(posedge {clk});")
    L.append(f"      {drive_sig}.{V}   <= 1'b1;")
    L.append(f"      {drive_sig}.{OP}  <= {_op(ops['read'])};")
    if user and user_default:
        L.append(f"      {drive_sig}.{user} <= {user_default};")
    L.append(f"      {drive_sig}.{A}   <= addr;")
    if mask:
        L.append(f"      {drive_sig}.{mask} <= 4'hF;")
    if size:
        L.append(f"      {drive_sig}.{size} <= 2'h2;")
    L.append(f"      {drive_sig}.{RR}  <= 1'b1;")
    L.append(f"      @(posedge {clk});")
    L.append("      stall = 0;")
    L.append(f"      while (!{d2h_port}.{AR}) begin")
    L.append(f"        @(posedge {clk});")
    L.append("        stall = stall + 1;")
    L.append(f"        if (stall > {timeout_cycles}) begin")
    L.append(f'          $display("[TB {name}] FAIL: the bus never accepted a '
             f'read of %h after %0d cycles", addr, stall);')
    L.append("          $fatal(1);")
    L.append("        end")
    L.append("      end")
    L.append(f"      {drive_sig}.{V}   <= 1'b0;")
    L.append("      stall = 0;")
    L.append(f"      while (!{d2h_port}.{DV}) begin")
    L.append(f"        @(posedge {clk});")
    L.append("        stall = stall + 1;")
    L.append(f"        if (stall > {timeout_cycles}) begin")
    L.append(f'          $display("[TB {name}] FAIL: the bus never returned '
             f'data for %h after %0d cycles", addr, stall);')
    L.append("          $fatal(1);")
    L.append("        end")
    L.append("      end")
    L.append(f"      data = {d2h_port}.{RD};")
    L.append("    end")
    L.append("  endtask")
    L.append("")
    L.append("  initial begin")
    L.append(f"    {drive_sig} = '0;")
    L.append(f"    #20 {rst} = 1'b{'1' if rst_active_low else '0'};")
    for _n, _w, _is_rst, _is_clk in extra_in:
        if _is_rst:
            L.append(f"    {_n} = 1'b{'1' if rst_active_low else '0'};")
    L.append(f"    repeat (4) @(posedge {clk});")
    for i, w in enumerate(key_w):
        if i in plan["key"]:
            L.append(f"    bus_write(32'h{plan['key'][i]:08x}, 32'h{w:08x});"
                     f"   // key word {i}")
    for i in sorted(plan["key"]):
        if i >= len(key_w):
            L.append(f"    bus_write(32'h{plan['key'][i]:08x}, 32'h0);"
                     f"   // unused key word {i}, written once as the design requires")
    for i, w in enumerate(iv_w):
        if i in plan["iv"]:
            L.append(f"    bus_write(32'h{plan['iv'][i]:08x}, 32'h{w:08x});"
                     f"   // iv word {i}")
    L.append(f"    bus_write(32'h{plan['ctrl_addr']:08x}, "
             f"32'h{plan['ctrl_value']:08x});   // control")
    if plan.get("ctrl_shadowed"):
        L.append(f"    bus_write(32'h{plan['ctrl_addr']:08x}, "
                 f"32'h{plan['ctrl_value']:08x});"
                 f"   // second write: the register's own name says it is "
                 f"shadowed")
    for i, w in enumerate(pt_w):
        if i in plan["data_in"]:
            L.append(f"    bus_write(32'h{plan['data_in'][i]:08x}, "
                     f"32'h{w:08x});   // input word {i}")
    L.append(f"    bus_write(32'h{plan['trigger_addr']:08x}, "
             f"32'h{1 << plan['start_bit']:08x});   // {plan['start_field']}")
    L.append("    // Wait on the DESIGN'S OWN done bit. No fixed settle time:")
    L.append("    // this block is multi-cycle and a fixed wait would be a guess.")
    L.append("    rdata = 32'h0;")
    L.append(f"    while (!rdata[{plan['done_bit']}]) begin")
    L.append(f"      bus_read(32'h{plan['status_addr']:08x}, rdata);")
    L.append("      wait_cycles = wait_cycles + 1;")
    L.append(f"      if (wait_cycles > {timeout_cycles}) begin")
    L.append(f'        $display("[TB {name}] FAIL: {plan["done_field"]} never '
             f'asserted after %0d polls", wait_cycles);')
    L.append("        errors = errors + 1;")
    L.append("        $fatal(1);")
    L.append("      end")
    L.append("    end")
    for i, w in enumerate(ct_w):
        if i not in plan["data_out"]:
            continue
        L.append(f"    bus_read(32'h{plan['data_out'][i]:08x}, rdata);")
        L.append(f"    if (rdata !== 32'h{w:08x}) begin")
        L.append("      errors = errors + 1;")
        L.append(f'      $display("[TB {name}] FAIL: output word {i} = %h, '
                 f'expected %h", rdata, 32\'h{w:08x});')
        L.append("    end")
    L.append("    if (errors != 0) begin")
    L.append(f'      $display("[TB {name}] FAIL: %0d mismatch(es) against '
             f'{case.get("citation")}", errors);')
    L.append("      $fatal(1);")
    L.append("    end")
    L.append(f'    $display("[TB {name}] PASS: known-answer vector matched '
             f'over the declared register bus ({case.get("citation")})");')
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"
