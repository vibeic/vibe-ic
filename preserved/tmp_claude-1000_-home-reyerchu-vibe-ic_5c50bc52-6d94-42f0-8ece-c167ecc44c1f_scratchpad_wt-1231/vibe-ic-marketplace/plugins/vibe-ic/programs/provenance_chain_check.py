#!/usr/bin/env python3
"""provenance_chain_check — was the ledger itself edited?  (vibe-ic#1116)

THE QUESTION, AND WHY THE EXISTING DIGESTS DO NOT ANSWER IT
===========================================================
`provenance_logger` records a sha256 per declared output and
`provenance_declared_output_check` re-derives them — measured on the three
published spm cells, `hash mismatches 0`. That is real and it catches the
"echo text to file" case: a file edited WITHOUT its ledger line.

It does not catch an agent that edits both. #1116 measured the attack:

    honest    : ledger digest == file digest -> True
    edit both : ledger digest == file digest -> True

No hash collision is required — the artefact and the ledger are both writable
and both live in the run root the producer owns, so it is two edits. The
motivating case is not hypothetical: an engineer reported an agent editing a
netlist until an N2N formal check passed. That is an optimiser doing what it
was asked, and if the evidence is writable, editing the evidence is a valid and
cheaper solution than fixing the design.

WHAT THIS ADDS
==============
`provenance_logger` now writes `chain_prev` — the sha256 of the PRECEDING
record line, exactly as written. This program recomputes the chain over the
file:

    record N's chain_prev  ==  sha256(record N-1's line)

Editing any record invalidates every record after it, so the two-edit attack is
detected unless the attacker rewrites the entire ledger and recomputes the whole
chain.

WHAT THIS IS NOT, said plainly because overstating it is the exact defect this
program exists to correct. `provenance_logger`'s docstring used to claim that
forging an entry required a hash collision. It did not, and nobody re-checked
because the claim sounded sufficient. So:

    THIS IS TAMPER-EVIDENT, NOT TAMPER-PROOF.

An attacker who can rewrite the whole file can recompute the chain and this
program will report an intact chain. The chain has no anchor outside the
producer's reach — that is the remaining half of #1116 and it is NOT delivered
here. A published cell gets one for free (git tracks both the artefact and the
ledger, so a post-publish edit shows in `git status`); an in-flight run does
not, and this program says which case it is in.

EXIT
    0  every record's chain_prev matches, and every recorded output digest
       re-derives. The counts are printed either way.
    1  a chain break or a digest mismatch — the evidence is not what it claims
       to be. Never a warning: a mismatch means the file is not the file the
       step produced.
    2  the question could not be asked: no ledger, an unparseable ledger, or a
       ledger with NO chain at all (written before #1116). NOT a pass — "no
       chain" and "an intact chain" are different observations, and folding the
       first into the second is how a checker reports confidence it never
       earned.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

RC_OK, RC_TAMPER, RC_UNRUNNABLE = 0, 1, 2
LEDGER_NAME = "provenance.jsonl"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def read_records(ledger: Path) -> Tuple[List[dict], List[bytes]]:
    """Records and the RAW lines they came from.

    The raw line is what the chain is computed over, so it must be the bytes on
    disk rather than a re-serialisation of the parsed record — `json.dumps` of
    an equal dict is not necessarily the same bytes, and a chain that compared
    re-serialised text would break on formatting and pass on a real edit.
    """
    recs: List[dict] = []
    raws: List[bytes] = []
    with ledger.open("rb") as f:
        for raw in f:
            if not raw.strip():
                continue
            try:
                recs.append(json.loads(raw))
            except json.JSONDecodeError:
                raise ValueError(f"unparseable ledger line {len(raws) + 1}")
            raws.append(raw.rstrip(b"\n"))
    return recs, raws


def verify_chain(recs: Sequence[dict], raws: Sequence[bytes]) -> List[str]:
    """Chain breaks, as human-readable findings. Empty == intact."""
    out: List[str] = []
    for i in range(1, len(recs)):
        claimed = recs[i].get("chain_prev")
        if claimed is None:
            continue                      # counted separately as "unchained"
        # The logger's own hasher emits `sha256:<hex>`; the outputs map uses the
        # same spelling. Normalise BOTH sides rather than assuming one — the
        # first version of this compared bare hex against a prefixed value and
        # reported every honest ledger the logger writes as tampered, which the
        # producer-half test caught. A verifier that cannot read its own
        # producer's format is a verifier that cries wolf on the truth.
        claimed = str(claimed).split("sha256:", 1)[-1]
        actual = sha256_bytes(raws[i - 1])
        if claimed != actual:
            out.append(
                f"record {i + 1} claims chain_prev={claimed[:16]}… but record "
                f"{i} hashes to {actual[:16]}… — the ledger was edited between "
                f"them, or a record was inserted/removed")
    return out


def verify_digests(project: Path, recs: Sequence[dict]) -> Tuple[List[str], int]:
    """Recorded output digests re-derived from the files on disk."""
    out: List[str] = []
    checked = 0
    for i, rec in enumerate(recs, 1):
        for rel, claimed in (rec.get("outputs") or {}).items():
            want = str(claimed).split("sha256:", 1)[-1]
            p = project / rel
            if not p.is_file():
                continue                  # `provenance_declared_output_check` owns absence
            got = sha256_file(p)
            checked += 1
            if got is not None and got != want:
                out.append(
                    f"record {i}: {rel} hashes to {got[:16]}… but the ledger "
                    f"records {want[:16]}… — the artefact is not the one the "
                    f"step produced")
    return out, checked


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(list(argv) if argv is not None else None)

    project = args.project.resolve()
    ledger = project / LEDGER_NAME
    if not ledger.is_file():
        print(f"provenance_chain_check: UNRUNNABLE — no {LEDGER_NAME} under "
              f"{project}; there is no ledger to verify", file=sys.stderr)
        return RC_UNRUNNABLE
    try:
        recs, raws = read_records(ledger)
    except ValueError as exc:
        print(f"provenance_chain_check: UNRUNNABLE — {exc}", file=sys.stderr)
        return RC_UNRUNNABLE
    if not recs:
        print(f"provenance_chain_check: UNRUNNABLE — {LEDGER_NAME} holds no "
              f"records; a chain over nothing is not an intact chain",
              file=sys.stderr)
        return RC_UNRUNNABLE

    chained = sum(1 for r in recs[1:] if r.get("chain_prev") is not None)
    chain_breaks = verify_chain(recs, raws)
    digest_breaks, digests_checked = verify_digests(project, recs)

    # THE DENOMINATOR IS PRINTED WHATEVER THE VERDICT.
    print(f"provenance_chain_check: {len(recs)} record(s), {chained} chained, "
          f"{digests_checked} output digest(s) re-derived")

    report = {"records": len(recs), "chained": chained,
              "digests_checked": digests_checked,
              "chain_breaks": chain_breaks, "digest_breaks": digest_breaks}
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")

    if chain_breaks or digest_breaks:
        for line in chain_breaks + digest_breaks:
            print(f"  [TAMPER] {line}", file=sys.stderr)
        print("The evidence is not what it claims to be. This is not a warning.",
              file=sys.stderr)
        return RC_TAMPER

    if len(recs) > 1 and chained == 0:
        print(f"NOT_CHECKED: {len(recs)} records and NONE carries `chain_prev` "
              f"— this ledger predates vibe-ic#1116. The digests still "
              f"re-derived ({digests_checked} checked), which catches a file "
              f"edited without its ledger line, but nothing here can detect a "
              f"ledger edited to match. Not a pass.", file=sys.stderr)
        return RC_UNRUNNABLE

    print(f"[PASS] chain intact across {chained} chained record(s); "
          f"{digests_checked} output digest(s) re-derive")
    print("    TAMPER-EVIDENT, NOT TAMPER-PROOF: an attacker who rewrites the "
          "whole ledger can recompute the chain. There is no anchor outside "
          "the producer's reach (vibe-ic#1116, remaining half).")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
