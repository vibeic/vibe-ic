"""Staged hard-macro model discovery + blackbox staging (chip-AGNOSTIC).

ORGANIC-20260801-staged-hardmacro-model-not-injected-into-sim-or-synth

A design may instantiate a hard-macro (SRAM / vendor IP) whose models are
STAGED under the design's OWN pdk-local tree rather than authored into rtl/.
L8 hard-macro integration ships the abstract triplet ``.lib/.lef/.v`` under
``input/pdk_local/``, and Phase 1 records the roots in
``pdk_staging_read.json:staged_pdk_roots``. But the Phase-2 sim compile set,
the generic sanity-synth, and the LEC gold build all glob ``rtl/`` ONLY, so
such a macro is ``Unknown module type: <macro>`` and those steps FAIL on an
otherwise-correct design — even though the author explicitly relied on "the
runner blackboxes the macro for synth and streams the behavioral .v for sim".

This module is the ONE place that resolves that gap, consumed by both
``design_one_shot_runner`` (sim + synth) and ``lec_run`` (equiv gold/gate):

  * sim   -> append the behavioral model .v (real memory behavior) to the
             iverilog compile set.
  * synth -> feed a ``(* blackbox *)``-attributed copy so EVERY yosys frontend
             (read_verilog / read_slang / sv2v) keeps the macro as an interface
             blackbox (surrounding logic synthesizes; the macro body is not
             elaborated into flops).
  * lec   -> put the SAME blackbox stub on BOTH the gold and gate side so the
             equiv miter proves the surrounding logic under an assume-guarantee
             on identical macro interfaces.

Only macros INSTANTIATED-but-UNDEFINED in staged rtl/ are injected — never a
blanket include. Returns [] for any design with no staged macro roots, so it
is byte-identical to prior behavior on designs without staged hard-macros.
Structural (module-name presence) only, no chip/PDK literal.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

__all__ = [
    "staged_pdk_roots",
    "module_names_in_text",
    "staged_hardmacro_models",
    "emit_blackbox_stub",
]

_MODULE_DECL_RE = re.compile(r'(?m)^\s*module\s+([A-Za-z_]\w*)')
_IDENT_RE = re.compile(r'\b([A-Za-z_]\w*)\b')
_LIB_CELL_RE = re.compile(r'\bcell\s*\(\s*([A-Za-z_]\w*)\s*\)')


def staged_pdk_roots(project: Path) -> List[Path]:
    """Design-staged PDK-local roots recorded by Phase 1, resolved under
    ``project``. Falls back to ``input/pdk_local`` when the manifest is absent
    but that directory exists."""
    roots: List[Path] = []
    manifest = project / "phase1" / "pdk_staging_read.json"
    try:
        if manifest.is_file():
            data = json.loads(manifest.read_text(errors="replace"))
            for r in (data.get("staged_pdk_roots") or []):
                p = (project / r).resolve() if not Path(r).is_absolute() \
                    else Path(r)
                if p.is_dir():
                    roots.append(p)
    except Exception:  # pragma: no cover — robustness aid, never crashes
        roots = []
    if not roots:
        fallback = (project / "input" / "pdk_local").resolve()
        if fallback.is_dir():
            roots.append(fallback)
    return roots


def module_names_in_text(txt: str) -> set:
    """Verilog/SV top-level module names declared in ``txt`` (line-anchored
    ``module <name>``; ``endmodule`` never matches)."""
    return set(_MODULE_DECL_RE.findall(txt))


def staged_hardmacro_models(project: Path, rtl_files) -> List[dict]:
    """Discover instantiated-but-unstaged hard-macro models.

    Returns one dict per macro that is (a) NOT defined in staged rtl/ and
    (b) referenced by name in the staged rtl/ text (i.e. actually
    instantiated). Each dict: ``{'name', 'v' (behavioral Path|None),
    'lib' (Liberty Path|None)}``. A macro referenced but with no staged model
    is still returned (v/lib None) so a caller can name the honest gap.
    """
    roots = staged_pdk_roots(project)
    if not roots:
        return []
    rtl_text_parts: List[str] = []
    defined: set = set()
    for f in rtl_files:
        try:
            t = Path(str(f)).read_text(errors="replace")
        except OSError:
            continue
        rtl_text_parts.append(t)
        defined |= module_names_in_text(t)
    rtl_text = "\n".join(rtl_text_parts)
    if not rtl_text:
        return []
    referenced = set(_IDENT_RE.findall(rtl_text))
    model_by_name: dict = {}
    lib_by_name: dict = {}
    for root in roots:
        for pat in ("*.v", "*.sv"):
            for mv in sorted(root.rglob(pat)):
                try:
                    for nm in module_names_in_text(
                            mv.read_text(errors="replace")):
                        model_by_name.setdefault(nm, mv)
                except OSError:
                    continue
        for lib in sorted(root.rglob("*.lib")):
            try:
                for nm in _LIB_CELL_RE.findall(lib.read_text(errors="replace")):
                    lib_by_name.setdefault(nm, lib)
            except OSError:
                continue
    out: List[dict] = []
    for nm in sorted(model_by_name):
        if nm in defined:
            continue          # authored in rtl/ — not a staged macro
        if nm not in referenced:
            continue          # staged but not instantiated — skip
        out.append({"name": nm,
                    "v": model_by_name.get(nm),
                    "lib": lib_by_name.get(nm)})
    return out


def emit_blackbox_stub(model_v: Path, name: str, out_dir: Path) -> Path:
    """Write a ``(* blackbox *)``-attributed copy of a hard-macro model so
    every yosys frontend treats it as an interface-only blackbox. The attribute
    is inserted before EACH ``module`` declaration (multi-module models
    supported). Pure text transform, no chip/PDK literal."""
    txt = model_v.read_text(errors="replace")
    txt = re.sub(r'(?m)^(\s*)(module\b)', r'\1(* blackbox *)\n\1\2', txt)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{name}.bb.v"
    dst.write_text(txt)
    return dst
