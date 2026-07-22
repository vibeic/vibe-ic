#!/usr/bin/env python3
"""Include-hub aggregator detection + macro-header ordering (chip-AGNOSTIC).

An INCLUDE-HUB AGGREGATOR is a source file whose body `` `include ``s a SIBLING
RTL file that is ALSO staged as a standalone source in the same set. It is
meant to be compiled ALONE — it pulls in everything, in order, in one unit.

Feeding BOTH the hub and its included siblings to one bag-of-files read defines
every included module TWICE:

    slang:         error: duplicate definition of 'top' [-Wduplicate-definition]
    read_verilog:  ERROR: Module `\\top' already declared

The read then ABORTS, so ZERO comparison points are built. The convention is
common (ChipFoundry/eFabless `` uprj_netlists.v `` is the canonical case, but
any "compile me alone" roll-up file has this shape), so the filter is written
against the `` `include ``/`` module `` grammar only — no chip, vendor, path or
SKU literal anywhere.

This module is the SINGLE SOURCE OF TRUTH for that predicate. Phase-2 synth
(`design_one_shot_runner._is_fpga_board_wrapper` signal 1) already applied it;
the LEC gold read and phase-3 synth now consume the SAME implementation rather
than a second, weaker copy — so the three selectors cannot drift apart.

Two refinements are load-bearing and are the reason a re-implementation is the
wrong move (each was paid for by a real regression):

  * #614 — only a sibling that DECLARES a module counts. Including a pure
    macro/HEADER sibling (an `` `ifndef ``-guarded file of `` `define ``s and NO
    `module`) is normal SystemVerilog composition, NOT an aggregator signal.
    Without this, a real RTL leaf that merely includes a macro header gets
    dropped from the source list and synth dies "unknown module".
  * comment-stripping + the `` // asic-sim-include: `` allow-marker — a
    commented-out `` `include `` is not a signal, and the rare legitimate
    include-based composition can opt out explicitly.

FAIL-OPEN throughout: any read error means "not a hub", i.e. do NOT exclude.
Dropping a real module is fatal; keeping a redundant file is harmless.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

# An `include of a .v/.sv source. Anchored at line start (after optional
# whitespace) so it cannot match inside a string or a trailing expression.
_INCLUDE_RE = re.compile(r'^\s*`?\s*include\s+"([^"]+\.s?v)"', re.IGNORECASE)

# Allow-marker that overrides the sibling-include signal for the rare
# legitimate include-based ASIC composition.
_ASIC_SIM_INCLUDE_MARKER = re.compile(r'//\s*asic-sim-include\s*:', re.IGNORECASE)

_MODULE_DECL_RE = re.compile(r'(?<![\w$])module\s+[A-Za-z_]\w*')
_DEFINE_RE = re.compile(r'(?<![\w$])`define\s+[A-Za-z_]\w*')


def strip_v_comments(text: str) -> str:
    """Remove // line comments and /* */ block comments (chip-AGNOSTIC)."""
    if not isinstance(text, str):
        return ""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def sibling_declares_module(sib_path: Path) -> bool:
    """#614 — True iff the sibling file declares an instantiable `module`.

    A pure macro/header sibling returns False, so including it is never read as
    an aggregator signal. Fail-open: unreadable / module-less => False."""
    try:
        txt = Path(sib_path).read_text(errors="replace")
    except Exception:
        return False
    return bool(_MODULE_DECL_RE.search(strip_v_comments(txt)))


def is_include_hub(path: Path,
                   sibling_basenames: Optional[set] = None) -> bool:
    """True iff `path` is an include-hub aggregator: it `` `include ``s a
    SIBLING source (present standalone in the same set) that DECLARES a module.

    `sibling_basenames` = basenames of the OTHER staged sources. An include of
    itself, or of a non-staged / module-less header, is NOT a hub signal.
    Fail-open: any read error => False (do not exclude)."""
    if not sibling_basenames:
        return False
    p = Path(path)
    try:
        raw = p.read_text(errors="replace")
    except Exception:
        return False
    lines = raw.splitlines()
    if any(_ASIC_SIM_INCLUDE_MARKER.search(ln) for ln in lines):
        return False
    for ln in lines:
        # A fully commented-out include line is not a signal.
        stripped = ln.split("//", 1)[0]
        m = _INCLUDE_RE.match(stripped)
        if not m:
            continue
        inc_base = os.path.basename(m.group(1))
        if inc_base in sibling_basenames and inc_base != p.name:
            if sibling_declares_module(p.parent / inc_base):
                return True
    return False


def drop_include_hubs(files: Sequence[Path]) -> List[Path]:
    """`files` minus every include-hub aggregator, order preserved.

    DEGENERATE GUARD: if EVERY file looks like a hub, return the input
    unchanged. An empty source list is a worse failure than a duplicate
    definition — the caller must still be able to read something and emit an
    honest verdict."""
    paths = [Path(f) for f in files]
    names = {p.name for p in paths}
    kept = [p for p in paths if not is_include_hub(p, names)]
    return kept or paths


def is_macro_header(path: Path) -> bool:
    """True iff `path` is a PURE macro header: it defines at least one
    `` `define `` and declares NO `module`.

    Such a file carries only preprocessor state, so under a single compilation
    unit it must be concatenated BEFORE any file that uses its macros."""
    try:
        txt = Path(path).read_text(errors="replace")
    except Exception:
        return False
    body = strip_v_comments(txt)
    return bool(_DEFINE_RE.search(body)) and not _MODULE_DECL_RE.search(body)


def macro_headers_first(files: Sequence[Path]) -> List[Path]:
    """Reorder so pure macro headers come FIRST, relative order preserved.

    Required by a SINGLE-COMPILATION-UNIT read (`read_slang --single-unit`),
    which concatenates the CLI files IN ORDER: a macro used by a file that is
    concatenated before its defining header is still `unknown macro or compiler
    directive`. The default source order is ALPHABETICAL, so whether the
    defining header lands first is pure luck of its filename
    (`defines.v` < `user_project_wrapper.v` works; `defines.v` > `counter.v`
    does NOT). This makes it deterministic instead of alphabetical luck.

    A no-op when the set has no pure macro header, and a no-op for the
    multi-unit / successive-`read_verilog` paths, which share preprocessor
    scope across reads anyway."""
    paths = [Path(f) for f in files]
    headers = [p for p in paths if is_macro_header(p)]
    if not headers:
        return paths
    rest = [p for p in paths if not is_macro_header(p)]
    return headers + rest
