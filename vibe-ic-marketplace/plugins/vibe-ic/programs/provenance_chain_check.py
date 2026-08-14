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


#: vibe-ic#1116 / BATCH IDX group (a) — CORPUS MODE, and why it REFUSES instead
#: of passing. This checker was reachable only from its own test: a fixture the
#: author wrote proves the logic, never the artefacts. Wiring it needs a
#: population, and the population is every run root that carries a ledger.
#:
#: MEASURED 2026-08-14 on this branch: 22 tracked ledgers, and after the
#: vacuous-pass repair below, 22 of 22 are NOT_CHECKED — `chain_prev` is
#: introduced by this very PR, so no published run can carry one yet. A corpus
#: whose every member is uncheckable must not report PASS, which is why the
#: hygiene script calls this through `run_tolerating_uncheckable`: it exits 2
#: and says how many, instead of printing a green line over 22 unverified
#: ledgers. The day a chained run lands, this decides with no further change.


def corpus_roots(corpus: Path) -> List[Path]:
    """Run roots under `corpus` carrying a ledger. Denominator, disclosed."""
    return sorted(q.parent for q in corpus.rglob(LEDGER_NAME) if q.is_file())


def check_corpus(corpus: Path) -> int:
    roots = corpus_roots(corpus)
    print(f"provenance_chain_check --corpus {corpus}: "
          f"{len(roots)} run root(s) carrying {LEDGER_NAME}")
    if not roots:
        print("VACUOUS: no run root under this corpus carries a provenance "
              "ledger, so no chain was verified. This is NOT a pass. rc=2.",
              file=sys.stderr)
        return RC_UNRUNNABLE
    tamper, unchecked, ok = [], [], []
    for r in roots:
        rc = main([str(r)])
        (tamper if rc == RC_TAMPER else ok if rc == RC_OK else unchecked).append(r)
    print(f"provenance_chain_check --corpus: {len(ok)} verified, "
          f"{len(unchecked)} NOT_CHECKED, {len(tamper)} TAMPER "
          f"(of {len(roots)} root(s))")
    if tamper:
        return RC_TAMPER
    if not ok:
        print(f"NOT_CHECKED: all {len(roots)} ledger(s) were unverifiable, so "
              f"this gate has never met a chain it could check. Reporting PASS "
              f"here would be a green line over {len(roots)} unverified "
              f"ledgers. rc=2.", file=sys.stderr)
        return RC_UNRUNNABLE
    return RC_OK


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("project", type=Path, nargs="?")
    ap.add_argument("--corpus", type=Path, default=None, metavar="DIR",
                    help="verify every run root under DIR that carries "
                         "a ledger; exits 2 when none is verifiable")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(list(argv) if argv is not None else None)
    if args.corpus is not None:
        return check_corpus(args.corpus.resolve())
    if args.project is None:
        ap.error("give a project path or --corpus DIR")

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

    #: A chain over ZERO chained records is vacuously intact, and reporting it
    #: as [PASS] is the shape this program exists to refuse — one level up.
    #: The guard used to read `len(recs) > 1 and chained == 0`, so a ledger with
    #: exactly ONE record escaped it and printed "chain intact across 0 chained
    #: record(s)". MEASURED on this tree: 13 of the 22 tracked ledgers are
    #: single-record, so wiring this checker into the corpus run would have
    #: reported 13 PASSes having verified no chain at all.
    #:
    #: The two reasons are distinct and are said separately, because "cannot"
    #: and "did not" are different facts about the evidence:
    #:   * ONE record  — `chain_prev` lives on records[1:], so a lone record can
    #:     never carry one. Structurally unchainable, not a defect in the run.
    #:   * MANY records, none chained — written before the chain existed.
    if chained == 0:
        why = ("a single record: `chain_prev` is written on the records AFTER "
               "the first, so a one-record ledger is structurally unchainable"
               if len(recs) <= 1 else
               f"{len(recs)} records and NONE carries `chain_prev` — this "
               f"ledger predates vibe-ic#1116")
        print(f"NOT_CHECKED: {why}. The digests still re-derived "
              f"({digests_checked} checked), which catches a file edited "
              f"without its ledger line, but nothing here can detect a ledger "
              f"edited to match. Not a pass.", file=sys.stderr)
        return RC_UNRUNNABLE

    print(f"[PASS] chain intact across {chained} chained record(s); "
          f"{digests_checked} output digest(s) re-derive")
    print("    TAMPER-EVIDENT, NOT TAMPER-PROOF: an attacker who rewrites the "
          "whole ledger can recompute the chain. There is no anchor outside "
          "the producer's reach (vibe-ic#1116, remaining half).")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
