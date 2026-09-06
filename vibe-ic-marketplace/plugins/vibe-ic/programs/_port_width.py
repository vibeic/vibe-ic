#!/usr/bin/env python3
"""_port_width.py — resolve a DUT port's DECLARED width to LITERAL bounds, or
REFUSE by name.

NOT A GATE. A shared producer imported by the two testbench generators that
declare a DUT's ports in a scope where the DUT's parameters are NOT visible:

  * ``design_one_shot_runner.step_full_stack_tb_gen``  (the full-stack TB)
  * ``testbench_gen``                                  (the L10 unit TBs)

WHY THIS EXISTS — the two failure modes it replaces, both measured.

A port declared ``input [aw-1:0] adr`` parses to the width cell ``[aw-1:0]``.
``aw`` is a parameter of the DUT's own header; it does not exist in the TB
module's scope. The two generators did two DIFFERENT wrong things with it:

  (1) SILENT.  The full-stack TB generator matched only a LITERAL ``[N:M]`` and
      returned "" for anything else — i.e. it declared the bus as ONE BIT and
      carried on.  ``reg adr = 0;`` binds bit 0 of a wide port and leaves the
      rest floating; iverilog accepts it with a port-width padding warning, the
      TB runs, and the step reports CONNECTIVITY_PASS over a connection that is
      not connected.  A wrong answer that says PASS is worse than no answer.

      That path was also NON-MONOTONE IN ITS INPUT: because the literal branch
      returned "" instead of falling through, a port that carried BOTH the RTL
      width cell AND the L9 ``msb``/``lsb`` numbers resolved to 1 bit, while the
      SAME port with the width cell DELETED resolved correctly to ``[9:0]``.
      Deleting evidence improved the answer.  A resolver that gets worse when it
      is told more is not a resolver.

  (2) LOUD.  The unit-TB generator copied the cell VERBATIM into the TB scope,
      so ``reg [aw-1:0] adr;`` reached iverilog, which cannot bind ``aw``:
          error: Unable to bind parameter `aw' in `tb_...'
          error: Dimensions must be a constant with no unknown or high-Z bits.
      rc=2, every unit TB for that DUT dead.

Both are the same missing step: nobody EVALUATED the width expression against
the parameter defaults the DUT itself declares.

WHAT THIS MODULE DOES.  It evaluates the cell over the DUT's OWN parameter
header and emits LITERAL bounds, and when it cannot, it says which symbol
stopped it and REFUSES.  It never emits a default, never falls back to one bit,
and never returns a width it did not derive.

WHY THE DUT'S OWN *DEFAULTS*, AND NOTHING ELSE.  Both consumers instantiate the
DUT as a bare ``<module> u_dut ( ... )`` with NO ``#(...)`` override, so the
elaborated widths are the module header's defaults BY CONSTRUCTION.  Harvesting
an override from somewhere else in the design (some other module instantiating
this one with ``#(.aw(24))``) would describe an elaboration that these TBs do
not perform, so overrides are deliberately NOT consulted here.  That is the one
place this module departs from ``register_bus_driver_gen.resolve_bus_widths``,
which resolves widths for a driver bound INSIDE the design and therefore must
honour the overrides.

NO FOURTH EVALUATOR.  The expression arithmetic and the parameter-header
harvest are ``register_bus_driver_gen._int_expr`` and
``register_bus_driver_gen.dut_parameter_defaults`` — the AST-based, bounded,
refuse-on-unknown-identifier pair already in the tree.  This module adds the
port-declaration shape around them and nothing else.  If that evaluator gains a
form, both TB generators gain it on the same day.

chip-AGNOSTIC: no chip, SKU, vendor, PDK or design literal appears here; every
number comes out of the design's own RTL.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

# A single packed dimension `[hi:lo]`, hi/lo arbitrary expressions.
_ONE_RANGE_RE = re.compile(r"^\[\s*([^:\]]+?)\s*:\s*([^:\]]+?)\s*\]$")
# The already-literal case, kept as its own pattern so a literal never depends
# on the evaluator being importable.
_LITERAL_RANGE_RE = re.compile(r"^\[\s*(\d+)\s*:\s*(\d+)\s*\]$")


def _evaluator():
    """`register_bus_driver_gen._int_expr`, or None when it cannot be imported.

    Imported lazily and by NAME so that a missing sibling degrades to an honest
    refusal ("the evaluator is not importable") rather than to a silent width.
    """
    try:
        import register_bus_driver_gen as _rbdg
    except Exception:
        return None
    return getattr(_rbdg, "_int_expr", None)


def dut_defaults(rtl_text: str, dut_module: str) -> Dict[str, int]:
    """`{PARAM: default}` for `dut_module`'s own header — see module docstring
    for why only the DEFAULTS are consulted. `{}` when the header is absent or
    unparsable (which is not an error: a module with no parameters has none)."""
    try:
        import register_bus_driver_gen as _rbdg
    except Exception:
        return {}
    try:
        return _rbdg.dut_parameter_defaults(rtl_text or "", dut_module or "")
    except Exception:
        return {}


def defaults_from_sources(sources: Sequence[Tuple[object, str]],
                          dut_module: str) -> Dict[str, int]:
    """`dut_defaults` over every RTL source, taking the FIRST file that actually
    declares a parameter header for `dut_module`.

    A module is defined once; scanning them all just means the caller does not
    have to know which file holds it. An empty result is returned when no file
    declares a parameterised header — again not an error.
    """
    for _path, text in sources or []:
        got = dut_defaults(text, dut_module)
        if got:
            return got
    return {}


def resolve(width_decl: Optional[str],
            params: Optional[Dict[str, int]] = None,
            msb: Optional[object] = None,
            lsb: Optional[object] = None,
            width: Optional[object] = None) -> Tuple[Optional[str], str]:
    """`(decl, why)` — the ` [hi:lo]` prefix for a port declaration.

    `decl` is:
      * ``" [hi:lo]"``  literal bounds, safe to splice into a TB scope;
      * ``""``          the port really is one bit (a scalar declaration);
      * ``None``        REFUSAL — the width is stated but not derivable. `why`
                        then names the symbol that blocked it. The caller must
                        NOT emit a declaration for this port.

    Precedence, and why each step is where it is:

      (a) the cell is already literal            -> use it. No evaluation needed,
                                                    so this cannot be broken by
                                                    a missing evaluator.
      (b) the cell evaluates over `params`       -> use the evaluated bounds.
                                                    This is the case the two
                                                    generators were missing.
      (c) the cell does NOT evaluate, but the L9
          extraction supplies numeric msb/lsb
          (or a numeric width)                   -> use those. They are a SECOND
                                                    INDEPENDENT MEASUREMENT of
                                                    the same port, and ignoring
                                                    them is what made the old
                                                    function non-monotone: this
                                                    is exactly the "both are
                                                    present" case it dropped.
      (d) no cell at all                         -> the L9 numbers alone, then a
                                                    scalar.
      (e) otherwise                              -> REFUSE, naming the symbol.

    A port with no width information of any kind is one bit and says so ("");
    that is a derivation, not a default.
    """
    params = dict(params or {})
    wd = (width_decl or "").strip() if isinstance(width_decl, str) else ""

    def _from_l9() -> Optional[str]:
        if isinstance(msb, int) and not isinstance(msb, bool) \
                and isinstance(lsb, int) and not isinstance(lsb, bool):
            if msb != lsb:
                return f" [{msb}:{lsb}]"
            return ""
        if isinstance(width, int) and not isinstance(width, bool):
            if width > 1:
                return f" [{width - 1}:0]"
            if width == 1:
                return ""
        return None

    if wd:
        # (a) already literal.
        m = _LITERAL_RANGE_RE.match(wd)
        if m:
            return f" [{m.group(1)}:{m.group(2)}]", "literal width cell"

        m = _ONE_RANGE_RE.match(wd)
        if m:
            hi_s, lo_s = m.group(1).strip(), m.group(2).strip()
            ev = _evaluator()
            if ev is None:
                blocked = "the shared width evaluator is not importable"
            else:
                hi, lo = ev(hi_s, params), ev(lo_s, params)
                if hi is not None and lo is not None:
                    # (b) evaluated. Emit descending bounds, the declaration
                    # form every consumer of this string splices.
                    a, b = (hi, lo) if hi >= lo else (lo, hi)
                    return (f" [{a}:{b}]" if a != b else "",
                            f"evaluated {wd!r} over the DUT's own parameter "
                            f"defaults {params!r}")
                unknown = sorted(
                    {t for t in re.findall(r"[A-Za-z_]\w*", wd)
                     if t not in params})
                blocked = (f"{wd!r} does not evaluate over the DUT's own "
                           f"parameter defaults "
                           f"{params if params else '{} (the DUT declares no parameter header)'}"
                           + (f"; unresolved symbol(s): {unknown}" if unknown
                              else "; the expression form is not supported"))
        else:
            # Not a single packed range at all (e.g. a multi-dimensional or
            # typed cell). Refusing is deliberate: this module resolves a
            # WIDTH, and it will not pretend a shape it did not parse is one
            # bit -- which is exactly what the old code did.
            blocked = (f"{wd!r} is not a single packed `[hi:lo]` dimension, so "
                       f"no scalar width follows from it")

        # (c) the cell failed, but L9 measured the same port independently.
        alt = _from_l9()
        if alt is not None:
            return alt, (f"width cell unresolved ({blocked}); used the L9 "
                         f"extraction's own numeric bounds for this port")
        # (e) refuse, by name.
        return None, blocked

    # (d) no cell.
    alt = _from_l9()
    if alt is not None:
        return alt, "L9 numeric bounds (no RTL width cell for this port)"
    return "", "no width stated anywhere — a scalar port"


def resolve_ports(ports: Sequence[Tuple[str, str, str]],
                  params: Optional[Dict[str, int]] = None
                  ) -> Tuple[List[Tuple[str, str, str]], List[str]]:
    """Resolve a whole `(direction, width_decl, name)` port list.

    Returns `(resolved_ports, refusals)`. `refusals` is a list of human-readable
    `"<name>: <why>"` strings, one per port whose width could not be derived.
    A caller with ANY refusal must not emit a testbench: a TB is a set of
    bindings, and one wrong binding is a wrong TB.
    """
    out: List[Tuple[str, str, str]] = []
    refusals: List[str] = []
    for d, w, n in ports or []:
        decl, why = resolve(w, params)
        if decl is None:
            refusals.append(f"{n}: {why}")
            continue
        out.append((d, decl.strip(), n))
    return out, refusals

def l9_bounds(generated_docs_dir) -> Dict[str, Dict[str, object]]:
    """`{port_name: {"msb":.., "lsb":.., "width":..}}` from L9_INTEGRATION_SPEC.

    The L9 extraction measures every top port independently of the RTL parse.
    When the RTL width cell is an expression this resolver cannot evaluate -- a
    `define macro, a localparam, a package constant -- those numbers are the
    only other thing that knows how wide the port is, and using them is what
    makes "resolve or refuse" refuse only when NOBODY knows.

    This is the same evidence the non-monotonicity bug threw away: the #629
    reconcile replaced `top_ports` with RTL-only dicts, so by the time the
    width was needed the L9 numbers were gone.

    Returns `{}` when L9 is absent or unreadable -- which is NOT_MEASURED, and
    the caller then refuses on the width cell alone rather than inventing one.
    """
    import json
    from pathlib import Path as _P
    out: Dict[str, Dict[str, object]] = {}
    try:
        doc = json.loads(
            (_P(generated_docs_dir) / "L9_INTEGRATION_SPEC.json").read_text())
    except Exception:
        return {}
    ports = doc.get("top_ports") or doc.get("ports") or []
    if not isinstance(ports, list):
        return {}
    for p in ports:
        if not isinstance(p, dict):
            continue
        nm = (p.get("name") or "").strip()
        if not nm:
            continue
        out[nm] = {"msb": p.get("msb"), "lsb": p.get("lsb"),
                   "width": p.get("width")}
    return out


def resolve_ports_with_l9(ports: Sequence[Tuple[str, str, str]],
                          params: Optional[Dict[str, int]] = None,
                          l9: Optional[Dict[str, Dict[str, object]]] = None
                          ) -> Tuple[List[Tuple[str, str, str]], List[str]]:
    """`resolve_ports`, but a port whose cell will not evaluate may still be
    resolved from the L9 extraction's own numbers for that same port."""
    l9 = l9 or {}
    out: List[Tuple[str, str, str]] = []
    refusals: List[str] = []
    for d, w, n in ports or []:
        b = l9.get(n) or {}
        decl, why = resolve(w, params, msb=b.get("msb"), lsb=b.get("lsb"),
                            width=b.get("width"))
        if decl is None:
            refusals.append(f"{n}: {why}")
            continue
        out.append((d, decl.strip(), n))
    return out, refusals
