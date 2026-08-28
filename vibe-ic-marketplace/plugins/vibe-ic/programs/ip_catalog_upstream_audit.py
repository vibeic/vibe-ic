#!/usr/bin/env python3
"""
ip_catalog_upstream_audit.py — Verify catalog manifests against canonical
upstream repos.

Hygiene 1 check:
  1. canonical_url is reachable (HTTP HEAD; or git ls-remote)
  2. canonical_commit exists on canonical_url (git ls-remote --refs)
  3. Each rtl_files path exists in upstream at canonical_commit
     (shallow git clone + ls)
  4. license SPDX claimed in manifest matches upstream LICENSE/COPYING
     (best-effort header parse)

Output: JSON audit dict + human-readable summary.

Options:
  --no-network    Skip steps 1-3 (only do LICENSE header parse if local
                  mirror exists)
  --local-mirror-only  Validate against LOCAL_MIRROR_MAP path only
  --ip <name>     Audit only this IP (default: all)
  --json          Emit JSON
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ip_catalog_query import find_catalog_dir, load_manifests  # noqa: E402
from ip_catalog_pull import LOCAL_MIRROR_ROOTS, LOCAL_MIRROR_MAP, find_local_mirror  # noqa: E402
# THE CONTENT HALF OF THIS AUDIT'S OWN QUESTION.
# The docstring above promises "each rtl_files path EXISTS in upstream at
# canonical_commit", and existence is where the check stopped: a mirror file
# edited byte-for-byte still exists, so the audit passed a tree that no longer
# reproduces. `ip_catalog_reproduce_pull` is the program that answers the other
# half — SHA256 of every rtl_files entry, mirror against a fresh clone — and it
# was authored, tested and merged and then reached by nothing at all.
#
# WIRED HERE AND NOT ON THE LANDING LANE, for the same reason this module is
# not on it: its two inputs are the developer's LOCAL MIRROR (~/ic_documents,
# not in this repository) and the network. It is the NETWORK arm that pays for
# it, and this module's `--no-network` arm — the one `ip_catalog_pull` calls on
# every design pull — never reaches it, so a design run costs nothing.
from ip_catalog_reproduce_pull import reproduce_one_ip  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402


# License keyword → SPDX inference
LICENSE_KEYWORDS = [
    # v1.6.587 — expanded SPDX coverage. Order matters: strict header
    # matches first, then body-content fallback, then variant patterns.
    # ----- Strict header matches -----
    (r"ISC License\b", "ISC"),
    (r"MIT License\b", "MIT"),
    (r"BSD 2-Clause License\b", "BSD-2-Clause"),
    (r"BSD-2-Clause License\b", "BSD-2-Clause"),
    (r"BSD 3-Clause License\b", "BSD-3-Clause"),
    (r"BSD-3-Clause License\b", "BSD-3-Clause"),
    (r"Apache License,?\s*Version\s*2\.0", "Apache-2.0"),
    (r"Mozilla Public License Version 2\.0", "MPL-2.0"),
    (r"GNU LESSER GENERAL PUBLIC LICENSE", "LGPL"),
    (r"GNU GENERAL PUBLIC LICENSE", "GPL"),
    (r"GNU AFFERO GENERAL PUBLIC LICENSE", "AGPL"),
    (r"SOLDERPAD HARDWARE LICENSE.*0\.51", "Solderpad-0.51"),
    (r"CC0 1\.0 Universal", "CC0-1.0"),
    (r"Creative Commons Zero v1\.0 Universal", "CC0-1.0"),
    (r"Creative Commons Attribution[- ]ShareAlike", "CC-BY-SA"),
    (r"Creative Commons Attribution[- ]NonCommercial", "CC-BY-NC"),
    (r"CERN.*Open Hardware Licence.*Version 2.*[Pp]ermissive", "CERN-OHL-P-2.0"),
    (r"CERN.*Open Hardware Licence.*Version 2.*[Ww]eakly", "CERN-OHL-W-2.0"),
    (r"CERN.*Open Hardware Licence.*Version 2.*[Ss]trongly", "CERN-OHL-S-2.0"),
    # ----- SPDX inline markers (from source-file headers) -----
    (r"SPDX-License-Identifier:\s*ISC\b", "ISC"),
    (r"SPDX-License-Identifier:\s*MIT\b", "MIT"),
    (r"SPDX-License-Identifier:\s*BSD-2-Clause\b", "BSD-2-Clause"),
    (r"SPDX-License-Identifier:\s*BSD-3-Clause\b", "BSD-3-Clause"),
    (r"SPDX-License-Identifier:\s*Apache-2\.0\b", "Apache-2.0"),
    (r"SPDX-License-Identifier:\s*CC0-1\.0\b", "CC0-1.0"),
    (r"SPDX-License-Identifier:\s*MPL-2\.0\b", "MPL-2.0"),
    (r"SPDX-License-Identifier:\s*GPL", "GPL"),
    (r"SPDX-License-Identifier:\s*LGPL", "LGPL"),
    (r"SPDX-License-Identifier:\s*AGPL", "AGPL"),
    # ----- Body-content infer when header missing -----
    (r"permission to use, copy, modify,? and/or distribute", "ISC"),
    (r"permission is hereby granted.*free of charge", "MIT"),
    (r"This Source Code Form is subject to the terms of the Mozilla Public License",
     "MPL-2.0"),
    # secworks-style BSD-2-Clause (no explicit header, just boilerplate)
    (r"copyright\s*\(c\)\s*\d{4}.*All rights reserved\..*Redistribution and use in source and binary forms",
     "BSD-2-Clause"),
    (r"copyright\s*\(c\)\s*\d{4}.*Redistribution and use in source and binary forms.*"
     r"Redistributions in binary form must reproduce the above copyright notice",
     "BSD-2-Clause"),
    # BSD-3-Clause (matches 'Neither the name of...' third clause)
    (r"Redistribution and use in source and binary forms.*"
     r"Neither the name of.*nor the names of its contributors",
     "BSD-3-Clause"),
    # Usselmann legacy header (no separate LICENSE file; license in each .v).
    # The .v files use //// ... //// comment padding which means up to
    # ~30 chars of whitespace + slashes between words.
    (r"may be used and distributed without\W{1,30}restriction\W{1,30}provided\W{1,30}that\W{1,30}this\W{1,30}copyright\W{1,30}statement",
     "Usselmann-Permissive"),
    # Unlicense
    (r"\bunlicense\b.*free and unencumbered software", "Unlicense"),
    (r"This is free and unencumbered software released into the public domain",
     "Unlicense"),
]


def infer_spdx_from_text(text: str) -> Optional[str]:
    text_excerpt = text[:5000]  # only check first ~5KB
    for pattern, spdx in LICENSE_KEYWORDS:
        if re.search(pattern, text_excerpt, re.IGNORECASE | re.DOTALL):
            return spdx
    return None


def _read_fpu_header_for_license(repo_root: Path) -> Optional[str]:
    """Usselmann-style IPs put license in each .v header, not a LICENSE file.
    Check first ~5 .v files because some repos lead with sub-modules.
    """
    checked = 0
    for v in repo_root.rglob("*.v"):
        try:
            with v.open() as f:
                head = f.read(3000)
            if re.search(r"may be used and distributed without\s*restriction provided that this copyright statement",
                         head, re.IGNORECASE | re.DOTALL):
                return "Usselmann-Permissive"
            # Other common SPDX inference patterns from file headers
            inferred = infer_spdx_from_text(head)
            if inferred:
                return inferred
        except Exception:
            pass
        checked += 1
        if checked >= 5:
            break
    return None


def find_license_file(repo_root: Path) -> Optional[Path]:
    for name in ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "COPYING.md", "LICENSE-2.0"]:
        p = repo_root / name
        if p.is_file():
            return p
    return None


def audit_local_files(m: Dict[str, Any]) -> Dict[str, Any]:
    """Verify rtl_files exist in LOCAL_MIRROR + check LICENSE matches."""
    ip_name = m.get("ip_name", "?")

    src_dir = find_local_mirror(ip_name)
    if src_dir is None:
        return {
            "ip_name": ip_name,
            "ok": False,
            "stage": "local_mirror",
            "issue": f"no local mirror found in {LOCAL_MIRROR_ROOTS}",
        }
    return audit_against_mirror(m, src_dir)


def audit_against_mirror(m: Dict[str, Any], src_dir: Path) -> Dict[str, Any]:
    """The same audit against a mirror the CALLER already resolved.

    Split out so `ip_catalog_pull.pull_catalog_ip` can ask this question about
    the very directory it is copying from. Re-resolving the mirror here would
    let the pull copy out of one tree while the audit judged another: the pull
    selects with `find_local_mirror(ip_name, rtl_files)` — content-gated on the
    manifest's own file list (ORGANIC #665) — and this module's own caller
    selects without it, so the two can legitimately land on different dirs for
    the same IP.
    """
    ip_name = m.get("ip_name", "?")
    claimed_lic = m.get("license", "?")
    rtl_files = m.get("rtl_files", []) or []
    issues: List[str] = []

    # 1. rtl_files existence
    files_present = []
    files_missing = []
    for rel in rtl_files:
        if (src_dir / rel).is_file():
            files_present.append(rel)
        else:
            # try basename fallback (some manifests use upstream-tree path
            # that differs from local mirror layout)
            alt = list(src_dir.rglob(Path(rel).name))
            if alt:
                files_present.append(f"{rel} (matched via basename: {alt[0]})")
            else:
                files_missing.append(rel)

    # 2. LICENSE SPDX inference
    lic_file = find_license_file(src_dir)
    license_check: Dict[str, Any] = {
        "claimed": claimed_lic,
        "file_found": str(lic_file) if lic_file else None,
        "inferred": None,
        "match": None,
    }
    inferred: Optional[str] = None
    if lic_file:
        try:
            text = lic_file.read_text(errors="ignore")
            inferred = infer_spdx_from_text(text)
        except Exception as e:
            license_check["match"] = f"read_error: {e}"
    else:
        # No LICENSE file — try header inference (Usselmann-style IPs put
        # license in each .v file header)
        inferred = _read_fpu_header_for_license(src_dir)
        if inferred is None:
            license_check["match"] = "no_license_file_or_header"
            issues.append(f"no LICENSE / COPYING file nor recognizable header in {src_dir}")

    if inferred is not None:
        license_check["inferred"] = inferred
        if inferred == claimed_lic:
            license_check["match"] = True
        else:
            license_check["match"] = False
            issues.append(
                f"license mismatch: manifest claims {claimed_lic!r}, "
                f"upstream content appears to be {inferred!r}"
            )
    elif lic_file:
        license_check["match"] = "unable_to_infer"

    if files_missing:
        issues.append(f"{len(files_missing)} rtl_files missing in mirror: {files_missing[:3]}...")

    return {
        "ip_name": ip_name,
        "ok": not issues,
        "stage": "local_mirror_audit",
        "src_dir": str(src_dir),
        "license_check": license_check,
        "files_present_count": len(files_present),
        "files_missing_count": len(files_missing),
        "files_missing_sample": files_missing[:5],
        "issues": issues,
    }


def audit_upstream(m: Dict[str, Any]) -> Dict[str, Any]:
    """Network audit: ls-remote canonical_url + check canonical_commit + rtl_files."""
    ip_name = m.get("ip_name", "?")
    url = m.get("canonical_url", "")
    commit = m.get("canonical_commit", "")
    rtl_files = m.get("rtl_files", []) or []
    issues: List[str] = []

    if not url or not url.startswith(("http://", "https://")):
        return {
            "ip_name": ip_name,
            "ok": False,
            "stage": "upstream",
            "issue": f"canonical_url not HTTP(S): {url!r}",
        }

    # 1. ls-remote — fast reachability test
    try:
        cp = subprocess.run(
            ["git", "ls-remote", "--heads", "--tags", url],
            capture_output=True, text=True, timeout=30,
        )
        if cp.returncode != 0:
            return {
                "ip_name": ip_name,
                "ok": False,
                "stage": "upstream_ls_remote",
                "issue": f"git ls-remote failed (rc={cp.returncode}): {cp.stderr[:200]}",
            }
        refs = cp.stdout
    except subprocess.TimeoutExpired:
        return {
            "ip_name": ip_name, "ok": False, "stage": "upstream_timeout",
            "issue": "git ls-remote timed out (30s)",
        }
    except FileNotFoundError:
        return {
            "ip_name": ip_name, "ok": False, "stage": "git_not_installed",
            "issue": "git command not found on host",
        }

    # 2. canonical_commit existence
    commit_found = False
    if commit and commit not in ("master", "main", "HEAD"):
        # Try to find this commit/tag/branch in ls-remote output
        if commit in refs:
            commit_found = True
        else:
            # Best-effort: search for exact substring (SHA prefix match)
            if any(commit in line.split()[0] if line.split() else False
                   for line in refs.split("\n")):
                commit_found = True
    else:
        # commit pinned to "master" / "main" — verify branch exists
        if "refs/heads/master" in refs or "refs/heads/main" in refs:
            commit_found = True

    if not commit_found and commit not in ("master", "main", "HEAD"):
        issues.append(f"canonical_commit {commit!r} not found in ls-remote output")

    # 3. Shallow clone + rtl_files existence
    files_audit: Dict[str, Any] = {"clone_ok": False, "files_present": 0, "files_missing": 0,
                                    "files_missing_sample": []}
    tmpdir = tempfile.mkdtemp(prefix=f"catalog_audit_{ip_name}_")
    try:
        cp = _pr.run(
            ["git", "clone", "--depth", "1", url, tmpdir],
            capture_output=True, text=True)
        if cp.returncode != 0:
            issues.append(f"git clone failed (rc={cp.returncode}): {cp.stderr[:200]}")
        else:
            files_audit["clone_ok"] = True
            present = []
            missing = []
            for rel in rtl_files:
                if (Path(tmpdir) / rel).is_file():
                    present.append(rel)
                else:
                    missing.append(rel)
            files_audit["files_present"] = len(present)
            files_audit["files_missing"] = len(missing)
            files_audit["files_missing_sample"] = missing[:5]
            if missing:
                issues.append(f"{len(missing)} rtl_files missing in upstream: {missing[:3]}")

            # License check from upstream
            lic_file = find_license_file(Path(tmpdir))
            if lic_file:
                try:
                    text = lic_file.read_text(errors="ignore")
                    inferred = infer_spdx_from_text(text)
                    claimed = m.get("license", "")
                    files_audit["upstream_license_inferred"] = inferred
                    files_audit["upstream_license_match"] = (inferred == claimed)
                    if inferred and inferred != claimed:
                        issues.append(
                            f"upstream LICENSE inferred as {inferred!r} "
                            f"but manifest claims {claimed!r}"
                        )
                except Exception:
                    pass
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # CONTENT, not merely presence. `reproduce_one_ip` clones upstream a second
    # time and compares the SHA256 of every `rtl_files` entry against the local
    # mirror's copy. Its SKIP statuses are not findings — with no mirror, or no
    # HTTP(S) canonical_url, there is no pair to compare and it says so — but a
    # DRIFT_DETECTED names files the catalog claims come from upstream and that
    # upstream does not have, which is precisely what this stage exists to
    # refuse. Recorded whatever it says, so a reader can tell "compared and
    # identical" from "never compared".
    reproduce = reproduce_one_ip(m)
    if reproduce.get("status") == "DRIFT_DETECTED":
        issues.append(
            f"{reproduce.get('n_diverge')} rtl_file(s) DIVERGE between the "
            f"local mirror and upstream: {reproduce.get('diverged_files')}")

    return {
        "ip_name": ip_name,
        "ok": not issues,
        "stage": "upstream",
        "canonical_url": url,
        "canonical_commit": commit,
        "commit_found_in_refs": commit_found,
        "files_audit": files_audit,
        "reproduce": reproduce,
        "issues": issues,
    }


def main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Audit ip-catalog manifests against upstream + local mirror")
    ap.add_argument("--catalog-dir", default=None)
    ap.add_argument("--no-network", action="store_true",
                    help="Skip upstream network calls (local-mirror only)")
    ap.add_argument("--local-mirror-only", action="store_true",
                    help="Same as --no-network")
    ap.add_argument("--ip", default=None, help="Audit only this IP")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    catalog_dir = Path(args.catalog_dir) if args.catalog_dir else find_catalog_dir()
    manifests = load_manifests(catalog_dir)
    if args.ip:
        manifests = [m for m in manifests if m.get("ip_name") == args.ip]

    skip_network = args.no_network or args.local_mirror_only

    if not manifests:
        # A verdict about a catalog nobody opened is not a verdict. Without
        # this the summary reads `0/0 local PASS` and the process exits 0 —
        # the zero-denominator pass this repo refuses everywhere else.
        print(f"ERROR: 0 manifest(s) found under {catalog_dir} — an audit over "
              f"an empty catalog is not a pass", file=sys.stderr)
        return 2

    results: List[Dict[str, Any]] = []
    for m in manifests:
        local = audit_local_files(m)
        if skip_network:
            results.append({"ip_name": m.get("ip_name"), "local": local, "upstream": None})
        else:
            up = audit_upstream(m)
            results.append({"ip_name": m.get("ip_name"), "local": local, "upstream": up})

    n_pass_local = sum(1 for r in results if r["local"].get("ok"))
    n_pass_up = sum(1 for r in results if r.get("upstream") and r["upstream"].get("ok"))

    if args.json:
        print(json.dumps({
            "summary": {
                "total": len(results),
                "local_pass": n_pass_local,
                "upstream_pass": n_pass_up,
                "skip_network": skip_network,
            },
            "results": results,
        }, indent=2))
    else:
        print(f"=== ip-catalog upstream audit ({len(results)} IPs) ===")
        for r in results:
            ip = r["ip_name"]
            loc = r["local"]
            loc_mark = "PASS" if loc.get("ok") else "FAIL"
            print(f"\n[{loc_mark} local] {ip}")
            lc = loc.get("license_check", {})
            print(f"    license: claimed={lc.get('claimed')} inferred={lc.get('inferred')} match={lc.get('match')}")
            print(f"    files: {loc.get('files_present_count')} present / {loc.get('files_missing_count')} missing")
            for issue in loc.get("issues", [])[:3]:
                print(f"    - {issue}")
            if not skip_network and r.get("upstream"):
                up = r["upstream"]
                up_mark = "PASS" if up.get("ok") else "FAIL"
                print(f"  [{up_mark} upstream] {up.get('canonical_url')}")
                fa = up.get("files_audit", {})
                print(f"    clone_ok={fa.get('clone_ok')}, files {fa.get('files_present')} present / {fa.get('files_missing')} missing")
                if fa.get("upstream_license_inferred"):
                    print(f"    upstream license inferred: {fa.get('upstream_license_inferred')} (match={fa.get('upstream_license_match')})")
                for issue in up.get("issues", [])[:3]:
                    print(f"    - {issue}")
        print()
        print(f"=== SUMMARY: {n_pass_local}/{len(results)} local PASS, {n_pass_up}/{len(results)} upstream PASS (skip_network={skip_network}) ===")

    # THE VERDICT REACHES THE EXIT CODE. Until this line the program printed
    # `[FAIL local] <ip>` beside a mismatched licence and returned 0, so every
    # caller that reads a status — which is every automatic one — was told the
    # catalog was clean. The findings were in the OUTPUT and the aggregation
    # reads the CODE; that is the exact substitution
    # `gate_zero_denominator_refuses_check` was written about one case over.
    if n_pass_local != len(results):
        return 1
    if not skip_network and n_pass_up != len(results):
        return 1
    return 0


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main, sys.argv[1:]))
