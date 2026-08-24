#!/usr/bin/env python3
"""serdes_width_synth.py — deterministic SOLVER for the serial<->parallel /
data-width-conversion family (parallel-to-serial, serial-to-parallel, N-to-2N
width converter), spec prose -> RTL.

Same flow as the VerilogEval-v2 solvers: PARSE the stated structure of the prompt
into a small structured record, then EMIT correct RTL deterministically, then
HOST-VERIFY against the dataset testbench. The body is NEVER guessed — every shape
fires ONLY when the prompt states the structure (width + the STATED packing /
bit-order) unambiguously, and returns None (SKIP) on any §4.05 ambiguity.

This is a clean prose-parsed canonical solver: it reads the interface through the
SHARED reader chain `prose_port_block_read.bridge_prompt -> port_parser.parse_ports`
(a no-op on VerilogEval bullet/header prompts), so the port names/widths come from
the prompt's "Input ports:/Output ports:" prose, never from a hard-coded table.

chip-AGNOSTIC RECOGNITION (this file's contract):
  * Each shape is recognised by its STRUCTURE — the operation described in prose +
    the port DIRECTIONS / WIDTHS / roles — NOT by the dataset's exact port-name set.
    Renaming the ports to generic equivalents (din/dout/valid) does NOT change
    whether a shape fires; the actual parsed names are used verbatim in the emitted
    RTL so the testbench still binds by name.
  * Direction (packing order, serialization bit-order) is PARSED from the prose,
    never hard-coded. A "first word in the lower byte" prompt emits lower-first; an
    "LSB first" serializer emits LSB-first. If the direction is UNSTATED the shape
    SKIPs (returns None) rather than guessing.

API:  synth(prompt_text, top="TopModule") -> str | None
      `top` is used verbatim; when it is the caller default ("TopModule") the
      prompt's "Module name:" token is used instead (the RTLLM TB instance name).
      Returns None on any §4.05 ambiguity.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# --- shared port reader (bridge -> port_parser) --------------------------------
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    import prose_port_block_read as _bridge  # noqa: E402
    import port_parser as _pp  # noqa: E402
except Exception:  # pragma: no cover - import guard for standalone smoke
    _bridge = None
    _pp = None

_DEFAULT_TOP = "TopModule"

Port = Tuple[str, int]


# ============================================================ helpers / parsing
def _module_name(text: str) -> Optional[str]:
    m = re.search(r"Module\s*name\s*[:：]\s*\n?\s*([A-Za-z_]\w*)", text, re.I)
    return m.group(1) if m else None


def _ports(text: str) -> Tuple[List[Port], List[Port]]:
    if _bridge is None or _pp is None:
        return [], []
    return _pp.parse_ports(_bridge.bridge_prompt(text))


def _names(ports: List[Port]) -> List[str]:
    return [n for n, _ in ports]


def _width_of(ports: List[Port], name: str) -> Optional[int]:
    for n, w in ports:
        if n == name:
            return w
    return None


def _int_after(text: str, *patterns: str) -> Optional[int]:
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return int(m.group(1))
    return None


def _has(text: str, *subs: str) -> bool:
    low = text.lower()
    return any(s.lower() in low for s in subs)


# --- STRUCTURAL role identification (chip-AGNOSTIC, name-free) ------------------
# A port is identified by DIRECTION + WIDTH role, never by a hard-coded name set.
# Renaming the ports does not change which structural role they fill.

_CLK_RE = re.compile(r"^(clk|clock|clk_in)$", re.I)
_RST_RE = re.compile(r"(rst|reset|clr|clear)", re.I)
# "valid" family: a 1-bit control/handshake port whose name advertises validity.
_VALID_RE = re.compile(r"(valid|vld|dout_valid|din_valid|ready|rdy)", re.I)


def _is_clk(name: str) -> bool:
    return bool(_CLK_RE.match(name))


def _is_rst(name: str) -> bool:
    return bool(_RST_RE.search(name))


def _is_valid(name: str) -> bool:
    return bool(_VALID_RE.search(name))


def _data_ports(ports: List[Port]) -> List[Port]:
    """Ports that carry DATA (not clk / reset / a 1-bit valid-handshake)."""
    out = []
    for n, w in ports:
        if _is_clk(n) or _is_rst(n):
            continue
        if _is_valid(n) and w == 1:
            continue
        out.append((n, w))
    return out


def _valid_ports(ports: List[Port]) -> List[Port]:
    return [(n, w) for n, w in ports if _is_valid(n) and w == 1]


def _pick_clk(ins: List[Port]) -> Optional[str]:
    for n, _ in ins:
        if _is_clk(n):
            return n
    return None


def _pick_rst(ins: List[Port]) -> Optional[str]:
    for n, _ in ins:
        if _is_rst(n):
            return n
    return None


def _single_data(ports: List[Port], want_width=None) -> Optional[Port]:
    """The sole data port (optionally of a given width predicate)."""
    cands = _data_ports(ports)
    if want_width is not None:
        cands = [(n, w) for n, w in cands if want_width(w)]
    if len(cands) == 1:
        return cands[0]
    return None


# --- DIRECTION parsers (PARSED from prose, never hard-coded) --------------------
def _parse_bit_order(text: str) -> Optional[str]:
    """Serialization / packing bit-order, PARSED from the prose.

    Returns "msb_first", "lsb_first", or None (unstated -> caller SKIPs).
    A real direction parser: it looks for an explicit ordering phrase, not a mere
    presence of the token "MSB". "MSB first" / "from MSB to LSB" / "most significant
    bit ... first" -> msb_first. "LSB first" / "from LSB to MSB" / "least
    significant bit ... first" -> lsb_first.
    """
    low = text.lower()
    msb = [
        r"msb\s*(?:[- ]?)\s*first",
        r"from\s+(?:the\s+)?(?:msb|most\s+significant\s+bit)\s+to\s+(?:the\s+)?(?:lsb|least\s+significant\s+bit)",
        r"most\s+significant\s+bit\b[^.]*\bfirst\b",
        r"starting\s+(?:from|with)\s+(?:the\s+)?(?:msb|most\s+significant\s+bit)",
        # "the most significant bit of d is output" THEN remaining bits follow ->
        # MSB leads the serial stream.
        r"most\s+significant\s+bit\b[^.]*\bis\s+output\b",
    ]
    lsb = [
        r"lsb\s*(?:[- ]?)\s*first",
        r"from\s+(?:the\s+)?(?:lsb|least\s+significant\s+bit)\s+to\s+(?:the\s+)?(?:msb|most\s+significant\s+bit)",
        r"least\s+significant\s+bit\b[^.]*\bfirst\b",
        r"starting\s+(?:from|with)\s+(?:the\s+)?(?:lsb|least\s+significant\s+bit)",
        r"least\s+significant\s+bit\b[^.]*\bis\s+output\b",
    ]
    is_msb = any(re.search(p, low) for p in msb)
    is_lsb = any(re.search(p, low) for p in lsb)
    if is_msb and is_lsb:
        return None  # contradictory -> SKIP
    if is_msb:
        return "msb_first"
    if is_lsb:
        return "lsb_first"
    return None


def _parse_packing_order(text: str, half: str) -> Optional[str]:
    """Where the FIRST arriving word lands in the wider word, PARSED from prose.

    `half` is a human label of the bit-region word size (e.g. "8") only used to
    recognise phrasings like "higher 8 bits".  Returns "first_upper",
    "first_lower", or None (unstated -> caller SKIPs).
    """
    low = text.lower()
    # phrasings anchored to the FIRST word's destination
    first_upper = [
        r"first[^.]*\b(?:high(?:er)?|upper|most\s+significant|msb)\b",
        r"\b(?:high(?:er)?|upper|most\s+significant|msb)\b[^.]*\bfirst\b",
    ]
    first_lower = [
        r"first[^.]*\b(?:low(?:er)?|least\s+significant|lsb|bottom)\b",
        r"\b(?:low(?:er)?|least\s+significant|lsb|bottom)\b[^.]*\bfirst\b",
    ]
    up = any(re.search(p, low) for p in first_upper)
    lo = any(re.search(p, low) for p in first_lower)
    if up and lo:
        return None  # contradictory -> SKIP
    if up:
        return "first_upper"
    if lo:
        return "first_lower"
    return None


# ============================================================ parallel2serial
def _try_parallel2serial(text: str, top: str, ins, outs) -> Optional[str]:
    # STRUCTURE: a converter described as parallel-to-serial, with a multi-bit
    # parallel DATA input and a 1-bit serial DATA output plus a valid output.
    if not _has(text, "parallel-to-serial", "parallel to serial",
                "parallel serial"):
        return None
    clk = _pick_clk(ins)
    rst = _pick_rst(ins)
    if clk is None or rst is None:
        return None
    # parallel data input = the multi-bit data input (or 1-bit if width comes from
    # the prose "every N input bits"); serial data output = the 1-bit data output.
    in_data = _data_ports(ins)
    out_data = _data_ports(outs)
    if len(in_data) != 1 or len(out_data) != 1:
        return None
    d_name, d_w = in_data[0]
    dout_name, dout_w = out_data[0]
    if dout_w != 1:  # the serial output must be one bit wide
        return None
    vouts = _valid_ports(outs)
    if len(vouts) != 1:
        return None
    vout_name = vouts[0][0]
    # width of the parallel word: from the port width, else from "every N input bits"
    nbits = d_w if d_w > 1 else None
    if nbits is None:
        nbits = _int_after(text, r"every (\d+) input bits")
    if nbits is None:
        words = {"two": 2, "three": 3, "four": 4, "eight": 8,
                 "sixteen": 16, "thirty-two": 32}
        m = re.search(r"every (\w+(?:-\w+)?) input bits", text, re.I)
        if m and m.group(1).lower() in words:
            nbits = words[m.group(1).lower()]
    if nbits is None or nbits < 2:
        return None
    order = _parse_bit_order(text)
    if order is None:
        return None  # §4.05: bit-order unstated -> SKIP
    cntw = max(1, (nbits - 1).bit_length())
    # serial tap + shift direction depend on the PARSED bit-order.
    if order == "msb_first":
        tap = f"    assign {dout_name} = data[{nbits-1}];"
        shift = f"                data <= {{data[{nbits-2}:0], data[{nbits-1}]}};"
    else:  # lsb_first
        tap = f"    assign {dout_name} = data[0];"
        shift = f"                data <= {{data[0], data[{nbits-1}:1]}};"
    body = [f"module {top} (",
            f"    input            {clk},",
            f"    input            {rst},",
            f"    input  [{nbits-1}:0]     {d_name},",
            f"    output reg       {vout_name},",
            f"    output           {dout_name}",
            ");",
            f"    reg [{nbits-1}:0] data;",
            f"    reg [{cntw-1}:0] cnt;",
            tap,
            f"    always @(posedge {clk} or negedge {rst}) begin",
            f"        if (!{rst}) begin",
            "            cnt <= 0;",
            f"            {vout_name} <= 0;",
            "            data <= 0;",
            "        end else begin",
            f"            if (cnt == {nbits-1}) begin",
            f"                data <= {d_name};",
            "                cnt <= 0;",
            f"                {vout_name} <= 1;",
            "            end else begin",
            "                cnt <= cnt + 1;",
            f"                {vout_name} <= 0;",
            shift,
            "            end",
            "        end",
            "    end",
            "endmodule"]
    return "\n".join(body) + "\n"


# ============================================================ serial2parallel
def _try_serial2parallel(text: str, top: str, ins, outs) -> Optional[str]:
    # STRUCTURE: a serial-to-parallel / series-parallel converter with a 1-bit
    # serial DATA input + a valid input, and a multi-bit parallel DATA output + a
    # valid output.
    if not _has(text, "series-parallel", "serial-to-parallel",
                "serial to parallel", "series parallel", "serial parallel"):
        return None
    clk = _pick_clk(ins)
    rst = _pick_rst(ins)
    if clk is None or rst is None:
        return None
    in_data = _data_ports(ins)
    out_data = _data_ports(outs)
    if len(in_data) != 1 or len(out_data) != 1:
        return None
    din_name, din_w = in_data[0]
    if din_w != 1:  # serial input must be one bit wide
        return None
    dout_name, dout_w = out_data[0]
    vins = _valid_ports(ins)
    vouts = _valid_ports(outs)
    if len(vins) != 1 or len(vouts) != 1:
        return None
    dvin = vins[0][0]
    dvout = vouts[0][0]
    # parallel width from the output port; else from a stated "N-bit data" token.
    w = dout_w if dout_w > 1 else None
    if w is None:
        w = _int_after(text, r"(\d+)-bit data", r"(\d+) input data",
                       r"(\d+) bits wide")
    if w is None or w < 2:
        return None
    order = _parse_bit_order(text)
    if order is None:
        return None  # §4.05: bit-order unstated -> SKIP
    cntw = max(1, (w).bit_length())  # counts 0..w inclusive
    # MSB-first: shift new bit into LSB, first-received bit migrates to MSB ->
    #   {din_tmp[w-2:0], din_serial}. LSB-first: shift new bit into MSB ->
    #   {din_serial, din_tmp[w-1:1]}.
    if order == "msb_first":
        shift = f"        else if ({dvin} && cnt <= {w-1}) {din_name}_tmp <= {{{din_name}_tmp[{w-2}:0], {din_name}}};"
    else:  # lsb_first
        shift = f"        else if ({dvin} && cnt <= {w-1}) {din_name}_tmp <= {{{din_name}, {din_name}_tmp[{w-1}:1]}};"
    body = [f"module {top} (",
            f"    input              {clk},",
            f"    input              {rst},",
            f"    input              {din_name},",
            f"    input              {dvin},",
            f"    output reg [{w-1}:0]   {dout_name},",
            f"    output reg         {dvout}",
            ");",
            f"    reg [{w-1}:0] {din_name}_tmp;",
            f"    reg [{cntw-1}:0] cnt;",
            f"    always @(posedge {clk} or negedge {rst}) begin",
            f"        if (!{rst})        cnt <= 0;",
            f"        else if ({dvin}) cnt <= (cnt == {w}) ? 0 : cnt + 1;",
            "        else               cnt <= 0;",
            "    end",
            f"    always @(posedge {clk} or negedge {rst}) begin",
            f"        if (!{rst})                       {din_name}_tmp <= 0;",
            shift,
            "    end",
            f"    always @(posedge {clk} or negedge {rst}) begin",
            f"        if (!{rst}) begin",
            f"            {dvout}    <= 0;",
            f"            {dout_name} <= 0;",
            f"        end else if (cnt == {w}) begin",
            f"            {dvout}    <= 1;",
            f"            {dout_name} <= {din_name}_tmp;",
            "        end else begin",
            f"            {dvout}    <= 0;",
            "        end",
            "    end",
            "endmodule"]
    return "\n".join(body) + "\n"


# ============================================================ width_8to16
def _try_width_8to16(text: str, top: str, ins, outs) -> Optional[str]:
    # STRUCTURE: a width converter with an N-bit DATA input + a valid input, and a
    # 2N-bit DATA output + a valid output.
    if not _has(text, "width conversion", "data width conversion",
                "width converter", "data-width conversion"):
        return None
    clk = _pick_clk(ins)
    rst = _pick_rst(ins)
    if clk is None or rst is None:
        return None
    in_data = _data_ports(ins)
    out_data = _data_ports(outs)
    if len(in_data) != 1 or len(out_data) != 1:
        return None
    din_name, iw = in_data[0]
    dout_name, ow = out_data[0]
    if iw < 1 or ow != 2 * iw:
        return None  # must be an N -> 2N converter (STRUCTURAL)
    vins = _valid_ports(ins)
    vouts = _valid_ports(outs)
    if len(vins) != 1 or len(vouts) != 1:
        return None
    vin = vins[0][0]
    vout = vouts[0][0]
    order = _parse_packing_order(text, str(iw))
    if order is None:
        return None  # §4.05: packing order unstated -> SKIP
    # PARSED packing order decides the concatenation: first word in the destination
    # half it was STATED to land in.
    if order == "first_upper":
        concat = f"                {dout_name}  <= {{data_lock, {din_name}}};"
    else:  # first_lower
        concat = f"                {dout_name}  <= {{{din_name}, data_lock}};"
    body = [f"module {top} (",
            f"    input               {clk},",
            f"    input               {rst},",
            f"    input               {vin},",
            f"    input  [{iw-1}:0]        {din_name},",
            f"    output reg          {vout},",
            f"    output reg [{ow-1}:0]   {dout_name}",
            ");",
            f"    reg [{iw-1}:0] data_lock;",
            "    reg flag;",
            f"    always @(posedge {clk} or negedge {rst}) begin",
            f"        if (!{rst}) begin",
            f"            {dout_name}  <= 0;",
            "            data_lock <= 0;",
            f"            {vout} <= 0;",
            "            flag      <= 0;",
            f"        end else if ({vin}) begin",
            "            if (!flag) begin",
            f"                data_lock <= {din_name};",
            "                flag      <= 1;",
            f"                {vout} <= 0;",
            "            end else begin",
            concat,
            "                flag      <= 0;",
            f"                {vout} <= 1;",
            "            end",
            "        end else begin",
            f"            {vout} <= 0;",
            "        end",
            "    end",
            "endmodule"]
    return "\n".join(body) + "\n"


# ============================================================ dispatcher
_SHAPES = [_try_parallel2serial, _try_serial2parallel, _try_width_8to16]


def synth(prompt_text: str, top: str = _DEFAULT_TOP) -> Optional[str]:
    """Parse the serdes / width-converter prompt and EMIT RTL, or None (SKIP).

    `top` is used verbatim; when it is the caller default ("TopModule") the
    prompt's 'Module name:' token is used instead. Returns None on any §4.05
    ambiguity (unstated width, unstated packing / bit-order, missing interface).
    """
    if not prompt_text or not prompt_text.strip():
        return None
    name = top
    if top == _DEFAULT_TOP:
        name = _module_name(prompt_text) or top
    ins, outs = _ports(prompt_text)
    for shape in _SHAPES:
        out = shape(prompt_text, name, ins, outs)
        if out:
            return out
    return None


# ============================================================ CLI
def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="spec prompt text file")
    ap.add_argument("--top", default=_DEFAULT_TOP, help="override module name")
    a = ap.parse_args(argv)
    text = Path(a.prompt).read_text(errors="replace")
    out = synth(text, top=a.top)
    if out is None:
        print("// SKIP: serdes_width_synth declined (no matching shape / §4.05 ambiguity)",
              file=sys.stderr)
        return 2
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
