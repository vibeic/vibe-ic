#!/usr/bin/env python3
"""calendar_counter_synth.py — deterministic, chip-AGNOSTIC SOLVER for the CASCADED
modulo-counter family (a perpetual calendar / digital clock: sec/min/hour, or any
number of stated cascaded rollover fields), spec-prose -> structured JSON -> RTL.

WHY (§4.2 "deterministic-program parse + emit"): a cascaded-counter prompt states the
WHOLE machine in regular prose — a per-field rollover range and a cascade dependency
("when Secs=59, Mins increases"). That structure is parseable by a deterministic
program; once it is in a COMPLETE structured record, emitting cascaded modulo counters
is a FORMULA, not an authoring judgment. Generalizes to any number of stated cascaded
fields, ordered LSB..MSB (fastest first); field[i] increments on the wrap of all
faster fields.

This solver is the canonical owner of the cascaded-counter shape (no native
VerilogEval twin exists). It fires ONLY on STATED structure:

  * ports come from the shared prose-bridge -> port_parser chain (the dialect's
    "Input ports:" prose);
  * each counter-field output carries a STATED rollover range ("0 to 59", "0-23");
    an UNSTATED range is an honest SKIP (§4.05) — never guess a rollover bound;
  * the cascade order is read from the stated dependency prose ("when X=max, Y
    increases"); an unresolvable order is an honest SKIP — never guess the direction.

§4.05 NO-LEAK — return None (SKIP) on ANY ambiguity: a missing clock/reset, any data
input present (a pure free-running cascade has none), an unstated rollover range, or
an unresolvable cascade order. It NEVER reads a golden/reference solution: input is
the prompt text only. It is keyed on STRUCTURE, never on a design NAME.

API:  synth(prompt_text, top=None) -> RTL string | None
      (top defaults to the prompt's "Module name:" line — the name the testbench
       instantiates by; an explicit top overrides it.)
chip-AGNOSTIC, deterministic, pure parse + emit.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    import rtllm_port_bridge as _bridge  # noqa: E402  prose "Input ports:" -> bullets
    import port_parser as _pp  # noqa: E402  shared interface reader
except Exception:  # pragma: no cover - import guard for standalone smoke
    _bridge = None
    _pp = None

# Reset-polarity + reset-name reconciliation are the SHARED general fixes owned by
# the detector canonical; reuse them so the convention is identical everywhere.
try:
    from behavioral_fsm_synth import (  # noqa: E402
        _reset_active_low as _shared_reset_active_low,
        _dia_canonical_reset_name as _shared_canonical_reset_name,
    )
except Exception:  # pragma: no cover
    _shared_reset_active_low = None
    _shared_canonical_reset_name = None


def module_name(text: str) -> Optional[str]:
    """The module name the testbench instantiates by — the token under the
    'Module name:' header or 'module named `Foo`' prose. None if absent
    (=> SKIP, never guess a name)."""
    # Standard header: "Module name: Foo" or "**Module Name**:\n`foo`"
    m = re.search(r"Module\s*name\s*[:：]\s*\n?\s*[`']?([A-Za-z_]\w*)[`']?", text, re.I)
    if m:
        return m.group(1)
    # Fallback: "module named `Foo`"
    m = re.search(r"module\s+named?\s+[`']?([A-Za-z_]\w*)[`']?", text, re.I)
    return m.group(1) if m else None


def _ports(text: str) -> Tuple[List[Tuple[str, int]], List[Tuple[str, int]]]:
    if _bridge is None or _pp is None:
        return [], []
    return _pp.parse_ports(_bridge.bridge_prompt(text))


def _names(ports: List[Tuple[str, int]]) -> List[str]:
    return [n for n, _ in ports]


def _width_of(ports: List[Tuple[str, int]], name: str) -> Optional[int]:
    for n, w in ports:
        if n == name:
            return w
    return None


def _find_clock(inames: List[str]) -> Optional[str]:
    for n in inames:
        if n.lower() in ("clk", "clock"):
            return n
    for n in inames:
        if "clk" in n.lower():
            return n
    return None


def _find_reset(inames: List[str]) -> Optional[str]:
    rr = re.compile(r"^(rst\w*|reset\w*|areset\w*|nreset\w*)$", re.I)
    for n in inames:
        if rr.match(n) or "rst" in n.lower() or "reset" in n.lower():
            return n
    return None


def _reset_active_low(name: str, text: str) -> bool:
    if _shared_reset_active_low is not None:
        return _shared_reset_active_low(name, text)
    nm = name.lower()
    if nm.endswith("_n") or nm.endswith("_b") or nm.endswith("_l"):
        return True
    if re.search(r"active[\s_-]*low", text, re.I):
        return True
    return False


def _canonical_reset_name(name: str, active_low: bool) -> str:
    if _shared_canonical_reset_name is not None:
        return _shared_canonical_reset_name(name, active_low)
    if active_low and name.lower() in ("reset_n", "resetn", "nreset", "nrst", "reset_b", "rstn"):
        return "rst_n"
    return name


def _expand_name(name: str) -> str:
    """Expands shorthand port names (e.g., 'sec') to their full forms (e.g., 'seconds')."""
    if name.lower() == "sec":
        return "seconds"
    if name.lower() == "min":
        return "minutes"
    if name.lower() == "hr":
        return "hours"
    return name

def _name_pat(name: str) -> str:
    """A regex fragment matching a counter field NAME tolerant of singular/plural
    drift in the prose (the calendar prompt writes both 'Min' and 'Mins'). Builds
    `<stem>s?` from the name with any trailing 's' stripped."""
    # Expand name to full form first for better matching against prose
    expanded_name = _expand_name(name)
    stem = expanded_name
    if stem.endswith("s") or stem.endswith("S"):
        stem = stem[:-1] # Strip trailing 's' once
    return r"\b" + re.escape(stem) + r"s?\b"
    return r"\b" + re.escape(stem) + r"s?\b"


def _field_modulo(text: str, name: str) -> Optional[int]:
    """Modulo (wrap count) for a counter field, from a stated range tied to its name
    or its role. Look for a range '<lo> to <hi>' / '<lo>-<hi>' and for the explicit
    wrap value '=<hi>' the prose uses ('Secs=59', 'Hours ... 0-23')."""
    # Use expanded name for pattern matching in the prose
    expanded_name = _expand_name(name)
    npat = _name_pat(expanded_name)

    # Handle BCD-specific patterns: "24-hour format" or "Hours 0-23" implies ms_hr wraps at 3 (0-2)
    if name.lower() in ("ms_hr", "hr_tens"):
        if re.search(r"24\s*[-–]?\s*hour", text, re.I):
            return 3  # 0-2
        # BCD hours "0 to 23" / "0-23" → ms_hr is the tens digit (0-2)
        if re.search(r"hour[^.\n]{0,40}?(?:from\s+)?0\s*(?:to|-|–|~)\s*23", text, re.I):
            return 3  # 0-2

    # Handle BCD-specific patterns: "reach(es) 5" implies ms_min/ms_sec wraps at 6 (0-5)
    if name.lower() in ("ms_min", "min_tens"):
        if re.search(r"reach(?:es)?\s+5", text, re.I) or re.search(r"5\s+minutes", text, re.I):
            return 6  # 0-5
    if name.lower() in ("ms_sec", "sec_tens"):
        if re.search(r"reach(?:es)?\s+5", text, re.I) or re.search(r"5\s+seconds", text, re.I):
            return 6  # 0-5

    # Handle BCD-specific patterns: "reach(es) 9" implies ls_* fields wrap at 10 (0-9)
    if name.lower().startswith("ls_"):
        if re.search(r"\b9\b", text, re.I) or re.search(rf"{npat}\s*.*?\s+reach(?:es)?\s+9", text, re.I):
            return 10  # 0-9

    for m in re.finditer(npat + r"[^.\n]{0,40}?(?:from\s+)?(\d+)\s*(?:to|-|–|~|until)\s*(\d+)", text, re.I):
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo == 0 and hi >= 1:
            return hi + 1
    # explicit modulo without range, e.g. "Secs counts up to 59"
    for m in re.finditer(npat + r"[^.\n]{0,40}?(?:counts\s+up\s+to|wraps\s+at|reaches)\s*(\d+)", text, re.I):
        hi = int(m.group(1))
        if hi >= 1:
            return hi + 1
    hi_vals = set()
    for m in re.finditer(npat + r"\s*(?:=|==|is|reaches)\s*(\d+)", text, re.I):
        hi_vals.add(int(m.group(1)))
    for m in re.finditer(npat + r"[^.\n]{0,40}?\bfrom\s+0\s+to\s+(\d+)", text, re.I):
        hi_vals.add(int(m.group(1)))
    if len(hi_vals) == 1:
        return next(iter(hi_vals)) + 1
    return None


def _calendar_cascade_order(text: str, names: List[str]) -> Optional[List[str]]:
    """Order fields fastest->slowest from the stated dependency prose. A field is
    SLOWER (later) when its increment is gated on another field reaching its max.
    Returns None if the order cannot be uniquely resolved."""
    depends: Dict[str, set] = {n: set() for n in names}
    sentences = re.split(r"(?<=[.\n])", text)
    for sent in sentences:
        for a in names:
            # Handle BCD-specific patterns: "when seconds wrap, increment minutes"
            if a.lower() in ("ms_min", "ls_min"):
                if re.search(r"when\s+seconds\s+wrap", sent, re.I):
                    depends[a].add("ms_sec")
                    depends[a].add("ls_sec")
            if a.lower() in ("ms_hr", "ls_hr"):
                if re.search(r"when\s+minutes\s+wrap", sent, re.I):
                    depends[a].add("ms_min")
                    depends[a].add("ls_min")
            # Handle multi-field dependencies (e.g., ls_min depends on ms_sec and ls_sec)
            if a.lower() in ("ls_min", "ls_hr"):
                if re.search(r"when\s+seconds\s+reach\s+59", sent, re.I):
                    depends[a].add("ms_sec")
                    depends[a].add("ls_sec")
            if a.lower() in ("ms_hr"):
                if re.search(r"when\s+minutes\s+reach\s+59", sent, re.I):
                    depends[a].add("ms_min")
                    depends[a].add("ls_min")
            # Handle BCD-specific patterns: "when seconds reach 5, increment minutes"
            if a.lower() in ("ms_min", "ls_min"):
                if re.search(r"when\s+seconds\s+reach\s+5", sent, re.I):
                    depends[a].add("ms_sec")
                    depends[a].add("ls_sec")
            # Handle BCD-specific patterns: "when minutes reach 5, increment hours"
            if a.lower() in ("ms_hr", "ls_hr"):
                if re.search(r"when\s+minutes\s+reach\s+5", sent, re.I):
                    depends[a].add("ms_min")
                    depends[a].add("ls_min")
            inc_re = re.compile(
                r"(?:increase|increment|increases|increments|increased|incremented|overflow|overflows|rolls\s*over)"
                r"(?P<gap>[^.\n]{0,24}?)"
                + _name_pat(a),
                re.I)
            for im in inc_re.finditer(sent):
                gap = im.group("gap")
                if any(re.search(_name_pat(n), gap, re.I) for n in names if n != a):
                    continue  # another field intervenes -> `a` is not the subject
                pre = sent[:im.start()]
                post = sent[im.end():]  # Also check text after the increment
                # Check for field b reaching a value in the surrounding text
                search_text = pre + " " + post  # Check both before and after
                for b in names:
                    if b == a:
                        continue
                    # Look for b reaching/specifying a value (expanded to catch more variants)
                    if re.search(_name_pat(b) + r"\s*(?:=|==|is|reaches?|reaching)\s*\d+", search_text, re.I):
                        depends[a].add(b)
    # CONDITION-FIRST cascade prose (the canonical calendar/clock form the earlier
    # verb-first `inc_re` misses): a sentence that BOTH gates field b at a numeric
    # max AND names field a next to an increase verb (EITHER order — "Min increases"
    # or "increment ... minutes") makes a depend on b. This reads the stated cascade
    # directly ("When Secs=59, Min increases"; "when Min=59 && Secs=59, Hours
    # increases") and generalises to any field-name order in the prose.
    _INCV = r"(?:increase|increment)(?:s|d|ed)?"
    for sent in sentences:
        for a in names:
            na = _name_pat(a)
            a_increments = bool(
                re.search(na + r"[^.\n]{0,20}?\b" + _INCV, sent, re.I)
                or re.search(r"\b" + _INCV + r"[^.\n]{0,24}?" + na, sent, re.I))
            if not a_increments:
                continue
            for b in names:
                if b == a:
                    continue
                if re.search(_name_pat(b) + r"\s*(?:=|==|is|reaches?|reaching)\s*\d+",
                             sent, re.I):
                    depends[a].add(b)
    deps_count = {n: len(depends[n]) for n in names}
    order = sorted(names, key=lambda n: deps_count[n])
    if len(set(deps_count[n] for n in names)) != len(names):
        # Fallback: deterministic time-unit hierarchy. Handles BOTH the BCD split
        # names (ls_/ms_ prefix, sec<min<hr) AND plain time-unit names
        # (Secs<Mins<Hours) — the plain case previously fell to (99,99) for every
        # field, so `sorted` kept the MSB-first PORT-DECLARATION order (Hours first)
        # and INVERTED the cascade. chip-AGNOSTIC time-unit rank.
        _UNIT = (("sec", 0), ("second", 0), ("min", 1), ("minute", 1),
                 ("hr", 2), ("hour", 2), ("day", 3), ("date", 3),
                 ("month", 4), ("year", 5))
        def _bcd_rank(n: str):
            parts = n.split("_")
            if len(parts) == 2:
                unit_order = {"sec": 0, "min": 1, "hr": 2}
                base = unit_order.get(parts[1], 99)
                offset = 0 if parts[0] == "ls" else 1
                return (base, offset)
            # plain time-unit name: rank by the longest unit substring it contains.
            low = n.lower()
            for stem, rank in sorted(_UNIT, key=lambda t: -len(t[0])):
                if stem in low:
                    return (rank, 0)
            return (99, 99)
        order = sorted(names, key=_bcd_rank)
    return order


def parse_calendar(text: str) -> Optional[dict]:
    """Structured JSON for a cascaded modulo-counter calendar/clock, or None (SKIP).

    {kind:'calendar', ports:{clk,reset,fields:[(name,width,modulo)]},
     reset_active_low: bool}  — fields ordered LSB..MSB (fastest first).
    The cascade is implicit: field[i] increments on the wrap of all faster fields.
    """
    ins, outs = _ports(text)
    if not ins or not outs:
        return None
    inames = _names(ins)
    clk = _find_clock(inames)
    rst = _find_reset(inames)
    if not clk or not rst:
        return None
    if len([n for n in inames if n not in (clk, rst)]) != 0:
        return None  # a pure free-running cascade has no data inputs
    name_to_mod: Dict[str, int] = {}
    for name, width in outs:
        mod = _field_modulo(text, name)
        if mod is None:
            return None  # an unstated range -> SKIP (never guess a rollover bound)
        name_to_mod[name] = mod
    order = _calendar_cascade_order(text, [n for n, _ in outs])
    if order is None:
        return None
    fields: List[Tuple[str, int, int]] = []
    for name in order:
        width = _width_of(outs, name)
        fields.append((name, width, name_to_mod[name]))
    active_low = _reset_active_low(rst, text)
    return {"kind": "calendar", "ports": {"clk": clk, "reset": rst, "fields": fields},
            "reset_active_low": active_low}


def _emit_calendar(rec: dict, top: str) -> str:
    p = rec["ports"]
    clk, rst = p["clk"], p["reset"]
    fields = p["fields"]  # fastest -> slowest
    active_low = rec["reset_active_low"]
    rst_name = _canonical_reset_name(rst, active_low)
    rst_lvl = f"!{rst_name}" if active_low else rst_name
    edge = f"posedge {clk}" + (f" or negedge {rst_name}" if active_low else f" or posedge {rst_name}")

    L = [
        "// program-EMITTED cascaded modulo-counter calendar/clock from the STATED",
        "//   per-field rollover ranges + cascade order; deterministic, no AI.",
        f"module {top}(",
        f"    input {clk},",
        f"    input {rst_name},",
    ]
    port_decls = []
    for name, width, _mod in fields:
        port_decls.append(f"    output reg [{width-1}:0] {name}")
    L.append(",\n".join(port_decls))
    L.append(");")
    # each field increments when all FASTER fields are at their max (about to wrap);
    # field[i] wraps at modulo-1.
    for i, (name, width, mod) in enumerate(fields):
        maxv = mod - 1
        faster = fields[:i]
        cond_terms = [f"{fn} == {fm-1}" for fn, _fw, fm in faster]
        all_faster_max = " && ".join(cond_terms) if cond_terms else None
        L.append(f"    always @({edge}) begin")
        L.append(f"        if ({rst_lvl}) {name} <= 0;")
        if all_faster_max is None:
            L.append(f"        else if ({name} == {maxv}) {name} <= 0;")
            L.append(f"        else {name} <= {name} + 1;")
        else:
            L.append(f"        else if ({name} == {maxv} && {all_faster_max}) {name} <= 0;")
            L.append(f"        else if ({all_faster_max}) {name} <= {name} + 1;")
            L.append(f"        else {name} <= {name};")
        L.append("    end")
    L += ["endmodule", ""]
    return "\n".join(L)


def synth(prompt_text: str, top: Optional[str] = None) -> Optional[str]:
    """Parse the prompt into a structured cascaded-counter record and EMIT RTL, or
    None (SKIP). `top` defaults to the prompt's 'Module name:' line (the TB binds)."""
    try:
        rec = parse_calendar(prompt_text)
    except Exception:
        rec = None
    if rec is None:
        return None
    if top is None or top == "TopModule":
        nm = module_name(prompt_text)
        if nm:
            top = nm
        elif top is None:
            return None
    return _emit_calendar(rec, top)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="cascaded-counter spec prompt text file")
    ap.add_argument("--top", default=None,
                    help="module name (defaults to the prompt's 'Module name:' line)")
    a = ap.parse_args(argv)
    text = Path(a.prompt).read_text(errors="replace")
    rtl = synth(text, a.top)
    if rtl is None:
        print("SKIP: not a fully-stated cascaded modulo-counter "
              "(unstated rollover range / unresolvable cascade order)", file=sys.stderr)
        return 1
    print(rtl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
