#!/usr/bin/env python3
"""
ip_catalog_pull.py — Pull catalog IP RTL files into project's canonical
phase2/stage1/rtl/ directory + record provenance.

For each CatalogMatch:
  1. Locate the IP source — preferring local mirror in ic_documents/,
     falling back to git clone canonical_url at canonical_commit.
  2. Copy rtl_files (per manifest) into project/phase2/stage1/rtl/.
  3. Append a provenance.jsonl line recording (ip, version, license,
     commit, files_pulled, sha256, timestamp).
  4. Update project/plugin_output/declaration.json with ip_catalog_used.

Plugin pipeline hook:
  - catalog-glue-author skill calls this after Plugin classifier emits
    catalog matches.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import sibling module
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ip_catalog_query import (  # noqa: E402
    CatalogMatch, check_license_compatibility, query_catalog,
)


# ---------------------------------------------------------------------------
# Local mirror discovery — these dirs hold pre-cloned open-source IPs
# (NOT through reverse-engineering — these are legitimate open-source repos
# the user already mirrored for offline use).
# ---------------------------------------------------------------------------
LOCAL_MIRROR_ROOTS = [
    Path("~/ic_documents/open_ic"),
    Path("~/ic_documents/open_ip"),
]


# Manifest ip_name → known local mirror subdir name (handles naming differences)
# v1.6.585 — second expansion (crypto v2 + arithmetic + peripheral additions)
LOCAL_MIRROR_MAP = {
    # cpu/
    "serv": ["serv"],
    "picorv32": ["picorv32"],
    "ibex": ["ibex"],
    # crypto/ (round 1)
    "sha256_core": ["sha256"],
    "aes_core": ["aes"],
    "chacha_core": ["chacha"],
    "sha3_core": ["sha3"],
    # crypto/ (round 2)
    "sha512_core": ["secworks-sha512"],
    "blake2s_core": ["blake2s"],
    "hmac_core": ["secworks-hmac"],
    "poly1305_core": ["secworks-poly1305"],
    "ascon_core": ["secworks-ascon"],
    # rng/
    "trng": ["trng"],
    # interconnect/
    "wb_intercon": ["wb_intercon"],
    # peripheral/
    "spi_master": ["../open_ip/spi-master"],  # relative to open_ic/
    "lfsr": ["alexforencich-lfsr"],
    # arithmetic/
    "fpu_single": ["freecores-fpu"],
    # memory/
    "shared_sram_rf": [
        "3rd_benchmark_ic/openMPW_shuttles/subservient",
    ],
}


# ---------------------------------------------------------------------------
def find_local_mirror(ip_name: str) -> Optional[Path]:
    """Return path to local mirror dir if present, else None."""
    candidate_names = LOCAL_MIRROR_MAP.get(ip_name, [ip_name])
    for root in LOCAL_MIRROR_ROOTS:
        for name in candidate_names:
            p = root / name
            if p.is_dir():
                return p
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def pull_catalog_ip(match: CatalogMatch,
                    project: Path,
                    dest_subdir: str = "phase2/stage1/rtl") -> Dict[str, Any]:
    """Pull a single catalog IP's RTL files into project's canonical rtl/ dir.

    Returns audit dict with files_pulled, sha256 of each, license, etc.
    Records a provenance.jsonl line.
    """
    # 1. License compliance gate
    ok, rationale = check_license_compatibility(match.license)
    if not ok:
        return {
            "ip_name": match.ip_name,
            "status": "REJECTED",
            "reason": rationale,
        }

    # 2. Locate source
    src_dir = find_local_mirror(match.ip_name)
    pull_method = "local_mirror"
    if src_dir is None:
        # Fallback: git clone canonical_url at canonical_commit
        # (only when network available + canonical_url set)
        src_dir = _git_clone_to_cache(match)
        pull_method = "git_clone"
    if src_dir is None or not src_dir.is_dir():
        return {
            "ip_name": match.ip_name,
            "status": "FAIL",
            "reason": f"no local mirror in {LOCAL_MIRROR_ROOTS} and git clone not available",
        }

    # 3. Copy listed RTL files
    dest_dir = project / dest_subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    files_copied: List[Dict[str, Any]] = []
    files_missing: List[str] = []

    for rtl_rel in match.rtl_files:
        src_path = src_dir / rtl_rel
        if not src_path.is_file():
            # Try basename only — manifest paths may differ from local mirror
            # tree layout
            alt = list(src_dir.rglob(Path(rtl_rel).name))
            if alt:
                src_path = alt[0]
            else:
                files_missing.append(rtl_rel)
                continue
        dest_path = dest_dir / Path(rtl_rel).name
        shutil.copy2(src_path, dest_path)
        files_copied.append({
            "rtl_rel": rtl_rel,
            "src": str(src_path),
            "dest": str(dest_path),
            "sha256": _sha256_file(dest_path),
            "size_bytes": dest_path.stat().st_size,
        })

    # 4. Locate license file in source dir (for attribution)
    license_file_text = ""
    for license_name in ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"]:
        lp = src_dir / license_name
        if lp.is_file():
            license_file_text = lp.read_text()[:200]
            break

    audit = {
        "ip_name": match.ip_name,
        "category": match.category,
        "version": match.version,
        "license": match.license,
        "license_file_first_200_chars": license_file_text,
        "canonical_url": match.canonical_url,
        "canonical_commit": match.canonical_commit,
        "pull_method": pull_method,
        "source_dir": str(src_dir),
        "spec_match_pattern": match.matched_pattern,
        "spec_match_confidence": match.confidence,
        "files_copied": files_copied,
        "files_missing": files_missing,
        "n_files_copied": len(files_copied),
        "n_files_missing": len(files_missing),
        "status": "PASS" if files_copied and not files_missing else (
            "PARTIAL" if files_copied else "FAIL"
        ),
        "ran_at_epoch": time.time(),
    }

    # 5. Append provenance.jsonl
    # provenance_output_hash_completeness_check expects each entry to carry an
    # `outputs` dict mapping project-relative path → "sha256:<hex>" (the same
    # shape the in-runner yosys/iverilog provenance entries use). The earlier
    # `outputs_sha256` list form did not satisfy that gate (PROVENANCE_OUTPUTS_
    # MISSING), so we now emit `outputs` as the canonical dict and keep
    # `outputs_sha256` as a backward-compatible alias.
    provenance_path = project / "provenance.jsonl"

    def _rel(dest: str) -> str:
        try:
            return str(Path(dest).resolve().relative_to(project.resolve()))
        except Exception:
            # dest is recorded project-relative already (e.g. "phase2/stage1/rtl/x.v")
            return dest

    outputs_map = {
        _rel(f["dest"]): f"sha256:{f['sha256']}" for f in files_copied
    }
    with provenance_path.open("a") as f:
        f.write(json.dumps({
            "event": "ip_catalog_pull",
            "ip": match.ip_name,
            "version": match.version,
            "license": match.license,
            "commit_pinned": match.canonical_commit,
            "files_pulled": len(files_copied),
            "outputs": outputs_map,
            "outputs_sha256": sorted(f["sha256"] for f in files_copied),
            "ran_at_epoch": time.time(),
        }) + "\n")

    return audit


def _git_clone_to_cache(match: CatalogMatch) -> Optional[Path]:
    """Best-effort clone canonical_url at canonical_commit to a session cache.

    Returns dir path or None on failure. Network-required path; usually
    skipped in favor of local mirrors.
    """
    if not match.canonical_url:
        return None
    cache_dir = Path("/tmp/vibe_ic_catalog_cache") / match.ip_name
    if cache_dir.is_dir():
        return cache_dir
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", match.canonical_url, str(cache_dir)],
            check=True, capture_output=True, timeout=120,
        )
        # Pin to canonical commit if provided
        if match.canonical_commit and match.canonical_commit != "master":
            try:
                subprocess.run(
                    ["git", "-C", str(cache_dir), "checkout", match.canonical_commit],
                    check=True, capture_output=True, timeout=30,
                )
            except Exception:
                pass  # best-effort
        return cache_dir
    except Exception:
        return None


def pull_all_catalog_matches(project: Path,
                              matches: List[CatalogMatch]) -> Dict[str, Any]:
    """Pull every matching IP, return aggregated audit + update declaration.json."""
    audits: List[Dict[str, Any]] = []
    for m in matches:
        audit = pull_catalog_ip(m, project)
        audits.append(audit)

    # Aggregate license set
    spdx_set = sorted({a.get("license", "") for a in audits
                       if a.get("status") in ("PASS", "PARTIAL")})
    all_permissive = all(
        check_license_compatibility(lic)[0] for lic in spdx_set if lic
    )

    aggregated = {
        "rtl_strategy": "catalog_lookup_plus_ai_glue",
        "n_ips_pulled": sum(1 for a in audits if a.get("status") in ("PASS", "PARTIAL")),
        "n_ips_rejected": sum(1 for a in audits if a.get("status") == "REJECTED"),
        "n_ips_failed": sum(1 for a in audits if a.get("status") == "FAIL"),
        "ip_catalog_used": audits,
        "license_compliance_audit": {
            "all_permissive": all_permissive,
            "spdx_set": spdx_set,
        },
    }

    # Merge into project/plugin_output/declaration.json
    decl_path = project / "plugin_output" / "declaration.json"
    decl_path.parent.mkdir(parents=True, exist_ok=True)
    if decl_path.is_file():
        try:
            existing = json.loads(decl_path.read_text())
        except Exception:
            existing = {}
    else:
        existing = {}
    existing.update(aggregated)
    decl_path.write_text(json.dumps(existing, indent=2))

    return aggregated


# ---------------------------------------------------------------------------
def main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Pull catalog IPs for a Plugin project")
    ap.add_argument("project", help="Project root")
    ap.add_argument("--catalog-dir", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="Query + show what would be pulled, don't actually copy")
    ap.add_argument("--min-confidence", type=float, default=0.4)
    args = ap.parse_args(argv)

    project = Path(args.project)
    matches = query_catalog(
        project,
        Path(args.catalog_dir) if args.catalog_dir else None,
        min_confidence=args.min_confidence,
    )

    if not matches:
        print(f"=== no catalog matches for {project.name} ===")
        return 0

    print(f"=== {len(matches)} catalog matches for {project.name} ===")
    for m in matches:
        print(f"  [{m.confidence:.2f}] {m.category}/{m.ip_name} v{m.version} ({m.license})")
        print(f"       matched: {m.matched_pattern}")

    if args.dry_run:
        print("(dry-run — no files copied)")
        return 0

    print()
    aggregated = pull_all_catalog_matches(project, matches)
    print(f"=== pull complete ===")
    print(f"  pulled: {aggregated['n_ips_pulled']}  "
          f"rejected: {aggregated['n_ips_rejected']}  "
          f"failed: {aggregated['n_ips_failed']}")
    print(f"  spdx_set: {aggregated['license_compliance_audit']['spdx_set']}")
    print(f"  all_permissive: {aggregated['license_compliance_audit']['all_permissive']}")
    print(f"  declaration.json updated at {project}/plugin_output/declaration.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
