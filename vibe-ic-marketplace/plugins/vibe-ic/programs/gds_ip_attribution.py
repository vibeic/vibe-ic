#!/usr/bin/env python3
"""
gds_ip_attribution.py — Embed IP attribution metadata into the foundry
handoff GDS as user-data records.

When Plugin's catalog-glue-author path pulls open-source IPs, the
declaration.json carries (ip_name, version, license, canonical_url,
canonical_commit, sha256). Foundry tape-out QA / IP audit reviewers
should be able to read this directly from the GDS without having to
chase the declaration.json side-file.

Strategy:
  1. Read project/plugin_output/declaration.json → ip_catalog_used + ai_authored_files
  2. Build a single text blob:
        "VIBE-IC-CATALOG-AUDIT v1\\n"
        "IP serv 1.4.0 ISC sha256:<...> commit:1.4.0\\n"
        "IP shared_sram_rf 0.2.2 Apache-2.0 sha256:<...> commit:master\\n"
        "AI-AUTHORED my_chip_top.v sha256:<...>\\n"
        "..."
  3. Inject as a klayout text shape at user-data layer (200, 43) on the
     top cell of the GDS.
  4. Verify by reading back with klayout / pya.

Layer choice: (200, 43) is well outside SKY130/GF180MCU production
routing range, so foundry QA strips/ignores it without affecting fab.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


VIBE_IC_USER_LAYER = (200, 42)
VIBE_IC_USER_TEXT_LAYER = (200, 43)


def build_attribution_blob(declaration: Dict[str, Any]) -> str:
    lines = ["VIBE-IC-CATALOG-AUDIT v1"]

    for ip in declaration.get("ip_catalog_used", []):
        if not isinstance(ip, dict):
            continue
        name = ip.get("ip_name", "?")
        ver = ip.get("version", "?")
        lic = ip.get("license", "?")
        commit = ip.get("canonical_commit", "?")
        url = ip.get("canonical_url", "?")
        files = ip.get("files_copied", []) or []
        n_files = len(files) if isinstance(files, list) else 0
        h = hashlib.sha256()
        for f in (files if isinstance(files, list) else []):
            if isinstance(f, dict) and f.get("sha256"):
                h.update(f["sha256"].encode())
        aggregate_sha = h.hexdigest()[:16] if files else "n/a"
        lines.append(
            f"IP {name} {ver} {lic} files={n_files} "
            f"sha256_agg:{aggregate_sha} url:{url} commit:{commit}"
        )

    for f in declaration.get("ai_authored_files", []):
        if isinstance(f, str):
            lines.append(f"AI-AUTHORED {f}")
        elif isinstance(f, dict):
            name = f.get("file_name") or f.get("path") or "?"
            sha = f.get("sha256", "?")[:16]
            lines.append(f"AI-AUTHORED {name} sha256:{sha}")

    lca = declaration.get("license_compliance_audit", {})
    if lca:
        spdx_set = sorted(lca.get("spdx_set", []))
        permissive = lca.get("all_permissive", "?")
        lines.append(
            f"LICENSE-AUDIT all_permissive={permissive} "
            f"spdx_set={','.join(spdx_set) if spdx_set else 'none'}"
        )

    rtl_strategy = declaration.get("rtl_strategy", "unspecified")
    lines.append(f"RTL-STRATEGY {rtl_strategy}")

    return "\n".join(lines)


def inject_into_gds(gds_path: Path, top_cell_name: str, attribution: str,
                    output_path: Path) -> bool:
    try:
        import pya as _pya
    except ImportError:
        print("ERROR: pya (klayout) not importable", file=sys.stderr)
        return False

    ly = _pya.Layout()
    ly.read(str(gds_path))

    top = ly.cell(top_cell_name) if top_cell_name else None
    if top is None:
        tops = list(ly.top_cells())
        if not tops:
            print(f"ERROR: no top cell in {gds_path}", file=sys.stderr)
            return False
        top = tops[0]

    text_layer_idx = ly.layer(VIBE_IC_USER_TEXT_LAYER[0], VIBE_IC_USER_TEXT_LAYER[1])
    text_obj = _pya.Text(attribution, _pya.Trans(0, 0))
    top.shapes(text_layer_idx).insert(text_obj)

    box_layer_idx = ly.layer(VIBE_IC_USER_LAYER[0], VIBE_IC_USER_LAYER[1])
    top.shapes(box_layer_idx).insert(_pya.Box(0, 0, 100, 100))

    ly.write(str(output_path))
    return True


def read_attribution_from_gds(gds_path: Path, top_cell_name: str = "") -> str:
    try:
        import pya as _pya
    except ImportError:
        return ""

    ly = _pya.Layout()
    ly.read(str(gds_path))
    text_layer_idx = ly.layer(VIBE_IC_USER_TEXT_LAYER[0], VIBE_IC_USER_TEXT_LAYER[1])
    if text_layer_idx < 0:
        return ""

    if top_cell_name:
        top = ly.cell(top_cell_name)
    else:
        tops = list(ly.top_cells())
        top = tops[0] if tops else None
    if top is None:
        return ""

    texts = []
    for shape in top.shapes(text_layer_idx).each():
        if shape.is_text():
            texts.append(shape.text.string)
    return "\n---\n".join(texts)


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="GDS IP attribution embed / extract")
    sub = ap.add_subparsers(dest="cmd", required=True)

    inject_p = sub.add_parser("inject", help="Embed attribution into GDS")
    inject_p.add_argument("project")
    inject_p.add_argument("--gds-in", required=True)
    inject_p.add_argument("--gds-out", required=True)
    inject_p.add_argument("--top", default="")

    extract_p = sub.add_parser("extract", help="Read attribution back from GDS")
    extract_p.add_argument("gds")
    extract_p.add_argument("--top", default="")

    build_p = sub.add_parser("build-text", help="Build attribution text only")
    build_p.add_argument("project")

    args = ap.parse_args(argv)

    if args.cmd == "build-text":
        decl_path = Path(args.project) / "plugin_output" / "declaration.json"
        if not decl_path.is_file():
            print(f"ERROR: {decl_path} not found", file=sys.stderr)
            return 2
        decl = json.loads(decl_path.read_text())
        print(build_attribution_blob(decl))
        return 0

    if args.cmd == "extract":
        text = read_attribution_from_gds(Path(args.gds), args.top)
        if text:
            print(text)
            return 0
        print("(no attribution found)", file=sys.stderr)
        return 1

    if args.cmd == "inject":
        decl_path = Path(args.project) / "plugin_output" / "declaration.json"
        if not decl_path.is_file():
            print(f"ERROR: {decl_path} not found", file=sys.stderr)
            return 2
        decl = json.loads(decl_path.read_text())
        blob = build_attribution_blob(decl)
        top = args.top or decl.get("top_module", "")
        ok = inject_into_gds(Path(args.gds_in), top, blob, Path(args.gds_out))
        if ok:
            print(f"injected {len(blob.encode())} bytes attribution into {args.gds_out}")
            print(f"  layer: {VIBE_IC_USER_TEXT_LAYER}, top cell: {top!r}")
            return 0
        return 1

    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
