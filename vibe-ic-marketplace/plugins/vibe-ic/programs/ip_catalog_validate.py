#!/usr/bin/env python3
"""
ip_catalog_validate.py — Validate catalog manifests against schema +
permissive-license whitelist.

Run from CI / pre-commit hook to catch broken manifests early.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ip_catalog_query import (  # noqa: E402
    FORBIDDEN_LICENSES, PERMISSIVE_LICENSES,
    find_catalog_dir, load_manifests,
)


REQUIRED_FIELDS = [
    "ip_name", "ip_version", "ip_class", "license", "canonical_url",
    "description", "implements", "matches_when", "interface", "rtl_files",
]


def validate_manifest(m: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a single manifest. Returns (ok, issues)."""
    issues: List[str] = []

    for f in REQUIRED_FIELDS:
        if f not in m:
            issues.append(f"missing required field: {f}")

    lic = m.get("license")
    if lic:
        if lic in FORBIDDEN_LICENSES:
            issues.append(f"FORBIDDEN license {lic!r} — Plugin will reject")
        elif lic not in PERMISSIVE_LICENSES:
            # v1.6.587 — surface unknown license as soft-warning by default
            # (caller can promote to hard-error via --strict-license-only).
            issues.append(f"unknown license {lic!r} — not in PERMISSIVE whitelist")

    mw = m.get("matches_when")
    if not isinstance(mw, list) or not mw:
        issues.append("matches_when must be non-empty list")

    rf = m.get("rtl_files")
    if not isinstance(rf, list) or not rf:
        issues.append("rtl_files must be non-empty list")
    elif not all(isinstance(p, str) for p in rf):
        issues.append("rtl_files entries must all be strings")

    url = m.get("canonical_url", "")
    if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
        issues.append(f"canonical_url should be HTTP(S) URL: got {url!r}")

    iface = m.get("interface", {})
    if not isinstance(iface, dict):
        issues.append("interface must be dict")
    else:
        ports = iface.get("ports")
        if not isinstance(ports, list) or not ports:
            issues.append("interface.ports must be non-empty list")
        else:
            for i, port in enumerate(ports):
                if not isinstance(port, dict):
                    issues.append(f"interface.ports[{i}] not a dict")
                    continue
                if "name" not in port:
                    issues.append(f"interface.ports[{i}] missing 'name'")
                if "dir" not in port:
                    issues.append(f"interface.ports[{i}] missing 'dir'")
                elif port["dir"] not in ("in", "out", "inout"):
                    issues.append(f"interface.ports[{i}].dir invalid: {port.get('dir')!r}")

    return (not issues, issues)


def main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Validate ip-catalog manifests")
    ap.add_argument("--catalog-dir", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict-license-only", action="store_true",
                    help="Fail if any manifest's license is not in "
                         "PERMISSIVE_LICENSES (whitelist-only mode). "
                         "Without this flag, unknown licenses are WARN.")
    args = ap.parse_args(argv)

    catalog_dir = Path(args.catalog_dir) if args.catalog_dir else find_catalog_dir()
    if catalog_dir is None:
        print("ERROR: ip-catalog/ not found", file=sys.stderr)
        return 2

    manifests = load_manifests(catalog_dir)
    results = []
    n_pass = n_fail = 0
    for m in manifests:
        ok, issues = validate_manifest(m)
        results.append({
            "manifest_path": m.get("_manifest_path"),
            "ip_name": m.get("ip_name"),
            "license": m.get("license"),
            "ok": ok,
            "issues": issues,
        })
        if ok:
            n_pass += 1
        else:
            n_fail += 1

    if args.json:
        print(json.dumps({
            "summary": {"total": len(manifests), "pass": n_pass, "fail": n_fail},
            "results": results,
        }, indent=2))
    else:
        print(f"=== ip-catalog validate — {len(manifests)} manifests ===")
        for r in results:
            mark = "PASS" if r["ok"] else "FAIL"
            print(f"  [{mark}] {r['ip_name']} ({r['license']})  {r['manifest_path']}")
            for issue in r["issues"]:
                print(f"      - {issue}")
        print()
        print(f"PASS: {n_pass}  FAIL: {n_fail}")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
