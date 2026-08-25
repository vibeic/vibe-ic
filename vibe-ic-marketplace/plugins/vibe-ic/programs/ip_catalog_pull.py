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


def _ip_mirror_root() -> Optional[Path]:
    """v1.0: the bundled top-level IP/ submodule mirror, categorized as
    IP/<category>/<core>. Resolve the nearest ancestor that holds IP/."""
    for anc in Path(__file__).resolve().parents:
        cand = anc / "IP"
        if cand.is_dir():
            return cand
    return None


IP_MIRROR_ROOT = _ip_mirror_root()


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
# RTL source extensions used to decide whether a candidate mirror dir is
# actually populated. Structural — no chip/vendor/IP-name literal.
_RTL_SOURCE_EXTS = (".v", ".sv", ".vhd", ".vhdl", ".vh", ".svh")


def _dir_has_rtl(cand: Path,
                 rtl_files: Optional[List[str]] = None) -> bool:
    """Return True iff `cand` is a populated mirror that actually holds RTL.

    A bundled git submodule that has never been initialized leaves a bare
    directory on disk that passes ``is_dir()`` but contains zero source
    files. Selecting it short-circuits the populated fallback mirrors and
    makes every manifest rtl_file land in files_missing → status FAIL.

    Acceptance rule (structural, chip-AGNOSTIC):
      1. If the manifest lists rtl_files, accept only when at least one of
         them resolves under `cand` (direct path OR basename rglob match) —
         the same resolution pull_catalog_ip() uses to copy them.
      2. Otherwise (no manifest hint), accept only when `cand` contains at
         least one RTL source file (``*.v`` / ``*.sv`` / ``*.vhd`` / …)
         anywhere in its tree.
    An un-initialized / empty submodule dir satisfies neither and is
    rejected so the fallback chain continues to a populated mirror.
    """
    if not cand.is_dir():
        return False
    if rtl_files:
        for rtl_rel in rtl_files:
            if (cand / rtl_rel).is_file():
                return True
            # basename rglob — manifest paths may differ from the mirror tree
            if list(cand.rglob(Path(rtl_rel).name)):
                return True
        return False
    for ext in _RTL_SOURCE_EXTS:
        if next(cand.rglob(f"*{ext}"), None) is not None:
            return True
    return False


def find_local_mirror(ip_name: str,
                      rtl_files: Optional[List[str]] = None) -> Optional[Path]:
    """Return path to a POPULATED local mirror dir if present, else None.

    v1.0: prefer the bundled top-level IP/ submodule mirror (categorized,
    IP/<category>/<core>), matched by leaf name; then the legacy flat
    ~/ic_documents mirrors.

    A candidate dir is accepted only if it actually contains RTL
    (``_dir_has_rtl``). An empty / un-initialized bundled submodule dir is
    skipped so the fallback chain falls through to a populated mirror —
    never selecting a dir with no RTL content (ORGANIC #665, field agent
    round-4 v1.0.42 adversarial verify)."""
    candidate_names = LOCAL_MIRROR_MAP.get(ip_name, [ip_name])
    if IP_MIRROR_ROOT and IP_MIRROR_ROOT.is_dir():
        leaves = [n.split("/")[-1] for n in (candidate_names + [ip_name])]
        for leaf in leaves:
            for cand in sorted(IP_MIRROR_ROOT.glob(f"*/{leaf}")):
                if _dir_has_rtl(cand, rtl_files):
                    return cand
    for root in LOCAL_MIRROR_ROOTS:
        for name in candidate_names:
            # ORGANIC #665 round-2 — LOCAL_MIRROR_ROOTS carry a literal `~`
            # (`Path("~/ic_documents/...")`); without expanduser() a `~`-rooted
            # candidate NEVER resolves (`Path('~/ic_documents/open_ic/serv')`
            # .is_dir() is always False), so the populated home-dir fallback the
            # #665 round-1 content-gate was meant to fall THROUGH to stayed
            # unreachable and the catalog-glue RTL pull still FAILed. Expand the
            # user home so the real mirror is found. chip-AGNOSTIC.
            p = (root / name).expanduser()
            if _dir_has_rtl(p, rtl_files):
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
    # 0. #187 self-match guard (defense-in-depth). query_catalog already refuses
    #    a self-match by default, but a caller that hand-builds a CatalogMatch (or
    #    passes allow_self_match) must not silently pull the IC's OWN reference
    #    design — that hands back the answer key (§4.05). A flagged self-match is
    #    REJECTED here too.
    if getattr(match, "self_match", False):
        return {
            "ip_name": match.ip_name,
            "status": "REJECTED",
            "reason": (match.self_match_reason
                       or "catalog entry supplies the IC-under-test's own design "
                          "(#187 benchmark integrity) — refused"),
        }

    # 1. License compliance gate
    ok, rationale = check_license_compatibility(match.license)
    if not ok:
        return {
            "ip_name": match.ip_name,
            "status": "REJECTED",
            "reason": rationale,
        }

    # 2. Locate source — require the mirror to actually hold this manifest's
    #    RTL (an empty/un-initialized submodule dir must not short-circuit a
    #    populated fallback mirror; ORGANIC #665).
    src_dir = find_local_mirror(match.ip_name, match.rtl_files)
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

    # 3b. AUDIT THE MIRROR THE FILES CAME OUT OF, before the provenance line
    #     claims anything about them. `audit_against_mirror` re-derives the SPDX
    #     identifier from the mirror's own LICENSE/COPYING (or, for the
    #     Usselmann-style cores, from a .v header) and compares it against what
    #     the manifest CLAIMS, and it reports which of `rtl_files` the mirror
    #     actually holds.
    #
    #     Only on the local-mirror path. A `git_clone` fallback tree is a fresh
    #     checkout of the canonical_url the manifest itself names, so the audit
    #     would be comparing the manifest against its own source of truth; the
    #     drift this catches is a MIRROR that stopped matching the claim.
    #
    #     A definite license MISMATCH REJECTS the pull. That is the one finding
    #     that must not become an advisory note: the whole point of
    #     `check_license_compatibility` above is that no copyleft RTL enters a
    #     design, and it decides on the manifest's WORD. If the vendored tree
    #     carries a different licence, that word has already been shown to be
    #     wrong, and copying the files anyway would put the design under a
    #     licence nobody checked. Missing files and an un-inferrable licence are
    #     recorded in the audit dict and in provenance, not refused — the copy
    #     step below already reports missing files as PARTIAL/FAIL.
    #     IMPORTED HERE AND NOT AT MODULE SCOPE, and it is not a style choice:
    #     `ip_catalog_upstream_audit` imports LOCAL_MIRROR_ROOTS /
    #     LOCAL_MIRROR_MAP / find_local_mirror from THIS module, so a top-level
    #     import is a cycle that fails at interpreter start.
    from ip_catalog_upstream_audit import audit_against_mirror

    mirror_audit = None
    if pull_method == "local_mirror":
        mirror_audit = audit_against_mirror(
            {"ip_name": match.ip_name, "license": match.license,
             "rtl_files": match.rtl_files}, src_dir)
        if mirror_audit.get("license_check", {}).get("match") is False:
            return {
                "ip_name": match.ip_name,
                "status": "REJECTED",
                "reason": (
                    f"local mirror contradicts the manifest's licence claim: "
                    f"{'; '.join(mirror_audit.get('issues', []))}"),
                "local_mirror_audit": mirror_audit,
            }

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
        "local_mirror_audit": mirror_audit,
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
            "license_verified_against_mirror": (
                None if mirror_audit is None
                else mirror_audit.get("license_check", {}).get("match")),
            "files_pulled": len(files_copied),
            "outputs": outputs_map,
            "outputs_sha256": sorted(f["sha256"] for f in files_copied),
            "ran_at_epoch": time.time(),
        }) + "\n")

    return audit


def _read_provenance_entries(project: Path) -> List[Dict[str, Any]]:
    """Read all provenance.jsonl entries (best-effort, skip bad lines)."""
    prov = project / "provenance.jsonl"
    out: List[Dict[str, Any]] = []
    if not prov.is_file():
        return out
    for raw in prov.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def prune_catalog_ip(project: Path, ip_name: str,
                     reason: str = "superseded",
                     superseded_by: str = "") -> Dict[str, Any]:
    """Cleanly prune / supersede a previously-pulled catalog IP.

    Removes every output file the IP's most-recent `ip_catalog_pull`
    provenance entry recorded, then APPENDS a removal-shaped provenance
    entry (event=ip_catalog_prune, op=remove) referencing the original
    entry's outputs in a `removed` list — instead of leaving a dangling
    pull entry whose files no longer exist on disk (the OLD failure mode
    that made provenance_output_hash_completeness_check FAIL with
    PROVENANCE_OUTPUT_FILE_MISSING).

    The prune entry carries empty `outputs` (it produces no artefact) but
    a non-empty `removed` list, so the provenance gate's removal-event
    shape accepts it.

    Returns an audit dict.
    """
    entries = _read_provenance_entries(project)
    # Find the most-recent pull entry for this IP that still references
    # outputs we can prune.
    target: Optional[Dict[str, Any]] = None
    for e in entries:
        if e.get("event") == "ip_catalog_pull" and e.get("ip") == ip_name:
            target = e  # keep iterating → last one wins
    if target is None:
        return {
            "ip_name": ip_name,
            "status": "FAIL",
            "reason": f"no ip_catalog_pull provenance entry found for "
                      f"{ip_name!r}; nothing to prune",
        }

    outputs = target.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        return {
            "ip_name": ip_name,
            "status": "FAIL",
            "reason": f"pull entry for {ip_name!r} declares no outputs to prune",
        }

    removed: List[Dict[str, Any]] = []
    not_found: List[str] = []
    for rel_path, sha in outputs.items():
        on_disk = project / rel_path
        if on_disk.is_file():
            try:
                on_disk.unlink()
            except OSError as exc:
                not_found.append(f"{rel_path} (unlink failed: {exc})")
                continue
        else:
            not_found.append(rel_path)
        removed.append({"path": rel_path, "sha256": sha})

    # Append the removal-shaped provenance entry.
    prov_path = project / "provenance.jsonl"
    prune_entry = {
        "event": "ip_catalog_prune",
        "op": "remove",
        "ip": ip_name,
        "reason": reason,
        "superseded_by": superseded_by,
        # Empty outputs (this event produces nothing) but a non-empty
        # `removed` list referencing the original entry's artefacts.
        "outputs": {},
        "removed": [r["path"] for r in removed],
        "removed_outputs": removed,
        "supersedes_event": "ip_catalog_pull",
        "ran_at_epoch": time.time(),
    }
    with prov_path.open("a") as f:
        f.write(json.dumps(prune_entry) + "\n")

    return {
        "ip_name": ip_name,
        "status": "PASS" if removed else "FAIL",
        "n_removed": len(removed),
        "removed": [r["path"] for r in removed],
        "not_found_on_disk": not_found,
        "reason": reason,
        "superseded_by": superseded_by,
    }


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

    # ORGANIC #711 — ALSO emit phase2/stage1/rtl/SOURCE_MANIFEST.json{reused_ip}
    # at pull time. l9_rtl_pin_consistency_check + flow_compliance read THIS
    # file (NOT declaration.json) to enable their reused-IP relaxations; pre-#711
    # NO program wrote it, so on every catalog-glue SoC the relaxations were dead
    # code and the pin gate hard-FAILed or forced a per-run waiver. The reused_ip
    # flag + ip_list are the keystone the relaxations key on. Emitted ONLY when
    # ≥1 IP was actually pulled (honest signal of catalog integration). MERGE-
    # preserving: never clobber a hand-authored manifest's tie_offs /
    # flattened_buses / wrapper_exposed_outputs / renamed_interfaces declarations.
    # chip-AGNOSTIC: structure only, no chip/vendor literal.
    ip_list = sorted({a.get("ip_name") for a in audits
                      if a.get("status") in ("PASS", "PARTIAL")
                      and a.get("ip_name")})
    if ip_list:
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
        mf["reused_ip"] = True
        mf["ip_list"] = ip_list
        mf["rtl_strategy"] = "catalog_lookup_plus_ai_glue"
        mf.setdefault("generated_by", "ip_catalog_pull")
        manifest_path.write_text(json.dumps(mf, indent=2))

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
    ap.add_argument("--ic-name", default=None,
                    help="IC-under-test name (strengthens the #187 self-match "
                         "guard; L1/L3/L9 identity is used when omitted)")
    ap.add_argument("--allow-self-match", action="store_true",
                    help="Do NOT refuse a catalog entry that supplies the IC's "
                         "OWN design (#187 — requires explicit acknowledgement)")
    ap.add_argument("--prune", metavar="IP_NAME", default=None,
                    help="Cleanly prune/supersede a previously-pulled IP: "
                         "remove its pulled files and record a removal "
                         "(ip_catalog_prune) provenance entry referencing "
                         "the original outputs (no dangling pull entry).")
    ap.add_argument("--reason", default="superseded",
                    help="Reason recorded in the prune provenance entry "
                         "(default: 'superseded').")
    ap.add_argument("--superseded-by", default="",
                    help="Name of the IP/entry that supersedes the pruned "
                         "one (recorded in the prune provenance entry).")
    args = ap.parse_args(argv)

    project = Path(args.project)

    # Prune / supersede path — record the removal instead of leaving a
    # dangling pull entry.
    if args.prune:
        if not project.is_dir():
            print(f"ERROR: project dir not found: {project}", file=sys.stderr)
            return 2
        audit = prune_catalog_ip(
            project, args.prune,
            reason=args.reason, superseded_by=args.superseded_by)
        if audit["status"] != "PASS":
            print(f"=== prune FAILED for {args.prune}: {audit['reason']} ===",
                  file=sys.stderr)
            return 1
        print(f"=== pruned {args.prune}: removed {audit['n_removed']} file(s) ===")
        for r in audit["removed"]:
            print(f"  - {r}")
        print(f"  reason: {audit['reason']}"
              + (f"  superseded_by: {audit['superseded_by']}"
                 if audit["superseded_by"] else ""))
        print(f"  recorded ip_catalog_prune event in {project}/provenance.jsonl")
        return 0

    matches = query_catalog(
        project,
        Path(args.catalog_dir) if args.catalog_dir else None,
        min_confidence=args.min_confidence,
        ic_name=args.ic_name,
        allow_self_match=args.allow_self_match,
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
