#!/usr/bin/env python3
"""hspice_lib_ngspice_normalize.py — chip-AGNOSTIC HSPICE→ngspice model-library
directive normalizer.

PROBLEM (floor G-ANALOG-SPICE F1)
---------------------------------
ngspice is the deepest-parsing OSS engine for a commercial BSIM4 (level=54)
model library, but it cannot consume a handful of HSPICE-ONLY *packaging*
directives that a foundry ships inside its corner `.lib` closure. The confirmed
fatal one is HSPICE's **``.malias``** (model/sub-circuit alias). ngspice has no
``.malias`` directive, so it evaluates the right-hand side of

    .malias  <canonical> = <alias>

as a parameter expression -> ``Undefined parameter [<alias>]`` -> the whole deck
exits 1 before a single analysis runs. These aliases exist ONLY so an LVS tool
can reconcile a differently-named ESD/layout cell with the canonical schematic
device; the alias right-hand names carry **no** simulation model at all, and the
canonical left-hand names are already real ``.subckt`` definitions. So for
*simulation* the alias lines are pure dead weight — stripping them is
behaviour-preserving (see the strip-vs-translate note in ``normalize_lib_text``).

WHAT THIS DOES
--------------
Given the top model lib a corner deck ``.lib``-includes (or ``.include``s), this
walks the transitive include/lib-reference graph, finds every file whose text
carries an HSPICE-only directive ngspice cannot consume, and emits a NORMALIZED,
ngspice-consumable copy of *only* those files (plus any file that references one)
into a caller-supplied STAGE dir. The real PDK libraries are NEVER mutated in
place. References to clean (non-offending) files are rewritten to a RELATIVE path
back to the original file so the staged copy resolves under EITHER container
bind-mount scheme (verbatim ``-v $PWD:$PWD`` OR the legacy ``/foss/designs``
rewrite) — a relative path between two files under the same mounted project
subtree is invariant across both.

chip-AGNOSTIC / GENERAL
-----------------------
Detection is by DIRECTIVE SYNTAX only (``^\\s*\\.malias`` at line start). There is
NO PDK name, vendor, SKU, cell, or device literal anywhere in this file. When the
resolved lib contains no HSPICE-only directive (e.g. the open-source
sky130 / gf180 ngspice model files) the whole operation is a byte-identical
NO-OP: the ORIGINAL path is returned unchanged.

CLI
---
    hspice_lib_ngspice_normalize.py <top_lib> --stage-dir <dir> [--json]
        -> prints the ngspice-consumable top-lib path (original when no-op).
    hspice_lib_ngspice_normalize.py --probe <lib>
        -> exit 0 if the lib's include closure has an HSPICE-only directive.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


# ── HSPICE-only directive registry ──────────────────────────────────────────
# Keyed on directive SYNTAX, never on any PDK name. Each entry is a directive
# that ngspice's hs-compat mode CANNOT consume and that is pure LVS / packaging
# metadata (safe to drop for SIMULATION). The CONFIRMED, reproduced blocker is
# `.malias` (HSPICE model/subckt alias); it is the only one enabled by default.
# Adding a future proven-fatal HSPICE-only directive is a one-line edit here.
#
# `.malias <name> = <target>` (and its whitespace variants) — model/subckt
# alias. RHS carries no simulation model; LHS is a real device. ngspice reads
# the RHS as an undefined parameter and aborts. Strip for simulation.
_HSPICE_ONLY_DIRECTIVES = (
    r"malias",
)
_HSPICE_ONLY_RE = re.compile(
    r"^\s*\.(?:" + "|".join(_HSPICE_ONLY_DIRECTIVES) + r")\b",
    re.IGNORECASE,
)

# `.include 'file'` / `.include "file"` / `.include file`
_INCLUDE_RE = re.compile(
    r"^(?P<lead>\s*\.include\s+)(?P<q>['\"]?)(?P<file>[^'\"\s]+)(?P=q)\s*$",
    re.IGNORECASE,
)
# `.lib 'file' section` — a FILE include (two args). NOT `.lib section` (a
# one-arg SECTION start, which defines a block and must be left alone).
_LIB_FILE_RE = re.compile(
    r"^(?P<lead>\s*\.lib\s+)(?P<q>['\"])(?P<file>[^'\"]+)(?P=q)"
    r"(?P<rest>\s+\S.*)$",
    re.IGNORECASE,
)
# Bare (unquoted) two-token form: `.lib file section`. The first token must look
# like a path/filename (contains a '.' or '/') to avoid matching `.lib section`.
_LIB_FILE_BARE_RE = re.compile(
    r"^(?P<lead>\s*\.lib\s+)(?P<file>[^\s'\"]*[./][^\s'\"]*)"
    r"(?P<rest>\s+\S.*)$",
    re.IGNORECASE,
)


def contains_hspice_only_directive(text: str) -> bool:
    """True iff `text` carries at least one HSPICE-only directive (this file's
    own lines, not its includes)."""
    return any(_HSPICE_ONLY_RE.match(ln) for ln in text.splitlines())


def _read(path: Path) -> str:
    """Read a lib file, tolerant of foundry encodings; normalise CRLF + BOM."""
    txt = path.read_text(encoding="utf-8", errors="ignore")
    return txt.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")


def _iter_references(text: str):
    """Yield (kind, raw_line, filename) for every include / lib-file reference.

    kind is 'include' or 'lib'. `.lib section` (one-arg section start) is NOT a
    reference and is skipped."""
    for ln in text.splitlines():
        m = _INCLUDE_RE.match(ln)
        if m:
            yield "include", ln, m.group("file")
            continue
        m = _LIB_FILE_RE.match(ln)
        if m:
            yield "lib", ln, m.group("file")
            continue
        m = _LIB_FILE_BARE_RE.match(ln)
        if m:
            yield "lib", ln, m.group("file")


def _resolve_ref(base_dir: Path, filename: str) -> Path:
    """Resolve a reference filename relative to the including file's directory
    (HSPICE / ngspice semantics)."""
    p = Path(filename)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()


# ── transitive staging decision ─────────────────────────────────────────────

def _build_closure(top: Path):
    """Walk the include/lib graph from `top`. Returns:
      graph:    {abs_path: [(kind, raw_line, ref_abs_path or None), ...]}
      offends:  {abs_path: bool}  — file's OWN text has an HSPICE-only directive
    Missing / unreadable references are recorded with ref_abs_path=None and are
    left untouched (they resolve — or fail — exactly as they did natively)."""
    graph: dict = {}
    offends: dict = {}
    text_cache: dict = {}
    stack = [top.resolve()]
    while stack:
        cur = stack.pop()
        if cur in graph:
            continue
        try:
            txt = _read(cur)
        except OSError:
            graph[cur] = []
            offends[cur] = False
            continue
        text_cache[cur] = txt
        offends[cur] = contains_hspice_only_directive(txt)
        refs = []
        for kind, raw, fname in _iter_references(txt):
            rp = _resolve_ref(cur.parent, fname)
            if rp.is_file():
                refs.append((kind, raw, rp))
                if rp not in graph:
                    stack.append(rp)
            else:
                refs.append((kind, raw, None))
        graph[cur] = refs
    return graph, offends, text_cache


def _must_stage_set(graph, offends):
    """A file must be staged (rewritten copy) iff it OWN-offends OR it references
    a file that must be staged. Computed to a fixed point over the graph."""
    must = {p: bool(offends.get(p)) for p in graph}
    changed = True
    while changed:
        changed = False
        for p, refs in graph.items():
            if must[p]:
                continue
            for _kind, _raw, rp in refs:
                if rp is not None and must.get(rp):
                    must[p] = True
                    changed = True
                    break
    return must


# ── normalized-text emission ────────────────────────────────────────────────

def normalize_lib_text(text: str):
    """Return (normalized_text, n_removed). Strips (comments-out) every
    HSPICE-only directive line.

    STRIP-vs-TRANSLATE — why STRIP:
      A `.malias LHS = RHS` aliases an ESD/layout cell (RHS) to a canonical
      device (LHS) for LVS. The RHS names have NO simulation model of their own;
      the LHS names ARE real `.subckt` definitions that the simulation netlist
      instantiates directly. Dropping the alias therefore removes nothing the
      simulator can reference — the canonical device still resolves. TRANSLATE
      (emitting a passthrough `.subckt RHS ... X LHS ... .ends`) would only
      re-create devices simulation never names, and the many-to-one aliases
      (one LHS, several RHS) would collide. STRIP is the behaviour-preserving
      choice for simulation. If a future PDK's design netlist genuinely
      instantiated an alias RHS, the registry/decision here is the single place
      to switch that file to translate.
    """
    out = []
    n = 0
    for ln in text.splitlines():
        if _HSPICE_ONLY_RE.match(ln):
            n += 1
            out.append("* [ngspice-normalized: HSPICE-only directive removed] "
                       + ln.strip())
        else:
            out.append(ln)
    return "\n".join(out) + "\n", n


def _stage_name(original: Path, used: set) -> str:
    """A collision-free basename for a staged copy living in the flat stage dir.
    Prefixes a short path hash so two same-named files in different source dirs
    never clash, while staged copies still reference each other by basename."""
    import hashlib
    h = hashlib.sha1(str(original.resolve()).encode()).hexdigest()[:8]
    name = f"{original.stem}.{h}.ngspice{original.suffix or '.lib'}"
    # (hash makes it unique already; `used` guards the theoretical collision)
    assert name not in used, f"stage-name collision for {original}"
    used.add(name)
    return name


def normalize_for_ngspice(top_lib, stage_dir):
    """Normalize the HSPICE model-lib include closure rooted at `top_lib` so
    ngspice can consume it. Emits rewritten copies of ONLY the files that need it
    into `stage_dir`; the real PDK libs are never touched.

    Returns a dict:
      normalized_lib : str  — ngspice-consumable top-lib path (== original when
                              nothing needed normalizing: a byte-identical NO-OP)
      changed        : bool
      staged_files   : [str, ...]
      directives_removed : int
      notes          : [str, ...]
    """
    top = Path(top_lib).resolve()
    notes: list = []
    if not top.is_file():
        return {"normalized_lib": str(top), "changed": False,
                "staged_files": [], "directives_removed": 0,
                "notes": [f"top lib not a file: {top}"]}

    graph, offends, text_cache = _build_closure(top)
    must = _must_stage_set(graph, offends)

    if not must.get(top):
        # No HSPICE-only directive anywhere in the closure — genuine NO-OP.
        return {"normalized_lib": str(top), "changed": False,
                "staged_files": [], "directives_removed": 0,
                "notes": ["no HSPICE-only directive in include closure — "
                          "ngspice-native lib, returned unchanged"]}

    stage_dir = Path(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    # Assign a stage basename to every file that must be staged.
    staged_name: dict = {}
    used: set = set()
    for p in sorted((p for p in graph if must.get(p)), key=lambda x: str(x)):
        staged_name[p] = _stage_name(p, used)

    total_removed = 0
    staged_files: list = []
    for src, dst_name in staged_name.items():
        txt = text_cache.get(src, "")
        # 1) rewrite references line-by-line.
        rewritten_lines = []
        ref_by_raw = {raw: rp for (_k, raw, rp) in graph.get(src, [])}
        for ln in txt.splitlines():
            if ln in ref_by_raw:
                rp = ref_by_raw[ln]
                rewritten_lines.append(_rewrite_ref_line(
                    ln, rp, staged_name, stage_dir))
            else:
                rewritten_lines.append(ln)
        body = "\n".join(rewritten_lines) + "\n"
        # 2) strip HSPICE-only directives.
        body, n = normalize_lib_text(body)
        total_removed += n
        header = (f"* ngspice-normalized copy of {src.name} "
                  f"(HSPICE->ngspice, real PDK lib untouched)\n")
        out_path = stage_dir / dst_name
        out_path.write_text(header + body)
        staged_files.append(str(out_path))

    top_out = stage_dir / staged_name[top]
    notes.append(
        f"staged {len(staged_files)} normalized lib file(s); removed "
        f"{total_removed} HSPICE-only directive line(s); real PDK untouched")
    return {"normalized_lib": str(top_out), "changed": True,
            "staged_files": staged_files, "directives_removed": total_removed,
            "notes": notes}


def _rewrite_ref_line(raw: str, ref_abs, staged_name, stage_dir) -> str:
    """Rewrite one include/lib reference line so it resolves from `stage_dir`.
      - a staged (offending) target -> its stage basename (same dir);
      - a clean target -> a RELATIVE path back to the ORIGINAL file (mount-scheme
        invariant);
      - an unresolved reference (ref_abs None) -> left byte-identical.
    """
    if ref_abs is None:
        return raw
    if ref_abs in staged_name:
        new_target = staged_name[ref_abs]
    else:
        new_target = os.path.relpath(ref_abs, stage_dir)
    m = _INCLUDE_RE.match(raw)
    if m:
        return f"{m.group('lead')}'{new_target}'"
    m = _LIB_FILE_RE.match(raw)
    if m:
        return f"{m.group('lead')}'{new_target}'{m.group('rest')}"
    m = _LIB_FILE_BARE_RE.match(raw)
    if m:
        return f"{m.group('lead')}'{new_target}'{m.group('rest')}"
    return raw


def include_closure_has_hspice_only(top_lib) -> bool:
    """Cheap capability probe: does the include closure rooted at `top_lib` carry
    any HSPICE-only directive ngspice cannot consume?"""
    top = Path(top_lib)
    if not top.is_file():
        return False
    graph, offends, _ = _build_closure(top.resolve())
    return any(offends.values())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("top_lib", nargs="?", help="top model lib the deck includes")
    ap.add_argument("--stage-dir", help="dir for normalized copies")
    ap.add_argument("--probe", metavar="LIB",
                    help="exit 0 iff LIB's closure has an HSPICE-only directive")
    ap.add_argument("--json", action="store_true", help="emit result as JSON")
    args = ap.parse_args(argv)

    if args.probe:
        has = include_closure_has_hspice_only(args.probe)
        print("HSPICE_ONLY" if has else "NGSPICE_NATIVE")
        return 0 if has else 1

    if not args.top_lib or not args.stage_dir:
        ap.error("top_lib and --stage-dir are required (unless --probe)")
    res = normalize_for_ngspice(args.top_lib, args.stage_dir)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(res["normalized_lib"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
