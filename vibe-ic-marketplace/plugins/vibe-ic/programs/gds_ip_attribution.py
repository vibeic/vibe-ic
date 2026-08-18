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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _shape_refusal as _sr  # noqa: E402  (#991)


VIBE_IC_USER_LAYER = (200, 42)
VIBE_IC_USER_TEXT_LAYER = (200, 43)


#: The token this record uses where a count or a hash would go but the field it
#: would have been computed from could not be read. It is deliberately NOT a
#: number and NOT a hex string: the whole point is that a foundry IP-audit
#: reviewer scanning this blob must not be able to read the field as a measured
#: zero. `REFUSED` sorts, greps and reads as what it is.
REFUSED = "REFUSED"


def build_attribution_blob(declaration: Dict[str, Any]) -> str:
    """The VIBE-IC-CATALOG-AUDIT record embedded in the foundry handoff GDS.

    #991 — WHY THERE ARE `REFUSED` LINES IN AN EMITTER. This function has no
    verdict, so the defect here is not a gate passing: it is that the record
    it writes INTO A TAPE-OUT DELIVERABLE stated things that were not true.
    MEASURED on `files_copied` carrying two entries keyed by filename:

        before   IP <n> <v> <l> files=0 sha256_agg:e3b0c44298fc1c14 …
        after    IP <n> <v> <l> files=REFUSED sha256_agg:REFUSED …
                 REFUSED `files_copied` … an object carrying 2 key(s) …

    `files=0` is the fail-open half — two copied files reported as none. The
    `sha256_agg` is worse and was not in the issue: `e3b0c44298fc1c14` is the
    head of SHA-256 of the EMPTY STRING, so the record published a plausible
    16-hex-digit aggregate attestation over a file set it had not read. A
    reviewer cannot tell that from a real digest, and an IP-provenance record
    whose hash means "I hashed nothing" is worse than one that has no hash: the
    absent case correctly printed `n/a`.

    The record's format for WELL-FORMED input is byte-identical to before.
    """
    lines = ["VIBE-IC-CATALOG-AUDIT v1"]
    refusals: List[Dict[str, Any]] = []

    def refuse(mismatch: Dict[str, Any], where: str = "") -> None:
        refusals.append(mismatch)
        lines.append(f"{REFUSED} {_sr.sentence(mismatch, where)}")

    ips, m_ips = _sr.read_list_from(declaration, "ip_catalog_used")
    if m_ips is not None:
        # The outer container. Unread, this emitted a blob with NO `IP` lines
        # at all — indistinguishable from a design that reused no catalog IP,
        # which is precisely the claim a licence auditor reads this record to
        # check.
        refuse(m_ips, "declaration.json")

    for ip in ips:
        if not isinstance(ip, dict):
            continue
        name = ip.get("ip_name", "?")
        ver = ip.get("version", "?")
        lic = ip.get("license", "?")
        commit = ip.get("canonical_commit", "?")
        url = ip.get("canonical_url", "?")
        files, m_files = _sr.read_list_from(ip, "files_copied")
        if m_files is not None:
            lines.append(
                f"IP {name} {ver} {lic} files={REFUSED} "
                f"sha256_agg:{REFUSED} url:{url} commit:{commit}"
            )
            refuse(m_files, f"ip_catalog_used[{name}]")
            continue
        n_files = len(files)
        h = hashlib.sha256()
        for f in files:
            if isinstance(f, dict) and f.get("sha256"):
                h.update(f["sha256"].encode())
        aggregate_sha = h.hexdigest()[:16] if files else "n/a"
        lines.append(
            f"IP {name} {ver} {lic} files={n_files} "
            f"sha256_agg:{aggregate_sha} url:{url} commit:{commit}"
        )

    authored, m_authored = _sr.read_list_from(declaration, "ai_authored_files")
    if m_authored is not None:
        refuse(m_authored, "declaration.json")
    for f in authored:
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
        blob = build_attribution_blob(decl)
        print(blob)
        # #991 — the record was still emitted (a partial provenance record is
        # more use to an auditor than none), but a run that produced one
        # carrying a REFUSED line must not report success: this is the only
        # signal a CALLER gets, and rc 0 would say the attribution is complete.
        return 0 if f"\n{REFUSED} " not in "\n" + blob else 3

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
            # #991 — same rule as build-text, and it matters more here: this
            # blob is now INSIDE the foundry handoff GDS.
            if f"\n{REFUSED} " in "\n" + blob:
                print(f"  {REFUSED}: the attribution record carries a stated "
                      f"hole — a declared list could not be read; see the "
                      f"{REFUSED} line(s) above", file=sys.stderr)
                return 3
            return 0
        return 1

    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
