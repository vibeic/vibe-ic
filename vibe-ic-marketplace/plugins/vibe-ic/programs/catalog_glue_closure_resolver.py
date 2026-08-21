#!/usr/bin/env python3
r"""
catalog_glue_closure_resolver.py — REUSED-IP / catalog-glue staging
instantiation-closure resolver + duplicate-module detector (ORGANIC #639).

THE PROBLEM
-----------
For a REUSED-IP processor / crypto-accelerator class whose vendor RTL is
dropped FLAT (one directory, no per-IP `rtl_files` manifest), the WAIVE
fallback (`catalog-glue-author`) stages every `*.sv` / `*.v` file as-is.
The runner source selector (`_select_asic_rtl_sources`) then flat-globs
ALL of them.  Selection is purely ADDITIVE — the only "closure" logic
(staged_rtl_closure_preflight #586, sv_package_closure_check #549)
backfills MISSING deps; nothing ever computes the transitive module /
package instantiation closure FROM the authored chip_top to DROP IPs
that are not in the design.  Two failure facets result:

  (1) over-broad set — unrelated sibling IPs (e.g. four crypto cores in
      one bundle) are fed to synth, dragging in macros / packages the
      synthesis define-set never satisfies → spurious elaboration errors;

  (2) vendor bundles ship DUPLICATE-MODULE defects (two source files
      declaring the same `module` name) which surface as a raw
      "duplicate definition" synth crash with no diagnostic.

WHAT THIS RESOLVER DOES
-----------------------
Given a top-module name and a flat vendor-RTL directory, it:

  1. Builds an index of `{module/package/macro-name -> defining file}`.
  2. Walks the transitive instantiation / scoped-reference / package-
     import / macro-instantiation closure FROM `top` over the directory,
     so include-only macro & package files (`*.svh` / `*.vh` / `*_pkg.sv`)
     and macro-instantiated modules (``\`PRIM_FLOP_SPARSE_FSM`` ->
     `prim_sparse_fsm_flop`) are pulled in but unrelated IPs are NOT.
  3. Reports the REACHABLE closure (the files to stage) vs the PRUNABLE
     files (everything else — the over-broad tail).
  4. Detects DUPLICATE-MODULE definitions among the reachable closure:
     two staged files declaring the same module name.  Picks the
     canonical file by filename-vs-module-name match (pure heuristic,
     no vendor literal) and names the variant / shim to drop.

This is a deterministic PRE-SYNTH preflight: catch the over-broad set
and the duplicate-module crash BEFORE the expensive elaborate.

VERDICTS
--------
  PASS            — closure resolved, no duplicate-module defect anywhere in
                    the staged set, and the reachable set is non-empty
                    (top found + walked).
  DUPLICATE       — reachable closure contains a duplicate-module defect.
  STAGED_DUPLICATE— a duplicate-module defect exists among the staged set
                    that synth actually COMPILES, but it is NOT in the
                    reachable closure of `top`.  Distinct from DUPLICATE so
                    #639 (reachable-only) is not masked; both are hard-gated
                    crash-prevention verdicts.  (ORGANIC #774.)

SCOPE OF THE DUPLICATE GATE (ORGANIC #781)
------------------------------------------
The duplicate-module verdicts exist for exactly one reason: to pre-empt a raw
yosys-slang "duplicate definition" abort.  A file that synth never READS can
never cause that abort, so it must never raise the gate.

`_gather()` deliberately walks `rglob` — nested headers must participate in
closure resolution so an include-only macro/package can chain a module in.
But the runner's compile set (`_select_asic_rtl_sources`) is a TOP-LEVEL
`glob`, not `rglob`.  Scanning the rglob set for duplicates therefore gates on
files that are never handed to the frontend: a vendor bundle whose sources also
live in a nested sub-path (`syn/rtl/foo.v` alongside a staged `foo.v`) is
flagged as a "bundle defect" although synth compiles exactly one `foo.v` and
elaborates cleanly.

`resolve()` therefore accepts `synth_files` — the exact set the caller will
feed to the frontend.  Duplicate REPORTING is restricted to that set; closure
resolution still uses the full rglob walk.  When `synth_files` is None the
resolver falls back to the top-level-glob semantics the runner uses, so the
standalone CLI agrees with the in-flow gate.
  TOP_NOT_FOUND   — the named top module is not defined in any file.
  EMPTY           — no .sv/.v files found at all (vacuous; FAIL-safe).

EXIT CODES
----------
  0 — PASS
  1 — DUPLICATE / STAGED_DUPLICATE (a real bundle defect was found that
      would crash synth — reachable or in the prunable tail)
  2 — TOP_NOT_FOUND / EMPTY / argument error

chip-AGNOSTIC: pure SystemVerilog / Verilog grammar + filename-canonical
heuristic.  No vendor / IC / SKU / module-name literal anywhere.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


_ID = r"[A-Za-z_]\w*"

# module <name>  /  package <name>  definitions.
_MODULE_DEF_RE = re.compile(rf"\bmodule\s+({_ID})", re.M)
_PKG_DEF_RE = re.compile(rf"\bpackage\s+({_ID})\s*;", re.M)
# `define NAME [(...)]  body...   — body may span continued lines (\\ at EOL)
_DEFINE_RE = re.compile(
    rf"^\s*`define\s+({_ID})\b", re.M)
# An instantiation `ModName [#(...)] inst (` at a plausible statement spot.
_INST_FULL_RE = re.compile(rf"\b({_ID})\s+(?:#\s*\([^;]*?\)\s*)?{_ID}\s*\(")
# import <pkg>::*  /  import <pkg>::<sym>
_IMPORT_RE = re.compile(rf"\bimport\s+({_ID})\s*::")
# scoped reference <pkg>::<sym>
_SCOPED_RE = re.compile(rf"\b({_ID})\s*::\s*{_ID}")
# `include "file"
_INCLUDE_RE = re.compile(r'`include\s+"([^"/]*?([^"/]+))"')
# macro USE: `MACRO_NAME  (not a `define / `include / `ifdef etc directive)
_MACRO_USE_RE = re.compile(rf"`({_ID})")

# Verilog/SV keywords that must never be treated as a module reference.
_KEYWORDS = frozenset({
    "module", "endmodule", "input", "output", "inout", "wire", "reg",
    "logic", "assign", "always", "always_ff", "always_comb", "always_latch",
    "parameter", "localparam", "generate", "endgenerate", "begin", "end",
    "if", "else", "for", "while", "case", "casez", "casex", "endcase",
    "function", "endfunction", "task", "endtask", "initial", "final",
    "typedef", "enum", "struct", "union", "package", "endpackage",
    "import", "export", "genvar", "integer", "int", "bit", "byte",
    "return", "unique", "unique0", "priority", "default", "posedge",
    "negedge", "signed", "unsigned", "automatic", "static", "const", "var",
    "interface", "endinterface", "modport", "clocking", "endclocking",
    "property", "endproperty", "assert", "assume", "cover", "sequence",
    "endsequence", "supply0", "supply1", "tri", "wand", "wor", "buf",
    "not", "and", "or", "xor", "nand", "nor", "xnor", "specify",
    "endspecify", "defparam", "event", "real", "time", "string", "void",
    "shortint", "longint", "shortreal", "realtime", "chandle", "type",
    "ref", "extern", "virtual", "pure", "context", "class", "endclass",
})

# Directive macro names that are NOT module instantiations when seen as
# `WORD — these are preprocessor constructs, not user macros to resolve.
_DIRECTIVE_MACROS = frozenset({
    "define", "undef", "ifdef", "ifndef", "elsif", "else", "endif",
    "include", "timescale", "resetall", "default_nettype", "line",
    "celldefine", "endcelldefine", "unconnected_drive", "nounconnected_drive",
    "pragma", "begin_keywords", "end_keywords", "__FILE__", "__LINE__",
})


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


# Source extensions walked for definitions / dependencies. `.svh` / `.vh`
# are include-only headers (macros / packages) that the closure must be
# able to chain through (a macro-instantiated module's `define usually
# lives in an .svh), so they are gathered too. Only `.sv` / `.v` files are
# ever reported as duplicate-module defects (a header redeclaring nothing).
_SRC_GLOBS = ("*.sv", "*.v", "*.svh", "*.vh")
_SYNTH_EXTS = (".sv", ".v")


def _gather(rtl_dir: Path) -> Dict[Path, str]:
    """Map every .sv/.v/.svh/.vh file under rtl_dir to its comment-stripped
    text. Headers (.svh/.vh) participate in closure resolution so an
    include-only macro/package definition can chain a referenced module
    into the reachable set, but they are excluded from duplicate-module
    reporting."""
    out: Dict[Path, str] = {}
    seen: Set[Path] = set()
    for g in _SRC_GLOBS:
        for f in sorted(rtl_dir.rglob(g)):
            if f in seen:
                continue
            seen.add(f)
            try:
                out[f] = _strip_comments(f.read_text(errors="replace"))
            except OSError:
                continue
    return out


def _macro_body_module_refs(text: str) -> Dict[str, Set[str]]:
    """Map `define NAME -> set of module identifiers instantiated inside
    the macro body. Resolves macro-instantiated modules (a macro whose
    expansion instantiates a flop/assertion module) chip-AGNOSTICally:
    we read the macro body and pull any `ModName inst (` instantiation
    or bareword identifier the body wires up."""
    out: Dict[str, Set[str]] = {}
    # Walk define directives capturing the (possibly multi-line) body.
    for m in re.finditer(rf"^\s*`define\s+({_ID})\b([^\n]*(?:\\\n[^\n]*)*)",
                         text, re.M):
        name = m.group(1)
        body = m.group(2).replace("\\\n", "\n")
        refs: Set[str] = set()
        for im in _INST_FULL_RE.finditer(body):
            ref = im.group(1)
            if ref not in _KEYWORDS:
                refs.add(ref)
        out[name] = refs
    return out


def build_index(files: Dict[Path, str]) -> Dict:
    """Build module / package / macro definition indexes.

    Returns a dict with:
      mod_def     : {module_name -> [files defining it]}  (list: dup-aware)
      pkg_def     : {package_name -> [files]}
      macro_def   : {macro_name -> [files]}
      macro_refs  : {macro_name -> set(module refs in its body)}
    """
    mod_def: Dict[str, List[Path]] = {}
    pkg_def: Dict[str, List[Path]] = {}
    macro_def: Dict[str, List[Path]] = {}
    macro_refs: Dict[str, Set[str]] = {}
    for f, text in files.items():
        for name in _MODULE_DEF_RE.findall(text):
            mod_def.setdefault(name, []).append(f)
        for name in _PKG_DEF_RE.findall(text):
            pkg_def.setdefault(name, []).append(f)
        for name in _DEFINE_RE.findall(text):
            macro_def.setdefault(name, []).append(f)
        for mname, refs in _macro_body_module_refs(text).items():
            macro_refs.setdefault(mname, set()).update(refs)
    return {
        "mod_def": mod_def,
        "pkg_def": pkg_def,
        "macro_def": macro_def,
        "macro_refs": macro_refs,
    }


def _file_dependencies(text: str, idx: Dict) -> Tuple[Set[str], Set[str],
                                                      Set[str], Set[str]]:
    """For one file's text, return the sets of referenced
    (module_names, package_names, macro_names, include_basenames)."""
    mods: Set[str] = set()
    for m in _INST_FULL_RE.finditer(text):
        ref = m.group(1)
        if ref not in _KEYWORDS and ref in idx["mod_def"]:
            mods.add(ref)
    pkgs: Set[str] = set()
    for m in _IMPORT_RE.finditer(text):
        pkgs.add(m.group(1))
    for m in _SCOPED_RE.finditer(text):
        pkgs.add(m.group(1))
    macros: Set[str] = set()
    for m in _MACRO_USE_RE.finditer(text):
        mn = m.group(1)
        if mn not in _DIRECTIVE_MACROS:
            macros.add(mn)
    incs: Set[str] = set()
    for m in _INCLUDE_RE.finditer(text):
        incs.add(Path(m.group(1)).name)
    return mods, pkgs, macros, incs


def resolve_closure(top: str, files: Dict[Path, str], idx: Dict
                    ) -> Tuple[Set[Path], List[str]]:
    """Walk the transitive closure from `top`. Returns
    (reachable_files, walk_trace). A definition file is reachable when
    it defines a module/package/macro that some already-reachable file
    references (BFS over the union dependency graph)."""
    # Reverse lookup: any defined name -> the files defining it.
    def _files_for(name: str) -> List[Path]:
        out: List[Path] = []
        for kind in ("mod_def", "pkg_def", "macro_def"):
            out.extend(idx[kind].get(name, []))
        return out

    # Resolve include-only files by basename.
    by_basename: Dict[str, List[Path]] = {}
    for f in files:
        by_basename.setdefault(f.name, []).append(f)

    reachable: Set[Path] = set()
    trace: List[str] = []
    # Seed with every file that DEFINES the top module.
    seeds = idx["mod_def"].get(top, [])
    if not seeds:
        return set(), trace
    frontier: List[Path] = list(seeds)
    reachable.update(seeds)
    while frontier:
        cur = frontier.pop()
        text = files.get(cur, "")
        mods, pkgs, macros, incs = _file_dependencies(text, idx)
        # Macro-instantiated modules: a referenced macro whose body wires
        # up a module pulls that module into closure too.
        for macro in macros:
            for mref in idx["macro_refs"].get(macro, set()):
                if mref in idx["mod_def"]:
                    mods.add(mref)
        names = list(mods) + list(pkgs) + list(macros)
        for name in names:
            for f in _files_for(name):
                if f not in reachable:
                    reachable.add(f)
                    frontier.append(f)
                    trace.append(f"{cur.name} -> {name} -> {f.name}")
        for base in incs:
            for f in by_basename.get(base, []):
                if f not in reachable:
                    reachable.add(f)
                    frontier.append(f)
                    trace.append(f"{cur.name} -> include {base} -> {f.name}")
    return reachable, trace


def _canonical_pick(module: str, candidates: List[Path]) -> Tuple[Path,
                                                                   List[Path]]:
    """Among files all declaring `module`, pick the canonical one by
    filename-vs-module-name match (chip-AGNOSTIC heuristic): a file whose
    basename stem == module name is canonical; the rest are shims/variants.
    Deterministic tie-break: shortest stem, then lexicographic."""
    exact = [c for c in candidates if c.stem == module]
    if exact:
        canon = sorted(exact, key=lambda p: (len(p.stem), str(p)))[0]
    else:
        canon = sorted(candidates, key=lambda p: (len(p.stem), str(p)))[0]
    variants = [c for c in candidates if c != canon]
    return canon, variants


def _disp(p: Path, peers: List[Path]) -> str:
    """Shortest UNAMBIGUOUS display name for `p` among `peers`.

    ORGANIC #781 — the remediation used bare `p.name`, so a duplicate whose
    copies share a basename (the common case: the same vendor file staged both
    flat and under its original sub-path) rendered as the self-contradictory
    "Canonical: foo.v ... drop variant/shim file(s): foo.v". Fall back to the
    path suffix that actually distinguishes the peers."""
    others = [q for q in peers if q != p]
    if all(q.name != p.name for q in others):
        return p.name
    parts = p.parts
    for depth in range(2, len(parts) + 1):
        cand = str(Path(*parts[-depth:]))
        if all(str(Path(*q.parts[-depth:])) != cand for q in others):
            return cand
    return str(p)


def _scan_staged_duplicates(idx: Dict, reachable_set: set,
                            synth_set: Optional[set] = None) -> List[Dict]:
    """ORGANIC #774 — scan the staged module-definition index for cross-file
    duplicate-module definitions, classifying each by scope ('reachable' when
    every defining file is in `reachable_set` — the #639 facet; 'staged' when any
    defining file is outside it — the #774 prunable-tail facet). `reachable_set`
    empty ⇒ every duplicate is scope='staged'. chip-AGNOSTIC.

    ORGANIC #781 — `synth_set` (when given) is the exact file set the caller
    feeds to the frontend. Only files in it can trigger a yosys-slang
    "duplicate definition" abort, so only they are eligible to raise this gate.
    A nested copy that synth never compiles is NOT a bundle defect."""
    dup_findings: List[Dict] = []
    for mod, deffiles in sorted(idx["mod_def"].items()):
        staged = [f for f in deffiles if f.suffix in _SYNTH_EXTS]
        if synth_set is not None:
            staged = [f for f in staged if f in synth_set]
        uniq = sorted(set(staged), key=str)
        if len(uniq) > 1:
            canon, variants = _canonical_pick(mod, uniq)
            all_reachable = bool(reachable_set) and all(
                f in reachable_set for f in uniq)
            scope = "reachable" if all_reachable else "staged"
            tail_note = ("" if all_reachable else
                         " (in the PRUNABLE tail — the runner still feeds "
                         "it to synth, so it still crashes yosys-slang)")
            dup_findings.append({
                "module": mod,
                "scope": scope,
                "canonical": str(canon),
                "variants": [str(v) for v in variants],
                "message": (
                    f"module {mod!r} is declared in {len(uniq)} staged "
                    f"files{tail_note} — vendor bundle duplicate-module "
                    f"defect. Canonical: {_disp(canon, uniq)} (filename "
                    f"matches module name); drop variant/shim file(s): "
                    f"{', '.join(_disp(v, uniq) for v in variants)}."),
            })
    return dup_findings


def _default_synth_set(rtl_dir: Path, files: Dict[Path, str]) -> set:
    """ORGANIC #781 — the file set the runner ACTUALLY compiles, when the caller
    did not pass one explicitly.

    Mirrors `design_one_shot_runner._select_asic_rtl_sources`: a TOP-LEVEL
    ``glob`` of ``*.sv`` / ``*.v`` (NOT ``rglob``). Nested sources are reachable
    for closure/`include purposes but are never handed to the frontend, so they
    cannot raise a duplicate-definition abort."""
    top_level = set()
    for f in files:
        if f.suffix in _SYNTH_EXTS and f.parent == rtl_dir:
            top_level.add(f)
    return top_level


def resolve(top: str, rtl_dir: Path,
            synth_files: Optional[List[Path]] = None) -> Dict:
    files = _gather(rtl_dir)
    if not files:
        return {"verdict": "EMPTY",
                "error": "no .sv/.v files found",
                "reachable": [], "prunable": [], "duplicates": []}
    # ORGANIC #781 — duplicate REPORTING is scoped to what synth compiles.
    if synth_files is not None:
        synth_set = {Path(p) for p in synth_files}
    else:
        synth_set = _default_synth_set(rtl_dir, files)
    idx = build_index(files)
    if top not in idx["mod_def"]:
        # ORGANIC #774 round-2 (Step-2.7) — the duplicate-module crash-gate must
        # run even when `top` does not resolve: a duplicate-module pair inside
        # the COMPILED set still crashes yosys-slang raw regardless of whether
        # the named top is found. With no reachable closure, every dup is
        # scope='staged'. (#781: scoped to the compiled set, not the rglob walk.)
        dup_findings = _scan_staged_duplicates(idx, set(), synth_set)
        if dup_findings:
            return {"verdict": "STAGED_DUPLICATE",
                    "top": top, "files_total": len(files),
                    "modules_defined": sorted(idx["mod_def"]),
                    "reachable": [], "prunable": [], "duplicates": dup_findings}
        return {"verdict": "TOP_NOT_FOUND",
                "error": f"top module {top!r} not defined in any staged file",
                "top": top,
                "modules_defined": sorted(idx["mod_def"]),
                "reachable": [], "prunable": [], "duplicates": []}

    reachable, trace = resolve_closure(top, files, idx)
    prunable = sorted(str(f) for f in files if f not in reachable)

    # Duplicate-module detection over the FULL staged synth set (ORGANIC
    # #774). The runner's `_select_asic_rtl_sources` feeds the ENTIRE flat
    # glob to yosys_synth (prune is advisory — "never auto-drop"), so a
    # duplicate-module pair living in the PRUNABLE tail is still handed to
    # synth and still crashes yosys-slang with a raw "duplicate definition"
    # abort. Scanning only the reachable closure (the pre-#774 behaviour)
    # left that tail invisible (verdict=PASS, duplicates=[]) → false-PASS.
    #
    # We classify each finding by scope:
    #   scope="reachable" — every defining file is in the reachable closure
    #                       (the #639 facet → top-level DUPLICATE verdict).
    #   scope="staged"    — at least one defining file is OUTSIDE the
    #                       reachable closure (the #774 prunable-tail facet
    #                       → top-level STAGED_DUPLICATE verdict).
    # Only synthesizable source files (.sv/.v) count as a duplicate-module
    # defect; an include-only header redeclaring under a guard is not a
    # vendor bundle defect.
    dup_findings = _scan_staged_duplicates(idx, set(reachable), synth_set)

    if not dup_findings:
        verdict = "PASS"
    elif any(d["scope"] == "reachable" for d in dup_findings):
        # A reachable-closure duplicate keeps the #639 DUPLICATE verdict so
        # that facet is never masked by a co-occurring prunable-tail one.
        verdict = "DUPLICATE"
    else:
        verdict = "STAGED_DUPLICATE"
    return {
        "verdict": verdict,
        "top": top,
        "files_total": len(files),
        "files_reachable": len(reachable),
        "files_prunable": len(prunable),
        "reachable": sorted(str(f) for f in reachable),
        "prunable": prunable,
        "duplicates": dup_findings,
        "trace": trace[:200],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--top", required=True,
                    help="authored chip_top / top module name")
    ap.add_argument("rtl_dir", help="flat vendor RTL directory")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    if not rtl_dir.is_dir():
        print(f"error: not a directory: {rtl_dir}", file=sys.stderr)
        return 2
    report = resolve(args.top, rtl_dir)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")

    print(f"=== catalog_glue_closure_resolver (top={args.top}) ===")
    print(f"  verdict: {report['verdict']}")
    if report["verdict"] in ("EMPTY", "TOP_NOT_FOUND"):
        print(f"  {report.get('error', '')}", file=sys.stderr)
        return 2
    print(f"  files: {report['files_total']} total, "
          f"{report['files_reachable']} reachable, "
          f"{report['files_prunable']} prunable")
    for d in report["duplicates"]:
        tag = "STAGED-DUPLICATE" if d.get("scope") == "staged" else "DUPLICATE"
        print(f"  [{tag}] {d['message']}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
