#!/usr/bin/env python3
"""CITATION_ROUTING.txt says whether a reader can follow each citation. Check it.

WHY THIS EXISTS
---------------
`CITATION_ROUTING.txt` is the artefact vibe-ic#448 added so that a citation the
published layout cannot carry is RECORDED as out of scope rather than left to
dangle. Its own header promises it answers "whether a reader of THIS cell can
follow it", and `benchmark_evidence_publish` states the same intent at the call
site: "Read from the STAGED tree, so it answers the reader's question — can I
follow this from what I received? — not the run's."

Nothing checked that the file it ships with is the tree it describes.

MEASURED, on the caravel_user_project x sky130A cell as committed:

    RESOLVES rows                                189
    of those, the cited file is not findable       8

        reports/orchestrator/phase2_one_shot.json :: phase2/stage2/synth/yosys.log
        reports/orchestrator/phase3_one_shot.json :: phase2/stage2/synth/synth.log
        reports/phase2/dft/path_delay_coverage.json :: phase2/stage2/dft/pdf/sat_run.log
        reports/phase2/dft/transition_coverage.json :: phase2/stage2/dft/tdf/sat_run.log
        reports/phase2/gates/yosys_hilomap.json :: phase2/stage2/synth/synth.log
        reports/phase2/gates/cpu_functional_oracle_waiver.json :: …/full_stack.log
        reports/phase2/gates/yosys_script_template.json :: phase2/stage2/synth/synth.log
        reports/orchestrator/phase2_one_shot.json :: …/generic_full_stack_run/full_stack.log

The publisher's rule is `(dest / cited).exists()` — correct when it runs. The
record is then committed and never re-derived, so any later pruning of the cell
leaves rows asserting RESOLVES about files that no longer ship. The artefact
whose job is to tell you whether you can follow a pointer was reporting the good
outcome for eight pointers it could not follow — an absence rendering as a pass,
inside the very record built to stop that.

WHAT IT CHECKS, AND WHAT IT DELIBERATELY DOES NOT
-------------------------------------------------
ONLY the `RESOLVES` rows, and only that the cited file is findable from the cell
as committed. The disclosure decisions — OUT_OF_PUBLISHED_SCOPE, DANGLING,
DANGLING_UNDER_PASS, UNFOLLOWABLE_ABSOLUTE — are claims that a reader CANNOT
follow something, and this gate has no business second-guessing them: they are
what the record is for, and a wrong one costs a reader nothing but an
unnecessary "not here". A wrong RESOLVES sends them looking.

Resolution walks the same ladder the citing document's reader would: the
document's own directory, then each ancestor up to the cell root. A
single-base resolver would fabricate findings for cell-root-relative citations
— the same measurement error `evidence_citation_resolves_check` records.

WHERE ITS SUBJECT WENT (#1710's treatment, applied)
---------------------------------------------------
THIS GATE'S SUBJECT LEFT WITH THE CORPUS — it was never absent from this repo in
the first place. Every `CITATION_ROUTING.txt` is published INSIDE a converged
cell, and the four that existed were deleted by c5d7f2d0 / e23d0be5e, the commits
that moved the published results to `vibeic/benchmark-data`:

    benchmark-data/ic/caravel_user_project/v1.9.43_<pdk>/CITATION_ROUTING.txt
    benchmark-data/ic/spm/v1.10.18_<pdk>/CITATION_ROUTING.txt
    benchmark-data/ic/spm/v1.9.96_<pdk>/CITATION_ROUTING.txt
    benchmark-data/ic/u_hawaii_adc/v1.9.86_<pdk>/CITATION_ROUTING.txt

So the gate answered `[CANNOT DETERMINE] no tracked CITATION_ROUTING.txt found`,
rc 2, which `run` in `_gate_dispatch.sh` maps to FAIL. The refusal was CORRECT —
a check that could not look has not passed — and it stays. What is added is the
ability to LOOK WHERE THE RECORDS NOW ARE, and a way for the call site to say
that this repo need not carry them.

    pointer set + unreadable          -> UNDETERMINED (rc 2). Never excused.
    pointer set + not a git checkout  -> UNDETERMINED (rc 2). This gate reads
                                         git's INDEX; an empty `ls-files` over a
                                         loose directory is "I could not look",
                                         not "there are none".
    pointer set + a checkout tracking
      no record at all                -> UNDETERMINED (rc 2). Somebody named a
                                         corpus that carries none of this gate's
                                         subject; that is a broken pointer, not
                                         an absent one.
    nothing anywhere + the CALL SITE
      opted in                        -> NO_CORPUS (rc 0). Nothing scanned and
                                         NOTHING CLAIMED to have been scanned.
    nothing anywhere + nobody said so -> UNDETERMINED (rc 2). Unchanged.

The two populations are UNIONED, not swapped: records tracked in THIS repo are
still adjudicated when a corpus is also supplied. A record that comes home must
not stop being judged because a pointer is set.

chip-AGNOSTIC: pure filesystem structure. No design, PDK, vendor or value
literal appears here.

USAGE
-----
    citation_routing_is_true_check.py [--root .] [--json OUT]
                                      [--corpus-may-be-absent]
    VIBE_IC_BENCHMARK_DATA=/path/to/benchmark-data-clone \
        citation_routing_is_true_check.py --root .

    exit 0 = every RESOLVES row resolves, or NO_CORPUS (opted in, and it says
             nothing was scanned)
    exit 1 = at least one does not (BLOCKING)
    exit 2 = could not be determined (no record found, unreadable record, a
             corpus pointer that is set and wrong) — never a vacuous pass
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import _corpus_location as _corpus         # sibling program, one seam for all

_ROUTING_NAME = "CITATION_ROUTING.txt"

#: Where a caller may point us at a clone of the published corpus. Taken from
#: `_corpus_location` rather than re-spelled here: one name for one thing.
#:
#: `_corpus_location.resolve` is deliberately NOT used to pick this gate's scan
#: root. That helper answers "the named corpus is missing — may I use the
#: pointer instead?", and this gate's named root is the REPOSITORY, which always
#: exists. Here the corpus is an ADDITIONAL population, not a replacement one:
#: see the union in `main`.
CORPUS_ENV = _corpus.CORPUS_ENV
_RESOLVES = "RESOLVES"
# The decisions that assert a reader CANNOT follow the citation. Listed so a
# decision word this gate has never seen is reported rather than silently
# treated as one of them.
_DISCLOSURES = {"OUT_OF_PUBLISHED_SCOPE", "DANGLING", "DANGLING_UNDER_PASS",
                "UNFOLLOWABLE_ABSOLUTE"}


def parse_routing(text: str) -> Tuple[List[Tuple[str, str, str]], List[str]]:
    """(rows, unknown_decisions) from a CITATION_ROUTING.txt body.

    A row is `<doc> :: <cited> <DECISION>`. Comment and blank lines are skipped.
    A line that does not end in a known decision word is returned as unknown
    rather than dropped — a vocabulary this gate does not recognise must be
    visible, not absorbed."""
    rows, unknown = [], []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or " :: " not in s:
            continue
        rest, _, decision = s.rpartition(" ")
        if not decision or " :: " not in rest:
            unknown.append(s)
            continue
        doc, _, cited = rest.partition(" :: ")
        doc, cited = doc.strip(), cited.strip()
        if not doc or not cited:
            unknown.append(s)
            continue
        if decision != _RESOLVES and decision not in _DISCLOSURES:
            unknown.append(s)
            continue
        rows.append((doc, cited, decision))
    return rows, unknown


def resolves(cell: Path, doc: str, cited: str) -> bool:
    """True iff `cited` is findable from `doc` by the ladder a reader walks:
    the document's own directory first, then each ancestor up to the cell."""
    if cited.startswith("/"):
        return False              # never followable for anyone but the author
    base = (cell / doc).parent
    while True:
        if (base / cited).exists():
            return True
        if base == cell or cell not in base.parents:
            return False
        base = base.parent


def audit_cell(cell: Path) -> Dict:
    text = (cell / _ROUTING_NAME).read_text(encoding="utf-8", errors="replace")
    rows, unknown = parse_routing(text)
    claimed = [(d, c) for d, c, k in rows if k == _RESOLVES]
    false_claims = [(d, c) for d, c in claimed if not resolves(cell, d, c)]
    return {"cell": cell.as_posix(), "rows": len(rows),
            "resolves_rows": len(claimed),
            "false_claims": [{"doc": d, "cited": c} for d, c in false_claims],
            "unparsed": unknown}


def tracked_routing_files(root: Path) -> Optional[List[Path]]:
    """Every tracked CITATION_ROUTING.txt. None when git cannot answer — an
    untracked scan would judge a working tree nobody published."""
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files",
                            f"*/{_ROUTING_NAME}"],
                           capture_output=True, text=True, errors="replace",
                           timeout=55)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return [root / ln for ln in r.stdout.splitlines() if ln.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="the caller asserts this repo need not carry the "
                         "published corpus. Turns 'no record tracked anywhere' "
                         "from UNDETERMINED into NO_CORPUS (rc 0), which STATES "
                         "that nothing was adjudicated. It does NOT excuse a "
                         f"pointer that is set and broken: ${CORPUS_ENV} aimed "
                         "at something unreadable, at a directory that is not a "
                         "git checkout, or at a checkout tracking no "
                         f"{_ROUTING_NAME} at all stays UNDETERMINED.")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()

    files = tracked_routing_files(root)
    if files is None:
        print("[CANNOT DETERMINE] citation_routing_is_true: git could not list "
              "tracked files, so no published record was read. NOT a pass.",
              file=sys.stderr)
        return 2

    # THE CORPUS IS ADDED, NOT SWAPPED IN, AND THE OVERRIDE IS ANNOUNCED (#1710).
    # This gate's subject ships INSIDE published cells, so it left with them in
    # v1.10.56. A record that later comes home to this repo must still be judged,
    # which is why the two populations are unioned rather than exchanged.
    env_tree = _corpus.env_pointer()
    if env_tree:
        print(f"note: {CORPUS_ENV} adds a corpus to scan -> {env_tree}",
              file=sys.stderr)
        corpus = Path(env_tree)
        if not corpus.is_dir():
            # SET AND WRONG IS NOT ABSENT. A mistyped path, a failed clone or a
            # no-op CI fetch step must never come out as a green gate over
            # nothing — the exact shape #1710 closed.
            print(f"UNDETERMINED: {CORPUS_ENV}={env_tree} is set and is not a "
                  f"readable directory, so no published record was read there. "
                  f"A pointer that is set and wrong is a broken configuration, "
                  f"not an absent corpus, and --corpus-may-be-absent does not "
                  f"excuse it.", file=sys.stderr)
            return 2
        _loose = _corpus.not_a_checkout_reason(corpus,
                                               f"tracked {_ROUTING_NAME}")
        if _loose:
            print(f"UNDETERMINED: {_loose} Point {CORPUS_ENV} at a clone.",
                  file=sys.stderr)
            return 2
        corpus_files = tracked_routing_files(corpus)
        if corpus_files is None:
            print(f"[CANNOT DETERMINE] citation_routing_is_true: git could not "
                  f"list tracked files under {env_tree}, so the corpus was not "
                  f"read. NOT a pass.", file=sys.stderr)
            return 2
        if not corpus_files:
            # The pointer was SET and led to a checkout carrying none of this
            # gate's subject. That is somebody's broken configuration, and the
            # opt-in must not reach it.
            print(f"UNDETERMINED: {CORPUS_ENV}={env_tree} is a git checkout but "
                  f"tracks no {_ROUTING_NAME} at all. A corpus that was NAMED "
                  f"and carries none of this gate's subject is a wrong pointer, "
                  f"not an absent corpus.", file=sys.stderr)
            return 2
        print(f"note: {len(corpus_files)} tracked {_ROUTING_NAME} under "
              f"{env_tree}, {len(files)} under {root}", file=sys.stderr)
        files = files + corpus_files

    if not files:
        if a.corpus_may_be_absent:
            # rc 0, and it must never read as an adjudication that happened.
            print(f"NO_CORPUS: no tracked {_ROUTING_NAME} under {root} and "
                  f"{CORPUS_ENV} is unset. This gate's subject ships inside a "
                  f"published cell, and the published cells live in their own "
                  f"repository now. NOTHING WAS SCANNED — 0 record(s) read, "
                  f"0 RESOLVES row(s) adjudicated and nothing is claimed. Point "
                  f"{CORPUS_ENV} at a clone to make this gate check something.",
                  file=sys.stderr)
            return 0
        print("[CANNOT DETERMINE] citation_routing_is_true: no tracked "
              f"{_ROUTING_NAME} found under {root}. NOT a pass. Set "
              f"{CORPUS_ENV}, or pass --corpus-may-be-absent if this repo need "
              f"not carry a corpus.", file=sys.stderr)
        return 2

    reports = [audit_cell(f.parent) for f in files]
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(reports, indent=2))

    bad = [r for r in reports if r["false_claims"]]
    unparsed = [r for r in reports if r["unparsed"]]
    total_rows = sum(r["resolves_rows"] for r in reports)

    for r in unparsed:
        print(f"[WARN] {r['cell']}: {len(r['unparsed'])} row(s) in an "
              f"unrecognised form — reported, not assumed:")
        for s in r["unparsed"][:5]:
            print(f"   {s}")

    if bad:
        n = sum(len(r["false_claims"]) for r in bad)
        print(f"[FAIL] {n} row(s) claim {_RESOLVES} for a citation a reader of "
              f"the published cell CANNOT follow:")
        for r in bad:
            for f in r["false_claims"]:
                print(f"   {r['cell']}: {f['doc']} :: {f['cited']}")
        print(f"\n  REMEDY: re-derive the cell's {_ROUTING_NAME} against the "
              f"tree as committed —\n"
              f"  the decision belongs to the deliverable the reader receives, "
              f"not to the run\n  directory it was published from. A citation "
              f"the published layout cannot carry is\n  recorded as out of "
              f"scope; it is never recorded as resolving.")
        return 1

    print(f"[PASS] citation_routing_is_true: {len(reports)} tracked record(s), "
          f"{total_rows} {_RESOLVES} row(s) — every one is followable from the "
          f"cell as committed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# selector-probe: no-op line added by the xdist equivalence experiment
