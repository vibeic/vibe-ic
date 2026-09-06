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

import _hdl_code_text  # offset-preserving comment/string blanker (#731)

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
    # A design may split the key across shares. The document that describes
    # this one says every register of BOTH shares must be written at least
    # once, and that the key in effect is their XOR, so a share that carries no
    # vector bits is still written — with zero, which is what makes the XOR the
    # vector's own key.
    "key_share1": re.compile(r"(?i)^key_?share1(?:_(?P<i>\d+))?$"),
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
#: "the unit is not busy" — writes to configuration are IGNORED while it is 0.
_IDLE_FIELD = ("idle", "ready_for_config", "not_busy")
#: "the unit will accept an input block now".
_INPUT_READY_FIELD = ("input_ready", "in_ready", "ready_for_data",
                      "data_in_ready")
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
    idle = _field_bit(stat, _IDLE_FIELD)
    in_ready = _field_bit(stat, _INPUT_READY_FIELD)
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
        "key_share1": by_role["key_share1"],
        # The two handshake bits the design's own programmer's guide makes the
        # sequence wait on. Absent is not fatal — a design that declares
        # neither simply gets no wait — but their PRESENCE is what makes the
        # configuration writes land at all on this design.
        "idle_bit": idle[1] if idle else None,
        "idle_field": idle[0] if idle else None,
        "input_ready_bit": in_ready[1] if in_ready else None,
        "input_ready_field": in_ready[0] if in_ready else None,
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
    for path, raw in sources:
        # BLANK COMMENTS AND STRINGS FIRST. `\bmodule\s+(\w+)` does not know a
        # comment from code: measured, `// module ghost_intg_gen (` sitting
        # above the real header wins the match and this function returns
        # `ghost_intg_gen` — the driver then instantiates a module no staged
        # source declares. The blanker preserves offsets, so the `hdr` span is
        # the same span of the same file.
        text = _hdl_code_text.strip_hdl_comments_and_strings(raw)
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


#: Names a package gives to the INACTIVE value of a typed control input. A
#: literal 0 is not that value: measured on opentitan_aes, `lc_ctrl_pkg` states
#: `Off = 4'b1010`, so tying `lc_escalate_en_i` to 0 hands the design a value it
#: reads as neither on nor off, and the unit never reaches idle again.
_INACTIVE_CONST_TOKENS = ("off", "false", "disabled", "inactive", "idle",
                          "none", "default")


def inactive_tieoff(port_type: str, sources: Sequence[Tuple[str, str]]
                    ) -> Optional[str]:
    """The package's own named INACTIVE constant for `port_type`, or None.

    `port_type` is `<pkg>::<type>`. The constant must be declared in that
    package, with that type, and its name must be an inactive-state word. No
    guessing: a package that names none yields None and the caller ties 0 and
    says so."""
    if "::" not in str(port_type or ""):
        return None
    pkg, tname = port_type.split("::", 1)
    for _path, text in sources:
        if not re.search(r"^\s*package\s+" + re.escape(pkg) + r"\s*;",
                         text, re.M):
            continue
        best = None
        for m in re.finditer(r"\bparameter\s+" + re.escape(tname)
                             + r"\s+(\w+)\s*=", text):
            nm = m.group(1)
            if _norm(nm) in _INACTIVE_CONST_TOKENS or any(
                    t in _norm(nm) for t in _INACTIVE_CONST_TOKENS):
                best = best or f"{pkg}::{nm}"
        if best:
            return best
    return None


def dut_port_types(rtl_text: str, dut_module: str) -> Dict[str, str]:
    """`{port: '<pkg>::<type>'}` for every package-typed port of the DUT."""
    m = re.search(r"\bmodule\s+" + re.escape(dut_module)
                  + r"\b(?P<hdr>.*?)\bendmodule\b", rtl_text or "", re.S)
    if not m:
        return {}
    out = {}
    for mm in re.finditer(
            r"\b(?:input|output)\s+(\w+::\w+)\s+(\w+)", m.group("hdr")):
        out[mm.group(2)] = mm.group(1)
    return out


def find_req_rsp_pairs(ports: Sequence[Tuple[str, str, str]],
                       rtl_text: str, dut_module: str) -> List[dict]:
    """Every request/response port PAIR the DUT exposes to an outside service.

    Shape, from the design's own module header: an `output <pkg>::<x>_req_t` and
    an `input <pkg>::<x>_rsp_t`. That is a service the DUT ASKS FOR and cannot
    provide itself — on opentitan_aes it is the entropy interface, and the
    design's own document says the unit "will first reseed the internal PRNGs
    ... via EDN" and only then becomes idle. With nothing answering, the unit
    never reaches idle and every configuration write is ignored by its own
    documented rule.

    Returned so the caller can DECLARE an environment model for each one. It is
    never wired into the DUT: the DUT is instantiated unchanged."""
    m = re.search(r"\bmodule\s+" + re.escape(dut_module)
                  + r"\b(?P<hdr>.*?)\bendmodule\b", rtl_text or "", re.S)
    if not m:
        return []
    hdr = m.group("hdr")
    reqs, rsps = {}, {}
    for direction, table in (("output", reqs), ("input", rsps)):
        for mm in re.finditer(
                r"\b" + direction + r"\s+([\w]+)::(\w+?)_(req|rsp)_t\s+(\w+)",
                hdr):
            pkg, base, kind, port = mm.groups()
            if (direction == "output") == (kind == "req"):
                table[(pkg, base)] = (port, f"{pkg}::{base}_{kind}_t")
    out = []
    for key in sorted(set(reqs) & set(rsps)):
        pkg, base = key
        out.append({"pkg": pkg, "base": base,
                    "req_port": reqs[key][0], "req_type": reqs[key][1],
                    "rsp_port": rsps[key][0], "rsp_type": rsps[key][1]})
    return out


# --------------------------------------------------------------------------
# PARAMETER-BOUND WIDTHS (issue #2035, family 3)
#
# A driver that assumes a width the DUT does not actually have is wrong in a way
# that no waveform makes obvious: the transaction is accepted and the upper bits
# are silently lost. The width a port really has is DECLARED in the design's own
# input — a parameter with a default, possibly overridden where the module is
# instantiated. So it is READ, never assumed, and when it cannot be read the
# caller is told WHICH symbol blocked it instead of receiving a guess.
# --------------------------------------------------------------------------
#: Bounds for evaluating a width expression read out of a design file.
#: A real bus is not a million bits wide, and a legitimate `2**N` / `1<<N` has a
#: small literal exponent. Anything outside these is refused, never computed.
_WIDTH_EXPR_MAX = 1 << 20
_WIDTH_EXPR_EXP_MAX = 64

#: A DECLARATION ENDS AT ITS OWN TERMINATOR, NOT AT THE END OF THE LINE.
#: The value used to be captured as `[^,\n]+` -- a deliberate bound, because a
#: capture that runs on swallows the NEXT declaration. But a real design writes
#: a long constant across two lines:
#:
#:     parameter int RsvdWidth = top_pkg::TL_AUW - prim_mubi_pkg::MuBi4Width -
#:                               H2DCmdIntgWidth - DataIntgWidth;
#:
#: and the capture stopped at the newline, so the value was the dangling
#: `A - B -`, failed to parse, and every port declared over `RsvdWidth` refused
#: on a number the design states in full.
#:
#: So the pattern now ends at the `=` and captures NOTHING; `_trim_value` reads
#: the value from there and cuts at the declaration's own terminator -- a `,`
#: or `;` at bracket depth 0, or the `)` that closes the parameter header. The
#: bound moved from the LINE to BRACKET DEPTH, which is where a declaration
#: actually ends, so it still cannot swallow the next one -- and a `,` inside
#: `(...)`, `[...]` or a `{...}` concatenation is no longer a terminator either.
#: Ending the match at the `=` also matters for `finditer`: a capture that ran
#: past the newline would CONSUME the following declarations and they would
#: never be matched at all.
_PARAM_DECL_RE = re.compile(
    r"\bparameter\b(?:\s+(?:int|integer|logic|bit|byte|shortint|longint"
    r"|unsigned|signed))*\s*(?:\[[^\]]*\]\s*)?(\w+)\s*=\s*")

#: The same shape for a LOCALPARAM. SystemVerilog allows one in the parameter
#: PORT LIST, and that is where a design puts a width it derives from its own
#: parameters -- `localparam int IdxW = $clog2(N)` -- which is then the declared
#: width of a real port. Reading only `parameter` left every such port
#: unresolvable even though the design states the value one line above it.
#: A localparam is NOT overridable at instantiation, which is why it is kept in
#: a separate harvest (`dut_header_constants`) rather than folded into
#: `dut_parameter_defaults`, whose result is merged with instantiation
#: overrides by `resolve_bus_widths`.
_LOCALPARAM_DECL_RE = re.compile(
    r"\blocalparam\b(?:\s+(?:int|integer|logic|bit|byte|shortint|longint"
    r"|unsigned|signed))*\s*(?:\[[^\]]*\]\s*)?(\w+)\s*=\s*")

#: `$clog2` is the one system function that appears in a width expression often
#: enough to matter, and it is a pure integer function of one integer, so it can
#: be evaluated exactly. Every other `$...` stays unresolvable and refuses.
_CLOG2_RE = re.compile(r"\$clog2\s*\(")


#: A width bound may be SCOPE-QUALIFIED -- `[top_pkg::TL_DW-1:0]` is an ordinary
#: SystemVerilog port width. `::` is not Python, so the AST evaluator below could
#: not even PARSE such an expression and every scoped bound refused, no matter
#: what the package said. The scope operator is rewritten to a name sequence
#: before parsing, and the SAME rewrite is applied to the parameter map's keys,
#: so `top_pkg::TL_DW` resolves exactly like an unscoped name -- and an unknown
#: one still refuses by its FULL scoped name.
#:
#: The marker is checked for FIRST: if the text already contains it, the rewrite
#: would be ambiguous, so the expression REFUSES rather than being mangled into
#: something that means something else.
_SCOPE_SEP = "__pkgscope__"
_SCOPE_OP_RE = re.compile(r"\s*::\s*")


def _mangle_scope(text: str) -> Optional[str]:
    """`a::b` -> `a__pkgscope__b`, or None when the rewrite is not unambiguous."""
    if _SCOPE_SEP in text:
        return None
    return _SCOPE_OP_RE.sub(_SCOPE_SEP, text)


def _mangle_params(params: Dict[str, int]) -> Dict[str, int]:
    """`params` with every scoped key rewritten the same way as an expression.

    A key that cannot be rewritten unambiguously is DROPPED, so a width over it
    refuses by name instead of resolving against a mangled near-miss.

    A non-INTEGER value is dropped for the same reason. Every harvest in this
    file stores only integers, but a caller may hand this evaluator anything,
    and once a width can be a constant CHOICE a non-integer no longer has to
    take part in the arithmetic to reach the answer: `A ? 1 : 2` would simply
    have found a string TRUTHY and returned a width. Dropping the name refuses
    by name instead. (`bool` is not an integer here either -- this evaluator
    has always refused to return one.)
    """
    out: Dict[str, int] = {}
    for k, v in (params or {}).items():
        if not isinstance(v, int) or isinstance(v, bool):
            continue
        mk = _mangle_scope(str(k))
        if mk is not None:
            out[mk] = v
    return out


#: VERILOG INTEGER DIVISION IS NOT PYTHON DIVISION. `localparam int RegBw =
#: RegDw/8` is ordinary SystemVerilog and IEEE 1364 says `/` on integers
#: TRUNCATES; Python's `/` yields a float, so the value came back non-integer
#: and the constant -- and every width declared over it -- refused on a number
#: the design states in full. `%` has the same problem. Both are rewritten to
#: integer helpers before evaluation rather than added to the operator
#: whitelist, so the arithmetic is Verilog's, not Python's.
#:
#: The table is `{name: arity}`. A call to anything not in it REFUSES: this
#: stays an arithmetic evaluator over the design's own constants, and running
#: the design's own FUNCTIONS (`prim_util_pkg::vbits(N)`) is not arithmetic.
_CONST_FUNCS = {"clog2": 1, "idiv": 2, "imod": 2,
                "ltoi": 1, "land": 2, "lor": 2, "lnot": 1}


def _idiv(a: int, b: int) -> int:
    """IEEE 1364 integer `/`: truncate toward zero. Division by zero raises,
    which the caller turns into a refusal."""
    if b == 0:
        raise ZeroDivisionError("integer division by zero")
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def _imod(a: int, b: int) -> int:
    """IEEE 1364 integer `%`: the sign follows the DIVIDEND."""
    if b == 0:
        raise ZeroDivisionError("integer modulo by zero")
    r = abs(a) % abs(b)
    return -r if a < 0 else r


#: A WIDTH IS SOMETIMES A CONSTANT CHOICE, NOT A CONSTANT SUM.
#: `localparam int DataOutW = EnableDataIntgPt ? SramDw + IntgWidth : SramDw`
#: states the width completely -- both arms, and the constant that picks between
#: them -- and an arithmetic-only evaluator could not even PARSE `?:`, `&&`,
#: `||` or `!`, so every port declared over such a constant refused on a number
#: the design states in full. Measured on the corpus: 48 such declarations, 21
#: of them needing a relational operator.
#:
#: The widening is BOUNDED and stays the same machinery: the Verilog forms are
#: REWRITTEN to the whitelisted-AST evaluator (integer results, no names it has
#: not harvested, no side effects, never `eval` of the design's own text). A
#: relational or logical result is an INTEGER 1/0, as in Verilog -- never a
#: Python bool, which this evaluator has always refused.
_TERNARY_NEST_MAX = 64
_OPENERS = "([{"
_CLOSERS = ")]}"

#: The operand of a Verilog `!`: a parenthesised group, a name, a literal, or
#: another `!`.
_NOT_PRIMARY_RE = re.compile(r"[A-Za-z_]\w*|\d[\w']*|'[sSdDhHbBoO][0-9a-fA-F_]+")


def _ltoi(v) -> int:
    """A relational result as Verilog states it: the integer 1 or 0."""
    return 1 if v else 0


def _land(a, b) -> int:
    """Verilog `&&` over constants. Both operands are already evaluated, so a
    division by zero in the right-hand operand REFUSES rather than being
    short-circuited away -- an honest refusal, not a guessed 0."""
    return 1 if (a and b) else 0


def _lor(a, b) -> int:
    """Verilog `||` over constants."""
    return 1 if (a or b) else 0


def _lnot(a) -> int:
    """Verilog `!` over a constant."""
    return 0 if a else 1


def _match_bracket(s: str, i: int) -> int:
    """Index of the bracket closing the opener at `s[i]`, or -1."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] in _OPENERS:
            depth += 1
        elif s[j] in _CLOSERS:
            depth -= 1
            if depth == 0:
                return j
    return -1


def _not_operand_span(s: str, j: int, budget: int):
    """`(start, end)` of the PRIMARY that a `!` at `s[j-1]` negates, or None."""
    if budget <= 0:
        return None
    while j < len(s) and s[j].isspace():
        j += 1
    if j >= len(s):
        return None
    if s[j] == "!" and not (j + 1 < len(s) and s[j + 1] == "="):
        inner = _not_operand_span(s, j + 1, budget - 1)
        return None if inner is None else (j, inner[1])
    if s[j] in _OPENERS:
        k = _match_bracket(s, j)
        return None if k < 0 else (j, k + 1)
    m = _NOT_PRIMARY_RE.match(s, j)
    return (j, m.end()) if m else None


def _rewrite_not(s: str, budget: int = _TERNARY_NEST_MAX) -> Optional[str]:
    """Verilog `!x` -> `lnot(x)`, at VERILOG's precedence.

    NOT a textual `!` -> `not`. Python's `not` binds LOOSER than `==` and
    Verilog's `!` binds TIGHTER, so `!a == b` would silently change meaning --
    from `(!a) == b` to `!(a == b)`. Rewriting to a CALL over the operand
    primary keeps the design's own grouping. `!=` is left alone; anything the
    operand scan cannot name REFUSES.
    """
    if budget <= 0:
        return None
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch != "!" or (i + 1 < len(s) and s[i + 1] == "="):
            out.append(ch)
            i += 1
            continue
        span = _not_operand_span(s, i + 1, budget)
        if span is None:
            return None
        inner = _rewrite_not(s[span[0]:span[1]], budget - 1)
        if inner is None:
            return None
        out.append("lnot(" + inner + ")")
        i = span[1]
    return "".join(out)


def _rewrite_groups(s: str, budget: int) -> Optional[str]:
    """`_rewrite_ternary` applied INSIDE every bracketed group of `s`.

    A ternary is legitimately nested inside a call -- `$clog2(ExplicitErrs ?
    N+1 : N)` -- so a rewrite that only looked at bracket depth 0 would leave
    exactly that shape unparsable.
    """
    if budget <= 0:
        return None
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch in _OPENERS:
            k = _match_bracket(s, i)
            if k < 0:
                return None
            inner = _rewrite_ternary(s[i + 1:k], budget - 1)
            if inner is None:
                return None
            out.append(ch + inner + s[k])
            i = k + 1
            continue
        if ch in _CLOSERS:
            return None                 # unbalanced: refuse rather than guess
        out.append(ch)
        i += 1
    return "".join(out)


def _rewrite_ternary(s: str, budget: int = _TERNARY_NEST_MAX) -> Optional[str]:
    """Verilog `c ? a : b` -> Python `((a) if (c) else (b))`, or None.

    Right-associative, as SystemVerilog is: the `:` that closes a `?` is the
    first one at the same bracket depth that no nested `?` has claimed, so
    `c1 ? a : c2 ? b : d` groups as `c1 ? a : (c2 ? b : d)`. Each part is
    parenthesised on the way out, so the design's own grouping survives the
    difference between Verilog's and Python's precedence tables.

    By the time this runs the scope operator has already been mangled away, so
    every remaining `:` at depth 0 is a ternary separator; one without a `?`
    is left alone and the parse below refuses it.
    """
    if budget <= 0:
        return None
    depth = q = 0
    q = -1
    for i, ch in enumerate(s):
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            depth -= 1
            if depth < 0:
                return None
        elif ch == "?" and depth == 0:
            q = i
            break
    if q < 0:
        return _rewrite_groups(s, budget)
    depth, pending, c = 0, 0, -1
    for i in range(q + 1, len(s)):
        ch = s[i]
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and ch == "?":
            pending += 1
        elif depth == 0 and ch == ":":
            if pending == 0:
                c = i
                break
            pending -= 1
    if c < 0:
        return None                      # a `?` with no `:` is not a ternary
    cond = _rewrite_ternary(s[:q], budget - 1)
    tval = _rewrite_ternary(s[q + 1:c], budget - 1)
    fval = _rewrite_ternary(s[c + 1:], budget - 1)
    if cond is None or tval is None or fval is None:
        return None
    return "((" + tval + ") if (" + cond + ") else (" + fval + "))"


def _clog2(n: int) -> int:
    """IEEE 1800 `$clog2`: the number of bits needed to index `n` values.

    $clog2(0) and $clog2(1) are 0; $clog2(2) is 1; $clog2(9) is 4.
    """
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise ValueError("clog2 of a non-negative integer only")
    return 0 if n <= 1 else (n - 1).bit_length()


def _int_expr(expr: str, params: Dict[str, int]) -> Optional[int]:
    """Evaluate a width expression over integer literals and KNOWN parameters.

    Returns None — never a default — when any symbol is unknown, so an
    unresolvable width becomes a refusal rather than a silent 32.
    """
    import ast as _ast
    # ONE EXPRESSION, WHATEVER LINE IT IS ON. A declaration's value legitimately
    # spans two lines, and a NEWLINE ends an expression in Python -- so the
    # value read across the line break parsed as a syntax error and refused on
    # arithmetic it states completely. Whitespace is collapsed before parsing;
    # Verilog has no whitespace-sensitive expression syntax to lose.
    text = " ".join(str(expr).split()).rstrip(";")
    # SCOPE-QUALIFIED names first: `top_pkg::TL_DW` is a legal width bound and
    # `::` is not Python, so without this the parse below fails and every
    # package-scoped width refuses whatever the package says.
    params = _mangle_params(params)
    mangled = _mangle_scope(text)
    if mangled is None:
        return None
    text = mangled
    # SystemVerilog sized literal: 8'd12 / 32'h20 / 'd7
    m = re.fullmatch(r"(?:\d+)?'[sS]?[dDhHbBoO]?([0-9a-fA-F_]+)", text)
    if m:
        base = {"h": 16, "b": 2, "o": 8}.get(text.split("'")[1][0].lower(), 10)
        try:
            return int(m.group(1).replace("_", ""), base)
        except ValueError:
            return None
    # `$clog2(N)` is not Python. Rewrite ONLY that one system function to a
    # plain call; any other `$...` is left alone and fails to parse, which is
    # the refusal we want.
    text = _CLOG2_RE.sub("clog2(", text)
    # VERILOG'S BOOLEAN FORMS ARE NOT PYTHON'S. `&&`, `||` and `!` are not
    # Python operators and `c ? a : b` is not Python syntax at all, so a width
    # written as a constant CHOICE did not parse and refused whatever the
    # design said. `&&`/`||` map onto Python's own `and`/`or`, whose precedence
    # against relational operators is Verilog's; `!` and `?:` are rewritten
    # structurally, because their precedence is NOT.
    text = text.replace("&&", " and ").replace("||", " or ")
    text = _rewrite_not(text)
    if text is None:
        return None
    text = _rewrite_ternary(text)
    if text is None:
        return None
    try:
        tree = _ast.parse(text, mode="eval")
    except SyntaxError:
        return None

    def _call(fn, args, node):
        return _ast.copy_location(
            _ast.Call(func=_ast.Name(id=fn, ctx=_ast.Load()),
                      args=args, keywords=[]), node)

    class _VerilogIntOps(_ast.NodeTransformer):
        """Verilog's arithmetic and logic, not Python's.

        `a / b` -> `idiv(a, b)`, `a % b` -> `imod(a, b)`, and every RELATIONAL
        or LOGICAL result -> the integer 1/0 Verilog states it as. Without the
        last part a comparison would come back as a Python bool, which this
        evaluator refuses by design -- so the wrapping is what lets a width be
        a constant choice at all.
        """

        def visit_BinOp(self, node):          # noqa: N802 — ast API name
            self.generic_visit(node)
            if isinstance(node.op, (_ast.Div, _ast.Mod)):
                fn = "idiv" if isinstance(node.op, _ast.Div) else "imod"
                return _call(fn, [node.left, node.right], node)
            return node

        def visit_Compare(self, node):        # noqa: N802 — ast API name
            self.generic_visit(node)
            if len(node.ops) != 1:
                # `a < b < c` is a CHAIN in Python and `(a<b)<c` in Verilog.
                # Left un-wrapped so the walk below refuses it by name rather
                # than evaluating one language's meaning of the other's text.
                return node
            return _call("ltoi", [node], node)

        def visit_BoolOp(self, node):         # noqa: N802 — ast API name
            self.generic_visit(node)
            fn = "land" if isinstance(node.op, _ast.And) else "lor"
            folded = node.values[0]
            for nxt in node.values[1:]:
                folded = _call(fn, [folded, nxt], node)
            return folded

        def visit_UnaryOp(self, node):        # noqa: N802 — ast API name
            self.generic_visit(node)
            if isinstance(node.op, _ast.Not):
                return _call("lnot", [node.operand], node)
            return node

    tree = _ast.fix_missing_locations(_VerilogIntOps().visit(tree))
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Name) and node.id not in params \
                and node.id not in _CONST_FUNCS:
            return None
        if not isinstance(node, (_ast.Expression, _ast.BinOp, _ast.UnaryOp,
                                 _ast.Constant, _ast.Name, _ast.Load,
                                 _ast.Add, _ast.Sub, _ast.Mult, _ast.USub,
                                 _ast.UAdd, _ast.FloorDiv, _ast.LShift,
                                 _ast.RShift, _ast.Pow, _ast.Call,
                                 # the constant-choice forms, and NOTHING else:
                                 # no subscript, no attribute, no comprehension.
                                 _ast.IfExp, _ast.BoolOp, _ast.And, _ast.Or,
                                 _ast.Not, _ast.Compare, _ast.Lt, _ast.LtE,
                                 _ast.Gt, _ast.GtE, _ast.Eq, _ast.NotEq)):
            return None
        if isinstance(node, _ast.Compare) and len(node.ops) != 1:
            return None      # a comparison CHAIN means different things in the
                             # two languages; refuse rather than pick one
        # A CALL is allowed for exactly one name, with exactly one argument.
        # Anything else -- another function, a method, a keyword or starred
        # argument -- refuses. This stays an arithmetic evaluator.
        if isinstance(node, _ast.Call):
            if (not isinstance(node.func, _ast.Name)
                    or node.func.id not in _CONST_FUNCS
                    or len(node.args) != _CONST_FUNCS[node.func.id]
                    or node.keywords):
                return None
        # BOUNDED. A width expression comes out of the DESIGN'S OWN FILE, so it
        # is input, and input must never be able to wedge the flow. `9**9**9`
        # parses to a legal tree of allowed nodes and then computes forever with
        # no diagnostic. Every operand is bounded here, and an exponent or shift
        # distance must be a small literal, so an unreasonable expression is
        # REFUSED (None, like every other unresolvable width) instead of hanging.
        if isinstance(node, _ast.Constant):
            if not isinstance(node.value, int) or isinstance(node.value, bool):
                return None
            if abs(node.value) > _WIDTH_EXPR_MAX:
                return None
        if isinstance(node, _ast.BinOp) and isinstance(node.op, (_ast.Pow,
                                                                _ast.LShift)):
            # `2**ADDR_W` and `1<<ADDR_W` are ordinary SystemVerilog, so the
            # exponent may be a PARAMETER as well as a literal — it just has to
            # RESOLVE to something small. Anything else refuses.
            rhs = node.right
            if isinstance(rhs, _ast.Constant):
                rv = rhs.value
            elif isinstance(rhs, _ast.Name):
                rv = params.get(rhs.id)
            else:
                return None
            if not isinstance(rv, int) or isinstance(rv, bool) \
                    or not 0 <= rv <= _WIDTH_EXPR_EXP_MAX:
                return None
    try:
        _ns = dict(params)
        _ns.update(clog2=_clog2, idiv=_idiv, imod=_imod,
                   ltoi=_ltoi, land=_land, lor=_lor, lnot=_lnot)
        val = eval(compile(tree, "<width>", "eval"), {"__builtins__": {}}, _ns)
    except Exception:
        return None
    if not isinstance(val, int) or isinstance(val, bool):
        return None
    if abs(val) > _WIDTH_EXPR_MAX:
        return None          # a bus wider than this is not a width, it is a typo
    return int(val)


def _dut_header_text(rtl_text: str, dut_module: str) -> str:
    """The text INSIDE `dut_module`'s `#( ... )` parameter header, or "".

    Split out so the parameter harvest and the parameter+localparam harvest
    below cannot drift apart: they are the same slice of the same file, read
    once, and only the declaration keyword differs.
    """
    # Comments are blanked FIRST. A `)` inside a comment -- "no ')' ever" is
    # enough -- closed the header early and truncated the parameter list, and a
    # `(` inside one held it open. Offsets are preserved by the blanker.
    code = _hdl_code_text.strip_hdl_comments_and_strings(rtl_text or "")
    # A package IMPORT may sit between the module name and its parameter
    # header:  `module prim_count\n  import prim_count_pkg::*;\n#(`.
    # Requiring only whitespace there made this slicer find nothing for every
    # such module, so every width declared over those parameters became
    # unresolvable -- the SAME header-import blindness ORGANIC #701 fixed in the
    # module ENUMERATOR, one regex later in the same file set.
    m = re.search(r"\bmodule\s+" + re.escape(dut_module)
                  + r"\b\s*(?:import\s+[^;]+;\s*)*#\s*\(", code)
    if not m:
        return ""
    i = m.end() - 1
    depth, j = 0, i
    while j < len(code):
        if code[j] == "(":
            depth += 1
        elif code[j] == ")":
            depth -= 1
            if depth == 0:
                break
        j += 1
    if depth != 0:
        # The header is never closed, so the scan ran to EOF and the slice now
        # spans other modules. Measured: an unterminated `#(` harvested `ZZ` out
        # of the NEXT module's header and offered it as this DUT's parameter.
        # An unparsable header yields NO parameters rather than someone else's.
        return ""
    return code[i:j]


def _trim_value(text: str) -> str:
    """A declaration's value: everything up to the declaration's OWN terminator.

    The terminator is a `,` or `;` at bracket depth 0, or a closing bracket
    with no opener of its own -- the `)` that closes the parameter header. It
    is NOT the end of the line: a design writes a long constant across two
    lines and the value carries on (see `_PARAM_DECL_RE`).

    Every bracket kind counts toward the depth, so a `,` inside a call, a
    packed range or a `{...}` concatenation is part of the value and not a
    terminator -- and `localparam int IdxW = $clog2(N)` keeps its own `)`,
    which is what this function was written for: stopping at the FIRST `)`
    truncated it to `$clog2(N`, the parse failed, the constant was silently
    absent, and every port declared over it refused.

    A value with no terminator at all runs to the end of the text and simply
    fails to evaluate, which is a refusal by name and not a wrong width.
    """
    depth = 0
    for i, ch in enumerate(text):
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            if depth == 0:
                return text[:i].strip()
            depth -= 1
        elif depth == 0 and ch in ",;":
            return text[:i].strip()
    return text.strip()


def _decl_hits(text: str, *regexes) -> List[Tuple[int, str, str]]:
    """`[(position, NAME, value)]` for every declaration `regexes` match.

    One place, so the four harvests in this file cannot drift on where a
    declaration's value ends. The match itself stops at the `=`; the value is
    read from there by `_trim_value`.
    """
    hits: List[Tuple[int, str, str]] = []
    for rx in regexes:
        for m in rx.finditer(text):
            hits.append((m.start(), m.group(1), _trim_value(text[m.end():])))
    return hits


def _harvest(header: str, *regexes,
             seed: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    """`{NAME: value}` for every declaration `regexes` match, IN SOURCE ORDER.

    Order is the point: a derived constant is written after the things it is
    derived from (`localparam int IdxW = $clog2(N)` after `parameter int N`),
    so feeding the accumulated map back in as it grows resolves the chain in
    one pass. A declaration that does not resolve is simply absent -- never a
    default -- so a width over it refuses by name.

    `seed` is what is in scope BEFORE the module's own declarations: the
    packages it imports and every package constant under its scoped name. A
    module's own default is legitimately written over one of those --
    `parameter int DATA_WIDTH = top_pkg::TL_DW` -- and harvesting the header
    against nothing but itself left DATA_WIDTH unknown, and every port declared
    over it refusing, on a number stated in a file the same run had already
    read. The module's OWN names still win: `out` is layered over `seed`.
    """
    hits = _decl_hits(header, *regexes)
    base = dict(seed or {})
    out: Dict[str, int] = {}
    for _pos, name, expr in sorted(hits):
        val = _int_expr(expr, {**base, **out})
        if val is not None:
            out[name] = val
    return out


def dut_parameter_defaults(rtl_text: str, dut_module: str) -> Dict[str, int]:
    """`{PARAM: default}` for the DUT's own parameter header, input only.

    PARAMETERS ONLY. `resolve_bus_widths` merges instantiation OVERRIDES over
    this map, and a localparam cannot be overridden, so localparams are kept out
    of it and offered separately by `dut_header_constants`.
    """
    return _harvest(_dut_header_text(rtl_text, dut_module), _PARAM_DECL_RE)


def dut_header_constants(rtl_text: str, dut_module: str,
                         seed: Optional[Dict[str, int]] = None
                         ) -> Dict[str, int]:
    """`{NAME: value}` for the DUT header's parameters AND its localparams.

    This is what a port declaration is actually written against. A design that
    derives its index width once and uses it on a port --

        parameter  int N    = 8,
        localparam int IdxW = $clog2(N)
        ) ( ... output logic [IdxW-1:0] idx_o ... )

    -- states that width completely; reading only `parameter` left `IdxW`
    unknown and the port unresolvable. Measured over the corpus, this shape is
    the ENTIRE residual: 17 instantiation-graph roots in one vendor tree.

    Not merged into `dut_parameter_defaults` because that map is merged with
    instantiation overrides, and overriding a localparam is not a thing.
    """
    return _harvest(_dut_header_text(rtl_text, dut_module),
                    _PARAM_DECL_RE, _LOCALPARAM_DECL_RE, seed=seed)


#: A PACKAGE is where a design puts the constants more than one module is
#: declared over -- `package top_pkg; localparam int TL_DW = 32; endpackage`.
#: A module reaches them either by SCOPE (`[top_pkg::TL_DW-1:0]`) or by IMPORT
#: (`module m import aes_reg_pkg::*; #(...) (... [NumRegsData-1:0] ...)`).
#: Reading only the module's own text left every such width unresolvable even
#: though the design states the number in a file the same run already has.
_PACKAGE_RE = re.compile(
    r"\bpackage\s+([A-Za-z_]\w*)\s*;(.*?)\bendpackage\b", re.S)

#: The import list a module may carry between its name and its `#(` / port list.
_MODULE_IMPORT_LIST_RE = r"\b\s*((?:import\s+[^;]+;\s*)*)"

#: `import <pkg>::*;` / `import <pkg>::<name>;` inside such a list.
_IMPORT_PKG_RE = re.compile(r"\b([A-Za-z_]\w*)\s*::\s*(?:\*|[A-Za-z_]\w*)")


def _dut_module_text(code: str, dut_module: str) -> str:
    """`dut_module`'s own text in ALREADY-BLANKED `code`, header included.

    From the module name to its `endmodule`. Returns "" when either end is
    absent, so an unterminated module contributes NOTHING rather than the next
    module's declarations -- the same rule `_dut_header_text` applies to an
    unterminated parameter header.
    """
    m = re.search(r"\bmodule\s+" + re.escape(dut_module) + r"\b", code)
    if not m:
        return ""
    e = re.search(r"\bendmodule\b", code[m.end():])
    return code[m.end():m.end() + e.start()] if e else ""


def _dut_body_text(rtl_text: str, dut_module: str) -> str:
    """`dut_module`'s text with its `#( ... )` parameter header BLANKED OUT.

    Offsets are preserved (the header is replaced by spaces, not removed) so a
    harvest over this text and one over the header cannot disagree about which
    declaration came first.
    """
    code = _hdl_code_text.strip_hdl_comments_and_strings(rtl_text or "")
    body = _dut_module_text(code, dut_module)
    if not body:
        return ""
    hdr = _dut_header_text(rtl_text, dut_module)
    if hdr:
        i = body.find(hdr)
        if i >= 0:
            body = body[:i] + (" " * len(hdr)) + body[i + len(hdr):]
    return body


def dut_body_constants(rtl_text: str, dut_module: str,
                       seed: Optional[Dict[str, int]] = None
                       ) -> Dict[str, int]:
    """`{NAME: value}` for constants `dut_module` declares in its BODY.

    Verilog-1995 has NO parameter header at all. The width is stated completely,
    in the body, one line below the port list:

        module ram (rd_out, addr_in, ...);
          parameter BITS = 39;
          output reg [BITS-1:0] rd_out;

    Reading only the `#( ... )` header left every port of every such module
    unresolvable, and a behavioural memory model is exactly the shape that has
    no header.

    AMBIGUITY IS DROPPED, NEVER RESOLVED BY POSITION. A body may declare the
    same name more than once -- in two arms of a `generate`, or inside a
    function -- and those are not the module-scope constant a port is declared
    over. A name whose body declarations do not AGREE on a value is left out, so
    a width over it refuses by name instead of taking whichever came first.
    """
    body = _dut_body_text(rtl_text, dut_module)
    if not body:
        return {}
    hits = _decl_hits(body, _PARAM_DECL_RE, _LOCALPARAM_DECL_RE)
    base = dict(seed or {})
    out: Dict[str, int] = {}
    seen: Dict[str, List[Optional[int]]] = {}
    for _pos, name, expr in sorted(hits):
        val = _int_expr(expr, {**base, **out})
        seen.setdefault(name, []).append(val)
        if val is not None:
            out[name] = val
    for name, vals in seen.items():
        if len({v for v in vals if v is not None}) > 1:
            out.pop(name, None)
    return out


def dut_scope_constants(rtl_text: str, dut_module: str,
                        seed: Optional[Dict[str, int]] = None
                        ) -> Dict[str, int]:
    """Every constant visible where `dut_module`'s ports are declared, from
    THIS text alone: its parameter header, then its body.

    The header WINS a name clash: it is the module's interface, and a body
    declaration of the same name is either a shadow or a duplicate.
    """
    out = dict(dut_body_constants(rtl_text, dut_module, seed=seed))
    out.update(dut_header_constants(rtl_text, dut_module, seed=seed))
    return out


def dut_imported_packages(rtl_text: str, dut_module: str) -> List[str]:
    """The packages `dut_module` IMPORTS, in source order.

    `module aes_control import aes_pkg::*; import aes_reg_pkg::*; #(` — the
    names those packages export are in scope for every port declaration below,
    which is where `[NumRegsData-1:0]` comes from.
    """
    code = _hdl_code_text.strip_hdl_comments_and_strings(rtl_text or "")
    m = re.search(r"\bmodule\s+" + re.escape(dut_module)
                  + _MODULE_IMPORT_LIST_RE, code)
    if not m:
        return []
    out: List[str] = []
    for im in _IMPORT_PKG_RE.finditer(m.group(1) or ""):
        if im.group(1) not in out:
            out.append(im.group(1))
    return out


def _module_declaring_file(sources: Sequence[Tuple[object, str]],
                           module: str) -> Optional[object]:
    """The path of the FIRST source that declares `module`, or None.

    Comments are blanked first: a sentence that names the module is not a
    declaration (#731).
    """
    if not module:
        return None
    pat = re.compile(r"\bmodule\s+" + re.escape(str(module)) + r"\b")
    for path, raw in sources or []:
        code = _hdl_code_text.strip_hdl_comments_and_strings(raw or "")
        if pat.search(code):
            return path
    return None


def _path_parts(path: object) -> List[str]:
    """`path` as directory segments, separator-agnostic."""
    return [s for s in re.split(r"[\\/]+", str(path)) if s not in ("", ".")]


def _source_tree_distance(a: object, b: object) -> int:
    """Directory steps between two source files: 0 in the same directory.

    This is how far apart the design keeps two files, and it is the only thing
    in the INPUT that says which copy of a duplicated package the elaboration
    of a given top actually compiles: a tool is handed a file list rooted where
    the top's own modules live, and a copy sitting outside that tree is not on
    it. Nothing here reads a directory NAME, so no convention is assumed.
    """
    da, db = _path_parts(a)[:-1], _path_parts(b)[:-1]
    i = 0
    while i < len(da) and i < len(db) and da[i] == db[i]:
        i += 1
    return (len(da) - i) + (len(db) - i)


def _package_fixpoint(bodies: Dict[str, List[Tuple[object, str]]]
                      ) -> Tuple[Dict[str, Dict[str, int]],
                                 Dict[str, Dict[str, set]]]:
    """`(constants, per-package {NAME: {values seen in each body}})`.

    Resolved to a FIXPOINT because one package legitimately states a constant
    over another's (`localparam int W = other_pkg::Base * 2`). Each round
    re-offers everything resolved so far; the loop stops the round nothing new
    resolves, so a genuinely circular or unresolvable constant is simply ABSENT
    and every width over it refuses by name.

    ONE NAME, TWO DECLARATIONS, TWO VALUES -> AMBIGUOUS, NOT FIRST-WINS. Every
    body is harvested; a name survives only if the bodies that resolve it
    AGREE. The second return value reports what each body said, so a caller can
    tell an agreement from a silence.
    """
    out: Dict[str, Dict[str, int]] = {p: {} for p in bodies}
    said: Dict[str, Dict[str, set]] = {p: {} for p in bodies}
    for _round in range(len(bodies) + 1):
        changed = False
        scoped = {f"{p}::{k}": v for p, d in out.items() for k, v in d.items()}
        for pkg, blist in bodies.items():
            local = out[pkg]
            seen: Dict[str, set] = {}
            for _path, body in blist:
                hits = _decl_hits(body, _PARAM_DECL_RE, _LOCALPARAM_DECL_RE)
                acc = dict(local)
                for _pos, name, expr in sorted(hits):
                    val = _int_expr(expr, {**scoped, **acc})
                    if val is not None:
                        acc[name] = val
                        seen.setdefault(name, set()).add(val)
            for name, vals in seen.items():
                said[pkg].setdefault(name, set()).update(vals)
                if name in local or len(vals) != 1:
                    continue
                local[name] = next(iter(vals))
                changed = True
        if not changed:
            break
    return out, said


def _bodies_diverge(pkg: str, blist: Sequence[Tuple[object, str]],
                    said: Dict[str, set],
                    constants: Dict[str, int]) -> bool:
    """True when the copies of `pkg` do not describe the SAME package.

    Two copies diverge when they disagree on a value (a name with more than one
    value) or when one states a constant the other does not. Copies that state
    the same names with the same values are the same package written twice, and
    nothing has to be decided about them -- they resolve exactly as one copy
    would, with no note.
    """
    if any(len(v) > 1 for v in said.values()):
        return True
    names = None
    for _path, body in blist:
        here = {n for _pos, n, _e in
                _decl_hits(body, _PARAM_DECL_RE, _LOCALPARAM_DECL_RE)}
        if names is None:
            names = here
        elif names != here:
            return True
    return False


def package_constants(sources: Sequence[Tuple[object, str]],
                      top: Optional[str] = None,
                      notes: Optional[List[str]] = None
                      ) -> Dict[str, Dict[str, int]]:
    """`{package: {NAME: value}}` for every package declared in `sources`.

    ONE PACKAGE DECLARED TWICE, WITH TWO DIFFERENT VALUES, IS NOT AMBIGUOUS IF
    THE DESIGN SAYS WHICH COPY IT BUILDS. Measured: a source set that carries a
    package twice -- once beside the RTL the top instantiates, once beside the
    documents -- agreeing on 17 constants and disagreeing on one. Refusing both
    is honest but needless: the design INPUT states which copy the elaboration
    of `top` reaches, because the file list a tool is handed is rooted where the
    top's own modules live. The copy on that path WINS; the other is SHADOWED,
    contributes nothing, and is named in `notes`.

    Without a `top`, or when no unique copy is nearer to it than the rest, the
    old rule stands unchanged: every body is harvested and a name survives only
    if the bodies that resolve it AGREE, so a width over a contested constant
    refuses by name rather than taking whichever file sorted first.

    `notes` (a list the caller supplies) receives one line per package that had
    to be decided. Nothing is written to it when a package is declared once, or
    when the copies say the same thing -- there is nothing to record.
    """
    bodies: Dict[str, List[Tuple[object, str]]] = {}
    for path, raw in sources or []:
        code = _hdl_code_text.strip_hdl_comments_and_strings(raw or "")
        for m in _PACKAGE_RE.finditer(code):
            bodies.setdefault(m.group(1), []).append((path, m.group(2)))
    out, said = _package_fixpoint(bodies)
    dupes = {p: b for p, b in bodies.items() if len(b) > 1}
    if not dupes:
        return out
    top_path = _module_declaring_file(sources, top) if top else None
    decided: Dict[str, List[Tuple[object, str]]] = {}
    for pkg, blist in dupes.items():
        if not _bodies_diverge(pkg, blist, said.get(pkg, {}), out.get(pkg, {})):
            continue
        contested = sorted(n for n, v in said.get(pkg, {}).items()
                           if len(v) > 1)
        if top_path is None:
            if notes is not None:
                why = (f"no top module was named"
                       if not top else
                       f"no source here declares the top module {top!r}")
                notes.append(
                    f"{pkg}: declared in {len(blist)} places and {why}, so no "
                    f"elaboration path decides between them; contested "
                    f"constant(s) {contested} are dropped")
            continue
        ranked = sorted((_source_tree_distance(top_path, path), str(path))
                        for path, _b in blist)
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            if notes is not None:
                notes.append(
                    f"{pkg}: declared in {len(blist)} places, none of them "
                    f"nearer the elaboration of {top!r} than another, so no "
                    f"copy wins; contested constant(s) {contested} are dropped")
            continue
        keep = ranked[0][1]
        decided[pkg] = [(path, body) for path, body in blist
                        if str(path) == keep]
        if notes is not None:
            shadowed = [pth for _d, pth in ranked[1:]]
            notes.append(
                f"{pkg}: declared in {len(blist)} places; the copy the "
                f"elaboration of {top!r} reaches wins ({keep}); shadowed "
                f"{shadowed}; they disagreed on {contested}")
    if not decided:
        return out
    for pkg, blist in decided.items():
        bodies[pkg] = blist
    out, _said = _package_fixpoint(bodies)
    return out


def parameter_overrides(sources: Sequence[Tuple[str, str]],
                        dut_module: str) -> Dict[str, int]:
    """`{PARAM: value}` from a named-port override where the DUT is instantiated.

    An explicit override at the instantiation is what the design actually built,
    so it WINS over the module's own default. A design that never overrides keeps
    its defaults — both are legitimate architectures and neither is forced.
    """
    out: Dict[str, int] = {}
    for _path, raw in sources or []:
        # A COMMENTED-OUT instantiation is not a build. Measured: a superseded
        # `// dut_mod #(.DW(999)) u_old (...)` left in a file was counted, and
        # once conflict detection existed it made that dead line REFUSE an
        # otherwise consistent design. Blank comments first; offsets survive.
        text = _hdl_code_text.strip_hdl_comments_and_strings(raw or "")
        for m in re.finditer(re.escape(dut_module) + r"\s*#\s*\(", text):
            i = m.end() - 1
            depth, j = 0, i
            while j < len(text):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            for pm in re.finditer(r"\.\s*(\w+)\s*\(([^()]*)\)", text[i:j]):
                val = _int_expr(pm.group(2), {})
                if val is not None:
                    out[pm.group(1)] = val
    return out


def parameter_override_conflicts(sources: Sequence[Tuple[str, str]],
                                 dut_module: str) -> Dict[str, List[int]]:
    """`{PARAM: [distinct values]}` for parameters overridden INCONSISTENTLY.

    A design that instantiates the same module twice with different widths is
    saying two different things. `parameter_overrides` returns a flat dict, so
    the last site silently won and the driver was bound to whichever
    instantiation happened to be parsed last. That is a guess, and this module
    never guesses -- the caller refuses and names the parameter instead.
    """
    seen: Dict[str, List[int]] = {}
    for _path, raw in sources or []:
        # A COMMENTED-OUT instantiation is not a build. Measured: a superseded
        # `// dut_mod #(.DW(999)) u_old (...)` left in a file was counted, and
        # once conflict detection existed it made that dead line REFUSE an
        # otherwise consistent design. Blank comments first; offsets survive.
        text = _hdl_code_text.strip_hdl_comments_and_strings(raw or "")
        for m in re.finditer(re.escape(dut_module) + r"\s*#\s*\(", text):
            i = m.end() - 1
            depth, j = 0, i
            while j < len(text):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            for pm in re.finditer(r"\.\s*(\w+)\s*\(([^()]*)\)", text[i:j]):
                val = _int_expr(pm.group(2), {})
                if val is None:
                    continue
                vals = seen.setdefault(pm.group(1), [])
                if val not in vals:
                    vals.append(val)
    return {k: v for k, v in seen.items() if len(v) > 1}


def struct_field_width(sources: Sequence[Tuple[str, str]], type_name: str,
                       field: str, params: Dict[str, int]
                       ) -> Tuple[Optional[int], str]:
    """Width of ONE field of the design's own bus struct, parameter-resolved."""
    if not type_name or not field:
        return None, "no struct type or field name to resolve"
    bare = type_name.split("::")[-1]
    # A type declared in two packages must not resolve by FILE ORDER. Measured:
    # the same `d2h_t` in two files gave width 8 or 32 depending which was
    # listed first -- a silent guess in a module whose contract is never to
    # guess. Every declaration is collected and disagreement refuses.
    found: List[Tuple[str, int, str]] = []
    for _path, text in sources or []:
        for m in re.finditer(
                r"typedef\s+struct\s+packed\s*\{(.*?)\}\s*"
                + re.escape(bare) + r"\s*;", text or "", re.S):
            body = _hdl_code_text.strip_hdl_comments_and_strings(m.group(1))
            fm = re.search(r"\blogic\s*(\[[^\]]*\])?\s*"
                           + re.escape(field) + r"\s*;", body)
            if not fm:
                continue
            if not fm.group(1):
                found.append((_path, 1, f"{bare}.{field} is a single bit"))
                continue
            rng = fm.group(1)[1:-1]
            if ":" not in rng:
                return None, f"{bare}.{field} has an unparsable range [{rng}]"
            hi, lo = rng.split(":", 1)
            hi_v, lo_v = _int_expr(hi, params), _int_expr(lo, params)
            # `[0:7]` is a legal little-endian vector of EIGHT bits, not a
            # negative width. Taking hi-lo+1 literally produced -6 and would have
            # emitted `reg [-7:0]`. The magnitude is the width either way.
            if hi_v is None:
                return None, (f"{bare}.{field} width depends on '{hi.strip()}', "
                              f"which the design's input does not resolve")
            if lo_v is None:
                return None, (f"{bare}.{field} low bound '{lo.strip()}' is "
                              f"unresolved")
            # `abs(...) + 1` is >= 1 for every pair of integers, so the width
            # check that used to sit here could never fire. A branch that cannot
            # fire is a green light rather than a check (N93), so it is gone
            # rather than left to look like protection.
            width = abs(hi_v - lo_v) + 1
            found.append((_path, width, f"{bare}.{field} = [{rng}] with {params}"))
    if not found:
        return None, f"no packed struct '{bare}' declaring field '{field}'"
    widths = {w for _p, w, _w in found}
    if len(widths) > 1:
        where = ", ".join(f"{p}:{w}" for p, w, _w in found)
        return None, (f"'{bare}.{field}' is declared with different widths in "
                      f"more than one place ({where}); which one the driver "
                      f"should bind to is not derivable from the input")
    return found[0][1], found[0][2]


def resolve_bus_widths(sources: Sequence[Tuple[str, str]], rtl_text: str,
                       dut_module: str, bus: dict
                       ) -> Tuple[Optional[dict], str]:
    """The typed width contract the driver must bind to, or a NAMED refusal.

    Defaults are read from the DUT's own header; an instantiation override wins.
    Nothing is assumed: if either width is unresolved the caller keeps its
    existing behaviour and is told which symbol blocked the resolution.
    """
    defaults = dut_parameter_defaults(rtl_text, dut_module)
    conflicts = parameter_override_conflicts(sources, dut_module)
    if conflicts:
        detail = "; ".join(f"{k} = {sorted(v)}" for k, v in sorted(conflicts.items()))
        return None, (f"the design overrides the same parameter with different "
                      f"values at different instantiations ({detail}); which one "
                      f"the driver should bind to is not derivable from the input")
    overrides = parameter_overrides(sources, dut_module)
    params = dict(defaults)
    params.update(overrides)
    h, d = bus.get("h2d") or {}, bus.get("d2h") or {}
    addr_w, addr_why = struct_field_width(sources, bus.get("h2d_type", ""),
                                          h.get("addr", ""), params)
    data_w, data_why = struct_field_width(sources, bus.get("d2h_type", ""),
                                          d.get("rdata", ""), params)
    if addr_w is None:
        return None, f"address width unresolved: {addr_why}"
    if data_w is None:
        return None, f"read-data width unresolved: {data_why}"
    return ({"addr": addr_w, "data": data_w, "params": params,
             "overridden": sorted(overrides),
             "evidence": f"{addr_why}; {data_why}"},
            f"addr={addr_w} data={data_w} "
            f"(defaults {defaults}, overrides {overrides})")


def emit_env_responder(pair: dict, clk: str, rst: str,
                       rst_active_low: bool) -> Tuple[List[str], List[str]]:
    """`(declarations, note)` for ONE declared test-environment responder.

    NAMED `tb_env_*` and commented as environment, so nobody can mistake it for
    part of the design. It answers every request with an acknowledge and a
    FIXED word: it supplies the SERVICE the design's document says it needs,
    not any behaviour of the design.

    WHAT THIS TESTBENCH THEN VERIFIES, stated plainly: the DUT is instantiated
    unchanged and every result still comes out of the design. What is NOT
    verified is anything that depends on the CONTENT of this service — with a
    fixed word there is no entropy quality, no reseed variation and no masking
    randomness in this run."""
    req, rsp = pair["req_port"], pair["rsp_port"]
    d = [
        "",
        f"  // ---- TEST ENVIRONMENT, not part of the design -----------------",
        f"  // The DUT asks an outside service for {pair['base']} "
        f"({pair['req_type']} out, {pair['rsp_type']} in). Nothing in the",
        f"  // design's own closure answers it, and the design's document says",
        f"  // the unit does not become idle until it has been answered.",
        f"  // This model acknowledges every request with a FIXED word: it",
        f"  // supplies the service, never any behaviour of the design.",
        f"  {pair['req_type']} tb_env_{req};",
        f"  {pair['rsp_type']} tb_env_{rsp};",
        f"  always_ff @(posedge {clk}"
        f" or {'negedge' if rst_active_low else 'posedge'} {rst}) begin",
        f"    if ({'!' if rst_active_low else ''}{rst}) tb_env_{rsp} <= '0;",
        f"    else begin",
        f"      tb_env_{rsp} <= '0;",
        f"      if (|tb_env_{req}) tb_env_{rsp} <= '1;",
        f"    end",
        f"  end",
    ]
    note = [f"{pair['base']}: acknowledged by a declared tb_env responder with "
            f"a fixed word — the service is supplied, its CONTENT is not "
            f"exercised"]
    return d, note


def emit_sequence_tb(case: dict, plan: dict, bus: dict, dut_module: str,
                     h2d_port: str, d2h_port: str, clk: str, rst: str,
                     rst_active_low: bool = True,
                     timeout_cycles: int = 20000,
                     ports: Optional[Sequence[Tuple[str, str, str]]] = None,
                     intg_gen: Optional[dict] = None,
                     env_pairs: Optional[Sequence[dict]] = None,
                     tieoffs: Optional[Dict[str, str]] = None,
                     widths: Optional[dict] = None
                     ) -> str:
    """The SystemVerilog testbench for one vector, driven over the design's own
    register bus.

    Every address, bit index, opcode and control word below came out of
    `resolve_register_plan` / `bus_contract`, i.e. out of the design's own
    register map, encoding tables and staged bus package. The wait is on the
    design's DONE bit with a bounded timeout that FAILS — there is no fixed
    settle time, because a multi-cycle block does not have one."""
    name = str(case.get("name"))
    # PARAMETER-BOUND WIDTHS (#2035 family 3). `widths` is the typed contract
    # `resolve_bus_widths` read out of the design's own header/package. With no
    # contract resolved the emission is byte-identical to before: a width is
    # never invented here, it is only ever bound to one the design DECLARED.
    # `or 32` treated a width of 0 as ABSENT and silently substituted 32.
    # A falsy int is not a missing one; ask whether the key is there.
    _w = widths or {}
    _AW = int(_w["addr"]) if _w.get("addr") is not None else 32
    _DW = int(_w["data"]) if _w.get("data") is not None else 32
    if _AW < 1 or _DW < 1:
        raise ValueError(
            f"a bus width must be at least 1 bit (addr={_AW}, data={_DW})")
    _AD, _DD = (_AW + 3) // 4, (_DW + 3) // 4

    def _fits(v: int, w: int, role: str) -> None:
        """A literal wider than the bus it is driven onto is TRUNCATED SILENTLY.

        Measured: with a 4-bit address bus the emitter produced
        `bus_write(4'h74, ...)`, and Verilog keeps the low 4 bits — the sequence
        would program a DIFFERENT register and still report itself green. That
        is the same silent-truncation defect this width contract exists to
        remove. A design whose register map does not fit the bus width it
        declares is INCONSISTENT, so this refuses and names the conflict rather
        than emitting a testbench that quietly addresses the wrong thing.
        """
        if v < 0 or v.bit_length() > w:
            raise ValueError(
                f"{role} 0x{v:x} needs {max(1, v.bit_length())} bits but the "
                f"design declares a {w}-bit {role.split()[0]} bus; the register "
                f"map and the bus width contradict each other")

    def _al(v: int) -> str:
        _fits(v, _AW, "address")
        return f"{_AW}'h{v:0{_AD}x}"

    def _dl(v: int) -> str:
        _fits(v, _DW, "data word")
        return f"{_DW}'h{v:0{_DD}x}"

    def _dz() -> str:
        """The all-zero data word, in the same shorthand the emitter always used."""
        return f"{_DW}'h0"

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
    L.append(f"  reg [{_DW-1}:0] rdata;")
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
    env = list(env_pairs or [])
    env_ports = {}
    env_decls: List[str] = []
    for p in env:
        d, _note = emit_env_responder(p, clk, rst, rst_active_low)
        env_decls += d
        env_ports[p["req_port"]] = f"tb_env_{p['req_port']}"
        env_ports[p["rsp_port"]] = f"tb_env_{p['rsp_port']}"
    L.extend(env_decls)
    _tie = dict(tieoffs or {})
    conn += [(f".{_n}({env_ports[_n]})" if _n in env_ports
              else (f".{_n}({_n})" if _r else (f".{_n}({clk})" if _c
                                               else f".{_n}({_tie.get(_n, chr(39) + '0')})")))
             for _n, _w, _r, _c in extra_in]
    # a request OUTPUT the environment answers is connected too
    for p in env:
        if p["req_port"] not in [n for n, _w, _r, _c in extra_in]:
            conn.append(f".{p['req_port']}(tb_env_{p['req_port']})")
    L.append(f"  {dut_module} dut (" + ", ".join(conn) + ");")
    L.append("")
    L.append(f"  task automatic bus_write(input [{_AW-1}:0] addr,")
    L.append(f"                           input [{_DW-1}:0] data);")
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
    L.append(f"  task automatic bus_read(input [{_AW-1}:0] addr,")
    L.append(f"                          output [{_DW-1}:0] data);")
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
    # ---- a bounded wait on one status bit, used by the sequence below -----
    L.append(f"  task automatic wait_bit(input [{_AW-1}:0] addr, input integer b,")
    L.append("                          input [1023:0] what);")
    L.append("    begin")
    L.append(f"      rdata = {_dz()};")
    L.append("      wait_cycles = 0;")
    L.append("      while (!rdata[b]) begin")
    L.append("        bus_read(addr, rdata);")
    L.append("        wait_cycles = wait_cycles + 1;")
    L.append(f"        if (wait_cycles > {timeout_cycles}) begin")
    L.append(f'          $display("[TB {name}] FAIL: %0s never asserted after '
             f'%0d polls", what, wait_cycles);')
    L.append("          $fatal(1);")
    L.append("        end")
    L.append("      end")
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

    idle_bit = plan.get("idle_bit")
    idle_name = plan.get("idle_field")
    inrdy_bit = plan.get("input_ready_bit")
    inrdy_name = plan.get("input_ready_field")
    st = plan["status_addr"]

    def _wait(bit, nm, note):
        if bit is None:
            L.append(f"    // {note}: the status register declares no such "
                     f"field, so there is nothing to wait on")
            return
        L.append(f'    wait_bit({_al(st)}, {bit}, "{nm}");   // {note}')

    # THE SEQUENCE, in the order the design's own programmer's guide states.
    # Every wait below is there because that document says a write is IGNORED
    # or a read is invalid without it — not because a value looked unsettled.
    _wait(idle_bit, idle_name,
          "config writes are ignored while the unit is not idle")
    L.append(f"    bus_write({_al(plan['ctrl_addr'])}, "
             f"{_dl(plan['ctrl_value'])});   // configuration FIRST")
    if plan.get("ctrl_shadowed"):
        L.append(f"    bus_write({_al(plan['ctrl_addr'])}, "
                 f"{_dl(plan['ctrl_value'])});"
                 f"   // second write: the register's own name says shadowed")
    # RESET UNDER ACTIVE CONTROLS (#2035 family 3). The configuration is live
    # at this point, which is the only moment the question can be asked: does a
    # reset asserted while the controls are ACTIVE actually return the design to
    # the reset condition its own register map documents? A reset exercised only
    # from an idle machine never tests that. Emitted ONLY when the design's own
    # input resolved both the bus widths and an idle/status field to check
    # against -- otherwise the gap is REPORTED, never papered over with a guess.
    if widths is not None:
        if idle_bit is None:
            L.append("    // reset-under-active-controls NOT CHECKED: the status "
                     "register declares no idle field to observe the reset "
                     "condition on -- unresolved, routed to review, not guessed")
        else:
            _on = f"1'b{'0' if rst_active_low else '1'}"
            _off = f"1'b{'1' if rst_active_low else '0'}"
            L.append("    // --- reset asserted WHILE the controls are active ---")
            L.append(f"    {rst} = {_on};")
            for _n, _w, _is_rst, _is_clk in extra_in:
                if _is_rst:
                    L.append(f"    {_n} = {_on};")
            L.append(f"    repeat (4) @(posedge {clk});")
            L.append(f"    {rst} = {_off};")
            for _n, _w, _is_rst, _is_clk in extra_in:
                if _is_rst:
                    L.append(f"    {_n} = {_off};")
            L.append(f"    repeat (4) @(posedge {clk});")
            L.append(f'    wait_bit({_al(st)}, {idle_bit}, "{idle_name} after '
                     f'reset under active controls");')
            L.append(f"    bus_write({_al(plan['ctrl_addr'])}, "
                     f"{_dl(plan['ctrl_value'])});"
                     f"   // reprogram: the reset was real, so the control is gone")
            L.append("    // --- end reset-under-active-controls ---")
    _wait(idle_bit, idle_name,
          "writing the configuration may start a reseed; the key must wait")
    for i2, w in enumerate(key_w):
        if i2 in plan["key"]:
            L.append(f"    bus_write({_al(plan['key'][i2])}, "
                     f"{_dl(w)});   // key word {i2}")
    for i2 in sorted(plan["key"]):
        if i2 >= len(key_w):
            L.append(f"    bus_write({_al(plan['key'][i2])}, {_dz()});"
                     f"   // unused key word {i2}: every register of the share "
                     f"is written at least once")
    for i2 in sorted(plan.get("key_share1") or {}):
        L.append(f"    bus_write({_al(plan['key_share1'][i2])}, {_dz()});"
                 f"   // second share word {i2}: the key in effect is the XOR "
                 f"of the shares, so this share is zero")
    if iv_w:
        _wait(idle_bit, idle_name,
              "the unit must be idle before the IV registers are written")
        for i2, w in enumerate(iv_w):
            if i2 in plan["iv"]:
                L.append(f"    bus_write({_al(plan['iv'][i2])}, "
                         f"{_dl(w)});   // iv word {i2}")
    _wait(inrdy_bit, inrdy_name,
          "the unit must be ready to accept an input block")
    for i2, w in enumerate(pt_w):
        if i2 in plan["data_in"]:
            L.append(f"    bus_write({_al(plan['data_in'][i2])}, "
                     f"{_dl(w)});   // input word {i2}")
    L.append("    // AUTOMATIC mode: the guide says the unit starts on its own")
    L.append("    // when a full input block has been written, and that the")
    L.append("    // explicit START trigger belongs to MANUAL operation. The")
    L.append(f"    // control word written above leaves manual operation clear,")
    L.append(f"    // so no write to the trigger register (0x{plan['trigger_addr']:x}) is made.")
    _wait(plan["done_bit"], plan["done_field"],
          "wait for the unit to finish the block")
    for i2, w in enumerate(ct_w):
        if i2 not in plan["data_out"]:
            continue
        L.append(f"    bus_read({_al(plan['data_out'][i2])}, rdata);")
        L.append(f"    if (rdata !== {_dl(w)}) begin")
        L.append("      errors = errors + 1;")
        L.append(f'      $display("[TB {name}] FAIL: output word {i2} = %h, '
                 f'expected %h", rdata, {_dl(w)});')
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
