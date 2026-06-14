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


# ORGANIC #671 — preprocessor-directive tokens for the port-surface parser.
_PP_DIRECTIVE_RE = re.compile(
    r"^[ \t]*`(ifdef|ifndef|elsif|else|endif|define)\b[ \t]*(\w+)?",
    re.MULTILINE)


def _collect_inline_defines(text: str, base: "Optional[set]" = None) -> set:
    """ORGANIC #671 — the set of macros UNCONDITIONALLY `define-d in `text`
    (those sitting at preprocessor depth 0 — not nested inside an un-taken
    `ifdef arm). Mirrors the way an in-file `` `define X `` that itself sits
    under a gate only becomes visible when that gate is taken. Seeded by the
    compile-time `base` define-set (the -D flags the sv2v / compile uses)."""
    active: set = set(base or set())
    # Walk the directive stream tracking a take/skip stack so a `define inside
    # an un-taken arm does not leak into the active set.
    take_stack: List[bool] = []  # one bool per open `ifdef/`ifndef/`else region

    def _all_taken() -> bool:
        return all(take_stack)

    for m in _PP_DIRECTIVE_RE.finditer(text):
        kind, name = m.group(1), m.group(2)
        if kind == "define":
            if name and _all_taken():
                active.add(name)
        elif kind == "ifdef":
            take_stack.append(_all_taken() and (name in active))
        elif kind == "ifndef":
            take_stack.append(_all_taken() and (name not in active))
        elif kind == "elsif":
            if take_stack:
                # flip: this arm is taken iff no earlier arm in the chain was,
                # the enclosing context is taken, and the macro is defined.
                outer = all(take_stack[:-1]) if len(take_stack) > 1 else True
                take_stack[-1] = outer and (not take_stack[-1]) \
                    and (name in active)
        elif kind == "else":
            if take_stack:
                outer = all(take_stack[:-1]) if len(take_stack) > 1 else True
                take_stack[-1] = outer and (not take_stack[-1])
        elif kind == "endif":
            if take_stack:
                take_stack.pop()
    return active


def _resolve_preprocessor_arms(text: str,
                               defines: "Optional[set]" = None) -> str:
    """ORGANIC #671 — blank out the bodies of NOT-TAKEN `ifdef/`ifndef/`elsif/
    `else arms under the compile-time define-set `defines`, so a downstream
    port-list scan never binds a conditionally-compiled port (e.g. a formal /
    debug interface gated by a define the sv2v/compile set does NOT pass).

    The historical caller passed no define-set, taking EVERY arm — which over-
    counts ports inside never-compiled `ifdef arms and makes the generated TB
    bind pins the DUT does not expose. With `defines` = the SAME define-set the
    in-runner sv2v DUT conversion uses (e.g. {SIMULATION} or {SYNTHESIS}), an
    arm whose gating macro is absent is removed before the port regex runs, so
    the TB↔DUT port surfaces match. Newlines are preserved (bodies blanked, not
    deleted) so byte offsets and line structure are stable.

    chip-AGNOSTIC: pure `ifdef/`define grammar + the abstract compile define-set
    — no chip / vendor / macro-name literal."""
    if "`if" not in text:
        return text  # no conditional compilation — nothing to resolve
    active = _collect_inline_defines(text, defines)
    out: List[str] = []
    # take_stack[i] = is region i currently taken (under the enclosing context)
    take_stack: List[bool] = []
    seen_taken: List[bool] = []  # has ANY arm of this if-chain been taken yet

    def _ctx_taken() -> bool:
        return all(take_stack) if take_stack else True

    for line in text.splitlines(keepends=True):
        m = _PP_DIRECTIVE_RE.match(line)
        kind = m.group(1) if m else None
        name = m.group(2) if m else None
        if kind in ("ifdef", "ifndef"):
            outer = _ctx_taken()
            taken = outer and (
                (name in active) if kind == "ifdef" else (name not in active))
            take_stack.append(taken)
            seen_taken.append(taken)
            out.append(line)  # keep the directive line itself
            continue
        if kind == "elsif":
            if take_stack:
                outer = all(take_stack[:-1]) if len(take_stack) > 1 else True
                taken = outer and (not seen_taken[-1]) and (name in active)
                take_stack[-1] = taken
                seen_taken[-1] = seen_taken[-1] or taken
            out.append(line)
            continue
        if kind == "else":
            if take_stack:
                outer = all(take_stack[:-1]) if len(take_stack) > 1 else True
                taken = outer and (not seen_taken[-1])
                take_stack[-1] = taken
                seen_taken[-1] = seen_taken[-1] or taken
            out.append(line)
            continue
        if kind == "endif":
            if take_stack:
                take_stack.pop()
                seen_taken.pop()
            out.append(line)
            continue
        # ordinary body line: keep only when the enclosing context is taken;
        # else blank it (preserve the trailing newline so line structure holds).
        if _ctx_taken():
            out.append(line)
        else:
            out.append("\n" if line.endswith("\n") else "")
    return "".join(out)


def _module_header(text: str, module: str,
                   defines: "Optional[set]" = None
                   ) -> Optional[Tuple[Optional[str], str, List[str]]]:
    """Return (param_block, port_block, import_clauses) for
    `module <module> [import pkg::*;]* [#(...)] (...)`, SKIPPING/capturing an
    optional `#(parameter ...)` block (balanced-paren + string-literal aware)
    and CAPTURING any `import pkg::*;` clauses that sit between the module name
    and the param/port regions. None if not found. Same parameterized-module
    fix as #517 reopen — a clocked chip-top is often parameterized
    (`module foo #(parameter W=8) (...)`).

    The `import_clauses` list (ORGANIC #656) carries the verbatim
    `import pkg::*;` text the regex loop consumes, so the wrapper emitter can
    RE-EMIT them in the wrapper header — without it the wrapper references
    package-scoped port-width params (e.g. a bus-pkg width localparam) with no
    import in scope → a deterministic SV `use of undeclared identifier` error.

    ORGANIC #671 — when `defines` (the compile-time -D set the sv2v/iverilog
    DUT conversion uses) is supplied, NOT-TAKEN `ifdef/`ifndef/`elsif/`else
    arms are blanked BEFORE the port list is extracted, so a conditionally-
    compiled port (e.g. a formal/debug interface gated by a macro absent from
    the compile set) is never returned as a DUT port. `defines=None` preserves
    the historical take-every-arm behaviour exactly (no regression)."""
    text = _strip_comments(text)
    if defines is not None:
        text = _resolve_preprocessor_arms(text, defines)
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
    # ORGANIC #656 — CAPTURE the consumed clauses (verbatim) so the wrapper
    # emitter can re-emit them; package-scoped port-width params only resolve
    # if the import is back in scope on the outer wrapper.
    import_clauses: List[str] = []
    while True:
        im = re.match(r"import\s+[\w:\*\s,]+;", text[i:])
        if not im:
            break
        import_clauses.append(im.group(0).strip())
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
        return (param_block, text[i + 1:j - 1], import_clauses)
    return None


def _module_portlist_block(text: str, module: str,
                           defines: "Optional[set]" = None) -> Optional[str]:
    hdr = _module_header(text, module, defines)
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


def parse_module_imports(rtl_text: str, module: str) -> List[str]:
    """Return the verbatim `import pkg::*;` clauses (in source order) sitting
    between `module <module>` and its param/port regions; [] when there are
    none (ORGANIC #656). Mirrors parse_module_params so the reset/clock wrapper
    of a package-importing top RE-EMITS the imports its port widths depend on —
    package-scoped width params (e.g. a bus-pkg width localparam) only resolve
    on the outer wrapper if the import is back in scope there."""
    hdr = _module_header(rtl_text, module)
    if hdr is None:
        return []
    return list(hdr[2])


def parse_module_ports(rtl_text: str, module: str,
                       defines: "Optional[set]" = None
                       ) -> List[Tuple[str, str, str]]:
    """Parse `module <module>`'s ANSI port list as [(dir, name, width), ...].

    ORGANIC #671 — `defines` is the compile-time -D set the in-runner sv2v /
    iverilog DUT conversion uses (e.g. {"SIMULATION"} or {"SYNTHESIS"}). When
    supplied, a port inside an `ifdef <MACRO> arm whose MACRO is NOT in that set
    is NOT returned (it is not a real DUT port under that conversion). When
    `defines=None` (the legacy default) every arm is parsed exactly as before —
    no regression on callers that don't pass a define-set."""
    block = _module_portlist_block(rtl_text, module, defines)
    if block is None:
        return []
    return [(pm.group(1), (pm.group(2) or "").strip(), pm.group(3))
            for pm in _PORT_DECL_RE.finditer(block)]


def emit_variant_alias_wrapper(core_module: str,
                               ports: List[Tuple[str, str, str]],
                               rename_map: Dict[str, str],
                               wrapper_name: Optional[str] = None,
                               param_block: Optional[str] = None,
                               param_names: Optional[List[str]] = None,
                               import_block: Optional[List[str]] = None) -> str:
    """Render a wrapper that exposes each renamed reset/clock port under its
    TB-facing variant name and wires it 1:1 to the core's original port; all
    other ports pass straight through. RAISES ValueError on a cross-polarity
    (or reset↔clock) rename — polarity is never crossed.

    When the core is PARAMETERIZED, the wrapper inherits the same `#(...)` block
    and forwards every parameter to the instance, so a parameterized clocked top
    elaborates (its `[W-1:0]` reset/clock-adjacent port widths resolve).

    When the core IMPORTS PACKAGES (ORGANIC #656), `import_block` carries the
    `import pkg::*;` clauses the parser consumed; they are re-emitted in the
    wrapper header (immediately after `module <wrapper>`, before the param
    header and the port list) so package-scoped port-width identifiers —
    e.g. a bus-pkg width localparam used as `[PKG_WIDTH-1:0]` in the inherited
    port decls — resolve on the outer wrapper instead of erroring as
    `use of undeclared identifier`. None/[] re-emits no import line."""
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
    # ORGANIC #656 — re-emit the consumed `import pkg::*;` clauses on the
    # wrapper header so package-scoped port-width params resolve. Rendered
    # right after `module <wrapper>` and before `#(...)` / the port list,
    # matching the standard SV ordering `module X import pkg::*; #(p) (ports);`.
    import_hdr = ""
    if import_block:
        import_hdr = "\n  " + "\n  ".join(c.strip() for c in import_block)
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
        f"module {wrapper_name}{import_hdr}{param_hdr} (",
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
