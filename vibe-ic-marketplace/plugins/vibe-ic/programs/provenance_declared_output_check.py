#!/usr/bin/env python3
"""provenance_declared_output_check.py — a declared output must be findable,
or be recorded as not shipped.

THIS GATE BLOCKS (rc=1). With `--reconcile` it also REPAIRS.

WHY IT EXISTS (#414, the #411/F9 family)
----------------------------------------
A provenance ledger's whole job is that a reader can take a declared output
path, open the file, and check its hash. Measured on the three published spm
deliverables, identical in each:

    declared 17 | at declared path 7 | hash mismatches 0 | not found 10

The hashes that CAN be checked are all correct — 0 mismatches — so this is a
pointer defect, not data corruption. Ten of seventeen pointers dangle.

Splitting those ten by HASH rather than by name (indexing every tracked file
in the deliverable and looking for the declared digest) gives the same answer
in all three cells:

    3 RELOCATED — the file ships, hashes exactly as declared, under a name the
                  ledger never mentions:
                      pnr/spm.def  -> pnr/routed.def
                      pnr/sta.rpt  -> reports/sta.rpt
                      pnr/spm.gds  -> stage4/gds/spm.gds
                  The publish/canonicalisation step renamed them and left the
                  ledger behind. These are the ACTIVELY MISLEADING ones: the
                  evidence is right there and the reader is sent elsewhere.
    7 PRUNED    — the digest appears nowhere in the deliverable; the publish
                  step did not ship the file at all.

WHAT REPAIR IS ALLOWED, and what is not
---------------------------------------
Not deleting the row: the hash of an output this run produced is provenance
whether or not the file shipped. Not re-hashing whatever sits at the path
today: that would replace a record of what the run made with a record of what
is lying around now, which is the failure this file exists to prevent. So a
relocation is only ever recorded when some shipped file's digest EQUALS the
declared one — the declared hash is never rewritten, only the pointer — and a
pruned output keeps its hash and gains an explicit marker.

    outputs_relocated_at_publish  {old path: new path}
    outputs_pruned_at_publish     [paths] + outputs_pruned_reason

A pruned marker is a disclosure, not a waiver: it says "this was produced and
is not here", which a reader can act on. A dangling path says nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import threading
from pathlib import Path

_PRUNED_REASON = (
    "NOT SHIPPED IN THIS DELIVERABLE — the run produced this file and "
    "recorded its digest; the published tree does not contain it, at this "
    "path or any other. Verified by digest, not by name: every tracked blob "
    "in the deliverable was hashed and none matches. Whether it was dropped "
    "deliberately or the run halted before the publish step is NOT asserted "
    "here — that is intent, and this record does not know it. The digest "
    "above is the run's own and is NOT re-derived from anything present "
    "today. Disclosed rather than left as a path that silently does not "
    "resolve (#414)."
)


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _toplevel(start: Path) -> Path:
    r = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() \
        else start


def _tracked_ledgers(repo: Path):
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "benchmark-data"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git could not list tracked files: "
                           f"{r.stderr.strip()[:200]}")
    return [repo / x for x in r.stdout.splitlines()
            if x.endswith("provenance.jsonl")]


def _indexed_digests(cell: Path, repo: Path) -> dict:
    """{path relative to `cell`: sha256 of the INDEXED BLOB}.

    THE WORKING TREE IS NOT THE DELIVERABLE, and reading it here produced a
    fabricated finding before this was fixed: five outputs in
    `benchmark-data/ic/subservient` reported HASH_MISMATCH — "the file at the
    declared path is not the one the run recorded" — against a PUBLISHED
    deliverable. All five files were UNTRACKED, left in one working copy by a
    later local run. A clone has no such files; from the repository they are
    simply absent. The same mistake as #416's NDA scan, and the same fix:
    judge what git holds.

    Blobs are read through one streaming `git cat-file --batch`, with the
    requests written on their own thread — writing them all first deadlocks
    once git's stdout pipe fills, which #416 learned the expensive way.
    """
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "-s", str(cell)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git could not list {cell}: {r.stderr.strip()[:200]}")
    entries = []
    for line in r.stdout.splitlines():
        try:
            meta, rel = line.split("\t", 1)
            mode, oid = meta.split()[0], meta.split()[1]
        except (ValueError, IndexError):
            continue
        if mode == "160000":            # gitlink: a commit elsewhere
            continue
        entries.append((oid, rel))
    if not entries:
        return {}

    proc = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def _feed():
        try:
            proc.stdin.write("".join(f"{o}\n" for o, _ in entries).encode())
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    t = threading.Thread(target=_feed, daemon=True)
    t.start()
    out = {}
    try:
        for _oid, rel in entries:
            header = proc.stdout.readline()
            if not header:
                break
            parts = header.split()
            if len(parts) < 3:
                continue
            data = proc.stdout.read(int(parts[2]))
            proc.stdout.read(1)
            try:
                key = str(Path(repo / rel).relative_to(cell))
            except ValueError:
                continue
            out[key] = "sha256:" + hashlib.sha256(data).hexdigest()
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
        proc.wait()
    return out


def audit_cell(cell: Path, repo: Path, reconcile: bool = False) -> dict:
    led = cell / "provenance.jsonl"
    rows = [json.loads(l) for l in led.read_text().splitlines() if l.strip()]
    # Always by INDEXED BLOB — see `_indexed_digests`. Cheap enough to build
    # unconditionally, and building it only in --reconcile mode is how the
    # check and the repair drift apart.
    by_path = _indexed_digests(cell, repo)
    by_digest = {}
    for p, dg in by_path.items():
        by_digest.setdefault(dg, []).append(p)
    # An append-only invocation ledger may name the same output path more than
    # once.  That is normal for flows such as setup STA followed by hold STA:
    # both invocations are evidence, but the worktree can contain only the
    # bytes written by the final invocation.  Remember the final declaration
    # for each path so an earlier digest is classified as SUPERSEDED only when
    # the indexed blob proves that the later declaration is the one shipped.
    # Merely seeing a later row is insufficient; a blob matching neither row
    # remains a HASH_MISMATCH.
    final_declaration = {}
    for row_index, row in enumerate(rows):
        for rel, digest in (row.get("outputs") or {}).items():
            final_declaration[rel] = (row_index, digest)
    declared = present = 0
    mismatch, dangling, relocated, pruned, superseded = [], [], [], [], []

    for row_index, row in enumerate(rows):
        # `outputs` IS THE RUN'S OWN RECORD AND IS NEVER MUTATED. An earlier
        # version of this repair rewrote a relocated key to its new path, and
        # the declared-output count across the corpus fell 156 -> 153: three
        # rows declare BOTH the original and the canonical name (spm's row
        # carries `spm.def` AND `routed.def`), so the rewrite collided with an
        # existing key and silently dropped a declaration. Repairing a ledger
        # by deleting three of its entries is worse than the dangling pointer
        # it was fixing. Disclosure is ADDITIVE: the run keeps saying what it
        # wrote, and we say where it now lives.
        outs = row.get("outputs") or {}
        marked = set(row.get("outputs_pruned_at_publish") or [])
        reloc = dict(row.get("outputs_relocated_at_publish") or {})
        newly_pruned = []
        for rel, digest in outs.items():
            declared += 1
            if rel in by_path:
                if by_path[rel] == digest:
                    present += 1
                else:
                    final_index, final_digest = final_declaration[rel]
                    if (final_index > row_index
                            and by_path[rel] == final_digest):
                        superseded.append(rel)
                    else:
                        mismatch.append(rel)
                continue
            tgt = reloc.get(rel)
            if tgt is not None:
                if by_path.get(tgt) == digest:
                    present += 1
                    relocated.append((rel, tgt))
                else:
                    dangling.append(
                        f"{rel} (declared relocated to {tgt}, which does not "
                        f"ship with that digest)")
                continue
            if rel in marked:
                pruned.append(rel)
                continue
            if reconcile:
                hits = [h for h in by_digest.get(digest, []) if h != rel]
                if hits:
                    reloc[rel] = hits[0]
                    relocated.append((rel, hits[0]))
                    continue
                newly_pruned.append(rel)
                continue
            dangling.append(rel)
        if reconcile:
            if reloc:
                row["outputs_relocated_at_publish"] = reloc
            if newly_pruned or marked:
                row["outputs_pruned_at_publish"] = sorted(
                    set(newly_pruned) | marked)
                row["outputs_pruned_reason"] = _PRUNED_REASON
                pruned.extend(newly_pruned)

    if reconcile:
        led.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                 for r in rows) + "\n")
    return {"cell": str(cell), "declared": declared, "present": present,
            "hash_mismatch": mismatch, "dangling": dangling,
            "relocated": relocated, "pruned": pruned,
            "superseded": superseded}


def audit(repo: Path, reconcile: bool = False) -> dict:
    cells, findings = [], []
    for led in _tracked_ledgers(repo):
        rep = audit_cell(led.parent, repo, reconcile)
        cells.append(rep)
        rel = led.parent.relative_to(repo)
        for m in rep["hash_mismatch"]:
            findings.append(f"{rel}: HASH_MISMATCH {m} — the file at the "
                            f"declared path is not the one the run recorded")
        for d in rep["dangling"]:
            findings.append(f"{rel}: DANGLING_OUTPUT {d} — declared, not "
                            f"present, and not marked pruned; a reader "
                            f"following the ledger finds nothing and is told "
                            f"nothing")
    return {"program": "provenance_declared_output_check", "cells": cells,
            "findings": findings, "verdict": "FAIL" if findings else "PASS"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--reconcile", action="store_true",
                    help="REPAIR: repoint a declared output at the shipped "
                         "file whose digest EQUALS the declared one, and mark "
                         "the rest pruned. Never rewrites a hash.")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)
    repo = _toplevel(Path(a.repo).resolve())
    try:
        rep = audit(repo, a.reconcile)
    except RuntimeError as exc:
        print(f"[ERROR] provenance_declared_output_check: {exc}\n"
              "   Nothing was checked. This is NOT a clean result.")
        return 2
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, indent=2) + "\n")

    decl = sum(c["declared"] for c in rep["cells"])
    if a.reconcile:
        nr = sum(len(c["relocated"]) for c in rep["cells"])
        np_ = sum(len(c["pruned"]) for c in rep["cells"])
        print(f"reconciled {len(rep['cells'])} ledger(s), {decl} declared "
              f"output(s): {nr} repointed to a hash-identical shipped file, "
              f"{np_} marked pruned. No hash was rewritten.")
        for c in rep["cells"]:
            for old, new in c["relocated"]:
                print(f"   RELOCATED {old} -> {new}")
        return 0

    if rep["findings"]:
        print(f"[FAIL] {len(rep['findings'])} declared output(s) a reader "
              f"cannot follow:")
        for f in rep["findings"][:40]:
            print(f"   {f}")
        if len(rep["findings"]) > 40:
            print(f"   … and {len(rep['findings']) - 40} more")
        print("   Run with --reconcile to repoint the ones that shipped under "
              "another name and mark the rest pruned.")
        return 1
    ns = sum(len(c["superseded"]) for c in rep["cells"])
    print(f"[PASS] provenance_declared_output_check: {len(rep['cells'])} "
          f"tracked ledger(s), {decl} declared output(s) — each is present at "
          f"its declared path and hashes as declared, explicitly marked "
          f"pruned, or superseded by a later same-path declaration whose "
          f"digest is the shipped blob ({ns} superseded).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
