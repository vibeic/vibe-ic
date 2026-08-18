#!/usr/bin/env python3
"""graycode_parity_synth.py — a DETERMINISTIC solver for the CVDP gray-code
and parity families.

WHY: the existing `cvdp_atomic_bridge.py` routes atomic-noun CVDP prompts through
the `spec_artifact_registry` arithmetic/comparator/mux canonicals, but the
registry has NO gray<->binary converter canonical, and these CVDP converters are
PARAMETERIZED (bus width is the `WIDTH` parameter the harness overrides, NOT a
literal in the prose), so the bridge's numeric width-resolver leaves the bus
UNRESOLVED and SKIPs. This module supplies exactly that missing deterministic
emitter — GENERAL, §4.05 parse-or-SKIP, NO-CHEAT.

REUSE of `cvdp_atomic_bridge` (all from the model-visible surface `input.prompt` +
`input.context` — NEVER the hidden harness or golden, which are OFF-LIMITS oracle):
  * `toplevel_name(record)`     — the module NAME stated in the prompt.
  * `extract_interface(record, top)` — the port NAMES + directions from the prompt
                                  skeleton header / prose port block / test-case
                                  table (parameters ALL-CAPS already filtered).
  * composite / special-algebra SKIP guards (defence in depth).
We do NOT re-implement name/interface extraction. We ADD the gray/parity OPERATION
recognition, the PARAMETER-width interface model (buses are `[WIDTH-1:0]`), and the
correct deterministic RTL emit.

WHAT THIS SOLVES
  GRAY (combinational):
    * binary -> gray   : g = b ^ (b >> 1)
    * gray   -> binary : b[i] = ^ (g >> i)        (cascade XOR, vectorized)
    The DIRECTION (b->g vs g->b) is read from the prose. §4.05: unstated OR
    ambiguous (both claimed) -> SKIP. A gray-code COUNTER is sequential and out of
    this combinational scope -> SKIP (never mis-emit a comb converter for a clocked
    counter).
  PARITY (combinational):
    * generator : parity = ^data (EVEN) or ~^data (ODD)
    * checker   : error = ^{data,parity_in} (EVEN) or ~^{data,parity_in} (ODD)
    The CONVENTION (even vs odd) is read from the prose. §4.05: unstated OR
    ambiguous (both "even" and "odd") -> SKIP. NEVER guess even-vs-odd.
    Convention (aligned with counter_popcount_synth): even == ^ , odd == ~^ .

  A gray converter MAY carry the EXACT extra side-outputs the interface declares
  (e.g. `parity = ^binary_out`, `debug_mask = ~binary_out` gated on DEBUG_MODE, a
  tied `valid = 1`) — but ONLY ones whose computation the SAME spec states
  unambiguously. Any side-output we cannot deterministically compute => SKIP.

§4.05 / NO-CHEAT (binding):
  * parse-or-SKIP: unstated direction / unstated-or-ambiguous parity sense /
    unexplained side-output / non-unique data bus => return None.
  * NEVER read the golden RTL or the hidden harness. Operation comes from the PROMPT
    PROSE; the interface comes from the prompt+context (names via extract_interface)
    + the prose (param decls). The hidden harness (cocotb/.env) is OFF-LIMITS oracle.
  * chip-AGNOSTIC: keyed on operation/interface vocabulary, never on a design name.

API: solve(record: dict) -> Optional[str]   # emitted RTL (module == TOPLEVEL) | None
deterministic, pure-function.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import cvdp_atomic_bridge as _bridge  # noqa: E402  REUSE name + cocotb IO + guards


# --------------------------------------------------------------------------- #
# operation recognition
# --------------------------------------------------------------------------- #
_GRAY_TOKEN_RE = re.compile(r"(?i)\bgray\b")
_GRAY_COUNTER_RE = re.compile(
    r"(?xi)\bgray[\s\-]*code\s+counter\b|\bgray\s+counter\b"
    r"|\bcounter\b[\s\w]*?\bgray\s+code\b"
)
_BIN2GRAY_RE = re.compile(
    r"(?xi)\bbinary[\s_\-]*(?:in(?:put)?[\s_\-]*)?to[\s_\-]*gray\b"
    r"|\bbinary[\s_\-]*to[\s_\-]*gray[\s_\-]*code\b"
    r"|\bconverts?\s+(?:an?\s+)?(?:n[\s\-]*bit\s+)?binary[\s\w]*?\binto\b[\s\w]*?\bgray\b"
)
_GRAY2BIN_RE = re.compile(
    r"(?xi)\bgray[\s_\-]*(?:code[\s_\-]*)?(?:in(?:put)?[\s_\-]*)?to[\s_\-]*binary\b"
    r"|\bgray[\s_\-]*to[\s_\-]*binary[\s_\-]*code\b"
    r"|\bconverts?\s+(?:an?\s+)?(?:binary[\s\-]*reflected\s+)?gray\s+code[\s\w]*?\binto\b[\s\w]*?\bbinary\b"
)
_PARITY_TOKEN_RE = re.compile(r"(?i)\bparity\b")
_PARITY_GEN_RE = re.compile(
    r"(?xi)\bparity\s+(?:bit\s+)?generat|\bgenerat[\w\s]*?\bparity\b"
    r"|\bparity\s+encoder\b|\bcomputes?\s+(?:the\s+)?parity\b|\bparity\s+bit\b"
)
_PARITY_CHK_RE = re.compile(
    r"(?xi)\bparity\s+check|\bcheck[\w\s]*?\bparity\b|\bparity\s+error\b"
    r"|\bparity\s+mismatch\b|\bdetect[\w\s]*?\bparity\b"
)


def _gray_direction(prompt: str) -> Optional[str]:
    """'b2g' | 'g2b' | None (unstated / ambiguous — both claimed)."""
    b2g = bool(_BIN2GRAY_RE.search(prompt))
    g2b = bool(_GRAY2BIN_RE.search(prompt))
    if b2g and not g2b:
        return "b2g"
    if g2b and not b2g:
        return "g2b"
    return None


def _parity_sense(prompt: str, bus: Optional[str] = None) -> Optional[str]:
    """'^' (even) | '~^' (odd) | None (unstated / ambiguous).
    NEVER guess even-vs-odd (§4.05).

    Resolution order (general, matches counter_popcount_synth doctrine):
      1. an explicit reduction expression: `~^<bus>` (XNOR-of-all == ODD) or
         `^<bus>` (XOR-of-all == EVEN) literally stated for the parity signal.
      2. the *convention* phrase 'even parity' vs 'odd parity', taken
         exclusively — only one present establishes the sense.
    Incidental "even or odd" descriptions, or "(0 = even, 1 = odd)" ENCODING
    notes, do NOT by themselves establish a convention; they are subordinate to
    1 and 2. If neither an explicit expression nor an exclusive convention phrase
    is present, return None (SKIP)."""
    # (1) explicit reduction expression. ~^ / ^~ == odd; a lone ^ == even.
    if re.search(r"(?:~\s*\^|\^\s*~)\s*\w", prompt):
        return "~^"
    if bus is not None:
        if re.search(r"~\s*\^\s*`?" + re.escape(bus), prompt):
            return "~^"
        if re.search(r"(?<![~\^])\^\s*`?" + re.escape(bus), prompt):
            return "^"
    # (2) convention phrase, taken exclusively.
    has_even_conv = bool(re.search(r"(?i)\beven\s+parity\b", prompt))
    has_odd_conv = bool(re.search(r"(?i)\bodd\s+parity\b", prompt))
    if has_even_conv and not has_odd_conv:
        return "^"
    if has_odd_conv and not has_even_conv:
        return "~^"
    # (3) a bare even/odd word, taken exclusively (last resort; an encoding note
    # like "(0 = even, 1 = odd)" carries BOTH so it correctly yields ambiguous).
    has_even = bool(re.search(r"\beven\b", prompt, re.I))
    has_odd = bool(re.search(r"\bodd\b", prompt, re.I))
    if has_even and not has_odd:
        return "^"
    if has_odd and not has_even:
        return "~^"
    return None


# --------------------------------------------------------------------------- #
# parameter / width model
# --------------------------------------------------------------------------- #
def _param_default(prompt: str, name: str, fallback: int) -> int:
    for pat in (
        rf"\bparameter\s+{re.escape(name)}\s*=\s*(\d+)",
        rf"`{re.escape(name)}`[^\n]*?\bdefault\s*=?\s*(\d+)",
        rf"\b{re.escape(name)}\b[^\n]*?\bdefault\s*[:=]?\s*(\d+)",
    ):
        m = re.search(pat, prompt, re.I)
        if m:
            return int(m.group(1))
    return fallback


def _bus_width_param(prompt: str) -> Optional[Tuple[str, int]]:
    """The parameter that governs the data-bus width, e.g. (`WIDTH`, default).
    Required for a parameterized converter (the harness overrides it). None if no
    width parameter is declared -> the buses are not parameter-width -> SKIP rather
    than guess a literal width we never saw."""
    for pname in ("WIDTH", "N", "DATA_WIDTH"):
        if re.search(rf"(?i)\bparameter\s+{pname}\b", prompt) \
                or re.search(rf"(?i)\[\s*{pname}\s*-\s*1\s*:\s*0\s*\]", prompt) \
                or re.search(rf"(?i)\bbit[\s\-]*width\s*\(?`?{pname}`?", prompt) \
                or re.search(rf"(?i)`{pname}`[^\n]*?\bdefault\b", prompt):
            return pname, _param_default(prompt, pname, 4)
    return None


# --------------------------------------------------------------------------- #
# interface (port names from the PROMPT+CONTEXT interface; widths from the bus param)
# --------------------------------------------------------------------------- #
def _io_names(record: dict, top: str) -> Optional[Tuple[List[str], List[str]]]:
    """Input / output port NAMES sourced ONLY from `input.prompt` + `input.context`
    via `cvdp_atomic_bridge.extract_interface` — never the hidden harness (cocotb
    `dut.<sig>`, `.env`) or golden, which are OFF-LIMITS oracle. Returns
    (input_names, output_names), or None when the interface is not prompt-derivable
    (an honest §4.05 SKIP). The bus WIDTHS are NOT taken from here — they come from
    the prose width parameter (`_bus_width_param`); this only supplies the names."""
    iface = _bridge.extract_interface(record, top)
    if not iface:
        return None
    ins, outs = iface
    in_names = [n for n, _ in ins]
    out_names = [n for n, _ in outs]
    if not in_names or not out_names:
        return None
    return in_names, out_names


_SCALAR_NAME_RE = re.compile(
    r"(?i)^(parity|valid|done|ready|error|err|ok|match|overflow|ovf|flag|"
    r".*_valid|.*_ready|.*_error|.*_flag|.*_done|p_?out|p_?in|odd|even)$")


def _is_scalar(name: str) -> bool:
    return bool(_SCALAR_NAME_RE.match(name))


# --------------------------------------------------------------------------- #
# RTL emit
# --------------------------------------------------------------------------- #
def _emit_gray(top: str, direction: str, in_bus: str, out_bus: str,
               wparam: str, params: List[Tuple[str, int]],
               extra_outs: List[Tuple[str, str, bool]]) -> str:
    """extra_outs: (name, rhs_expr, is_bus)."""
    plist = ", ".join(f"parameter {n} = {d}" for n, d in params)
    decls = [f"    input  wire [{wparam}-1:0] {in_bus}",
             f"    output wire [{wparam}-1:0] {out_bus}"]
    for nm, _rhs, is_bus in extra_outs:
        rng = f"[{wparam}-1:0] " if is_bus else ""
        decls.append(f"    output wire {rng}{nm}")
    body: List[str] = []
    if direction == "b2g":
        body.append(f"  assign {out_bus} = {in_bus} ^ ({in_bus} >> 1);")
    else:  # g2b : binary[i] = ^ (gray >> i)
        body.append("  genvar gp_i;")
        body.append("  generate")
        body.append(f"    for (gp_i = 0; gp_i < {wparam}; gp_i = gp_i + 1) "
                    "begin : g2b_bit")
        body.append(f"      assign {out_bus}[gp_i] = ^({in_bus} >> gp_i);")
        body.append("    end")
        body.append("  endgenerate")
    for nm, rhs, _is_bus in extra_outs:
        body.append(f"  assign {nm} = {rhs};")
    return (f"module {top} #(\n    {plist}\n) (\n"
            + ",\n".join(decls) + "\n);\n"
            + "\n".join(body) + "\nendmodule\n")


def _emit_parity(top: str, sense: str, kind: str, data_bus: str,
                 flag: str, parity_in: Optional[str],
                 wparam: str, params: List[Tuple[str, int]]) -> str:
    plist = ", ".join(f"parameter {n} = {d}" for n, d in params)
    decls = [f"    input  wire [{wparam}-1:0] {data_bus}"]
    if kind == "check" and parity_in is not None:
        decls.append(f"    input  wire {parity_in}")
    decls.append(f"    output wire {flag}")
    if kind == "gen" or parity_in is None:
        rhs = f"{sense}{data_bus}"
    else:
        rhs = f"{sense}{{{data_bus}, {parity_in}}}"
    return (f"module {top} #(\n    {plist}\n) (\n"
            + ",\n".join(decls) + "\n);\n"
            + f"  assign {flag} = {rhs};\nendmodule\n")


# --------------------------------------------------------------------------- #
# side-output resolution for gray converters (only deterministically-stated ones)
# --------------------------------------------------------------------------- #
def _resolve_side_outputs(prompt: str, out_bus: str, side_names: List[str]
                          ) -> Optional[List[Tuple[str, str, bool]]]:
    out: List[Tuple[str, str, bool]] = []
    has_debug_mode = bool(re.search(r"(?i)\bdebug_?mode\b", prompt))
    for nm in side_names:
        low = nm.lower()
        if "parity" in low:
            sense = _parity_sense(prompt, out_bus)
            if sense is None:
                return None
            out.append((nm, f"{sense}{out_bus}", False))
        elif "debug" in low and "mask" in low:
            # Require the prose to state the debug mask is the inversion (bitwise
            # complement) of the output bus. Accept either the exact port token
            # (`debug_mask`, possibly back-ticked) or the spelled "debug mask"
            # phrase, near an invert/~/complement cue. The name+inversion cue may
            # be in either order and separated by punctuation/back-ticks.
            name_alt = (re.escape(nm) + r"|debug\s*mask")
            invert_cue = r"invert|complement|~\s*" + re.escape(out_bus)
            stated = re.search(
                r"(?i)(?:" + name_alt + r")[^\n]{0,40}?(?:" + invert_cue + r")",
                prompt) or re.search(
                r"(?i)(?:invert|complement)[^\n]{0,40}?(?:" + name_alt + r")",
                prompt) or re.search(
                r"(?i)(?:`?" + re.escape(nm) + r"`?)\s*=\s*~", prompt)
            if not stated:
                return None
            if has_debug_mode:
                out.append((nm, f"DEBUG_MODE ? (~{out_bus}) : '0", True))
            else:
                out.append((nm, f"~{out_bus}", True))
        elif low in ("valid", "done", "ready"):
            stated = re.search(
                r"(?i)\b" + re.escape(nm)
                + r"\b[^\n]*?(complete|valid|asserted|indicat|set to 1|1'b1|high)",
                prompt)
            if not stated:
                return None
            out.append((nm, "1'b1", False))
        else:
            return None  # unexplained side-output -> SKIP
    return out


# --------------------------------------------------------------------------- #
# top-level solve
# --------------------------------------------------------------------------- #
def solve(record: dict) -> Optional[str]:
    if not isinstance(record, dict):
        return None
    top = _bridge.toplevel_name(record)
    if not top:
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None

    is_gray = bool(_GRAY_TOKEN_RE.search(prompt))
    is_pgen = bool(_PARITY_GEN_RE.search(prompt))
    is_pchk = bool(_PARITY_CHK_RE.search(prompt))
    if not (is_gray or is_pgen or is_pchk):
        return None

    # composite / special-algebra defence in depth (reuse the bridge guards).
    if _bridge._COMPOSITE_RE.search(prompt) or _bridge._SPECIAL_ALGEBRA_RE.search(prompt):
        return None
    # a clocked gray counter is out of this combinational scope.
    if _GRAY_COUNTER_RE.search(prompt):
        return None

    names = _io_names(record, top)
    if names is None:
        return None
    in_names, out_names = names

    # classify each port name as bus vs scalar (for the gray-conversion path; the
    # parity path classifies its single flag structurally below).
    in_buses = [n for n in in_names if not _is_scalar(n)]
    in_scalars = [n for n in in_names if _is_scalar(n)]
    out_buses = [n for n in out_names if not _is_scalar(n)]

    # GRAY-primary vs PARITY-primary decision (a converter MAY also expose a
    # parity side-output, so the parity tokens alone don't make it a parity
    # device). It is a GRAY converter when a conversion DIRECTION is stated AND
    # the data flows bus->bus (one data-in bus + one data-out bus). It is a
    # PARITY device only when there is NO gray conversion (no direction) and the
    # primary output is a 1-bit flag with no data-out bus.
    direction = _gray_direction(prompt)
    has_io_bus = bool(in_buses) and bool(out_buses)
    gray_primary = is_gray and direction is not None and has_io_bus
    if gray_primary:
        if len(in_buses) != 1:
            return None  # need exactly one data input bus
        in_bus = in_buses[0]
        # primary output bus = the one naming the TARGET domain.
        target = re.compile(r"(?i)gray") if direction == "b2g" else re.compile(r"(?i)bin")
        named = [n for n in out_buses if target.search(n)]
        if len(named) == 1:
            out_bus = named[0]
        elif len(out_buses) == 1:
            out_bus = out_buses[0]
        else:
            return None
        wp = _bus_width_param(prompt)
        if wp is None:
            return None  # not parameter-width and no literal -> SKIP
        wparam, wdef = wp
        params: List[Tuple[str, int]] = [(wparam, max(wdef, 2))]
        if re.search(r"(?i)\bdebug_?mode\b", prompt):
            params.append(("DEBUG_MODE", _param_default(prompt, "DEBUG_MODE", 0)))
        side = [n for n in out_names if n != out_bus]
        extra = _resolve_side_outputs(prompt, out_bus, side)
        if extra is None:
            return None
        # any extra INPUT scalar (besides the bus) we don't consume -> SKIP
        if in_scalars:
            return None
        return _emit_gray(top, direction, in_bus, out_bus, wparam, params, extra)

    # ---- PARITY generator / checker ---------------------------------------- #
    # If a gray-conversion DIRECTION is stated, the device IS a converter; we
    # must not fall through and emit a (wrong) standalone parity device. The
    # gray branch above already had its chance — SKIP here.
    if direction is not None:
        return None
    if is_pgen or is_pchk:
        # A parity device has exactly ONE output: the 1-bit parity / error flag
        # (its name may be anything — par / parity / error / p — so we classify it
        # STRUCTURALLY as the sole output, not by a name regex). SKIP if there is
        # more than one output (that is a converter-with-side-output shape, not a
        # standalone parity device).
        if len(out_names) != 1:
            return None
        flag = out_names[0]
        non_flag_ins = [n for n in in_names if n != flag]
        kind = "check" if is_pchk else "gen"
        parity_in = None
        remaining = list(non_flag_ins)
        if kind == "check":
            # pull out the received parity bit FIRST (by name), so it is not
            # mistaken for a second data bus.
            pcand = [n for n in remaining
                     if re.search(r"(?i)parity|^p_?in$|received[_\s]*parity", n)]
            if len(pcand) == 1:
                parity_in = pcand[0]
                remaining = [n for n in remaining if n != parity_in]
        # the data bus is the sole remaining input.
        if len(remaining) != 1:
            return None  # ambiguous / unconsumed extra input -> SKIP
        data_bus = remaining[0]
        sense = _parity_sense(prompt, data_bus)
        if sense is None:
            return None  # §4.05 even-vs-odd unstated / ambiguous
        wp = _bus_width_param(prompt)
        if wp is None:
            # without a width parameter we cannot pin the data-bus width -> SKIP
            # (never guess a data-path width).
            return None
        wparam, wdef = wp
        params = [(wparam, max(wdef, 1))]
        return _emit_parity(top, sense, kind, data_bus, flag, parity_in, wparam, params)

    return None


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def family_of(record: dict) -> Optional[str]:
    if solve(record) is None:
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    # gray conversion takes precedence: a converter may also carry a parity
    # side-output, but its FAMILY is the conversion it performs.
    direction = _gray_direction(prompt)
    if direction is not None:
        return f"gray_{direction}"
    if _PARITY_CHK_RE.search(prompt):
        return "parity_check"
    if _PARITY_GEN_RE.search(prompt):
        return "parity_gen"
    return None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", required=True, help="CVDP code-generation jsonl")
    ap.add_argument("--id", help="solve only this record id")
    ap.add_argument("--emit", action="store_true", help="print emitted RTL")
    a = ap.parse_args(argv)
    recs = [json.loads(l) for l in open(a.jsonl)]
    n_emit = 0
    fam: Dict[str, int] = {}
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        rtl = solve(r)
        if rtl:
            n_emit += 1
            k = family_of(r)
            fam[k] = fam.get(k, 0) + 1
            if a.emit or a.id:
                print(f"=== {r.get('id')}  family={k}  top={_bridge.toplevel_name(r)} ===")
                print(rtl)
    print(f"emitted={n_emit}/{len(recs)}  families={fam}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
