#!/usr/bin/env python3
"""reset_clock_variant_alias.py — v0.3.18 (ORGANIC #518).

A design frequently declares its reset/clock port as ONE common standard
spelling (e.g. `reset_n`) while a hidden testbench instantiates an EQUIVALENT
standard spelling (`rst_n`) — same semantic (active-low reset), different name
→ an "Unknown port" compile-FAIL. The set of standard reset/clock spellings is
small and well-known, so this is recoverable deterministically.

This program provides the POLARITY-SAFE variant map plus a wrapper emitter:
given a chip-top port list, it renames each non-canonical reset/clock port to
the canonical spelling for its polarity/role, so a hidden TB using the common
canonical name elaborates. The renaming is 1:1 (one TB-facing name per core
input — the only electrically-safe alias for an input clock/reset) and the
canonical-per-polarity target is the single most likely hidden-TB convention.

ABSOLUTE GUARANTEE — POLARITY IS NEVER CROSSED
----------------------------------------------
An active-LOW reset (`reset_n`, `rstn`, `nreset`, `resetb`, …) only ever maps to
another active-low name; an active-HIGH reset (`reset`, `rst`, `areset`) only to
an active-high name. `emit_variant_alias_wrapper` RAISES on any cross-polarity
rename. Wiring an active-high reset to an active-low port name would silently
inverts the reset semantic — that must never happen.

HONEST LIMIT
------------
Only the closed set of STANDARD reset/clock spellings below is recognised; a
truly novel reset name is left untouched (Category-A port-identity FLOOR). The
canonical-per-polarity rename is a single best bet — if the hidden TB happens to
use the design's original (non-canonical) spelling, that case is not rescued.

chip-AGNOSTIC: only the generic reset/clock spelling sets are baked in.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Standard reset spellings, split by polarity. Active-low names carry an
# explicit low-asserted marker (`_n`/`n`/`_b`/`b` suffix or `n` prefix).
_RESET_ACTIVE_LOW = frozenset({
    "rst_n", "rstn", "reset_n", "resetn", "arst_n", "arstn",
    "nrst", "nreset", "n_rst", "n_reset", "rst_b", "resetb", "reset_b",
})
_RESET_ACTIVE_HIGH = frozenset({
    "rst", "reset", "arst", "areset", "rst_i", "reset_i",
})
# Canonical target spelling per reset polarity.
_RESET_CANON = {"active_low": "rst_n", "active_high": "rst"}

# Standard clock spellings (no polarity) + canonical target.
_CLOCK_NAMES = frozenset({"clk", "clock", "clk_i", "clock_i", "clk_in"})
_CLOCK_CANON = "clk"


def classify_reset(name: str) -> Optional[str]:
    """Return 'active_low' / 'active_high' if `name` is a recognised standard
    reset spelling, else None."""
    n = name.lower()
    if n in _RESET_ACTIVE_LOW:
        return "active_low"
    if n in _RESET_ACTIVE_HIGH:
        return "active_high"
    return None


def is_clock(name: str) -> bool:
    return name.lower() in _CLOCK_NAMES


def equivalent_variants(name: str) -> List[str]:
    """Standard spellings equivalent to `name` (same reset polarity, or the
    clock set), EXCLUDING `name` itself. [] when `name` is not recognised."""
    n = name.lower()
    pol = classify_reset(n)
    if pol == "active_low":
        pool = _RESET_ACTIVE_LOW
    elif pol == "active_high":
        pool = _RESET_ACTIVE_HIGH
    elif is_clock(n):
        pool = _CLOCK_NAMES
    else:
        return []
    return sorted(v for v in pool if v != n)


def canonical_variant(name: str) -> Optional[str]:
    """The canonical target spelling for `name`'s polarity/role, else None."""
    pol = classify_reset(name)
    if pol:
        return _RESET_CANON[pol]
    if is_clock(name):
        return _CLOCK_CANON
    return None


def _same_class(a: str, b: str) -> bool:
    """True iff a and b are reset of the SAME polarity, or both clocks."""
    pa, pb = classify_reset(a), classify_reset(b)
    if pa or pb:
        return pa is not None and pa == pb
    return is_clock(a) and is_clock(b)


def plan_aliases(port_names: List[str]) -> Dict[str, str]:
    """Deterministic rename policy: map each recognised reset/clock port whose
    spelling is NOT already canonical to its canonical-per-polarity spelling.

    Skips a port if the canonical name would collide with another EXISTING port
    OR with a canonical name ALREADY ASSIGNED to an earlier port in this plan —
    so a design declaring two same-polarity variants (e.g. `reset_n` AND `rstn`,
    both → `rst_n`) never produces a duplicate wrapper port (ORGANIC #518
    adversarial review). Only the first such variant is canonicalised; the rest
    keep their original spelling. POLARITY-SAFE by construction."""
    existing = {p.lower() for p in port_names}
    assigned_targets: set = set()
    plan: Dict[str, str] = {}
    for p in port_names:
        canon = canonical_variant(p)
        if canon is None or canon == p.lower():
            continue
        if canon in existing:
            continue  # would collide with a real port — skip
        if canon in assigned_targets:
            continue  # another same-polarity variant already took this name
        # canonical_variant guarantees same class; assert it explicitly.
        if not _same_class(p, canon):
            continue
        plan[p] = canon
        assigned_targets.add(canon)
    return plan


# Word-boundary anchored: matches both spaced and COMPACT Verilog (#517 r3).
_PORT_DECL_RE = re.compile(
    r"\b(input|output|inout)\b\s*"
    r"(?:(?:wire|reg|logic|signed|unsigned)\b\s*)*"
    r"(\[[^\]]+\])?\s*(\w+)")


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _module_header(text: str, module: str
                   ) -> Optional[Tuple[Optional[str], str]]:
    """Return (param_block, port_block) for `module <module> [#(...)] (...)`,
    SKIPPING/capturing an optional `#(parameter ...)` block (balanced-paren +
    string-literal aware). None if not found. Same parameterized-module fix as
    #517 reopen — a clocked chip-top is often parameterized
    (`module foo #(parameter W=8) (...)`)."""
    text = _strip_comments(text)
    m = re.search(rf"\bmodule\s+{re.escape(module)}\b", text)
    if not m:
        return None
    i, n = m.end(), len(text)

    def _skip_ws(j: int) -> int:
        while j < n and text[j].isspace():
            j += 1
        return j

    def _skip_balanced(j: int) -> Optional[int]:
        # string-literal aware (#517 r3): a '(' inside "..." must not unbalance.
        depth = 0
        while j < n:
            c = text[j]
            if c == '"':
                j += 1
                while j < n and text[j] != '"':
                    if text[j] == "\\":
                        j += 1
                    j += 1
                j += 1
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return None

    i = _skip_ws(i)
    # ORGANIC #637 — consume any `import pkg::*;` clauses between
    # `module <name>` and the `#(...)`/`(...)` regions (the standard SV
    # ordering `module X import a_pkg::*; #(params) (ports);`). Without this
    # the `#`/`(` test below finds `import` and returns None, so the port
    # parser / clock-reset alias emitter see zero ports on any package-
    # importing top (REUSED-IP / IP-integration-wrapper class). Repeatable.
    while True:
        im = re.match(r"import\s+[\w:\*\s,]+;", text[i:])
        if not im:
            break
        i = _skip_ws(i + im.end())
    param_block: Optional[str] = None
    if i < n and text[i] == "#":
        i = _skip_ws(i + 1)
        if i < n and text[i] == "(":
            j = _skip_balanced(i)
            if j is None:
                return None
            param_block = text[i + 1:j - 1].strip()
            i = _skip_ws(j)
    if i < n and text[i] == "(":
        j = _skip_balanced(i)
        if j is None:
            return None
        return (param_block, text[i + 1:j - 1])
    return None


def _module_portlist_block(text: str, module: str) -> Optional[str]:
    hdr = _module_header(text, module)
    return None if hdr is None else hdr[1]


def parse_module_params(rtl_text: str, module: str
                        ) -> Tuple[Optional[str], List[str]]:
    """Return (raw_param_block, [param_names]) for `module <module> #(...)`.
    (None, []) when not parameterized. Mirrors leaf_typo_alias_emit so the
    reset/clock wrapper of a parameterized top forwards its parameters."""
    hdr = _module_header(rtl_text, module)
    if hdr is None or hdr[0] is None:
        return (None, [])
    return (hdr[0], re.findall(r"(\w+)\s*=", hdr[0]))


def parse_module_ports(rtl_text: str, module: str
                       ) -> List[Tuple[str, str, str]]:
    block = _module_portlist_block(rtl_text, module)
    if block is None:
        return []
    return [(pm.group(1), (pm.group(2) or "").strip(), pm.group(3))
            for pm in _PORT_DECL_RE.finditer(block)]


def emit_variant_alias_wrapper(core_module: str,
                               ports: List[Tuple[str, str, str]],
                               rename_map: Dict[str, str],
                               wrapper_name: Optional[str] = None,
                               param_block: Optional[str] = None,
                               param_names: Optional[List[str]] = None) -> str:
    """Render a wrapper that exposes each renamed reset/clock port under its
    TB-facing variant name and wires it 1:1 to the core's original port; all
    other ports pass straight through. RAISES ValueError on a cross-polarity
    (or reset↔clock) rename — polarity is never crossed.

    When the core is PARAMETERIZED, the wrapper inherits the same `#(...)` block
    and forwards every parameter to the instance, so a parameterized clocked top
    elaborates (its `[W-1:0]` reset/clock-adjacent port widths resolve)."""
    for orig, new in rename_map.items():
        if not _same_class(orig, new):
            raise ValueError(
                f"refusing cross-polarity/role reset-clock alias "
                f"{orig!r} -> {new!r}: "
                f"{orig}={classify_reset(orig) or ('clock' if is_clock(orig) else '?')}, "
                f"{new}={classify_reset(new) or ('clock' if is_clock(new) else '?')}")
    wrapper_name = wrapper_name or f"{core_module}_aliased"
    # Defensive duplicate-face guard (#518): the TB-facing port names (after
    # renaming) must be UNIQUE — a rename_map that collapses two ports onto one
    # name would emit invalid Verilog (`input rst_n, input rst_n`). plan_aliases
    # already prevents this; reject any hand-built map that doesn't.
    faces = [rename_map.get(name, name) for _d, _w, name in ports]
    dupes = sorted({f for f in faces if faces.count(f) > 1})
    if dupes:
        raise ValueError(
            f"refusing reset/clock alias that produces duplicate wrapper "
            f"port name(s) {dupes}: a rename collapsed two ports onto one name.")
    param_hdr = ""
    inst_params = ""
    if param_block:
        param_hdr = f" #(\n    {param_block}\n)"
        if param_names:
            inst_params = " #(" + ", ".join(
                f".{p}({p})" for p in param_names) + ")"
    decls, conns = [], []
    for direction, width, name in ports:
        face = rename_map.get(name, name)
        w = f" {width}" if width else ""
        decls.append(f"    {direction}{w} {face}")
        conns.append(f"        .{name}({face})")
    lines = [
        f"// {wrapper_name} — reset/clock NAME-VARIANT alias wrapper for "
        f"`{core_module}`",
        "// Exposes the canonical-per-polarity reset/clock spelling so a hidden",
        "// testbench using a different but equivalent STANDARD name elaborates.",
        "// Polarity is preserved 1:1. Generated by reset_clock_variant_alias.py"
        " (#518).",
        f"module {wrapper_name}{param_hdr} (",
        ",\n".join(decls),
        ");",
        f"    {core_module}{inst_params} u_{core_module} (",
        ",\n".join(conns),
        "    );",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit a reset/clock name-variant alias wrapper (canonical "
                    "spelling, polarity-preserved) for a chip-top module.")
    ap.add_argument("--rtl", required=True, help="RTL file with the core module")
    ap.add_argument("--module", required=True, help="core (chip-top) module name")
    ap.add_argument("--out", default=None, help="wrapper output path")
    args = ap.parse_args(argv)
    rtl = Path(args.rtl)
    if not rtl.is_file():
        print(f"error: rtl not found: {rtl}", file=sys.stderr)
        return 2
    ports = parse_module_ports(rtl.read_text(errors="replace"), args.module)
    if not ports:
        print(f"error: module {args.module!r} not found / no ANSI ports.",
              file=sys.stderr)
        return 1
    plan = plan_aliases([p[2] for p in ports])
    if not plan:
        print(f"ok: {args.module!r} reset/clock ports already canonical "
              f"(no alias wrapper needed)")
        return 0
    wrapper = emit_variant_alias_wrapper(args.module, ports, plan)
    out = Path(args.out) if args.out else rtl.with_name(f"{args.module}_aliased.v")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(wrapper)
    print(f"ok: wrote {out} (aliases={plan})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
