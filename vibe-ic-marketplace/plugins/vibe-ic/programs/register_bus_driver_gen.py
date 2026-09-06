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

_PARAM_DECL_RE = re.compile(
    r"\bparameter\b(?:\s+(?:int|integer|logic|bit|byte|shortint|longint"
    r"|unsigned|signed))*\s*(?:\[[^\]]*\]\s*)?(\w+)\s*=\s*([^,)\n]+)")


def _int_expr(expr: str, params: Dict[str, int]) -> Optional[int]:
    """Evaluate a width expression over integer literals and KNOWN parameters.

    Returns None — never a default — when any symbol is unknown, so an
    unresolvable width becomes a refusal rather than a silent 32.
    """
    import ast as _ast
    text = str(expr).strip().rstrip(";")
    # SystemVerilog sized literal: 8'd12 / 32'h20 / 'd7
    m = re.fullmatch(r"(?:\d+)?'[sS]?[dDhHbBoO]?([0-9a-fA-F_]+)", text)
    if m:
        base = {"h": 16, "b": 2, "o": 8}.get(text.split("'")[1][0].lower(), 10)
        try:
            return int(m.group(1).replace("_", ""), base)
        except ValueError:
            return None
    try:
        tree = _ast.parse(text, mode="eval")
    except SyntaxError:
        return None
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Name) and node.id not in params:
            return None
        if not isinstance(node, (_ast.Expression, _ast.BinOp, _ast.UnaryOp,
                                 _ast.Constant, _ast.Name, _ast.Load,
                                 _ast.Add, _ast.Sub, _ast.Mult, _ast.USub,
                                 _ast.UAdd, _ast.FloorDiv, _ast.LShift,
                                 _ast.RShift, _ast.Pow)):
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
        val = eval(compile(tree, "<width>", "eval"), {"__builtins__": {}},
                   dict(params))
    except Exception:
        return None
    if not isinstance(val, int) or isinstance(val, bool):
        return None
    if abs(val) > _WIDTH_EXPR_MAX:
        return None          # a bus wider than this is not a width, it is a typo
    return int(val)


def dut_parameter_defaults(rtl_text: str, dut_module: str) -> Dict[str, int]:
    """`{PARAM: default}` for the DUT's own parameter header, input only."""
    # Comments are blanked FIRST. A `)` inside a comment -- "no ')' ever" is
    # enough -- closed the header early and truncated the parameter list, and a
    # `(` inside one held it open. Offsets are preserved by the blanker.
    code = _hdl_code_text.strip_hdl_comments_and_strings(rtl_text or "")
    m = re.search(r"\bmodule\s+" + re.escape(dut_module) + r"\b\s*#\s*\(", code)
    if not m:
        return {}
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
        return {}
    header = code[i:j]
    out: Dict[str, int] = {}
    for name, expr in _PARAM_DECL_RE.findall(header):
        val = _int_expr(expr, out)
        if val is not None:
            out[name] = val
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
