#!/usr/bin/env python3
"""artefact_digest_ledger.py — a digest record the producing step cannot rewrite
without being caught (vibe-ic#1116).

THE DEFECT, REPRODUCED AGAINST OUR OWN MACHINERY
================================================
#1116 measured four tampering methods against LibreLane 3.0.8 and ORFS and all
four succeeded. The narrower question that decides what we must build is whether
OUR `provenance.jsonl` is any better. It is better against ONE attacker and not
against the other, measured:

    honest artefact                     -> audit PASS
    edit the ARTEFACT only              -> audit FAIL   (caught)
    edit the artefact AND the record    -> audit PASS   (NOT caught)

`provenance_logger.py`'s own docstring argues the second case is hard:

    A cheating agent CAN write a fake entry — but they'd have to:
      (i)  write a .jsonl entry AND
      (ii) make the file on disk hash to the value in the entry
    ... "hash collision required"

**(ii) is only hard if the entry is FIXED.** An adversary who writes the
artefact FIRST and then records its hash needs no collision at all — it controls
both sides. `provenance.jsonl` lives at `<project>/provenance.jsonl`, inside the
run directory the step writes, so both sides are always in reach. That is
#1116's requirement 3: *"A hash the producer writes next to its own output
proves nothing against a producer that edits both."*

WHAT THIS ADDS, AND WHAT IT HONESTLY DOES NOT
=============================================
A HASH-CHAINED ledger. Entry N carries the chain value of entry N-1, so the
chain head is a function of EVERY entry ever appended:

    chain_0 = sha256(GENESIS)
    chain_N = sha256(chain_{N-1} || canonical_json(entry_N))

Rewriting or removing any entry changes the head. Verification re-derives the
whole chain from the entries and compares against an ANCHOR.

**The anchor is the trust boundary, and it is stated rather than hidden.** A
chain alone is not enough: an adversary who rewrites the ledger can also
recompute the head stored inside it. What the chain buys is that the head is a
single small value which can be kept somewhere the step does not write —
`--anchor`, defaulting OUTSIDE the run directory. Everything this module
promises is conditional on that one file being out of the producer's reach.

So this is not "tamper-proof". It is **tamper-EVIDENT with an explicit, named
boundary**, which is the achievable form of #1116 requirement 3 without a
separate signing service. If the anchor is inside the run dir, this degrades to
exactly today's guarantee — and `verify` says so out loud rather than reporting
a pass it has not earned.

EXIT CODES follow the repo convention: 0 PASS, 1 FAIL, 2 VACUOUS/could-not-look.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082

GENESIS = "vibe-ic/artefact-digest-ledger/1"
LEDGER_NAME = "artefact_digest_ledger.jsonl"
ANCHOR_NAME = "artefact_digest_anchor.json"

RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _canonical(entry: dict) -> str:
    """Byte-stable rendering. `chain` is excluded — it is derived FROM this."""
    return json.dumps({k: v for k, v in sorted(entry.items()) if k != "chain"},
                      separators=(",", ":"), ensure_ascii=False)


def chain_next(prev: str, entry: dict) -> str:
    return hashlib.sha256((prev + _canonical(entry)).encode("utf-8")).hexdigest()


def read_ledger(ledger: Path):
    if not ledger.is_file():
        return []
    out = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def derive_head(entries) -> str:
    """Re-derive the chain head from the entries alone."""
    head = hashlib.sha256(GENESIS.encode("utf-8")).hexdigest()
    for e in entries:
        head = chain_next(head, e)
    return head


def append(run_dir: Path, anchor: Path, step: str, paths) -> dict:
    """Record a digest for each path, extend the chain, re-anchor the head."""
    ledger = run_dir / LEDGER_NAME
    entries = read_ledger(ledger)
    head = derive_head(entries)
    added = []
    for rel in paths:
        p = run_dir / rel
        if not p.is_file():
            raise FileNotFoundError(f"declared output not produced: {rel}")
        entry = {"seq": len(entries), "step": step,
                 "path": str(rel), "digest": sha256_file(p)}
        head = chain_next(head, entry)
        entry["chain"] = head
        entries.append(entry)
        added.append(entry)
    with open(ledger, "a", encoding="utf-8") as fh:
        for e in added:
            fh.write(json.dumps(e, separators=(",", ":"), ensure_ascii=False) + "\n")
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text(json.dumps({"_comment": (
        "Chain head for the artefact digest ledger (vibe-ic#1116). This file is "
        "the trust boundary: it MUST live outside the run directory the "
        "producing step writes, or the guarantee degrades to the pre-#1116 one."),
        "head": head, "entries": len(entries)}, indent=2) + "\n", encoding="utf-8")
    return {"head": head, "added": len(added)}


def verify(run_dir: Path, anchor: Path) -> dict:
    """Re-derive every digest and the chain; compare against the anchor."""
    ledger = run_dir / LEDGER_NAME
    entries = read_ledger(ledger)
    rep = {"run_dir": str(run_dir), "anchor": str(anchor),
           "entries": len(entries), "findings": [],
           "anchor_inside_run_dir": False}

    try:
        rep["anchor_inside_run_dir"] = (
            os.path.commonpath([anchor.resolve(), run_dir.resolve()])
            == str(run_dir.resolve()))
    except ValueError:
        rep["anchor_inside_run_dir"] = False

    if not entries:
        rep["verdict"] = "VACUOUS"
        rep["reason"] = f"no ledger at {ledger} — nothing was recorded to verify"
        return rep

    # 1. Every recorded artefact must still hash to what was recorded.
    for e in entries:
        p = run_dir / e["path"]
        if not p.is_file():
            rep["findings"].append(
                f"seq {e['seq']}: recorded artefact {e['path']!r} is GONE")
            continue
        now = sha256_file(p)
        if now != e["digest"]:
            rep["findings"].append(
                f"seq {e['seq']}: {e['path']!r} CONTENT CHANGED since it was "
                f"recorded (recorded {e['digest'][:20]}..., now {now[:20]}...)")

    # 2. The chain must re-derive. This is what catches a COORDINATED edit:
    #    updating an entry's digest changes every chain value after it.
    head = hashlib.sha256(GENESIS.encode("utf-8")).hexdigest()
    for e in entries:
        head = chain_next(head, e)
        if e.get("chain") != head:
            rep["findings"].append(
                f"seq {e['seq']}: CHAIN BROKEN — entry records "
                f"{str(e.get('chain'))[:16]}..., re-derives to {head[:16]}... "
                f"(an entry at or before this one was rewritten)")
            break
    rep["derived_head"] = head

    # 3. The head must match the anchor, which is the half a run-dir-only
    #    attacker cannot reach.
    if not anchor.is_file():
        rep["findings"].append(
            f"no anchor at {anchor} — the chain head is unattested, so a "
            f"wholesale rewrite of the ledger would be undetectable")
    else:
        want = json.loads(anchor.read_text(encoding="utf-8")).get("head")
        rep["anchor_head"] = want
        if want != head:
            rep["findings"].append(
                f"ANCHOR MISMATCH — anchored head {str(want)[:16]}..., ledger "
                f"re-derives to {head[:16]}...; the ledger was rewritten")

    rep["verdict"] = "FAIL" if rep["findings"] else "PASS"
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append", help="record digests for declared outputs")
    a.add_argument("run_dir", type=Path)
    a.add_argument("--step", required=True)
    a.add_argument("--output", action="append", default=[], dest="outputs")
    a.add_argument("--anchor", type=Path)
    v = sub.add_parser("verify", help="re-derive digests + chain vs the anchor")
    v.add_argument("run_dir", type=Path)
    v.add_argument("--anchor", type=Path)
    v.add_argument("--json", dest="json_out", type=Path)
    args = ap.parse_args(argv)

    run_dir = args.run_dir
    anchor = args.anchor or (run_dir.parent / ANCHOR_NAME)

    if args.cmd == "append":
        if not args.outputs:
            print("[FAIL] append needs at least one --output", file=sys.stderr)
            return RC_FAIL
        res = append(run_dir, anchor, args.step, args.outputs)
        print(f"[OK] recorded {res['added']} digest(s); chain head "
              f"{res['head'][:16]}... anchored at {anchor}", file=sys.stderr)
        return RC_PASS

    rep = verify(run_dir, anchor)
    if args.json_out:
        atomic_write_text(args.json_out,
                          json.dumps(rep, indent=2) + "\n", encoding="utf-8")

    if rep["verdict"] == "VACUOUS":
        print(f"[VACUOUS] artefact_digest_ledger: {rep['reason']} — this is NOT "
              f"a pass over the artefacts", file=sys.stderr)
        return RC_VACUOUS

    if rep["anchor_inside_run_dir"]:
        print(f"[WARN] the anchor {anchor} is INSIDE the run directory, which "
              f"the producing step writes. The chain is still checked, but a "
              f"producer that rewrites both degrades this to the pre-#1116 "
              f"guarantee (vibe-ic#1116 requirement 3).", file=sys.stderr)

    if rep["verdict"] == "FAIL":
        print(f"[FAIL] artefact_digest_ledger: {len(rep['findings'])} finding(s) "
              f"over {rep['entries']} recorded artefact(s):", file=sys.stderr)
        for f in rep["findings"]:
            print(f"    {f}", file=sys.stderr)
        print("\nThe evidence is not what it claims to be. This is not a "
              "warning — a consumer must refuse to read these artefacts.",
              file=sys.stderr)
        return RC_FAIL

    print(f"[PASS] artefact_digest_ledger: {rep['entries']} artefact(s) "
          f"re-derived, chain intact, head matches the anchor.", file=sys.stderr)
    return RC_PASS


if __name__ == "__main__":
    raise SystemExit(main())
