#!/usr/bin/env python3
"""Deterministic transitive-cone reduction for a staged RTL source tree.

Problem this solves (chip-AGNOSTIC, measured on a reused-IP bundle):
  A reused-IP / vendor package is frequently shipped as a whole LIBRARY — every
  module of the IP block plus a large pool of shared primitives, of which any one
  design instantiates only a fraction. When such a bundle is staged FLAT into
  ``phase2/stage1/rtl/`` in its entirety, three failure modes follow that a
  single-top authored design never hits:

    1. ORPHAN files unrelated to the declared top drag in their own unmet
       dependencies — an unstaged macro / package / include the top's real cone
       never needed (an "unknown macro" error raised inside a primitive file the
       top does not instantiate).
    2. DUPLICATE module definitions — a shim / stub file and the real module both
       define the same module name → ``DUPLICATE definition`` under a
       single-unit frontend.
    3. The single-unit elaboration cannot even reach the top because packages are
       presented out of dependency order.

  Reducing the staged set to the TRANSITIVE CONE of the declared top removes the
  orphans (1) outright, removes every out-of-cone duplicate (2), and lets the
  packages be emitted in dependency order (fixed by ``topological_package_first``
  here / the runner's ``_v682_topological_package_order``). Whatever duplicate
  survives INSIDE the cone is resolved canonically (stem-match) here.

  A module the top INSTANTIATES but that NO staged file defines (a dataset-
  excluded variant selected by a parameter default — e.g. a masked S-box variant
  the package dropped) is reported as an UNRESOLVED reference rather than silently
  dropped: the caller must fail loudly instead of emitting a top that references
  an absent module. Choosing a *different* present variant would silently rewrite
  a security-relevant parameter, so that is explicitly NOT done here.

chip-AGNOSTIC: pure SystemVerilog/Verilog structural grammar (module / package /
interface / primitive declarations, module-instantiation heads, ``import pkg::``,
``pkg::sym``, ```include``, ```define`` / ```MACRO``). No chip / vendor / IP /
SKU / parameter literal from any design appears anywhere in this file.

The public entry point is :func:`transitive_cone`, which takes a top module name
and a directory of staged sources and returns a :class:`ConeResult`. It is the
general core; the runner supplies the thin adapter that resolves *which* top to
pass (the emitted ``chip_top`` wrapper, else the instantiation-graph root).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_RTL_EXTS = (".v", ".sv")
_HDR_EXTS = (".vh", ".svh")

# ---- structural grammar (comment/string-masked text) -----------------------

_RE_MODULE_DEF = re.compile(r"(?<![\w$])module\s+([A-Za-z_]\w*)")
_RE_PACKAGE_DEF = re.compile(r"(?<![\w$])package\s+([A-Za-z_]\w*)")
_RE_INTERFACE_DEF = re.compile(r"(?<![\w$])interface\s+([A-Za-z_]\w*)")
_RE_PRIMITIVE_DEF = re.compile(r"(?<![\w$])primitive\s+([A-Za-z_]\w*)")
_RE_MACRO_DEF = re.compile(r"(?<![\w$])`define\s+([A-Za-z_]\w*)")

# A module INSTANTIATION head:  `<type> [#(params)] <instance> [range] (`
#   group(1) = instantiated module TYPE.
# The type and the instance name MUST be separated by EITHER a `#(params)`
# override OR at least one whitespace char — a plain function call `foo(` has the
# name flush against `(` and so never matches (this is the difference between a
# module instantiation and a call). `#(...)` carries ONE level of nested parens
# (the common case); a deeper-nested override that this misses only DROPS an edge
# — the textual keep-scan below still retains a defined submodule appearing by
# name, so the cone is never UNDER-approximated. The instantiation scan's precise
# job is UNRESOLVED detection, which stays sound: it can only fail to flag, never
# mis-flag a function call as a module.
_RE_INST_HEAD = re.compile(
    r"(?m)^[ \t]*([A-Za-z_]\w*)"
    r"(?:\s*#\s*\((?:[^()]|\([^()]*\))*\)\s*|\s+)"
    r"[A-Za-z_]\w*\s*(?:\[[^\]]*\]\s*)?\(")

_RE_IMPORT_PKG = re.compile(r"(?<![\w$])import\s+([A-Za-z_]\w*)\s*::")
_RE_SCOPE_PKG = re.compile(r"(?<![\w$])([A-Za-z_]\w*)\s*::")
_RE_INCLUDE = re.compile(r'(?<![\w$])`include\s+"([^"]+)"')
_RE_MACRO_USE = re.compile(r"(?<![\w$])`([A-Za-z_]\w*)")
_RE_WORD = re.compile(r"[A-Za-z_]\w*")

# Verilog compiler directives are not user macros — never "unresolved".
_COMPILER_DIRECTIVES = frozenset({
    "define", "undef", "ifdef", "ifndef", "elsif", "else", "endif", "include",
    "timescale", "default_nettype", "resetall", "celldefine", "endcelldefine",
    "line", "begin_keywords", "end_keywords", "unconnected_drive",
    "nounconnected_drive", "pragma", "__FILE__", "__LINE__",
})

# Keywords that can appear in instantiation-head position but are NOT modules.
_INST_HEAD_KEYWORDS = frozenset({
    "if", "else", "for", "while", "case", "casex", "casez", "endcase",
    "begin", "end",
    "generate", "endgenerate", "assign", "always", "always_ff", "always_comb",
    "always_latch", "initial", "final", "module", "endmodule", "function",
    "endfunction", "task", "endtask", "package", "endpackage", "import",
    "export", "typedef", "localparam", "parameter", "logic", "wire", "reg",
    "input", "output", "inout", "assert", "assume", "cover", "return", "unique",
    "unique0", "priority", "foreach", "repeat", "forever", "do", "wait",
    "disable", "posedge", "negedge", "or", "and", "not", "buf", "signed",
    "unsigned", "const", "automatic", "static", "virtual", "class", "endclass",
    "interface", "endinterface", "modport", "clocking", "property",
    "endproperty", "sequence", "endsequence", "covergroup", "endgroup",
    "randcase", "with", "new", "super", "this", "null", "void", "int",
    "integer", "bit", "byte", "real", "string", "struct", "union", "enum",
    "expect", "restrict", "bind", "table", "endtable", "specify", "endspecify",
    "genvar", "defparam", "force", "release", "fork", "join", "join_any",
    "join_none", "typedef", "chandle", "event", "time", "shortint", "longint",
    "shortreal", "tri", "triand", "trior", "tri0", "tri1", "wand", "wor",
    "supply0", "supply1", "uwire", "wait_order", "type",
    # Verilog built-in GATE primitives — instantiated as `and u1 (o,a,b)` etc.
    # (must never be read as an unresolved user module).
    "and", "nand", "or", "nor", "xor", "xnor", "not", "buf", "bufif0",
    "bufif1", "notif0", "notif1", "nmos", "pmos", "cmos", "rnmos", "rpmos",
    "rcmos", "tran", "tranif0", "tranif1", "rtran", "rtranif0", "rtranif1",
    "pullup", "pulldown", "pmos", "nmos",
})


def _mask(text: str) -> str:
    """Return `text` with line + block comments and string literals blanked
    (length preserved), so grammar scans never trip on commented-out code or a
    module name inside a string."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            out.append("  ")
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n
                                 and text[i + 1] == "/"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
        elif c == '"':
            out.append(" ")
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    out.append("  ")
                    i += 2
                    continue
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            out.append(" ")
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


@dataclass(eq=False)
class Unit:
    """The structural facts of ONE source file. Identity-hashed (eq=False) so it
    can live in the cone `set`."""
    path: Path
    modules: Set[str] = field(default_factory=set)
    packages: Set[str] = field(default_factory=set)
    interfaces: Set[str] = field(default_factory=set)
    primitives: Set[str] = field(default_factory=set)
    macros: Set[str] = field(default_factory=set)
    inst_types: Set[str] = field(default_factory=set)      # instantiated types
    ref_pkgs: Set[str] = field(default_factory=set)        # import / :: scope
    includes: Set[str] = field(default_factory=set)        # basenames
    used_macros: Set[str] = field(default_factory=set)
    words: Set[str] = field(default_factory=set)           # all bare idents
    raw: str = ""

    @property
    def defines(self) -> Set[str]:
        return (self.modules | self.packages | self.interfaces
                | self.primitives)


def parse_unit(path: Path) -> Unit:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return Unit(path=path)
    masked = _mask(text)
    u = Unit(path=path, raw=masked)
    u.modules = set(_RE_MODULE_DEF.findall(masked))
    u.packages = set(_RE_PACKAGE_DEF.findall(masked))
    u.interfaces = set(_RE_INTERFACE_DEF.findall(masked))
    u.primitives = set(_RE_PRIMITIVE_DEF.findall(masked))
    u.macros = set(_RE_MACRO_DEF.findall(masked))
    u.inst_types = {m for m in _RE_INST_HEAD.findall(masked)
                    if m not in _INST_HEAD_KEYWORDS}
    u.ref_pkgs = set(_RE_IMPORT_PKG.findall(masked)) \
        | set(_RE_SCOPE_PKG.findall(masked))
    u.includes = {Path(x).name for x in _RE_INCLUDE.findall(masked)}
    u.used_macros = {m for m in _RE_MACRO_USE.findall(masked)
                     if m not in _COMPILER_DIRECTIVES}
    u.words = set(_RE_WORD.findall(masked))
    return u


@dataclass
class ConeResult:
    top: str
    cone_files: List[Path]                # staged (kept) files, topo-ordered
    dropped_files: List[Path]             # out-of-cone files removed
    unresolved_modules: List[str]         # instantiated, defined by NO file
    dropped_duplicates: List[Tuple[str, str, str]]  # (module, kept, dropped)
    reason: str = ""

    @property
    def reduced(self) -> bool:
        return bool(self.dropped_files)


def _collect_units(rtl_dir: Path) -> List[Unit]:
    files: List[Path] = []
    for ext in _RTL_EXTS + _HDR_EXTS:
        files.extend(sorted(rtl_dir.glob(f"*{ext}")))
    return [parse_unit(f) for f in sorted(set(files), key=lambda p: p.name)]


def _canonical_definer(module: str, definers: List[Unit]) -> Tuple[Unit, List[Unit]]:
    """Pick the canonical file for a module defined by >1 file, plus the losers.

    Rule (structural, chip-AGNOSTIC): the file whose STEM equals the module name
    is the module's own file and wins over a shim/stub that merely re-declares
    it. If none or several stem-match, fall back to the byte-shortest file (a
    shim/stub is a thin re-declaration), ties broken by name for determinism."""
    stem_match = [u for u in definers if u.path.stem == module]
    if len(stem_match) == 1:
        keep = stem_match[0]
    else:
        keep = min(definers, key=lambda u: (len(u.raw), u.path.name))
    losers = [u for u in definers if u is not keep]
    return keep, losers


def transitive_cone(top: str, rtl_dir: Path) -> ConeResult:
    """Compute the transitive cone of module `top` over the sources in `rtl_dir`.

    A file is KEPT when it is reachable from the file(s) defining `top` by
    following:
      * module instantiations (`inst_types`) resolved to the file defining that
        module,
      * ANY defined module / package / interface / primitive name that appears as
        a bare word in a cone file (a SAFE over-approximation — it can only KEEP
        an extra file, never wrongly drop one, so a missed instantiation-head
        parse cannot under-stage the cone),
      * `import pkg::` / `pkg::sym` package references,
      * ``include "hdr"` header files,
      * ``MACRO` uses resolved to the file that ``define`s them.

    When a needed module has >1 definer, the canonical definer is kept and the
    rest are dropped (recorded). A module instantiated in the cone but defined by
    NO file is reported in `unresolved_modules` — the caller must fail loudly.
    Headers (.vh/.svh) are kept whenever any cone file ``include`s them."""
    units = _collect_units(rtl_dir)
    if not units:
        return ConeResult(top, [], [], [], [],
                          reason="no RTL sources to reduce")

    # symbol -> defining unit(s)
    mod_def: Dict[str, List[Unit]] = {}
    pkg_def: Dict[str, List[Unit]] = {}
    other_def: Dict[str, List[Unit]] = {}     # interfaces + primitives
    macro_def: Dict[str, List[Unit]] = {}
    by_basename: Dict[str, Unit] = {}
    for u in units:
        by_basename.setdefault(u.path.name, u)
        for m in u.modules:
            mod_def.setdefault(m, []).append(u)
        for p in u.packages:
            pkg_def.setdefault(p, []).append(u)
        for s in u.interfaces | u.primitives:
            other_def.setdefault(s, []).append(u)
        for mac in u.macros:
            macro_def.setdefault(mac, []).append(u)

    # every DEFINED module/pkg/iface/prim name — the vocabulary the safe
    # textual keep-scan resolves against.
    defined_named: Dict[str, str] = {}   # name -> kind
    for name in mod_def:
        defined_named[name] = "module"
    for name in pkg_def:
        defined_named.setdefault(name, "package")
    for name in other_def:
        defined_named.setdefault(name, "other")

    if top not in mod_def:
        # cannot anchor the cone — signal the caller to skip pruning (no regress)
        return ConeResult(
            top, [u.path for u in units], [], [], [],
            reason=f"top '{top}' not defined among staged sources; "
                   f"cone reduction skipped (no pruning)")

    cone: Set[Unit] = set()
    dropped_dupes: List[Tuple[str, str, str]] = []
    unresolved: Set[str] = set()
    # module -> the single canonical definer chosen for it (stable within a run)
    chosen_definer: Dict[str, Unit] = {}

    def _resolve_module(name: str) -> Optional[Unit]:
        if name in chosen_definer:
            return chosen_definer[name]
        definers = mod_def.get(name)
        if not definers:
            return None
        if len(definers) == 1:
            keep = definers[0]
        else:
            keep, losers = _canonical_definer(name, definers)
            for lo in losers:
                dropped_dupes.append((name, keep.path.name, lo.path.name))
        chosen_definer[name] = keep
        return keep

    work: List[Unit] = []

    def _add(u: Optional[Unit]) -> None:
        if u is not None and u not in cone:
            cone.add(u)
            work.append(u)

    _add(_resolve_module(top))
    while work:
        u = work.pop()
        # module instantiations — precise edges + unresolved detection
        for t in u.inst_types:
            if t in mod_def:
                _add(_resolve_module(t))
            elif t in other_def:
                for d in other_def[t]:
                    _add(d)
            elif t not in pkg_def and t not in defined_named:
                # an instantiation head naming nothing we define. Only flag it
                # when it is plausibly a module reference: it is NOT also a bare
                # signal we can see defined locally. Recorded for the caller.
                unresolved.add(t)
        # package references
        for p in u.ref_pkgs:
            for d in pkg_def.get(p, []):
                _add(d)
        # macro uses -> defining file
        for mac in u.used_macros:
            for d in macro_def.get(mac, []):
                _add(d)
        # SAFE textual over-approximation: any DEFINED module/pkg/iface/prim
        # name appearing as a bare word pulls its definer in. Never drops.
        for w in u.words:
            if w in u.defines:
                continue
            if w in mod_def:
                _add(_resolve_module(w))
            elif w in pkg_def:
                for d in pkg_def[w]:
                    _add(d)
            elif w in other_def:
                for d in other_def[w]:
                    _add(d)

    # headers: keep any .vh/.svh a cone file includes (+ transitively).
    hdr_units = [u for u in units if u.path.suffix in _HDR_EXTS]
    changed = True
    while changed:
        changed = False
        want: Set[str] = set()
        for u in cone:
            want |= u.includes
        for h in hdr_units:
            if h.path.name in want and h not in cone:
                cone.add(h)
                changed = True

    cone_paths = sorted((u.path for u in cone), key=lambda p: p.name)
    dropped = sorted((u.path for u in units if u not in cone),
                     key=lambda p: p.name)
    ordered = topological_package_first(cone_paths)
    return ConeResult(
        top=top,
        cone_files=ordered,
        dropped_files=dropped,
        unresolved_modules=sorted(unresolved),
        dropped_duplicates=sorted(set(dropped_dupes)),
        reason=(f"cone of '{top}' = {len(cone_paths)} file(s); "
                f"dropped {len(dropped)} out-of-cone; "
                f"{len(set(dropped_dupes))} duplicate(s) resolved; "
                f"{len(unresolved)} unresolved instantiation(s)"))


def prune_to_cone(rtl_dir: Path, result: ConeResult,
                  sidecar: Optional[Path] = None) -> List[str]:
    """MOVE every out-of-cone file in `rtl_dir` into a sidecar directory (default
    ``<rtl_dir>_out_of_cone/``) so the staged synth/sim set is exactly the cone.

    REVERSIBLE + AUDITABLE (never deletes): the sidecar sits OUTSIDE ``rtl_dir``
    so neither a ``glob`` nor an ``rglob`` under ``rtl_dir`` sees the moved files.
    A no-op when nothing is out of cone. Returns the moved basenames. The
    SOURCE_MANIFEST.json keystone is never moved (it is not an RTL source)."""
    import shutil
    if not result.dropped_files:
        return []
    if sidecar is None:
        sidecar = rtl_dir.parent / (rtl_dir.name + "_out_of_cone")
    sidecar.mkdir(parents=True, exist_ok=True)
    cone_names = {p.name for p in result.cone_files}
    moved: List[str] = []
    for f in result.dropped_files:
        if f.name in cone_names or not f.is_file():
            continue
        try:
            shutil.move(str(f), str(sidecar / f.name))
            moved.append(f.name)
        except OSError:
            continue
    return sorted(moved)


# ---- package topological ordering (dependency-first) -----------------------

_RE_PKG_IMPORT = re.compile(r"(?<![\w$])import\s+([A-Za-z_]\w*)\s*::")


def _pkg_symbol(path: Path) -> str:
    """The package name a *_pkg file declares (first `package <name>`), else the
    file stem."""
    try:
        masked = _mask(path.read_text(errors="replace"))
    except OSError:
        return path.stem
    m = _RE_PACKAGE_DEF.search(masked)
    return m.group(1) if m else path.stem


def topological_package_first(files: List[Path]) -> List[Path]:
    """Order `files` so every package precedes any package that imports it, and
    all packages/headers precede non-package RTL (single-unit elaboration needs
    a package declared before use). Non-package order is preserved; import
    cycles degrade to stable alphabetical order. chip-AGNOSTIC import grammar."""
    hdrs = [f for f in files if f.suffix in _HDR_EXTS]
    pkgs = [f for f in files if f.suffix in _RTL_EXTS and "pkg" in f.name]
    rest = [f for f in files if f.suffix in _RTL_EXTS and "pkg" not in f.name]

    if len(pkgs) > 1:
        by_name: Dict[str, Path] = {}
        name_of: Dict[Path, str] = {}
        for p in pkgs:
            nm = _pkg_symbol(p)
            name_of[p] = nm
            by_name.setdefault(nm, p)
        deps: Dict[Path, Set[Path]] = {p: set() for p in pkgs}
        for p in pkgs:
            try:
                body = _mask(p.read_text(errors="replace"))
            except OSError:
                continue
            for dep_name in _RE_PKG_IMPORT.findall(body):
                dep = by_name.get(dep_name)
                if dep is not None and dep is not p:
                    deps[p].add(dep)
        order: List[Path] = []
        state: Dict[Path, int] = {}
        for root in pkgs:
            if state.get(root, 0) == 2:
                continue
            stack = [(root, iter(sorted(deps[root], key=lambda q: name_of[q])))]
            state[root] = 1
            while stack:
                node, it = stack[-1]
                advanced = False
                for child in it:
                    st = state.get(child, 0)
                    if st == 2:
                        continue
                    if st == 1:
                        continue
                    state[child] = 1
                    stack.append((child, iter(sorted(deps[child],
                                                     key=lambda q: name_of[q]))))
                    advanced = True
                    break
                if not advanced:
                    state[node] = 2
                    order.append(node)
                    stack.pop()
        pkgs = order

    # headers first (macros/typedefs), then packages, then the rest
    return hdrs + pkgs + rest


def main(argv: List[str]) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(
        description="Transitive-cone reduction of a staged RTL tree.")
    ap.add_argument("rtl_dir")
    ap.add_argument("top")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    res = transitive_cone(ns.top, Path(ns.rtl_dir).resolve())
    if ns.json:
        print(json.dumps({
            "top": res.top,
            "cone_files": [p.name for p in res.cone_files],
            "dropped_files": [p.name for p in res.dropped_files],
            "unresolved_modules": res.unresolved_modules,
            "dropped_duplicates": res.dropped_duplicates,
            "reason": res.reason,
        }, indent=2))
    else:
        print(res.reason)
        print(f"  cone      : {len(res.cone_files)}")
        print(f"  dropped   : {len(res.dropped_files)}")
        print(f"  unresolved: {res.unresolved_modules}")
        print(f"  dup-resolved: {res.dropped_duplicates}")
    return 0


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(main(_sys.argv[1:]))
