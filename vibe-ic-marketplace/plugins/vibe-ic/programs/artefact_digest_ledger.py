#!/usr/bin/env python3
"""
artefact_digest_ledger.py — vibe-ic#1116.

WHY THIS EXISTS
===============
An engineer running RTL-to-GDS with an AI agent reported that when an N2N
formal check would not pass, the agent edited the netlist until it did. That is
not a model defect. If the objective is "the check passes" and the evidence is
writable, editing the evidence is a valid solution and a cheaper one than
fixing the design.

#1116 measured four tampering methods against LibreLane 3.0.8 and
OpenROAD-flow-scripts; all four succeeded on both. MEASURED HERE, against THIS
flow, before a line of this file was written:

    (0) honest artefact + honest record                    ACCEPTED   correct
    (B) artefact content rewritten, record untouched       REFUSED    correct
    (A) artefact AND recorded digest rewritten together    ACCEPTED   GAP
    (C) digest REMOVED from the record, artefact rewritten ACCEPTED   GAP
    (D) any digest recorded outside the producer's reach   NONE       GAP

(B) already fails closed here — `provenance_hash_audit` re-derives and refuses
on mismatch, which is more than either reference flow does. This file is about
(A), (C) and (D), which are one defect wearing three faces: **the audit's power
comes from data the audited party supplies.**

  * (C) is the cheapest and the worst. Delete the `sha256` key and the artefact
    becomes unverifiable — and unverifiable is scored as clean. That is an
    absence rendering as a pass, which this repo removes from gates one at a
    time; here it is the whole mechanism turning itself off on request.
  * (A) needs no cleverness either: the producing step writes both the artefact
    and the record that vouches for it, so it edits both and they agree.

WHAT THIS DOES, AND WHAT IT HONESTLY CANNOT DO
==============================================
It records every declared output's digest in a SECOND, INDEPENDENT ledger that
the producing step does not write, and refuses unless the two records agree AND
both exist. Concretely:

    MISMATCH    ledger digest != the bytes on disk        -> refuse
    UNRECORDED  a declared output with no ledger entry    -> refuse  (closes C)
    DISAGREE    gate report digest != ledger digest       -> refuse  (closes A)
    ORPHANED    a ledger entry whose artefact is gone     -> refuse

This does NOT make tampering impossible, and claiming it would be the same
shape of lie this file exists to catch. A process that can write anywhere can
write both records. What it does is make one consistent edit into two, put the
second one in an append-only file whose whole content is a diff a reviewer
reads, and remove the free bypass entirely — after this, deleting the digest is
a refusal rather than a pass. The remaining defence is that the ledger is a
tracked artefact: forging it is visible in the commit that does it, which is
where `no-mix` and the published-record gates already take over.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: Deliberately NOT under `gate_reports/`. The producing step writes its own
#: report there; a second record kept beside the first is one `sed` away from
#: agreeing with it, which is the (A) result above.
LEDGER_REL = "reports/provenance/artefact_digests.jsonl"

_CHUNK = 1 << 20


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for blk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(blk)
    return h.hexdigest()


def _norm(d: Any) -> str:
    """A digest, without the `sha256:` prefix and case, or "" if absent."""
    return str(d or "").lower().replace("sha256:", "").strip()


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------
def ledger_path(project: Path) -> Path:
    return project / LEDGER_REL


def read_ledger(project: Path) -> List[Dict[str, Any]]:
    p = ledger_path(project)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            # A corrupt line is NOT skipped silently — an unreadable ledger
            # must not read as an empty one, which would be a clean verdict
            # over nothing. Surfaced as a sentinel the verifier refuses on.
            out.append({"_corrupt": line[:200]})
    return out


def record(project: Path, step: str, outputs: List[str]) -> Tuple[int, List[str]]:
    """Append one entry per declared output. APPEND-ONLY BY CONTRACT.

    Re-recording the same (step, path) with a DIFFERENT digest does not
    overwrite: both lines stay, and `verify` reports REDECLARED. A ledger that
    let the second write win would be exactly the single record the producer
    already controls.
    """
    msgs: List[str] = []
    lp = ledger_path(project)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for rel in outputs:
        f = project / rel
        if not f.is_file():
            msgs.append(f"[SKIP] {rel}: not a file at record time")
            continue
        lines.append(json.dumps({"step": step, "path": rel,
                                 "sha256": sha256_file(f)},
                                sort_keys=True))
        msgs.append(f"[REC ] {step}: {rel}")
    if lines:
        with lp.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    if not outputs:
        msgs.append("[NOTE] no outputs given — nothing recorded")
    return 0, msgs


# --------------------------------------------------------------------------
# what the producing step claims, read back for cross-checking
# --------------------------------------------------------------------------
def gate_report_claims(project: Path) -> Dict[str, str]:
    """{declared output path -> digest the GATE REPORT claims} ("" if none).

    Same `output_files` shape `provenance_hash_audit` already reads, so this
    does not invent a second declaration format for the same fact.
    """
    claims: Dict[str, str] = {}
    gdir = project / "gate_reports"
    if not gdir.is_dir():
        return claims
    for rp in sorted(gdir.rglob("*.json")):
        try:
            doc = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        for ent in doc.get("output_files") or []:
            if isinstance(ent, dict):
                path, dig = ent.get("path"), ent.get("sha256") or ent.get("hash")
            elif isinstance(ent, str):
                path, dig = ent, None
            else:
                continue
            if path:
                # First claim wins; a second, DIFFERENT claim for one path is
                # itself a disagreement and is surfaced rather than merged.
                prev = claims.get(str(path))
                if prev is None or not prev:
                    claims[str(path)] = _norm(dig)
    return claims


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------
def verify(project: Path, require_ledger: bool = True) -> Dict[str, Any]:
    findings: List[Dict[str, str]] = []
    entries = read_ledger(project)
    claims = gate_report_claims(project)

    def add(cat: str, msg: str) -> None:
        findings.append({"category": cat, "message": msg})

    corrupt = [e for e in entries if "_corrupt" in e]
    for c in corrupt:
        add("LEDGER_CORRUPT",
            f"unparseable ledger line: {c['_corrupt'][:120]}")
    entries = [e for e in entries if "_corrupt" not in e]

    # (D)/(C): a declared output with no independent record is UNVERIFIABLE, and
    # unverifiable must not score as clean.
    recorded: Dict[str, List[str]] = {}
    for e in entries:
        p = str(e.get("path") or "")
        if p:
            recorded.setdefault(p, []).append(_norm(e.get("sha256")))

    for path, digests in sorted(recorded.items()):
        f = project / path
        if not f.is_file():
            add("ORPHANED", f"{path}: ledger records a digest, artefact is gone")
            continue
        actual = sha256_file(f)
        uniq = sorted(set(d for d in digests if d))
        if len(uniq) > 1:
            add("REDECLARED",
                f"{path}: ledger holds {len(uniq)} DIFFERENT digests for one "
                f"(step, path) — the artefact was re-recorded after production")
            continue
        if uniq and actual != uniq[0]:
            add("MISMATCH",
                f"{path}: ledger {uniq[0][:16]}.. != on-disk {actual[:16]}..")

    for path, claimed in sorted(claims.items()):
        if path not in recorded:
            if require_ledger:
                add("UNRECORDED",
                    f"{path}: a gate report declares this output and the "
                    f"independent ledger has no entry for it — nothing "
                    f"establishes it is what the step produced")
            continue
        led = next((d for d in recorded[path] if d), "")
        if not claimed:
            add("UNCLAIMED",
                f"{path}: the gate report declares this output with NO digest, "
                f"so the report vouches for nothing; the ledger has one")
        elif led and claimed != led:
            add("DISAGREE",
                f"{path}: gate report says {claimed[:16]}.. and the "
                f"independent ledger says {led[:16]}..")

    return {
        "program": "artefact_digest_ledger",
        "project": str(project),
        "ledger": str(ledger_path(project)),
        "ledger_entries": len(entries),
        "declared_outputs": len(claims),
        "verified": len(recorded),
        "findings": findings,
        "pass": not findings,
    }


def _print(res: Dict[str, Any]) -> None:
    if res["ledger_entries"] == 0 and res["declared_outputs"] == 0:
        print("[SKIP] artefact_digest_ledger: no ledger and no declared "
              "output — 0 artefact(s) examined, and this is NOT a pass over "
              "any artefact")
        return
    for f in res["findings"]:
        print(f"[FAIL] {f['category']}: {f['message']}")
    verdict = "PASS" if res["pass"] else "FAIL"
    print(f"[{verdict}] artefact_digest_ledger: {res['verified']} artefact(s) "
          f"re-derived against an independent ledger of "
          f"{res['ledger_entries']} entry(ies); "
          f"{res['declared_outputs']} declared output(s) cross-checked; "
          f"{len(res['findings'])} finding(s)")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Record and verify artefact digests in a ledger the "
                    "producing step does not own (vibe-ic#1116).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="append digests for declared outputs")
    r.add_argument("project")
    r.add_argument("--step", required=True)
    r.add_argument("--output", action="append", default=[])

    v = sub.add_parser("verify", help="re-derive and cross-check")
    v.add_argument("project")
    v.add_argument("--json")
    v.add_argument("--allow-unrecorded", action="store_true",
                   help="do not refuse a declared output that has no ledger "
                        "entry. MIGRATION ONLY: it reopens (C), the cheapest "
                        "of the four tampering methods.")

    a = ap.parse_args(argv)
    project = Path(a.project).resolve()
    if not project.is_dir():
        print(f"[ERROR] not a directory: {project}", file=sys.stderr)
        return 2

    if a.cmd == "record":
        rc, msgs = record(project, a.step, a.output)
        for m in msgs:
            print(m)
        return rc

    res = verify(project, require_ledger=not a.allow_unrecorded)
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(res, indent=2) + "\n")
    _print(res)
    if res["ledger_entries"] == 0 and res["declared_outputs"] == 0:
        # "I could not look" is rc 2 here, never 0 — the `_vacuous_exit`
        # convention this repo applies to every other gate.
        return 2
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
