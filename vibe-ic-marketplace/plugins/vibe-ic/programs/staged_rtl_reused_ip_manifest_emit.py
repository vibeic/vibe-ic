#!/usr/bin/env python3
"""ORGANIC #732 — auto-emit the keystone SOURCE_MANIFEST.json on the
PRE-STAGED-vendor-RTL catalog-glue path.

Reused-IP / catalog-glue designs reach phase2 via TWO entry paths:

  (1) catalog-pull — ``ip_catalog_pull.pull_all_catalog_matches`` copies the
      matched open-source IP into ``phase2/stage1/rtl/`` and (since #711)
      AUTO-EMITS ``phase2/stage1/rtl/SOURCE_MANIFEST.json{reused_ip:true}``
      whenever ≥1 IP was actually pulled.

  (2) pre-staged vendor RTL — ``input/vendor_rtl/`` is already populated, so
      ``design_one_shot_runner.step_rtl_gen`` WAIVES immediately with
      ``fallback_skill=catalog-glue-author`` and RETURNS. It never queries the
      catalog, never calls ``ip_catalog_pull``, and (pre-#732) never emitted
      the manifest. Because ``l9_rtl_pin_consistency_check.load_source_manifest``
      returns ``None`` when the file is absent, ALL reused-IP relaxations
      (#659 struct-bus flatten / tie-off, #711 rename, #712 exposed-output)
      were DEAD CODE on path (2) and the gating pin check hard-FAILed with
      ``L9 <-> RTL top pin/direction mismatch``. The keystone artifact only
      ever got written by AI hand-authoring.

This helper closes that gap: it emits the minimal keystone manifest on the
pre-staged path, mirroring ``ip_catalog_pull.py``'s merge contract so it can
NEVER clobber a hand-authored ``flattened_buses`` / ``flattened_outputs`` /
``tie_offs`` / ``renamed_interfaces`` block.

§4.05 NO-LEAK: ``emit_prestaged_reused_ip_manifest`` writes ONLY when the
pre-staged WAIVE actually fired — i.e. ``input/vendor_rtl/`` contains at least
one ``.v`` / ``.sv`` file. A NON-reused design (no ``input/vendor_rtl/``, or an
empty one) gets NO manifest, so it never receives a spurious ``reused_ip:true``.

chip-AGNOSTIC: structure-only — derives ``ip_list`` from the staged module
names / declaration.json; no chip or vendor literal anywhere.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional


# A SystemVerilog/Verilog `module <name>` declaration. Structure-only — matches
# the language grammar, no chip/vendor literal. We scan the staged vendor RTL
# to derive a human-meaningful ip_list (the module names), preferring this over
# bare file stems because a single file may declare several modules.
_RE_MODULE_DECL = re.compile(
    r"^\s*module\s+([A-Za-z_]\w*)", re.MULTILINE)


def _derive_ip_list(project: Path, vendor_dir: Path) -> List[str]:
    """Derive a structural ip_list from the pre-staged vendor RTL.

    Priority:
      1. declaration.json's ``ip_list`` (if a prior step / author populated it),
      2. else declaration.json's ``pulled_ip_files`` / ``ai_authored_files``
         file stems,
      3. else the ``module <name>`` declarations found under input/vendor_rtl/,
      4. else the staged file stems.

    Returns a sorted, de-duplicated list. Never empty when ≥1 staged file
    exists (falls through to file stems)."""
    # (1)/(2) declaration.json hints
    decl_path = project / "plugin_output" / "declaration.json"
    if decl_path.is_file():
        try:
            decl = json.loads(decl_path.read_text())
        except Exception:
            decl = {}
        if isinstance(decl, dict):
            existing = decl.get("ip_list")
            if isinstance(existing, list):
                names = sorted({str(x) for x in existing if str(x).strip()})
                if names:
                    return names
            stems: set = set()
            for key in ("pulled_ip_files", "ai_authored_files"):
                vals = decl.get(key)
                if isinstance(vals, list):
                    for v in vals:
                        if isinstance(v, str) and v.strip():
                            stems.add(Path(v).stem)
            if stems:
                return sorted(stems)

    # (3) module declarations under the staged vendor RTL
    staged = sorted(vendor_dir.rglob("*.v")) + sorted(vendor_dir.rglob("*.sv"))
    modules: set = set()
    for f in staged:
        try:
            txt = f.read_text(errors="ignore")
        except OSError:
            continue
        for m in _RE_MODULE_DECL.finditer(txt):
            modules.add(m.group(1))
    if modules:
        return sorted(modules)

    # (4) file stems
    return sorted({f.stem for f in staged})


def emit_prestaged_reused_ip_manifest(project: Path) -> Optional[Path]:
    """ORGANIC #732 — emit the keystone phase2/stage1/rtl/SOURCE_MANIFEST.json
    for a PRE-STAGED-vendor-RTL reused-IP project.

    Emits ONLY when ``input/vendor_rtl/`` is populated with ≥1 ``.v`` / ``.sv``
    file (the exact condition under which ``step_rtl_gen`` WAIVES with
    ``fallback_skill=catalog-glue-author``). Returns the manifest path on emit,
    or ``None`` when the no-leak guard declines (no vendor RTL → never write a
    reused_ip manifest for a non-reused design).

    MERGE-preserving (mirrors ip_catalog_pull.py): if a manifest already exists
    its hand-authored ``flattened_buses`` / ``flattened_outputs`` / ``tie_offs``
    / ``renamed_interfaces`` (and every other key) are read back and preserved;
    only ``reused_ip`` / ``ip_list`` / ``rtl_strategy`` are (re)asserted and
    ``generated_by`` is set via ``setdefault`` so a hand-authored provenance is
    never overwritten.

    chip-AGNOSTIC: structure-only; no chip/vendor literal."""
    vendor_dir = project / "input" / "vendor_rtl"
    if not vendor_dir.is_dir():
        return None
    staged = (sorted(vendor_dir.rglob("*.v"))
              + sorted(vendor_dir.rglob("*.sv")))
    if not staged:
        # §4.05 NO-LEAK: an empty / absent vendor_rtl is NOT the reused-IP
        # WAIVE path — never fabricate a reused_ip:true manifest.
        return None

    manifest_path = (project / "phase2" / "stage1" / "rtl"
                     / "SOURCE_MANIFEST.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.is_file():
        try:
            mf = json.loads(manifest_path.read_text())
            if not isinstance(mf, dict):
                mf = {}
        except Exception:
            mf = {}
    else:
        mf = {}

    ip_list = _derive_ip_list(project, vendor_dir)

    # MERGE-preserving — assert only the keystone keys; never touch a
    # hand-authored flattened_buses / flattened_outputs / tie_offs /
    # renamed_interfaces block (they survive untouched in `mf`).
    mf["reused_ip"] = True
    if ip_list:
        # Don't clobber a richer hand-authored ip_list with a thinner derived
        # one — only fill it when absent / empty.
        if not isinstance(mf.get("ip_list"), list) or not mf.get("ip_list"):
            mf["ip_list"] = ip_list
    mf["rtl_strategy"] = "catalog_lookup_plus_ai_glue"
    mf.setdefault("generated_by", "phase2_runner_prestaged")
    # ORGANIC (GAP-E2E-8) — emit an EMPTY reconciliation SCAFFOLD so the
    # catalog-glue handoff is EXPLICIT, not a silent minimal manifest. When a
    # REUSED-IP's genuine interface differs from the L9 doc's abstraction (e.g.
    # SERV's split o_sram_wdata/i_sram_rdata + separate waddr/raddr/wen/ren vs the
    # doc's combined SRAM bus), l9_rtl_pin_consistency_check needs a
    # `renamed_interfaces` / `flattened_buses` pairing; the minimal auto-manifest
    # provided none, so the completion audit FAILed with nothing to reconcile and
    # nothing telling the glue-author WHERE to look. This emits the two keys as
    # EMPTY lists + a one-line note pointing at the skill.
    #
    # §4.05 NO-LEAK (load-bearing): the scaffold is EMPTY. `_manifest_renamed_groups`
    # skips a `renamed_interfaces:[]` (the loop body never runs) so it reconciles
    # ZERO ports — the gate's verdict is byte-for-byte UNCHANGED (a real
    # doc-vs-RTL interface mismatch STILL FAILs until the pairing is authored).
    # setdefault preserves any hand-authored / already-populated block untouched.
    mf.setdefault("renamed_interfaces", [])
    mf.setdefault("flattened_buses", [])
    mf.setdefault(
        "_reconciliation_scaffold_note",
        "EMPTY scaffold (GAP-E2E-8). If the vendor RTL's interface differs from "
        "the L9 doc abstraction, author renamed_interfaces / flattened_buses "
        "entries ({l9:[...], rtl:[...]}) per catalog-glue-author/SKILL.md; an "
        "empty scaffold reconciles nothing, so l9_rtl_pin_consistency_check still "
        "reports the exact L9-only / RTL-only ports to pair.")
    manifest_path.write_text(json.dumps(mf, indent=2))
    return manifest_path


def main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Emit keystone SOURCE_MANIFEST.json on the pre-staged "
                    "vendor-RTL catalog-glue path (ORGANIC #732)")
    ap.add_argument("project", help="Project root")
    ns = ap.parse_args(argv)
    project = Path(ns.project).resolve()
    out = emit_prestaged_reused_ip_manifest(project)
    if out is None:
        print("NO-EMIT: input/vendor_rtl/ absent or empty "
              "(not the pre-staged reused-IP path)")
        return 0
    print(f"EMITTED: {out}")
    return 0


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(main(_sys.argv[1:]))
