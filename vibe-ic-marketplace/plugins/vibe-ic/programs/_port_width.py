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

WHERE A WIDTH IS STATED.  Not one place — four, and a resolver that reads only
the first refuses on numbers the design states in full:

  * the module's ``#( ... )`` parameter header, parameters and its localparams
    (``localparam int IdxW = $clog2(N)``);
  * the module BODY — Verilog-1995 has no header at all and states the width
    one line below the port list (``parameter BITS = 39;``);
  * a PACKAGE, reached by SCOPE (``[top_pkg::TL_DW-1:0]``) or by IMPORT
    (``module m import aes_reg_pkg::*; #(...) ( ... [NumRegsData-1:0] ... )``);
  * and the module's OWN default written over one of those
    (``parameter int DATA_WIDTH = top_pkg::TL_DW``), which is why the header and
    body harvests are SEEDED with what is in scope before them.

Precedence runs the other way: the module's own names win over an imported one,
and a name two IMPORTED packages define DIFFERENTLY is ambiguous and is dropped
— an ambiguous width is not a known width.

NO FOURTH EVALUATOR.  The expression arithmetic and every harvest above are
``register_bus_driver_gen._int_expr``, ``dut_scope_constants``,
``package_constants`` and ``dut_imported_packages`` — the AST-based, bounded,
refuse-on-unknown-identifier machinery already in the tree, extended in place.
(``dut_parameter_defaults`` stays parameters-only over the module's own header,
because ``resolve_bus_widths`` merges instantiation overrides onto it.)  This
module adds the port-declaration shape around them and nothing else.  If that
evaluator gains a form, both TB generators gain it on the same day.

chip-AGNOSTIC: no chip, SKU, vendor, PDK or design literal appears here; every
number comes out of the design's own RTL.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

def _split_range(cell: str) -> Optional[Tuple[str, str]]:
    """`(hi, lo)` for a single packed dimension `[hi:lo]`, else None.

    Not a regex, because of `::`. A width bound may be package-scoped --
    `[flash_phy_pkg::ProgTypes-1:0]` -- and a pattern that simply forbids `:`
    inside the bounds fails to match it, which made this module report "not a
    single packed `[hi:lo]` dimension" about something that is exactly that.
    A wrong REASON is its own defect: the refusal must name the symbol that
    actually blocked it, or the reader goes looking for the wrong thing.

    The separator is the one `:` at bracket depth 0 that is not part of a `::`
    scope operator. More than one `[...]` group is a multi-dimensional cell and
    genuinely is not a single packed dimension.
    """
    t = (cell or "").strip()
    if not (t.startswith("[") and t.endswith("]")):
        return None
    inner = t[1:-1]
    if "[" in inner or "]" in inner:
        return None                     # multi-dimensional / unpacked as well
    seps = []
    for i, ch in enumerate(inner):
        if ch != ":":
            continue
        if (i and inner[i - 1] == ":") or (i + 1 < len(inner)
                                           and inner[i + 1] == ":"):
            continue                    # part of a `::` scope operator
        seps.append(i)
    if len(seps) != 1:
        return None
    i = seps[0]
    hi, lo = inner[:i].strip(), inner[i + 1:].strip()
    return (hi, lo) if hi and lo else None
# The already-literal case, kept as its own pattern so a literal never depends
# on the evaluator being importable.
_LITERAL_RANGE_RE = re.compile(r"^\[\s*(\d+)\s*:\s*(\d+)\s*\]$")


#: An identifier in a width bound, SCOPE OPERATOR INCLUDED. Splitting
#: `flash_phy_pkg::ProgTypes` into two bare names made the refusal name two
#: things that are not the symbol, and a reader who greps for either finds the
#: wrong file.
_SYMBOL_RE = re.compile(r"[A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*")


def scope_summary(params: Optional[Dict[str, int]]) -> str:
    """A BOUNDED description of the constants a width was evaluated against.

    The scope a port is declared in now legitimately holds every constant every
    package in the design exports -- hundreds of entries. Printing the map
    printed all of them into a step's FAIL text and buried the one name the
    reader needs. The DUT's OWN names are listed (there are a handful and they
    are the ones a reader can act on); the package-scoped ones are counted.
    """
    params = params or {}
    own = sorted(k for k in params if "::" not in str(k))
    extra = len(params) - len(own)
    if not own and not extra:
        return ("no constants at all (the DUT declares no parameter header "
                "and no body constant, and no package is in scope)")
    where = (f"the DUT's own constants {own}" if own
             else "no constant of the DUT's own")
    if extra:
        where += f" plus {extra} package-scoped constant(s)"
    return where


def _unresolved_symbols(cell: str, params: Dict[str, int]) -> List[str]:
    """The symbols in `cell` that `params` does not define, scoped names kept
    whole. `$clog2` and the other admitted constant functions are not symbols
    and are not listed; a `$` function that is NOT admitted is, because that is
    exactly what blocked the width."""
    out = []
    for m in _SYMBOL_RE.finditer(cell or ""):
        t = re.sub(r"\s*::\s*", "::", m.group(0))
        if t in params or t in out:
            continue
        out.append(t)
    for m in re.finditer(r"\$[A-Za-z_]\w*", cell or ""):
        if m.group(0) not in out:
            out.append(m.group(0))
    return sorted(out)


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


def _rbdg():
    """`register_bus_driver_gen`, or None. Imported lazily and by NAME so that a
    missing sibling degrades to an honest refusal, never to a silent width."""
    try:
        import register_bus_driver_gen as _m
    except Exception:
        return None
    return _m


def _declares(text: str, dut_module: str) -> bool:
    """True when `text` declares `module <dut_module>`.

    Comments are blanked FIRST. A sentence in a comment that says the module's
    name -- `// see module foo` -- is not a declaration, and a scan that counts
    one mints a module that does not exist (#731). The blanker preserves
    offsets, so nothing else shifts.
    """
    m = _rbdg()
    code = text or ""
    if m is not None:
        try:
            code = m._hdl_code_text.strip_hdl_comments_and_strings(code)
        except Exception:
            code = text or ""
    return bool(re.search(r"\bmodule\s+" + re.escape(dut_module) + r"\b",
                          code))


def _package_scope(pkgs: Dict[str, Dict[str, int]],
                   imported: Sequence[str]) -> Dict[str, int]:
    """The names a module's port declarations can see from PACKAGES.

    Two access paths, and they are not the same:

      * SCOPED  — `pkg::NAME` is visible whether or not the module imports the
                  package, so every package constant is offered under its full
                  scoped key.
      * IMPORTED — `import pkg::*;` also puts the package's names in scope
                  UNQUALIFIED. Only the packages this module actually imports
                  contribute those.

    A name two IMPORTED packages define with DIFFERENT values is AMBIGUOUS. It
    is dropped rather than resolved by import order, so a width over it refuses
    by name — an ambiguous width is not a known width.
    """
    out: Dict[str, int] = {}
    for pkg, consts in (pkgs or {}).items():
        for name, val in consts.items():
            out[f"{pkg}::{name}"] = val
    plain: Dict[str, set] = {}
    for pkg in imported or []:
        for name, val in (pkgs or {}).get(pkg, {}).items():
            plain.setdefault(name, set()).add(val)
    for name, vals in plain.items():
        if len(vals) == 1:
            out[name] = next(iter(vals))
    return out


def dut_defaults(rtl_text: str, dut_module: str) -> Dict[str, int]:
    """`{NAME: value}` for every constant visible where `dut_module` declares
    its ports, read out of THIS ONE text.

    See the module docstring for why only the DEFAULTS (never an instantiation
    override) are consulted. `{}` when nothing is declared — which is not an
    error: a module with no constants has none.

    Three scopes, in the order a port declaration sees them:

      * the `#( ... )` parameter header — parameters and its localparams. A
        derived constant (`localparam int IdxW = $clog2(N)`) is exactly what a
        width is written over.
      * the module BODY — Verilog-1995 has no header at all and states the
        width there instead (`parameter BITS = 39;`).
      * PACKAGES this text declares, scoped (`top_pkg::TL_DW`) and, for the
        packages this module imports, unqualified as well.
    """
    m = _rbdg()
    if m is None:
        return {}
    try:
        pkgs = m.package_constants([("<text>", rtl_text or "")])
        imported = m.dut_imported_packages(rtl_text or "", dut_module or "")
        out = _package_scope(pkgs, imported)
        # SEEDED: a module's own default is legitimately written over a package
        # constant (`parameter int DATA_WIDTH = top_pkg::TL_DW`).
        own = m.dut_scope_constants(rtl_text or "", dut_module or "", seed=out)
    except Exception:
        return {}
    out.update(own)          # the module's own declarations win
    return out


def defaults_from_sources(sources: Sequence[Tuple[object, str]],
                          dut_module: str) -> Dict[str, int]:
    """`dut_defaults` for `dut_module`, with PACKAGES read from EVERY source.

    A package is declared in a file of its own, so a module's own text can
    never state the constants it imports. Harvesting packages across the whole
    source set is what makes `[top_pkg::TL_DW-1:0]` and `[NumRegsData-1:0]`
    resolvable at all; the module's own header and body still WIN any clash.

    An empty result is returned when no file declares the module — again not an
    error, and the caller then refuses on the width cell alone.
    """
    m = _rbdg()
    if m is None:
        return {}
    try:
        pkgs = m.package_constants(sources or [])
    except Exception:
        pkgs = {}
    own: Dict[str, int] = {}
    imported: Sequence[str] = []
    for _path, text in sources or []:
        if not _declares(text or "", dut_module):
            continue
        try:
            imported = m.dut_imported_packages(text or "", dut_module or "")
            own = m.dut_scope_constants(
                text or "", dut_module or "",
                seed=_package_scope(pkgs, imported))
        except Exception:
            own, imported = {}, []
        if own or imported:
            break
    out = _package_scope(pkgs, imported)
    out.update(own)
    return out


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

        rng = _split_range(wd)
        if rng:
            hi_s, lo_s = rng
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
                unknown = _unresolved_symbols(wd, params)
                # NAME THE SYMBOL, NOT THE MAP. The scope a port is declared in
                # now legitimately holds every constant every package in the
                # design exports, so printing the map printed hundreds of
                # entries and buried the one name the reader needs. The map is
                # reported by SIZE and by the DUT's own unscoped names; the
                # thing that blocked the width is named in full.
                blocked = (f"{wd!r} does not evaluate over "
                           f"{scope_summary(params)}"
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
