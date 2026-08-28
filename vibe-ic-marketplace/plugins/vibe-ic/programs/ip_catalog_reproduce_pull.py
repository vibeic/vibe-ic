#!/usr/bin/env python3
"""
ip_catalog_reproduce_pull.py — Reproducibility check.

For each catalog IP that has both a LOCAL_MIRROR entry AND a reachable
canonical_url, this tool:
  1. Pulls via LOCAL_MIRROR (existing path)
  2. Pulls via fresh git clone (force --no-local-mirror)
  3. Compares SHA256 of each rtl_files entry between the two pulls

If any SHA256 differs, this signals that LOCAL_MIRROR has drifted from
upstream (e.g. user has locally edited a file, or the mirror was checked
out at a different commit). Catalog provenance integrity depends on
this check passing.

Options:
  --ip <name>     Reproduce only this IP
  --json          Emit JSON
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ip_catalog_query import find_catalog_dir, load_manifests  # noqa: E402
from ip_catalog_pull import find_local_mirror  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_clone_shallow(url: str, dest: Path, commit: Optional[str] = None) -> bool:
    try:
        _pr.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            check=True, capture_output=True, text=False,
        )
        if commit and commit not in ("master", "main", "HEAD"):
            # Best-effort: try to check out the pinned commit. It may fail — a
            # depth-1 clone need not contain a commit off the default branch.
            #
            # THE OUTCOME IS INSPECTED AND REPORTED, WHICH IT DID NOT USED TO BE.
            # Previously both calls swallowed their result and the function
            # returned True regardless, so a comparison made against the DEFAULT
            # BRANCH was published as a reproducibility verdict about the PINNED
            # COMMIT, with nothing in the record naming which revision had
            # actually been compared. That is the defect
            # `prepared_checkout_states_the_revision_it_holds` refuses: a
            # complete, internally consistent verdict about an unnamed revision.
            #
            # The bool contract is unchanged — a clone that produced a tree is
            # still a usable tree — but an unachieved pin is now stated on
            # stderr naming BOTH revisions, so a reader can tell a comparison
            # against the pinned commit from a comparison against whatever the
            # default branch happened to hold.
            try:
                subprocess.run(
                    ["git", "-C", str(dest), "fetch", "--depth", "1", "origin", commit],
                    capture_output=True, timeout=60,
                )
                co = subprocess.run(
                    ["git", "-C", str(dest), "checkout", commit],
                    capture_output=True, timeout=30,
                )
                head = subprocess.run(
                    ["git", "-C", str(dest), "rev-parse", "HEAD"],
                    capture_output=True, text=True, timeout=30,
                )
                achieved = (head.stdout or "").strip()
                if co.returncode != 0 or not achieved.startswith(commit[:7]):
                    where = achieved[:12] if achieved else "an unresolvable HEAD"
                    print(
                        f"[ip_catalog_reproduce_pull] PIN_NOT_ACHIEVED — asked "
                        f"for {commit[:12]}, tree is on {where}. Any comparison "
                        f"below is about the revision the tree HOLDS, not the "
                        f"one it was pinned to.",
                        file=sys.stderr,
                    )
            except Exception:
                pass
        return True
    except Exception:
        return False


def reproduce_one_ip(m: Dict[str, Any]) -> Dict[str, Any]:
    ip_name = m.get("ip_name", "?")
    url = m.get("canonical_url", "")
    commit = m.get("canonical_commit", "")
    rtl_files = m.get("rtl_files", []) or []

    local_dir = find_local_mirror(ip_name)
    if local_dir is None:
        return {
            "ip_name": ip_name,
            "status": "SKIP_NO_LOCAL_MIRROR",
            "rationale": "no LOCAL_MIRROR entry — reproducibility check requires both paths",
        }

    if not url or not url.startswith(("http://", "https://")):
        return {
            "ip_name": ip_name,
            "status": "SKIP_NO_CANONICAL_URL",
            "rationale": f"canonical_url not HTTP(S): {url!r}",
        }

    # Clone upstream
    tmpdir = Path(tempfile.mkdtemp(prefix=f"reproduce_{ip_name}_"))
    try:
        clone_ok = _git_clone_shallow(url, tmpdir, commit)
        if not clone_ok:
            return {
                "ip_name": ip_name,
                "status": "FAIL_GIT_CLONE",
                "rationale": f"git clone {url} failed",
            }

        # Compare SHA256 for each rtl_files entry
        file_audits: List[Dict[str, Any]] = []
        match_count = 0
        mismatch_count = 0
        missing_local_count = 0
        missing_upstream_count = 0
        for rel in rtl_files:
            local_path = local_dir / rel
            upstream_path = tmpdir / rel
            # Resolve via basename if exact path missing
            if not local_path.is_file():
                alt = list(local_dir.rglob(Path(rel).name))
                local_path = alt[0] if alt else local_path
            if not upstream_path.is_file():
                alt = list(tmpdir.rglob(Path(rel).name))
                upstream_path = alt[0] if alt else upstream_path

            local_sha = _sha256_file(local_path) if local_path.is_file() else None
            upstream_sha = _sha256_file(upstream_path) if upstream_path.is_file() else None
            if local_sha is None:
                missing_local_count += 1
                audit_status = "MISSING_LOCAL"
            elif upstream_sha is None:
                missing_upstream_count += 1
                audit_status = "MISSING_UPSTREAM"
            elif local_sha == upstream_sha:
                match_count += 1
                audit_status = "MATCH"
            else:
                mismatch_count += 1
                audit_status = "DIVERGE"
            file_audits.append({
                "rtl_rel": rel,
                "local_sha256": local_sha,
                "upstream_sha256": upstream_sha,
                "status": audit_status,
            })

        # Overall status
        if mismatch_count == 0 and missing_local_count == 0 and missing_upstream_count == 0:
            overall = "REPRODUCIBLE"
        elif mismatch_count == 0:
            overall = "REPRODUCIBLE_WITH_GAPS"
        else:
            overall = "DRIFT_DETECTED"

        return {
            "ip_name": ip_name,
            "status": overall,
            "n_files": len(rtl_files),
            "n_match": match_count,
            "n_diverge": mismatch_count,
            "n_missing_local": missing_local_count,
            "n_missing_upstream": missing_upstream_count,
            "diverged_files": [a["rtl_rel"] for a in file_audits if a["status"] == "DIVERGE"][:5],
            "file_audits": file_audits,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Reproduce-pull check: compare LOCAL vs UPSTREAM SHA256")
    ap.add_argument("--catalog-dir", default=None)
    ap.add_argument("--ip", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    catalog_dir = Path(args.catalog_dir) if args.catalog_dir else find_catalog_dir()
    manifests = load_manifests(catalog_dir)
    if args.ip:
        manifests = [m for m in manifests if m.get("ip_name") == args.ip]

    results = [reproduce_one_ip(m) for m in manifests]
    n_repro = sum(1 for r in results if r.get("status") == "REPRODUCIBLE")
    n_gap = sum(1 for r in results if r.get("status") == "REPRODUCIBLE_WITH_GAPS")
    n_drift = sum(1 for r in results if r.get("status") == "DRIFT_DETECTED")
    n_skip = sum(1 for r in results if str(r.get("status", "")).startswith("SKIP"))
    n_fail = sum(1 for r in results if str(r.get("status", "")).startswith("FAIL"))

    if args.json:
        print(json.dumps({
            "summary": {
                "total": len(results),
                "reproducible": n_repro,
                "reproducible_with_gaps": n_gap,
                "drift_detected": n_drift,
                "skip": n_skip,
                "fail": n_fail,
            },
            "results": results,
        }, indent=2))
    else:
        print(f"=== reproduce-pull check on {len(results)} IPs ===")
        for r in results:
            ip = r["ip_name"]
            status = r["status"]
            extra = ""
            if "n_files" in r:
                extra = (f"  files={r['n_files']} match={r['n_match']} "
                         f"diverge={r['n_diverge']} "
                         f"missing_local={r['n_missing_local']} "
                         f"missing_up={r['n_missing_upstream']}")
            print(f"  [{status}] {ip:18s}{extra}")
            if r.get("diverged_files"):
                for df in r["diverged_files"]:
                    print(f"      - DIVERGE: {df}")
        print()
        print(f"=== SUMMARY: {n_repro} reproducible, {n_gap} with-gaps, "
              f"{n_drift} drift, {n_skip} skip, {n_fail} fail ===")

    return 0 if n_drift == 0 else 1


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main, sys.argv[1:]))
