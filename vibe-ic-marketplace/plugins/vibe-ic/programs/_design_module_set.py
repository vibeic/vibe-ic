"""_design_module_set.py — the design's OWN module set, and the reconciliation
of a DECLARED top-module name against it (chip-AGNOSTIC).

THE DEFECT CLASS (vibe-ic#760)
==============================
A layer document declares a ``top_module`` name. A downstream gate reads that
name as ground truth and requires a DIFFERENT artefact — the testbench — to
instantiate it. When the name is not a module the design declares at all, the
requirement is UNSATISFIABLE, and the gate names the wrong subject: it reports
a testbench defect an author could fix, for a name no testbench could ever
bind.

    [FAIL] TB_INSTANTIATES_TOP — tb_<top>_full.v must instantiate the chip
    top `SPI` ...; no `SPI` instantiation found in tb

`SPI` was harvested out of prose in a register description ("Single SPI
interrupt request line ...") and published as ``L9.top_module``. The design
staged 13 modules and none of them is named ``SPI``; the testbench correctly
instantiated the real top, which the rest of the run honoured throughout.

THE RULE THIS MODULE ENCODES
----------------------------
**A requirement no artefact in the run can satisfy must name ITSELF as the
defect.** A declared identifier is a POINTER into the design's namespace, so
before any gate may require another artefact to honour it, the pointer has to
be reconciled against the namespace it claims to address. When the design's
own module set refutes it, the honest verdict is "the declaration names a
module this design does not declare" — never "the other artefact is missing an
instantiation".

WHY THE DESIGN'S MODULE SET IS THE ARBITER, AND WHEN IT IS NOT
--------------------------------------------------------------
The module set is derived from the artefacts the run itself staged (the RTL
directory, and the synthesis output when present). Two properties make it safe
to reason from:

  * It is CONSERVATIVE. Every declaration site found in any staged source
    widens the set, so a name the set does not contain was staged nowhere the
    run can see.
  * It is FALSIFIABLE ONLY WHEN NON-EMPTY. An empty module set means nothing
    was staged / nothing parsed — it refutes nothing, and
    :func:`reconcile_declared_top` answers ``unverifiable`` rather than
    manufacturing an absence. A gate that treated "I found no modules" as "the
    declared module is absent" would be the same mis-attribution one layer
    down.

WHY THE STRUCTURAL ROOT, AND NOT "WHATEVER THE TESTBENCH INSTANTIATES"
----------------------------------------------------------------------
Once a declared name is refuted, something still has to stand in for the top,
or the gate that depended on it silently stops biting. The replacement must be
derived INDEPENDENTLY of the artefact under audit: resolving the top as
"whatever the testbench instantiates" would make every testbench self-
certifying, and the pad-path requirement would be satisfied by a testbench
that binds an arbitrary leaf module. :func:`instantiation_roots` therefore
reads only the design: the root is the module no other staged module
instantiates. It is reported ONLY when it is unique — an ambiguous root is a
non-answer, and guessing between several would trade one unfounded requirement
for another.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

__all__ = [
    "SOURCE_GLOBS",
    "strip_comments",
    "module_names_in_text",
    "module_bodies_in_text",
    "design_module_set",
    "design_module_bodies",
    "instantiation_roots",
    "reconcile_declared_top",
]

#: HDL source extensions a design's module declarations can live in.
SOURCE_GLOBS = ("*.v", "*.sv", "*.vh", "*.svh")

#: Do not read a single source file larger than this when building the module
#: set. A flattened gate-level netlist can be hundreds of MB; the top module of
#: such a file is already declared in the RTL this set also scans, so the cap
#: costs no reachable name while keeping the gate bounded.
_MAX_SOURCE_BYTES = 32 * 1024 * 1024

_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_MODULE_DECL_RE = re.compile(r"(?m)^[ \t]*module\s+([A-Za-z_]\w*)")
_MODULE_BLOCK_RE = re.compile(
    r"(?ms)^[ \t]*module\s+([A-Za-z_]\w*)\b(.*?)^[ \t]*endmodule\b")


def strip_comments(text: str) -> str:
    """``text`` with Verilog/SystemVerilog comments blanked out.

    Comments are replaced, not deleted, only where that is free; the caller
    uses the result for name scanning, so exact offsets do not matter. A
    commented-out instantiation must not make a module look instantiated, and a
    commented-out declaration must not make a name look declared.
    """
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", text))


def module_names_in_text(text: str) -> Set[str]:
    """Module names declared in ``text`` (comments ignored).

    Both the line-anchored declaration and the full ``module``..``endmodule``
    block are counted, so a source whose final ``endmodule`` is missing still
    contributes its name — widening the set is always the safe direction.
    """
    clean = strip_comments(text)
    names = set(_MODULE_DECL_RE.findall(clean))
    names |= {m.group(1) for m in _MODULE_BLOCK_RE.finditer(clean)}
    return names


def module_bodies_in_text(text: str) -> Dict[str, str]:
    """``{module_name: body}`` for every complete block in ``text``."""
    clean = strip_comments(text)
    return {m.group(1): m.group(2) for m in _MODULE_BLOCK_RE.finditer(clean)}


def _source_files(dirs: Iterable[Path]) -> List[Path]:
    out: List[Path] = []
    seen: Set[Path] = set()
    for d in dirs:
        if d is None:
            continue
        d = Path(d)
        if not d.is_dir():
            continue
        for pat in SOURCE_GLOBS:
            for f in sorted(d.rglob(pat)):
                try:
                    if not f.is_file() or f.stat().st_size > _MAX_SOURCE_BYTES:
                        continue
                    key = f.resolve()
                except Exception:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                out.append(f)
    return out


def design_module_set(dirs: Iterable[Path]) -> Set[str]:
    """Every module name the design declares across ``dirs`` (recursive).

    An empty result means "nothing was staged or nothing parsed" — it is not
    evidence that any particular name is absent. Callers must route it through
    :func:`reconcile_declared_top`, which answers ``unverifiable`` for it.
    """
    names: Set[str] = set()
    for f in _source_files(dirs):
        try:
            names |= module_names_in_text(f.read_text(errors="ignore"))
        except Exception:
            continue
    return names


def design_module_bodies(dirs: Iterable[Path]) -> Dict[str, str]:
    """``{module_name: body}`` across ``dirs`` (recursive)."""
    bodies: Dict[str, str] = {}
    for f in _source_files(dirs):
        try:
            for name, body in module_bodies_in_text(
                    f.read_text(errors="ignore")).items():
                bodies.setdefault(name, body)
        except Exception:
            continue
    return bodies


def _instantiates(body: str, name: str) -> bool:
    """True iff ``body`` instantiates module ``name``.

    Matches the Verilog instantiation shape ``<module> [#(params)] <inst> (``.
    ``body`` is already comment-stripped by the block parser.
    """
    pat = re.compile(
        rf"\b{re.escape(name)}\s+(?:#\s*\((?:[^;]*?)\)\s*)?[A-Za-z_]\w*\s*"
        rf"(?:\[[^\]]*\]\s*)?\(")
    return bool(pat.search(body))


def instantiation_roots(bodies: Dict[str, str]) -> Set[str]:
    """Modules in ``bodies`` that no OTHER module in ``bodies`` instantiates.

    The design's own hierarchy is the only input; nothing outside it (least of
    all the artefact a caller is auditing) participates. A design with one root
    has an unambiguous top; any other count is a non-answer and the caller must
    say so rather than pick.
    """
    instantiated: Set[str] = set()
    for parent, body in bodies.items():
        for name in bodies:
            if name == parent or name in instantiated:
                continue
            if _instantiates(body, name):
                instantiated.add(name)
    return set(bodies) - instantiated


#: Reconciliation verdicts. ``absent`` is the ONLY one that licenses a caller
#: to refuse a declared name.
NO_DECLARATION = "no_declaration"
UNVERIFIABLE = "unverifiable"
PRESENT = "present"
ABSENT = "absent"


def reconcile_declared_top(declared: Optional[str],
                           module_set: Set[str]) -> dict:
    """Judge a DECLARED top-module name against the design's module set.

    Returns ``{"declared", "verdict", "module_set_size"}`` where ``verdict`` is
    one of :data:`NO_DECLARATION`, :data:`UNVERIFIABLE`, :data:`PRESENT`,
    :data:`ABSENT`. Only ``ABSENT`` is a refutation: it requires BOTH a
    non-empty declaration AND a non-empty module set, so neither a missing
    declaration nor an unreadable design can be turned into a finding against
    something else.
    """
    name = (declared or "").strip()
    size = len(module_set or set())
    if not name:
        verdict = NO_DECLARATION
    elif size == 0:
        verdict = UNVERIFIABLE
    elif name in module_set:
        verdict = PRESENT
    else:
        verdict = ABSENT
    return {"declared": name or None, "verdict": verdict,
            "module_set_size": size}
