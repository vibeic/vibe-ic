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
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Tuple, Any, Dict, List, Optional

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


def _file_license_evidence(path: Path, fallback: Optional[dict] = None,
                           *, payload: Optional[bytes] = None) -> dict:
    """Read the existing SPDX/header parser's evidence for these actual bytes.

    A complete explicit identifier overrides the entry's license. Unsupported
    expressions and conflicting identifiers cannot become a permissive prefix.
    This is evidence for the copy audit, not a new license policy.
    """
    from ip_catalog_upstream_audit import LICENSE_KEYWORDS, infer_spdx_from_text
    from _prose_polarity import LINE_END_BREAKS, is_denied, sentence_scope
    record = {'path': str(path), 'sha256': None, 'spdx': None,
              'status': 'NOT_MEASURED', 'basis': None, 'readable': False}
    try:
        payload = path.read_bytes() if payload is None else payload
        record['sha256'] = hashlib.sha256(payload).hexdigest()
        text = payload.decode('utf-8')
        header = text[:5000]
    except (OSError, UnicodeError) as exc:
        return dict(record, reason=f'LICENSE_SOURCE_UNREADABLE: {exc}')
    record['readable'] = True
    markers = [match for match in re.finditer(r'SPDX-License-Identifier:[ \t]*([^\r\n]*)', text, re.I)
               if match.start() < 5000]
    identifiers = sorted({match.group(1).strip().removesuffix('*/').strip()
                          for match in markers})  # Keep expressions crossing the header boundary complete.
    record['declared_spdx'] = identifiers
    if len(identifiers) > 1:
        return dict(record, status='REJECTED', basis='SPDX-License-Identifier',
                    reason='LICENSE_SOURCE_CONTRADICTORY: multiple explicit identifiers')
    if identifiers:
        for match in markers:
            # SPDX is a line record; unrelated warranty prose is not its polarity.
            lo, hi = sentence_scope(text, match.start(), match.start(1), extra_breaks=('\n',))
            denial = is_denied(text[lo:hi], ignore_bracketed=False)
            if denial:
                return dict(record, status='REJECTED', basis='SPDX-License-Identifier',
                            reason=f'LICENSE_SOURCE_DENIED: {denial} in SPDX declaration')
        license_id = identifiers[0]
        record['basis'] = 'SPDX-License-Identifier'
    else:
        license_id = infer_spdx_from_text(header)
        record['basis'] = 'source_header' if license_id else None
        if license_id:
            for pattern, inferred in LICENSE_KEYWORDS:
                match = re.search(pattern, header, re.I | re.S)
                if inferred != license_id or not match:
                    continue
                # Ask the actual licensing sentence, not the whole LICENSE.
                # Body patterns can start at a copyright preamble; the grant
                # itself owns permission, so scope at that clause when present.
                grant = re.search(r'permission|redistribution and use|may be used and distributed',
                                  match.group(), re.I)
                start = match.start() + (grant.start() if grant else 0)
                lo, hi = sentence_scope(header, start, start + 1, extra_breaks=LINE_END_BREAKS)
                claim = header[lo:hi]
                if grant:
                    # These existing grant forms permit use without the named
                    # limit; they do not deny the grant. Other denials remain.
                    claim = re.sub(r'\bwithout\W{1,30}(?:restriction|limitation|fee|modification)\b',
                                   '', claim, flags=re.I)
                denial = is_denied(claim, ignore_bracketed=False)
                if denial:
                    return dict(record, status='REJECTED',
                                reason=f'LICENSE_SOURCE_DENIED: {denial} in license declaration')
                break
        if not license_id and fallback and fallback['status'] == 'PASS':
            license_id = fallback['spdx']
            record.update(basis='upstream_license_file',
                          license_path=fallback['path'], license_sha256=fallback['sha256'])
    if license_id is None:
        return dict(record, reason='LICENSE_SOURCE_UNKNOWN: no readable license evidence')
    compatible, reason = check_license_compatibility(license_id)
    return dict(record, spdx=license_id, status='PASS' if compatible else 'REJECTED', reason=reason)


def pull_catalog_ip(match: CatalogMatch,
                    project: Path,
                    dest_subdir: str = "phase2/stage1/rtl",
                    *, official_only: bool = False,
                    cache_root: Optional[Path] = None) -> Dict[str, Any]:
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
    src_dir = None if official_only else find_local_mirror(
        match.ip_name, match.rtl_files)
    pull_method = "local_mirror"
    clone_pin: Optional[Dict[str, Any]] = None
    if src_dir is None:
        # Fallback: git clone canonical_url, checked out AT canonical_commit
        # and proven by sha -- never a silent fall-back to the branch tip.
        src_dir, clone_pin = _git_clone_to_cache(match, cache_root=cache_root)
        pull_method = "git_clone"
    if src_dir is None or not src_dir.is_dir():
        return {
            "ip_name": match.ip_name,
            "status": "FAIL",
            "reason": (f"no local mirror in {LOCAL_MIRROR_ROOTS}, and the git "
                       f"clone fallback did not yield canonical_commit: "
                       f"{(clone_pin or {}).get('reason')}"),
            "clone_pin": clone_pin,
        }

    official_payloads: Dict[str, bytes] = {}
    errata_applied: List[Dict[str, Any]] = []
    if official_only:
        # The ordinary catalog path accepts user mirrors. An input-declared,
        # versioned reuse must instead be the official repository at the exact
        # catalog tag. Validate every byte and erratum before publishing any.
        remote = _git(["-C", str(src_dir), "remote", "get-url", "origin"])
        dirty = _git(["-C", str(src_dir), "status", "--porcelain"])
        if (remote.returncode != 0 or
                remote.stdout.strip().rstrip("/").removesuffix(".git") !=
                match.canonical_url.rstrip("/").removesuffix(".git") or
                dirty.returncode != 0 or dirty.stdout.strip()):
            return {"ip_name": match.ip_name, "status": "FAIL",
                    "reason": "IP_REUSE_OFFICIAL_SOURCE_UNVERIFIED"}
        try:
            for rel in match.rtl_files:
                path = Path(rel)
                if path.is_absolute() or ".." in path.parts or path.suffix not in _RTL_SOURCE_EXTS:
                    raise ValueError(f"IP_REUSE_RTL_PATH_REFUSED: {rel}")
                src = src_dir / path
                if not src.is_file() or src.is_symlink():
                    raise ValueError(f"IP_REUSE_RTL_MISSING: {rel}")
                official_payloads[rel] = src.read_bytes()
            if not official_payloads:
                raise ValueError("IP_REUSE_EMPTY_RTL_FILESET")
            for entry in match.errata:
                if not isinstance(entry, dict):
                    raise ValueError("IP_REUSE_ERRATUM_MALFORMED")
                commit = entry.get("upstream_commit")
                rel = entry.get("file")
                if not isinstance(commit, str) or not isinstance(rel, str) or rel not in official_payloads:
                    raise ValueError(f"IP_REUSE_ERRATUM_UNBOUND: {rel}")
                ancestor = _git(["-C", str(src_dir), "merge-base", "--is-ancestor",
                                 match.canonical_commit, commit])
                before = _git(["-C", str(src_dir), "show", f"{commit}^:{rel}"])
                after = _git(["-C", str(src_dir), "show", f"{commit}:{rel}"])
                if (ancestor.returncode != 0 or before.returncode != 0 or
                        after.returncode != 0 or
                        official_payloads[rel] != before.stdout.encode()):
                    raise ValueError(f"IP_REUSE_ERRATUM_BASE_MISMATCH: {rel}")
                official_payloads[rel] = after.stdout.encode()
                errata_applied.append({
                    "upstream_commit": commit, "file": rel,
                    "disclosure": entry.get("disclosure", ""),
                    "before_sha256": hashlib.sha256(before.stdout.encode()).hexdigest(),
                    "after_sha256": hashlib.sha256(after.stdout.encode()).hexdigest(),
                })
        except (ValueError, OSError) as exc:
            return {"ip_name": match.ip_name, "status": "FAIL",
                    "reason": str(exc), "clone_pin": clone_pin}

    # 3. Copy listed RTL files
    dest_dir = project / dest_subdir
    if official_only:
        names = [Path(rel).name for rel in match.rtl_files]
        if len(names) != len(set(names)):
            return {"ip_name": match.ip_name, "status": "FAIL",
                    "reason": "IP_REUSE_RTL_BASENAME_COLLISION"}
        occupied = [name for name in names if (dest_dir / name).exists()]
        if occupied:
            return {"ip_name": match.ip_name, "status": "FAIL",
                    "reason": f"IP_REUSE_OUTPUT_EXISTS: {occupied}"}
    dest_dir.mkdir(parents=True, exist_ok=True)
    files_copied: List[Dict[str, Any]] = []
    files_missing: List[str] = []
    file_license_refusals: List[Dict[str, Any]] = []
    from ip_catalog_upstream_audit import find_license_file
    license_path = find_license_file(src_dir)
    entry_license_evidence = (_file_license_evidence(license_path) if license_path else
                             {'status': 'NOT_MEASURED', 'spdx': None,
                              'reason': 'LICENSE_SOURCE_UNKNOWN: no upstream license file'})

    for rtl_rel in match.rtl_files:
        if official_only:
            source_license = _file_license_evidence(
                src_dir / rtl_rel, entry_license_evidence,
                payload=official_payloads[rtl_rel])
            if not source_license['readable'] or source_license['status'] == 'REJECTED':
                file_license_refusals.append(dict(source_license, rtl_rel=rtl_rel))
                files_missing.append(rtl_rel)
                continue
            dest_path = dest_dir / Path(rtl_rel).name
            dest_path.write_bytes(official_payloads[rtl_rel])
            files_copied.append({
                "rtl_rel": rtl_rel,
                "src": f"{match.canonical_url}@{(clone_pin or {}).get('checked_out_sha')}:{rtl_rel}",
                "dest": str(dest_path),
                "sha256": _sha256_file(dest_path),
                "size_bytes": dest_path.stat().st_size,
                "license_evidence": _file_license_evidence(dest_path, entry_license_evidence),
            })
            continue
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
        source_license = _file_license_evidence(src_path, entry_license_evidence)
        if not source_license['readable'] or source_license['status'] == 'REJECTED':
            file_license_refusals.append(dict(source_license, rtl_rel=rtl_rel))
            files_missing.append(rtl_rel)
            continue
        shutil.copy2(src_path, dest_path)
        files_copied.append({
            "rtl_rel": rtl_rel,
            "src": str(src_path),
            "dest": str(dest_path),
            "sha256": _sha256_file(dest_path),
            "size_bytes": dest_path.stat().st_size,
            "license_evidence": _file_license_evidence(dest_path, entry_license_evidence),
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
                # The mirror audit runs after copy. Preserve that delivered
                # population even when its entry claim is subsequently refused.
                "license": match.license,
                "entry_license_evidence": entry_license_evidence,
                "file_license_refusals": file_license_refusals,
                "files_copied": files_copied,
                "files_missing": files_missing,
            }

    # 4. Locate license file in source dir (for attribution)
    license_file_text = ""
    for license_name in ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"]:
        lp = src_dir / license_name
        if lp.is_file():
            try:
                license_file_text = lp.read_text()[:200]
            except (OSError, UnicodeError):
                pass  # The named NOT_MEASURED evidence is retained above.
            break

    audit = {
        "ip_name": match.ip_name,
        "category": match.category,
        "version": match.version,
        "license": match.license,
        "entry_license_evidence": entry_license_evidence,
        "file_license_refusals": file_license_refusals,
        "license_file_first_200_chars": license_file_text,
        "canonical_url": match.canonical_url,
        "canonical_commit": match.canonical_commit,
        "pull_method": pull_method,
        "source_dir": (f"{match.canonical_url}@{(clone_pin or {}).get('checked_out_sha')}"
                       if official_only else str(src_dir)),
        "spec_match_pattern": match.matched_pattern,
        "spec_match_confidence": match.confidence,
        "local_mirror_audit": mirror_audit,
        "clone_pin": clone_pin,
        "errata_applied": errata_applied,
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
            "commit_checked_out": (clone_pin or {}).get("checked_out_sha"),
            "errata_applied": errata_applied,
            "license_verified_against_mirror": (
                None if mirror_audit is None
                else mirror_audit.get("license_check", {}).get("match")),
            "files_pulled": len(files_copied),
            "file_license_evidence": [
                {**f['license_evidence'], "dest": _rel(f['dest']),
                 "path": _rel(f['license_evidence']['path'])}
                for f in files_copied],
            "file_license_refusals": file_license_refusals,
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


#: Session cache for the clone fallback. One directory per (IP, pin), so a
#: cache holding another commit is never mistaken for this pin.
CACHE_ROOT = Path("/tmp/vibe_ic_catalog_cache")


def _git(args: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          timeout=timeout, check=False)


def _pinned_head(repo: Path, pin: str) -> Dict[str, Any]:
    """HEAD and the pin, both resolved to commit shas by git itself."""
    head = _git(["-C", str(repo), "rev-parse", "HEAD"])
    want = _git(["-C", str(repo), "rev-parse", "--verify", "--quiet",
                 f"{pin}^{{commit}}"])
    return {"checked_out_sha": head.stdout.strip() if head.returncode == 0 else None,
            "canonical_commit_sha": want.stdout.strip() if want.returncode == 0 else None}


def _git_clone_to_cache(match: CatalogMatch, *,
                        cache_root: Optional[Path] = None) -> tuple[Optional[Path], Dict[str, Any]]:
    """Clone canonical_url and check out canonical_commit, PROVEN by sha.

    Returns ``(dir, record)``; ``dir`` is None unless git resolves HEAD and
    ``canonical_commit`` to the same commit. The clone used to be ``--depth
    1`` with the checkout inside ``except: pass``, and any existing cache dir
    was reused whatever its commit: a tag pin such as ``1.4.0`` fell back to
    the default branch's tip without a word. A cache is reused only when it
    proves the same pin.
    """
    pin = match.canonical_commit or ""
    record: Dict[str, Any] = {"canonical_url": match.canonical_url,
                              "canonical_commit": pin, "checked_out_sha": None,
                              "canonical_commit_sha": None, "reason": None}
    if not match.canonical_url or not pin:
        record["reason"] = "manifest names no canonical_url/canonical_commit"
        return None, record
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in pin)
    cache_dir = (CACHE_ROOT if cache_root is None else cache_root) / f"{match.ip_name}@{safe}"
    if not cache_dir.is_dir():
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_dir.with_name(cache_dir.name + f".partial{time.time_ns()}")
        try:
            cloned = _git(["clone", "--quiet", match.canonical_url, str(tmp)])
            if cloned.returncode == 0:
                checked = _git(["-C", str(tmp), "checkout", "--quiet", "--detach",
                                pin], timeout=60)
                if checked.returncode != 0:
                    record["reason"] = ("git checkout of canonical_commit failed: "
                                        + checked.stderr.strip()[-300:])
                    return None, record
                tmp.rename(cache_dir)
            else:
                record["reason"] = "git clone failed: " + cloned.stderr.strip()[-300:]
                return None, record
        except (OSError, subprocess.SubprocessError) as exc:
            record["reason"] = f"git unavailable: {exc}"
            return None, record
    record.update(_pinned_head(cache_dir, pin))
    if not record["checked_out_sha"] or \
            record["checked_out_sha"] != record["canonical_commit_sha"]:
        record["reason"] = (f"checked-out {record['checked_out_sha']} is not "
                            f"canonical_commit {pin} "
                            f"({record['canonical_commit_sha']}) in {cache_dir}")
        return None, record
    return cache_dir, record


def pull_all_catalog_matches(project: Path,
                              matches: List[CatalogMatch],
                              *, official_only: bool = False,
                              cache_root: Optional[Path] = None,
                              apply_corrections: bool = True) -> Dict[str, Any]:
    """Pull every matching IP, return aggregated audit + update declaration.json."""
    corrections = catalog_local_corrections(matches) if apply_corrections else []
    if corrections:
        # A local correction always preserves an independently fetched official
        # parent. Mirrors never establish that parent identity.
        official_only = True
        if (project / "phase2/stage1/rtl/SOURCE_MANIFEST.json").is_file():
            outcome = adopt_catalog_local_correction(project, matches, corrections)
            prior = _local_json(project / "plugin_output/declaration.json")
            return {**prior, "n_ips_pulled": len(matches) if outcome["status"] == PIN_VERIFIED else 0,
                    "catalog_correction": outcome, "reuse_kind": "LOCAL_DERIVATIVE",
                    "status": "ALREADY_FETCHED"}
    audits: List[Dict[str, Any]] = []
    for m in matches:
        audit = (pull_catalog_ip(m, project, official_only=True,
                                 cache_root=cache_root)
                 if official_only else pull_catalog_ip(m, project))
        audits.append(audit)

    # The delivered population, rather than only the catalog's entry claim.
    entry_spdx_set = {a.get('license', '') for a in audits
                      if a.get('status') in ('PASS', 'PARTIAL')}
    file_evidence = [dict(f.get('license_evidence') or {'status': 'NOT_MEASURED'},
                          ip_name=a['ip_name'], dest=f.get('dest'))
                     for a in audits for f in a.get('files_copied', [])]
    evidence = [*file_evidence, *(a.get('entry_license_evidence') or
                 {'status': 'NOT_MEASURED'} for a in audits),
                *(r for a in audits for r in a.get('file_license_refusals', []))]
    spdx_set = sorted(entry_spdx_set | {e['spdx'] for e in file_evidence if e.get('spdx')})
    license_status = ('REJECTED' if any(e['status'] == 'REJECTED' for e in evidence)
                      or any(a.get('status') == 'REJECTED' for a in audits) else
                      'NOT_MEASURED' if not file_evidence or
                      any(e['status'] != 'PASS' for e in evidence) else 'PASS')
    all_permissive = license_status == 'PASS' and all(
        check_license_compatibility(lic)[0] for lic in spdx_set)

    aggregated = {
        "rtl_strategy": "catalog_lookup_plus_ai_glue",
        "n_ips_pulled": sum(1 for a in audits if a.get("status") in ("PASS", "PARTIAL")),
        "n_ips_rejected": sum(1 for a in audits if a.get("status") == "REJECTED"),
        "n_ips_failed": sum(1 for a in audits if a.get("status") == "FAIL"),
        "ip_catalog_used": audits,
        "license_compliance_audit": {
            "status": license_status,
            "all_permissive": all_permissive,
            "spdx_set": spdx_set,
            "entry_spdx_set": sorted(entry_spdx_set),
            "file_evidence": file_evidence,
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
        if official_only:
            mf["source_pins"] = [
                {"ip_name": a["ip_name"], "version": a["version"],
                 "canonical_url": a["canonical_url"],
                 "canonical_commit": a["canonical_commit"],
                 "checked_out_sha": (a.get("clone_pin") or {}).get("checked_out_sha"),
                 "errata_applied": a.get("errata_applied", []),
                 "files_sha256": {f["rtl_rel"]: f["sha256"]
                                  for f in a.get("files_copied", [])}}
                for a in audits if a.get("status") == "PASS"
            ]
        mf.setdefault("generated_by", "ip_catalog_pull")
        manifest_path.write_text(json.dumps(mf, indent=2))

    if corrections and aggregated["n_ips_pulled"] == len(matches):
        outcome = adopt_catalog_local_correction(project, matches, corrections)
        aggregated.update(catalog_correction=outcome, reuse_kind="LOCAL_DERIVATIVE")
        existing.update(aggregated)
        decl_path.write_text(json.dumps(existing, indent=2))
    return aggregated


#: `verify_existing_official_pins_outcome` states WHY a prior pull was not
#: accepted.
#: MISMATCH    — a comparison that could be made disagreed: the project's RTL
#:               against its own receipts, or a fetched reference against the
#:               project, or the reference refused the pin ON FETCHED BYTES or by
#:               policy (erratum base, missing RTL, unverified source, licence,
#:               a checkout at another sha). Always a FAIL.
#: UNAVAILABLE — every comparison that could be made agreed, and at least one
#:               IP's reference tree was never reached (clone failed, timed out,
#:               git unavailable, the pinned ref absent upstream: its clone
#:               record has no checked_out_sha). The prior pull is still not
#:               accepted, but nothing about those bytes was compared.
PIN_VERIFIED = "VERIFIED"
PIN_MISMATCH = "MISMATCH"
PIN_UNAVAILABLE = "UNAVAILABLE"

_PULL_EVENT_KEYS = ("event", "ip", "version", "license", "commit_pinned",
                    "commit_checked_out", "errata_applied", "files_pulled",
                    "outputs", "outputs_sha256")


def verify_existing_official_pins(project: Path,
                                  matches: List[CatalogMatch],
                                  manifest: Dict[str, Any]) -> bool:
    """True only when every pin was independently reproduced (see below)."""
    return verify_existing_official_pins_outcome(
        project, matches, manifest)[0] == PIN_VERIFIED


def _reference_never_reached(audit: Dict[str, Any]) -> bool:
    """Did this IP's reference pull fail before any tree was checked out?

    Only a transport-stage failure qualifies: the clone record exists and
    holds no checked_out_sha. A refusal with no clone record (licence,
    self-match, unverified source) or one reached on a checked-out tree is a
    decision about the reference, not its absence."""
    pin = audit.get("clone_pin")
    return (audit.get("status") == "FAIL" and isinstance(pin, dict)
            and not pin.get("checked_out_sha"))


def _own_receipt_mismatch(project: Path, pins: List[Any],
                          events: List[Any]) -> Optional[str]:
    """Compare the project's RTL with its OWN receipts; no reference needed."""
    rtl = project / "phase2" / "stage1" / "rtl"
    for pin in pins:
        if not isinstance(pin, dict):
            return "a source_pins entry is not an object"
        files = pin.get("files_sha256")
        if not isinstance(files, dict) or not files:
            return f"source_pins for {pin.get('ip_name')} record no file digests"
        for rel, digest in files.items():
            target = rtl / Path(str(rel)).name
            if target.is_symlink() or not target.is_file() or \
                    _sha256_file(target) != digest:
                return (f"project RTL differs from its own pin receipt: "
                        f"{target.relative_to(project)}")
        pulls = [e for e in events if isinstance(e, dict)
                 and e.get("event") == "ip_catalog_pull"
                 and e.get("ip") == pin.get("ip_name")]
        if not pulls:
            return f"no project pull event for {pin.get('ip_name')}"
        for rel, digest in (pulls[-1].get("outputs") or {}).items():
            target = project / rel
            if target.is_symlink() or not target.is_file() or \
                    "sha256:" + _sha256_file(target) != digest:
                return f"project RTL differs from its own pull event: {rel}"
    return None


def verify_existing_official_pins_outcome(project: Path,
                                          matches: List[CatalogMatch],
                                          manifest: Dict[str, Any]
                                          ) -> Tuple[str, str]:
    """Accept a prior official pull only after independently reproducing its bytes.

    The project manifest and provenance are user-writable receipts, so matching
    their hashes to the project's own RTL cannot establish upstream origin.
    Re-run the pinned official pull in an isolated directory, then require its
    complete pin records, pull events, and output bytes in the project.

    NOT ALL-OR-NOTHING (review wave 58). The order is: (1) the project's RTL
    against its own receipts — a difference there is proven without any
    reference; (2) every IP whose reference WAS fetched, against the project;
    (3) only then, if nothing disagreed, an IP whose reference could not be
    reached makes the answer UNAVAILABLE. A second IP whose clone always
    fails therefore cannot hide a proven mismatch in the first.
    """
    if manifest.get("generated_by") != "ip_catalog_pull":
        return PIN_MISMATCH, "manifest was not written by ip_catalog_pull"
    pins = manifest.get("source_pins")
    if not isinstance(pins, list) or len(pins) != len(matches) or \
            sorted(str(p.get("ip_name")) for p in pins if isinstance(p, dict)) != \
            sorted(m.ip_name for m in matches):
        return PIN_MISMATCH, "source_pins do not cover the declared matches"
    try:
        events = [json.loads(line) for line in
                  (project / "provenance.jsonl").read_text().splitlines()]
    except (OSError, ValueError, TypeError):
        return PIN_MISMATCH, "project provenance.jsonl unreadable"
    own = _own_receipt_mismatch(project, pins, events)
    if own:
        return PIN_MISMATCH, own
    by_name = {p["ip_name"]: p for p in pins}
    unreached: List[str] = []
    # The operator-staged canonical cache is an input, never project authority.
    # Refuse project-contained cache entries even through a symlink.
    for match in matches:
        safe = "".join(c if c.isalnum() or c in "._-" else "_"
                       for c in (match.canonical_commit or ""))
        cached = (CACHE_ROOT / f"{match.ip_name}@{safe}").resolve()
        if cached.is_relative_to(project.resolve()):
            return PIN_MISMATCH, "official reference cache is inside the project"
    with tempfile.TemporaryDirectory(prefix="ip-pin-verify-") as scratch:
        reference = Path(scratch)
        # Independently re-fetch the current upstream pin and errata. Reusing
        # the initial pull's cache would accept unreachable or rewritten tags
        # solely because their old checkout still matches the local receipts.
        audit = pull_all_catalog_matches(reference, matches, official_only=True,
                                         cache_root=reference / "canonical",
                                         apply_corrections=False)

        def _scrub(text: Any) -> str:
            # The reference pull runs in a throw-away directory; its path in a
            # tool message would become a dangling external reference in every
            # report that quotes this reason.
            return str(text).replace(str(reference), "<independent-pull scratch>")

        try:
            ref_pins = {p.get("ip_name"): p for p in json.loads(
                (reference / "phase2/stage1/rtl/SOURCE_MANIFEST.json").read_text()
            ).get("source_pins") or [] if isinstance(p, dict)}
        except (OSError, ValueError, AttributeError):
            ref_pins = {}
        try:
            reference_events = [json.loads(line) for line in
                                (reference / "provenance.jsonl").read_text().splitlines()]
        except (OSError, ValueError):
            reference_events = []
        for used in audit.get("ip_catalog_used") or []:
            if not isinstance(used, dict):
                return PIN_MISMATCH, "reference pull returned a malformed record"
            name = used.get("ip_name")
            if used.get("status") != "PASS":
                if _reference_never_reached(used):
                    unreached.append(f"{name}: {_scrub(used.get('reason'))}")
                    continue
                return PIN_MISMATCH, (f"the reference for {name} was refused on "
                                      f"what it fetched: {_scrub(used.get('reason'))}")
            if by_name.get(name) != ref_pins.get(name):
                return PIN_MISMATCH, f"source_pins for {name} differ from the reference pull"
            expected_rows = [e for e in reference_events if isinstance(e, dict)
                             and e.get("event") == "ip_catalog_pull"
                             and e.get("ip") == name]
            if not expected_rows:
                return PIN_MISMATCH, f"the reference pull recorded no event for {name}"
            for expected in expected_rows:
                if not any(isinstance(event, dict) and
                           all(event.get(k) == expected.get(k) for k in _PULL_EVENT_KEYS)
                           for event in events):
                    return PIN_MISMATCH, (f"no project pull event matches the "
                                          f"reference for {name}")
                for rel, digest in expected["outputs"].items():
                    target = project / rel
                    if target.is_symlink() or not target.is_file() or \
                            "sha256:" + _sha256_file(target) != digest:
                        return PIN_MISMATCH, f"output bytes differ: {rel}"
    if unreached:
        return PIN_UNAVAILABLE, "; ".join(unreached)
    return PIN_VERIFIED, "every pin reproduced by an independent pull"


LOCAL_DERIVATIVE_SCHEMA = "vibeic.reused_ip_local_derivative.v1"


def _local_json(path: Path) -> Dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    value = json.loads(path.read_text(), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("local derivative JSON must be an object")
    return value


def _local_path(project: Path, rel: Any, *, directory=False) -> Path:
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or \
            any(p in (".", "..") for p in rel.split("/")):
        raise ValueError(f"invalid project-relative local path: {rel!r}")
    root = project.resolve()
    path = root / rel
    if not path.resolve().is_relative_to(root) or \
            any(p.is_symlink() for p in (path, *path.parents) if p != root):
        raise ValueError(f"local path escapes project or contains symlink: {rel}")
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError(f"local source/patch/evidence missing: {rel}")
    return path


def _local_ref(project: Path, ref: Any) -> Path:
    if not isinstance(ref, dict):
        raise ValueError("local derivative reference must bind path and sha256")
    path = _local_path(project, ref.get("path"))
    if _sha256_file(path) != ref.get("sha256"):
        raise ValueError(f"local source/patch/evidence digest differs: {ref.get('path')}")
    return path


def _local_inventory(rtl: Path) -> Dict[str, str]:
    """All staged files, including headers; the keystone is checked separately."""
    result = {}
    for path in sorted(rtl.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink in local derivative inventory")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("nonregular file in local derivative inventory")
        rel = path.relative_to(rtl).as_posix()
        if rel != "SOURCE_MANIFEST.json":
            result[rel] = _sha256_file(path)
    return result


AUTHORED_INTERFACE_SCHEMA = "vibeic.authored_interface_renames.v1"


def _authored_interface_plan(project: Path, rel: str) -> Dict[str, Any]:
    """Validate a caller's input declaration; never infer or publish a rename.

    BLOCKING source admission only. Current input delegation, selected-top
    identity and literal electrical facts must independently authorize every
    pair. Pad sides and functional equivalence remain ordinary obligations.
    """
    if not isinstance(rel, str) or not rel.startswith("plugin_input/") or \
            Path(rel).as_posix() != rel or any(not part for part in rel.split("/")):
        raise ValueError("authored interface input must be under plugin_input")
    path = _local_path(project, rel)

    def unique_keys(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("duplicate authored interface JSON key")
            result[key] = value
        return result

    contract_bytes = path.read_bytes()
    data = json.loads(contract_bytes.decode("utf-8"), object_pairs_hook=unique_keys)
    keys = {"schema", "top_module", "actor", "rationale", "renamed_interfaces",
            "input_obligations"}
    if not isinstance(data, dict) or set(data) != keys or \
            data.get("schema") != AUTHORED_INTERFACE_SCHEMA:
        raise ValueError("authored interface schema or fields differ")
    if any(not isinstance(data[k], str) or not data[k].strip()
           for k in ("actor", "rationale", "top_module")):
        raise ValueError("authored interface actor/rationale/top missing")
    guards = {path: contract_bytes}
    obligations = data["input_obligations"]
    if not isinstance(obligations, list) or not obligations:
        raise ValueError("authored interface input obligation missing")
    for row in obligations:
        if not isinstance(row, dict) or set(row) != {"path", "quote"} or \
                not isinstance(row["path"], str) or not row["path"].startswith("input/docs/"):
            raise ValueError("authored interface obligation must quote original input/docs")
        source = _local_path(project, row["path"])
        if not isinstance(row["quote"], str) or not row["quote"] or \
                row["quote"] not in source.read_text():
            raise ValueError("authored interface input quote differs")
        guards[source] = source.read_bytes()
    # All original documents are inputs to the existing delegation/fixed-name
    # checks. An author-selected quote cannot hide a contrary document.
    for source in sorted((project / "input/docs").rglob("*")):
        if source.is_file():
            source = _local_path(project, str(source.relative_to(project)))
            guards[source] = source.read_bytes()
    l9_path = _local_path(project, "phase1/generated_docs/L9_INTEGRATION_SPEC.json")
    l9_bytes = l9_path.read_bytes()
    l9 = json.loads(l9_bytes)
    if not isinstance(l9, dict):
        raise ValueError("authored interface current L9 is not an object")
    rosters = [l9[key] for key in ("ports", "top_ports", "top_module_pins") if key in l9]
    if not rosters or any(not isinstance(rows, list) or rows != rosters[0] for rows in rosters):
        raise ValueError("authored interface current L9 rosters disagree")
    if any(not isinstance(port, dict) or not isinstance(port.get("name"), str)
           or not re.fullmatch(r"[A-Za-z_]\w*", port["name"]) for port in rosters[0]) or \
            len({port["name"] for port in rosters[0]}) != len(rosters[0]):
        raise ValueError("authored interface current L9 ports are malformed or repeated")
    from _staged_top_module import bind_selected_interface
    from _l_doc_pad_placement import accept_renames
    from renamed_interface_derive import _rtl_top_ports
    bound = bind_selected_interface(project, l9, include_synthesis_handoff=False)
    binding = bound.get("selected_interface_binding") or {}
    groups = binding.get("illustrative_groups") or []
    if not groups or data["top_module"] != binding.get("top_module"):
        raise ValueError("authored interface lacks current input delegation or selected top")
    selected = _rtl_top_ports(project, data["top_module"])
    if not selected or selected[0] != binding["selected_source"] or \
            not selected[0].startswith("phase2/stage1/rtl/"):
        raise ValueError("authored interface current selected source is unavailable")
    choice = _local_path(project, "plugin_output/declaration.json")
    guards[l9_path] = l9_bytes
    guards[choice] = choice.read_bytes()
    selected_path = _local_path(project, selected[0])
    guards[selected_path] = selected_path.read_bytes()
    sidecar = project / "plugin_output/declaration.provenance.json"
    if sidecar.exists():
        sidecar = _local_path(project, str(sidecar.relative_to(project)))
        guards[sidecar] = sidecar.read_bytes()
    entries = data["renamed_interfaces"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("authored interface rename pairs missing")
    pairs, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"l9", "rtl"}:
            raise ValueError("authored interface pair fields differ")
        for key in ("l9", "rtl"):
            names = entry[key]
            if not isinstance(names, list) or not names or any(
                    not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w*", name)
                    for name in names) or len(set(names)) != len(names):
                raise ValueError("authored interface pair names malformed or repeated")
        lhs, rhs = set(entry["l9"]), set(entry["rtl"])
        identity = (tuple(sorted(lhs)), tuple(sorted(rhs)))
        if identity in seen or not any(lhs <= set(group["l9"]) and rhs <= set(group["rtl"])
                                       for group in groups):
            raise ValueError("authored interface pair is repeated or outside input delegation")
        seen.add(identity)
        pairs.append((lhs, rhs))
    for group in groups:
        authorized = [(lhs, rhs) for lhs, rhs in pairs
                      if lhs <= set(group["l9"]) and rhs <= set(group["rtl"])]
        if (set().union(*(lhs for lhs, _ in authorized)) != set(group["l9"]) or
                set().union(*(rhs for _, rhs in authorized)) != set(group["rtl"])):
            raise ValueError("authored interface pairs do not cover the selected interface")
    accepted, rejected = accept_renames(pairs, bound["ports"], selected[1])
    if rejected or len(accepted) != len(pairs):
        raise ValueError("authored interface electrical declaration refused: " + repr(rejected))
    ports = {p["name"]: p for p in bound["ports"]}
    for lhs, rhs in pairs:
        for name in lhs | rhs:
            width = ports[name].get("width")
            if not isinstance(width, int) or isinstance(width, bool) or width < 1 or \
                    ports[name].get("direction", ports[name].get("mode")) not in {"input", "output", "inout"}:
                raise ValueError("authored interface electrical extent/direction is unknown")
    if any(p.read_bytes() != raw for p, raw in guards.items()):
        raise ValueError("authored interface inputs changed during validation")
    return {"ref": {"path": rel, "sha256": hashlib.sha256(contract_bytes).hexdigest()},
            "pairs": entries, "guards": guards,
            "inputs": {str(p.relative_to(project)): "sha256:" + hashlib.sha256(raw).hexdigest()
                       for p, raw in guards.items()}}


def _verify_authored_interface(project: Path, manifest: Dict[str, Any]) -> None:
    """Reused-source admission retains the actual caller input's authority."""
    if "authored_interface" not in manifest:
        return
    ref = manifest["authored_interface"]
    _local_ref(project, ref)
    plan = _authored_interface_plan(project, ref["path"])
    if ref != plan["ref"] or manifest.get("renamed_interfaces") != plan["pairs"]:
        raise ValueError("authored interface input or published mappings changed")
    events = [json.loads(line) for line in (project / "provenance.jsonl").read_text().splitlines()]
    if not any(isinstance(event, dict) and event.get("event") in {
                   "ip_catalog_authored_glue_inventory", "ip_catalog_local_derivative"}
               and event.get("exit_code") == 0 and event.get("authored_interface") == ref
               and event.get("renamed_interfaces") == plan["pairs"]
               and event.get("inputs", {}).get(ref["path"]) == "sha256:" + ref["sha256"]
               for event in events):
        raise ValueError("authored interface native publication event is missing")


def emit_authored_glue_inventory(project: Path, matches: List[CatalogMatch],
                                 names: List[str], *,
                                 authored_interface: Optional[str] = None) -> Dict[str, Any]:
    """Record explicitly declared glue through the existing source producer.

    Source admission only: read actual bytes, independently verify the official
    pins, and refuse undeclared inventory before publishing any metadata.
    """
    project = project.resolve()
    mf_path = _local_path(project, "phase2/stage1/rtl/SOURCE_MANIFEST.json")
    manifest = _local_json(mf_path)
    if manifest.get("reused_ip") is not True or \
            manifest.get("generated_by") != "ip_catalog_pull":
        raise ValueError("authored glue requires an official catalog parent")
    previous_interface = manifest.get("authored_interface")
    if previous_interface is not None:
        _local_ref(project, previous_interface)
    interface_rel = (authored_interface if authored_interface is not None
                     else (previous_interface or {}).get("path"))
    interface = _authored_interface_plan(project, interface_rel) if interface_rel is not None else None
    if interface and manifest.get("renamed_interfaces") not in (None, [], interface["pairs"]):
        raise ValueError("authored interface cannot overwrite another rename declaration")
    official = {}
    for pin in manifest.get("source_pins") or []:
        for rel, digest in pin.get("files_sha256", {}).items():
            name = Path(rel).name
            if name in official:
                raise ValueError("colliding official inventory basenames")
            official[name] = digest
    if not official or not names:
        raise ValueError("official inventory and explicit authored glue required")
    authored = {}
    for name in names:
        if not isinstance(name, str) or not name or name in (".", "..") or \
                "/" in name or "\\" in name or Path(name).name != name:
            raise ValueError("authored glue must be a staged source basename")
        if Path(name).suffix.lower() not in (".v", ".sv", ".vh", ".svh"):
            raise ValueError("authored glue must be RTL or a source header")
        if name in official or name in authored:
            raise ValueError("authored glue overlaps official or repeated source")
        authored[name] = _sha256_file(_local_path(
            project, "phase2/stage1/rtl/" + name))
    reused = official
    if "local_derivative" in manifest:
        current = _local_json(_local_ref(project, manifest["local_derivative"]))
        reused = {name: current["current_inventory"][name] for name in official}
    before = {**reused, **authored}
    if _local_inventory(project / "phase2/stage1/rtl") != before:
        raise ValueError("undeclared or changed staged inventory")
    decl_path = project / "plugin_output/declaration.json"
    provenance_path = project / "provenance.jsonl"
    for path in (decl_path, provenance_path):
        if not path.resolve().is_relative_to(project) or \
                any(p.is_symlink() for p in (path, *path.parents) if p != project) or \
                (path.exists() and not path.is_file()):
            raise ValueError("authored glue metadata path escapes or is nonregular")
    declaration = _local_json(decl_path) if decl_path.is_file() else {}
    metadata_before = {path: path.read_bytes() if path.is_file() else None
                       for path in (mf_path, decl_path, provenance_path)}
    events = []
    if provenance_path.is_file():
        for line in provenance_path.read_text().splitlines():
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("invalid existing producer provenance")
            events.append(event)
    rows = [{"path": name, "sha256": authored[name]} for name in sorted(authored)]
    inputs = {"phase2/stage1/rtl/" + name: "sha256:" + digest
              for name, digest in authored.items()}
    already = (manifest.get("ai_authored_files") == rows and
               declaration.get("ai_authored_files") == sorted(authored) and any(
                   event.get("event") == "ip_catalog_authored_glue_inventory" and
                   event.get("exit_code") == 0 and event.get("ai_authored_files") == rows and
                   event.get("inputs") == inputs for event in events))
    if interface:
        current_outputs = {str(path.relative_to(project)): "sha256:" + _sha256_file(path)
                           for path in (mf_path, decl_path) if path.is_file()}
        latest_outputs = {}
        for event in events:
            if event.get("exit_code") == 0 and isinstance(event.get("outputs"), dict):
                latest_outputs.update(event["outputs"])
        if "local_derivative" in manifest and latest_outputs.get(
                "phase2/stage1/rtl/SOURCE_MANIFEST.json") != current_outputs[
                    "phase2/stage1/rtl/SOURCE_MANIFEST.json"]:
            raise ValueError("authored interface requires a current native derivative manifest binding")
        already = (manifest.get("ai_authored_files") == rows and
                   declaration.get("ai_authored_files") == sorted(authored) and
                   previous_interface == interface["ref"] and
                   manifest.get("renamed_interfaces") == interface["pairs"] and any(
                       event.get("event") == "ip_catalog_authored_glue_inventory" and
                       event.get("exit_code") == 0 and event.get("ai_authored_files") == rows and
                       event.get("authored_interface") == interface["ref"] and
                       event.get("renamed_interfaces") == interface["pairs"] and
                       event.get("inputs", {}).get(interface_rel) == "sha256:" + interface["ref"]["sha256"]
                       for event in events) and
                   all(latest_outputs.get(path) == digest for path, digest in current_outputs.items()))
    derivative = "local_derivative" in manifest
    if derivative and not already:
        outcome = adopt_catalog_local_correction(project, matches, authored_rows=rows,
                                                authored_interface=interface_rel)
        if outcome["status"] != PIN_VERIFIED:
            return outcome
        manifest = _local_json(mf_path)
        metadata_before = {path: path.read_bytes() if path.is_file() else None
                           for path in (mf_path, decl_path, provenance_path)}
    state, why = (verify_existing_reused_pins_outcome(project, matches, manifest)
                  if derivative else verify_existing_official_pins_outcome(project, matches, manifest))
    if state != PIN_VERIFIED:
        return {"status": state, "reason": why, "kind": "AUTHORED_GLUE_INVENTORY"}
    # Refuse bytes changed during independent source reproduction.
    if _local_inventory(project / "phase2/stage1/rtl") != before:
        raise ValueError("staged inventory changed before authored publication")
    for path, data in metadata_before.items():
        if not path.resolve().is_relative_to(project) or \
                any(p.is_symlink() for p in (path, *path.parents) if p != project) or \
                (path.exists() and not path.is_file()) or \
                (path.read_bytes() if path.is_file() else None) != data:
            raise ValueError("source metadata changed before authored publication")
    if interface and _authored_interface_plan(project, interface_rel)["guards"] != interface["guards"]:
        raise ValueError("authored interface inputs changed before authored publication")
    if already:
        return {"status": PIN_VERIFIED, "kind": "AUTHORED_GLUE_INVENTORY",
                "already_current": True, "outputs": {}}
    manifest["ai_authored_files"] = rows
    declaration["ai_authored_files"] = sorted(authored)
    if interface:
        manifest["authored_interface"] = interface["ref"]
        manifest["renamed_interfaces"] = interface["pairs"]
        inputs.update(interface["inputs"])
    import _atomic_artefact as atomic
    atomic.write_json(mf_path, manifest)
    atomic.write_json(decl_path, declaration)
    event = {"event": "ip_catalog_authored_glue_inventory", "exit_code": 0,
             "ai_authored_files": rows,
             "inputs": inputs,
             "outputs": {str(path.relative_to(project)): "sha256:" + _sha256_file(path)
                         for path in (mf_path, decl_path)}}
    if interface:
        event.update(authored_interface=interface["ref"], renamed_interfaces=interface["pairs"])
    with provenance_path.open("ab") as stream:
        previous = metadata_before[provenance_path]
        if previous and not previous.endswith(b"\n"):
            stream.write(b"\n")
        stream.write((json.dumps(event, sort_keys=True) + "\n").encode())
    return {"status": PIN_VERIFIED, "kind": "AUTHORED_GLUE_INVENTORY", **event}


def _local_derivative_plan(project: Path, matches: List[CatalogMatch],
                           manifest: Dict[str, Any], ref: Dict[str, Any], *,
                           allow_parent=False):
    """Verify data and the independent official parent; replay exact byte edits.

    BLOCKING source admission only. This cannot judge the semantic correction
    or supply RTL-to-current-synthesis LEC, which remains an ordinary obligation.
    The official verifier above is unchanged and never accepts derivative bytes.
    """
    record = _local_json(_local_ref(project, ref))
    if record.get("schema") != LOCAL_DERIVATIVE_SCHEMA or \
            record.get("kind") != "LOCAL_DERIVATIVE":
        raise ValueError("local derivative schema/kind missing")
    provenance = record.get("local_provenance")
    if not isinstance(provenance, dict) or \
            any(not isinstance(provenance.get(k), str) or not provenance[k].strip()
                for k in ("actor", "reason", "owner_ruling")):
        raise ValueError("local provenance actor/reason/owner_ruling missing")
    parent = _local_path(project, record.get("parent_project"), directory=True)
    if parent == project.resolve():
        raise ValueError("official parent must be separate from derivative project")
    pm = _local_json(_local_ref(project, record.get("parent_manifest")))
    parent_mf = parent / "phase2/stage1/rtl/SOURCE_MANIFEST.json"
    if _local_ref(project, record["parent_manifest"]) != parent_mf or \
            _local_ref(project, record.get("parent_provenance")) != parent / "provenance.jsonl":
        raise ValueError("parent manifest/provenance do not belong to parent project")
    if "local_derivative" in pm or manifest.get("reused_ip") is not True or \
            manifest.get("ip_list") != pm.get("ip_list") or \
            manifest.get("generated_by") != "ip_catalog_pull" or \
            pm.get("source_pins") != manifest.get("source_pins") or \
            pm.get("generated_by") != "ip_catalog_pull":
        raise ValueError("official parent pins/identity changed or derivative mislabeled")
    official = {}
    for pin in pm.get("source_pins") or []:
        for rel, digest in pin.get("files_sha256", {}).items():
            name = Path(rel).name
            if name in official:
                raise ValueError("colliding official inventory basenames")
            official[name] = digest
    if not official or _local_inventory(parent / "phase2/stage1/rtl") != official:
        raise ValueError("official parent full inventory differs from its pins")
    authored = {}
    for row in manifest.get("ai_authored_files") or []:
        name, digest = row["path"], row["sha256"]
        if name in official or name in authored:
            raise ValueError("authored glue overlaps official reused-IP inventory")
        authored[name] = digest
    before = {**official, **authored}
    patch = _local_json(_local_ref(project, record.get("patch")))
    if patch.get("format") != "exact_utf8_replacements.v1" or \
            not isinstance(patch.get("files"), list) or not patch["files"]:
        raise ValueError("finite exact local patch missing")
    replacements = {}
    after = dict(before)
    for row in patch["files"]:
        name = row["path"]
        if name not in official or name in replacements:
            raise ValueError("patch file undeclared, repeated, or not a reused-IP file")
        data = _local_path(parent, "phase2/stage1/rtl/" + name).read_bytes()
        if row.get("sha256_before") != official[name]:
            raise ValueError("patch before digest differs from official parent")
        if not isinstance(row.get("edits"), list) or not row["edits"]:
            raise ValueError("exact patch edits missing")
        for edit in row["edits"]:
            old, new = edit["before"].encode("utf-8"), edit["after"].encode("utf-8")
            if not old or data.count(old) != 1:
                raise ValueError("exact patch context missing or ambiguous")
            data = data.replace(old, new, 1)
        digest = hashlib.sha256(data).hexdigest()
        if digest != row.get("sha256_after") or digest == official[name]:
            raise ValueError("replayed patch after digest differs or patch is empty")
        after[name], replacements[name] = digest, data
    if record.get("current_inventory") != after:
        raise ValueError("declared complete current inventory differs from patch/parent/glue")
    acceptable = (before, after) if allow_parent else (after,)
    if _local_inventory(project / "phase2/stage1/rtl") not in acceptable:
        raise ValueError("current full inventory drift, extra file, or undeclared modification")
    obligations = record.get("input_obligations")
    if not isinstance(obligations, list) or not obligations:
        raise ValueError("prompt-defined input obligation missing")
    for obligation in obligations:
        path = _local_ref(project, obligation)
        if not path.is_relative_to(project.resolve() / "input") or \
                not isinstance(obligation.get("quote"), str) or \
                not obligation["quote"] or obligation["quote"] not in path.read_text():
            raise ValueError("input obligation quote/source binding differs")
    proof = record.get("proof") or {}
    challenge = _local_ref(project, proof.get("challenge"))
    for key, want, inventory in (("parent_red", 1, before), ("candidate_green", 0, after)):
        receipt = _local_json(_local_ref(project, proof.get(key)))
        outcomes = {r["name"]: r["rc"] for r in receipt.get("results", [])}
        if outcomes.get("compile") != 0 or outcomes.get("run") != want or \
                receipt.get("tb_sha256") != _sha256_file(challenge) or \
                receipt.get("rtl") != inventory:
            raise ValueError(f"{key} does not bind unchanged challenge/outcome/full RTL inventory")
    local_event = {"event": "ip_catalog_local_derivative", "kind": "LOCAL_DERIVATIVE",
             "record": ref, "current_inventory": after,
             "exit_code": 0,
             "outputs": {"phase2/stage1/rtl/" + name: "sha256:" + after[name]
                         for name in replacements},
             "official_unmodified_files": len(official)-len(replacements),
             "locally_adapted_reused_files": len(replacements),
             "separately_authored_files": sorted(authored)}
    if "authored_interface" in manifest:
        interface = _authored_interface_plan(project, manifest["authored_interface"]["path"])
        if (manifest["authored_interface"] != interface["ref"] or
                manifest.get("renamed_interfaces") != interface["pairs"]):
            raise ValueError("authored interface input or published mappings changed")
        local_event.update(authored_interface=interface["ref"],
                           renamed_interfaces=interface["pairs"],
                           inputs={interface["ref"]["path"]: "sha256:" + interface["ref"]["sha256"]})
    if manifest.get("local_derivative") == ref:
        local_event["outputs"]["phase2/stage1/rtl/SOURCE_MANIFEST.json"] = (
            "sha256:" + _sha256_file(project / "phase2/stage1/rtl/SOURCE_MANIFEST.json"))
    if not allow_parent:
        # Existing consumers already owe this producer event. Known local
        # corruption must outrank an unavailable independent parent replay;
        # new-producer staging has not emitted its event yet.
        events = [json.loads(line) for line in (project / "provenance.jsonl").read_text().splitlines()]
        if local_event not in events:
            raise ValueError("local derivative producer provenance missing or changed")
    # Fresh independent upstream reproduction is mandatory even when all local
    # receipts agree. Its UNAVAILABLE outcome never becomes source acceptance.
    state, why = verify_existing_official_pins_outcome(parent, matches, pm)
    if state != PIN_VERIFIED:
        return state, "official parent: " + why, None
    for reference in [ref, record["parent_manifest"], record["parent_provenance"],
                      record["patch"], *obligations, proof["challenge"],
                      proof["parent_red"], proof["candidate_green"]]:
        _local_ref(project, reference)
    current_events = [json.loads(line) for line in (project / "provenance.jsonl").read_text().splitlines()]
    parent_events = [json.loads(line) for line in (parent / "provenance.jsonl").read_text().splitlines()]
    for event in parent_events:
        if event.get("event") == "ip_catalog_pull" and not any(
                all(e.get(k) == event.get(k) for k in _PULL_EVENT_KEYS)
                for e in current_events if isinstance(e, dict)):
            raise ValueError("current project dropped or changed official parent pull provenance")
    return PIN_VERIFIED, "LOCAL_DERIVATIVE: independent official parent plus exact declared local patch", {
        "record": record, "before": before, "after": after,
        "replacements": replacements,
        "event": local_event,
    }


def verify_existing_reused_pins_outcome(project: Path, matches: List[CatalogMatch],
                                       manifest: Dict[str, Any]) -> Tuple[str, str]:
    """Ordinary runner admission: official bytes or explicit LOCAL DERIVATIVE."""
    try:
        _verify_authored_interface(project, manifest)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return PIN_MISMATCH, "AUTHORED_INTERFACE_REFUSED: " + str(exc)
    if "local_derivative" not in manifest:
        return verify_existing_official_pins_outcome(project, matches, manifest)
    try:
        # Do not accept a caller's manifest while the actual keystone differs.
        if _local_json(project / "phase2/stage1/rtl/SOURCE_MANIFEST.json") != manifest:
            raise ValueError("current local derivative manifest changed")
        ref = manifest["local_derivative"]
        state, why, plan = _local_derivative_plan(project, matches, manifest, ref)
        if plan is None:
            return state, why
        if _local_inventory(project / "phase2/stage1/rtl") != plan["after"]:
            raise ValueError("current full inventory drift, extra file, or undeclared modification")
        if _local_json(project / "phase2/stage1/rtl/SOURCE_MANIFEST.json") != manifest:
            raise ValueError("current local derivative manifest changed during verification")
        events = [json.loads(line) for line in (project / "provenance.jsonl").read_text().splitlines()]
        if plan["event"] not in events:
            raise ValueError("local derivative producer provenance missing or changed")
        return state, why
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return PIN_MISMATCH, "LOCAL_DERIVATIVE_REFUSED: " + str(exc)


def apply_local_derivative(project: Path, matches: List[CatalogMatch],
                           ref: Dict[str, Any], *, authored_rows=None,
                           authored_interface: Optional[str] = None) -> Dict[str, Any]:
    """Existing pull producer stages only the finite replay, retaining parent data."""
    try:
        mf_path = project / "phase2/stage1/rtl/SOURCE_MANIFEST.json"
        manifest = _local_json(mf_path)
        if authored_interface is not None and authored_rows is None:
            raise ValueError("authored interface derivative publication requires typed glue rows")
        interface = _authored_interface_plan(project, authored_interface) if authored_interface is not None else None
        if interface and manifest.get("renamed_interfaces") not in (None, [], interface["pairs"]):
            raise ValueError("authored interface cannot overwrite another rename declaration")
        if "local_derivative" in manifest and manifest["local_derivative"] != ref:
            successor = _local_json(_local_ref(project, ref))
            old = _local_json(_local_ref(project, manifest["local_derivative"]))
            if (authored_rows is None or
                    successor.get("previous_local_derivative") != manifest["local_derivative"] or
                    _local_ref(project, old["patch"]).read_bytes() !=
                    _local_ref(project, successor["patch"]).read_bytes()):
                raise ValueError("another local derivative is already declared")
            # Only the typed glue publisher may extend this exact patch's
            # context, using new actual full-inventory native measurements.
            manifest = {k: v for k, v in manifest.items() if k != "local_derivative"}
            manifest["ai_authored_files"] = authored_rows
        if "local_derivative" in manifest:
            if manifest["local_derivative"] != ref:
                raise ValueError("another local derivative is already declared")
            state, why = verify_existing_reused_pins_outcome(project, matches, manifest)
            if state == PIN_VERIFIED:
                return {"status": state, "reason": why, "kind": "LOCAL_DERIVATIVE"}
            if why != "LOCAL_DERIVATIVE_REFUSED: local derivative producer provenance missing or changed":
                return {"status": state, "reason": why, "kind": "LOCAL_DERIVATIVE"}

            # A pre-output producer event is recoverable only when every field
            # other than the not-yet-introduced outputs map matches exactly.
            # Re-derive the complete plan first, including the independent
            # official parent, exact patch, current inventory and input proof.
            record_events = [event for event in
                (json.loads(line) for line in (project / "provenance.jsonl").read_text().splitlines())
                if isinstance(event, dict) and event.get("event") == "ip_catalog_local_derivative"
                and event.get("record") == ref]
            state, why, plan = _local_derivative_plan(project, matches, manifest, ref,
                                                     allow_parent=True)
            if plan is None:
                return {"status": state, "reason": why, "kind": "LOCAL_DERIVATIVE"}
            if _local_inventory(project / "phase2/stage1/rtl") != plan["after"]:
                raise ValueError("legacy output recovery requires the exact current derivative inventory")
            # The preserved pre-contract event predates both publication
            # fields (`exit_code` and `outputs`); recognize only that exact
            # historical shape, with every other value equal to today's plan.
            legacy_event = {key: value for key, value in plan["event"].items()
                            if key not in ("exit_code", "outputs")}
            if len(record_events) != 1 or record_events[0] != legacy_event:
                raise ValueError("legacy output recovery requires one exact output-less producer event")

            # Recheck immediately before publication; a changed receipt or RTL
            # remains a refusal. The historical line is retained byte-for-byte.
            current_lines = (project / "provenance.jsonl").read_bytes().splitlines(keepends=True)
            current_events = [json.loads(line) for line in current_lines]
            if current_events.count(legacy_event) != 1 or \
                    _local_inventory(project / "phase2/stage1/rtl") != plan["after"]:
                raise ValueError("legacy producer event or current inventory changed during recovery")
            import _atomic_artefact as atomic
            rtl = project / "phase2/stage1/rtl"
            outputs = {}
            for name, data in plan["replacements"].items():
                atomic.write_bytes(rtl / name, data)
                outputs["phase2/stage1/rtl/" + name] = "sha256:" + _sha256_file(rtl / name)
            outputs["phase2/stage1/rtl/SOURCE_MANIFEST.json"] = "sha256:" + _sha256_file(mf_path)
            if outputs != plan["event"]["outputs"]:
                raise ValueError("recovered producer output bytes differ from the verified patch")
            with (project / "provenance.jsonl").open("ab") as stream:
                stream.write((json.dumps({**plan["event"], "outputs": outputs},
                                        sort_keys=True) + "\n").encode())
            return {"status": PIN_VERIFIED, "reason": why, **plan["event"]}
        state, why, plan = _local_derivative_plan(project, matches, manifest, ref,
                                                 allow_parent=True)
        if plan is None:
            return {"status": state, "reason": why, "kind": "LOCAL_DERIVATIVE"}
        rtl = project / "phase2/stage1/rtl"
        if _local_inventory(rtl) not in (plan["before"], plan["after"]):
            raise ValueError("current inventory is neither exact parent nor declared derivative")
        import _atomic_artefact as atomic
        outputs = {}
        for name, data in plan["replacements"].items():
            atomic.write_bytes(rtl / name, data)
            outputs["phase2/stage1/rtl/" + name] = "sha256:" + _sha256_file(rtl / name)
        if outputs != plan["event"]["outputs"]:
            raise ValueError("written derivative output differs from replayed patch")
        manifest["local_derivative"] = ref
        if interface:
            if _authored_interface_plan(project, authored_interface)["guards"] != interface["guards"]:
                raise ValueError("authored interface inputs changed before derivative publication")
            manifest["authored_interface"] = interface["ref"]
            manifest["renamed_interfaces"] = interface["pairs"]
        atomic.write_json(mf_path, manifest)
        outputs["phase2/stage1/rtl/SOURCE_MANIFEST.json"] = "sha256:" + _sha256_file(mf_path)
        event = {**plan["event"], "outputs": outputs}
        if interface:
            event.update(authored_interface=interface["ref"], renamed_interfaces=interface["pairs"],
                         inputs={interface["ref"]["path"]: "sha256:" + interface["ref"]["sha256"]})
        with (project / "provenance.jsonl").open("a") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")
        return {"status": PIN_VERIFIED, "reason": why, **event}
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return {"status": PIN_MISMATCH, "kind": "LOCAL_DERIVATIVE",
                "reason": "LOCAL_DERIVATIVE_REFUSED: " + str(exc)}


def catalog_local_corrections(matches: List[CatalogMatch]) -> List[Path]:
    """Catalog-owned correction data; upstream errata retain their old meaning."""
    from _flow_yaml import load
    paths = []
    for match in matches:
        manifest = Path(match.manifest_path)
        if not manifest.is_file():
            continue
        data = load(manifest)
        correction = data.get("local_derivative")
        if correction:
            path = (manifest.parent / correction).resolve()
            if not path.is_relative_to(manifest.parent.resolve()):
                raise ValueError("catalog local correction is outside its entry")
            paths.append(path)
    return paths


def _measure_catalog_glue_context(support, parent_rtl, current_rtl, authored,
                                  patch, challenge, profile):
    """Repeat the catalog's actual component challenge on its full glue context.

    The original sealed certificate is retained. These are new native receipts,
    with relative arguments that remain bound when a held Step1 is published.
    """
    cases = profile["native_measurements"]["case_rows"]
    positive_names = profile["positive_cases"]
    negative_names = profile["negative_cases"]
    if (not positive_names or not negative_names or
            [row["case"]["name"] for row in cases] != positive_names + negative_names):
        raise ValueError("catalog native challenge population is incomplete")
    positive = len(positive_names)
    top = cases[0]["compile_argv"][cases[0]["compile_argv"].index("-s") + 1]
    receipts = {}
    for arm in ("parent_red", "candidate_green"):
        work = support / ("native_" + arm)
        shutil.copytree(parent_rtl, work)
        (work / "SOURCE_MANIFEST.json").unlink()
        for name in authored:
            shutil.copy2(current_rtl / name, work / name)
        if arm == "candidate_green":
            for row in patch["files"]:
                path = work / row["path"]
                data = path.read_bytes()
                if _sha256_file(path) != row["sha256_before"]:
                    raise ValueError("native context differs from the exact patch parent")
                for edit in row["edits"]:
                    old = edit["before"].encode()
                    if not old or data.count(old) != 1:
                        raise ValueError("native context patch is ambiguous")
                    data = data.replace(old, edit["after"].encode(), 1)
                if hashlib.sha256(data).hexdigest() != row["sha256_after"]:
                    raise ValueError("native context patch digest differs")
                path.write_bytes(data)
        inventory = _local_inventory(work)
        sources = sorted(name for name in inventory if Path(name).suffix in (".v", ".sv"))
        rows = []
        generated = work / "native_outputs"
        generated.mkdir()
        for index, original in enumerate(cases):
            case = original["case"]
            params = {key: value for key, value in case.items() if key != "name"}
            if not params or any(type(value) is not int for value in params.values()):
                raise ValueError("catalog native challenge parameters are not numeric")
            binary = f"native_outputs/case{index}.vvp"
            argv = ["iverilog", "-g2012", "-I", ".", "-s", top,
                    *[f"-P{top}.{key}={value}" for key, value in params.items()],
                    "-o", binary, "../" + challenge.name, *sources]
            cc = subprocess.run(argv, cwd=work, capture_output=True, text=True, timeout=30)
            row = {"case": case, "compile_argv": argv, "compile_rc": cc.returncode,
                   "compile_stdout": cc.stdout, "compile_stderr": cc.stderr}
            if cc.returncode == 0:
                run = subprocess.run(["vvp", binary], cwd=work, capture_output=True,
                                     text=True, timeout=30)
                row.update(native_argv=["vvp", binary], native_rc=run.returncode,
                           stdout=run.stdout, stderr=run.stderr,
                           compiled_vvp_sha256=_sha256_file(work / binary))
            rows.append(row)
        compile_rc = int(any(row["compile_rc"] != 0 for row in rows))
        run_rc = int(any(row.get("native_rc") != 0 for row in rows[:positive]))
        receipt = {"scope": "Actual full-inventory component challenge with authored glue; no whole CPU/IC verdict",
                   "results": [{"name": "compile", "rc": compile_rc}, {"name": "run", "rc": run_rc}],
                   "tb_sha256": _sha256_file(challenge), "rtl": inventory,
                   "native_measurements": {"case_rows": rows, "terminal": True},
                   "positive_cases": positive_names, "negative_cases": negative_names}
        target = support / (arm + "-glue.json")
        target.write_text(json.dumps(receipt, indent=2) + "\n")
        receipts[arm] = target
        if compile_rc or any(row.get("native_rc") != 1 for row in rows[positive:]):
            raise ValueError("native full-context compile or negative challenge is incomplete")
    return receipts


def adopt_catalog_local_correction(project: Path, matches: List[CatalogMatch],
                                   corrections: Optional[List[Path]] = None, *,
                                   authored_rows=None,
                                   authored_interface: Optional[str] = None) -> Dict[str, Any]:
    """Publish the existing LOCAL_DERIVATIVE contract from sealed catalog data.

    Native evidence is a component source challenge on the declared exact
    inventory. It never supplies this project's functional or physical verdict.
    Existing choice, history and independent official-parent checks still belong
    to apply_local_derivative and verify_existing_reused_pins_outcome.
    """
    try:
        corrections = catalog_local_corrections(matches) if corrections is None else corrections
        if not corrections:
            return {"status": PIN_VERIFIED, "kind": "OFFICIAL"}
        manifest_path = project / "phase2/stage1/rtl/SOURCE_MANIFEST.json"
        manifest = _local_json(manifest_path)
        previous_ref = manifest.get("local_derivative")
        if previous_ref and authored_rows is None:
            return apply_local_derivative(project, matches, manifest["local_derivative"])
        if len(corrections) != 1:
            return {"status": PIN_UNAVAILABLE, "reason": "combined catalog correction evidence is not measured"}
        recipe_path = corrections[0]
        recipe = _local_json(recipe_path)
        official = {Path(name).name: digest for pin in manifest["source_pins"]
                    for name, digest in pin["files_sha256"].items()}
        authored = {row["path"]: row["sha256"] for row in
                    (authored_rows if authored_rows is not None else manifest.get("ai_authored_files") or [])}
        support = project / ("catalog_local_derivative_" + str(time.time_ns()))
        # Never overwrite a prior attempt or a caller's local choices.
        support.mkdir(exist_ok=False)
        if previous_ref:
            previous = _local_json(_local_ref(project, previous_ref))
            parent = _local_path(project, previous["parent_project"], directory=True)
        else:
            parent = support / "parent"
            parent_rtl = parent / "phase2/stage1/rtl"
            parent_rtl.mkdir(parents=True)
            for name in official:
                shutil.copy2(_local_path(project, "phase2/stage1/rtl/" + name), parent_rtl / name)
            parent_manifest = {key: value for key, value in manifest.items()
                               if key not in ("local_derivative", "ai_authored_files", "authored_interface")}
            (parent_rtl / "SOURCE_MANIFEST.json").write_text(json.dumps(parent_manifest, indent=2) + "\n")
            shutil.copy2(project / "provenance.jsonl", parent / "provenance.jsonl")
        def ref(path):
            return {"path": path.relative_to(project).as_posix(), "sha256": _sha256_file(path)}
        def copy_source(name):
            source = (recipe_path.parent / recipe[name]).resolve()
            if not source.is_relative_to(recipe_path.parent.resolve()):
                raise ValueError("catalog correction data is outside its recipe")
            target = support / source.name
            shutil.copy2(source, target)
            return ref(target)
        from ip_catalog_query import versioned_reuse_evidence
        obligations = []
        for path in sorted((project / "input").rglob("*")):
            if path.is_file() and path.suffix in (".md", ".txt", ".json"):
                for line in path.read_text().splitlines():
                    if any(versioned_reuse_evidence({"_full_text": line}, match)[0]
                           for match in matches):
                        obligations.append({**ref(path), "quote": line})
        proof = {key: copy_source(key) for key in ("challenge", "parent_red", "candidate_green")}
        if authored:
            challenge = _local_ref(project, proof["challenge"])
            profile = _local_json(_local_ref(project, proof["candidate_green"]))
            for key, inventory, want in (("parent_red", official, 1),
                                          ("candidate_green", recipe["current_inventory"], 0)):
                receipt = _local_json(_local_ref(project, proof[key]))
                if (receipt["rtl"] != inventory or receipt["tb_sha256"] != _sha256_file(challenge) or
                        {row["name"]: row["rc"] for row in receipt["results"]} != {"compile": 0, "run": want}):
                    raise ValueError("sealed catalog challenge does not bind its original inventory/outcome")
            measured = _measure_catalog_glue_context(support, parent / "phase2/stage1/rtl",
                                                     project / "phase2/stage1/rtl", authored,
                                                     _local_json(_local_ref(project, copy_source("patch"))),
                                                     challenge, profile)
            proof.update({key: ref(path) for key, path in measured.items()})
        record = {"schema": LOCAL_DERIVATIVE_SCHEMA, "kind": "LOCAL_DERIVATIVE",
                  "parent_project": str(parent.relative_to(project)),
                  "parent_manifest": ref(parent / "phase2/stage1/rtl/SOURCE_MANIFEST.json"),
                  "parent_provenance": ref(parent / "provenance.jsonl"),
                  "patch": copy_source("patch"), "current_inventory": {**recipe["current_inventory"], **authored},
                  "local_provenance": recipe["local_provenance"],
                  "input_obligations": obligations,
                  "proof": proof}
        if previous_ref:
            record["previous_local_derivative"] = previous_ref
        path = support / "record.json"
        path.write_text(json.dumps(record, indent=2) + "\n")
        return apply_local_derivative(project, matches, ref(path), authored_rows=authored_rows,
                                      authored_interface=authored_interface)
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            subprocess.TimeoutExpired) as exc:
        return {"status": PIN_UNAVAILABLE, "reason": "catalog local correction is not admitted: " + str(exc)}


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
    source_action = ap.add_mutually_exclusive_group()
    source_action.add_argument("--local-derivative", metavar="RECORD",
                    help="apply an explicit project-relative LOCAL DERIVATIVE record; independently verify its official parent, exact patch, full inventory and retained challenge evidence")
    source_action.add_argument("--authored-glue", action="append", metavar="BASENAME",
                    help="record each explicitly declared staged RTL/header as authored glue; verify official pins and reject undeclared inventory before publishing source metadata")
    ap.add_argument("--authored-interface", metavar="INPUT",
                    help="with --authored-glue, publish explicit rename pairs from strict plugin_input JSON; current input delegation and known electrical facts remain blocking")
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
    if args.authored_interface is not None and not args.authored_glue:
        ap.error("--authored-interface requires --authored-glue")
    if args.authored_glue and (args.dry_run or args.prune):
        ap.error("--authored-glue cannot be combined with --dry-run or --prune")

    project = Path(args.project)

    if args.local_derivative or args.authored_glue:
        try:
            from ip_catalog_query import load_project_facts, versioned_reuse_evidence
            facts = load_project_facts(project)
            matches = [m for m in query_catalog(
                project, min_confidence=args.min_confidence,
                catalog_dir=Path(args.catalog_dir) if args.catalog_dir else None)
                if versioned_reuse_evidence(facts, m)[0]]
            if args.authored_glue:
                outcome = emit_authored_glue_inventory(project, matches, args.authored_glue,
                                                       authored_interface=args.authored_interface)
            else:
                path = _local_path(project, args.local_derivative)
                outcome = apply_local_derivative(project, matches,
                                                {"path": args.local_derivative, "sha256": _sha256_file(path)})
        except (OSError, ValueError, TypeError) as exc:
            outcome = {"status": PIN_MISMATCH, "reason": str(exc)}
        print(json.dumps(outcome, indent=2))
        return 0 if outcome["status"] == PIN_VERIFIED else 1

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
    correction = aggregated.get("catalog_correction")
    if correction and correction["status"] != PIN_VERIFIED:
        print(json.dumps(correction, indent=2))
        return 1
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
