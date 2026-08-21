#!/usr/bin/env python3
"""l_doc_field_producer_check.py — a field a checker READS must have a PRODUCER.

THIS GATE BLOCKS (rc=1) on a NEW reader-without-producer.

WHY THIS GATE EXISTS
--------------------
The same defect shape was measured FIVE separate times in one campaign:

    #309/#348  L21 `declared_rails`   read by the Phase-3 supply gate,
                                      populated in 3 of 30 real L21 docs
    #366       `.sby` + transcript    cited by a PASS verdict, tracked
                                      ZERO times repo-wide
    #369       `carried`/`decided`    computed by the assessment, ignored
                                      by the summary that consumed it
    #365       `duration_ms`          read from provenance, written as a
                                      hardcoded 0 that was never measured
    #312       `ai_patches`           read by 4 checkers, written by none

Three of the five were "the producer never existed". The consequence is
always the same and always silent: a checker that reads a field nobody
fills sees an EMPTY value, and an empty value is indistinguishable from a
clean one. Every PASS on that path is a false certificate — not because
anyone fabricated it, but because nothing was ever measured.

WHAT IT CHECKS  (EMPIRICAL, not static)
---------------------------------------
1. READERS — field names a checker pulls out of an L-doc `fields` dict.
2. PRODUCERS — across the real L-docs in the corpus, how many actually
   carry a NON-EMPTY value for that field.

A field with at least one reader and ZERO non-empty values across the whole
corpus is the defect: the schema knows the field (the emitter writes the
key), a consumer reads it, and no design has ever filled it.

WHY EMPIRICAL RATHER THAN STATIC. A static "who writes this key" analysis
over Python is noisy enough that its findings would need triage, and a gate
whose output needs triage gets ignored. Asking the CORPUS is exact: either
some real document carries a value or none does.

WHAT IT DELIBERATELY DOES NOT JUDGE
-----------------------------------
A field that appears in NO document at all (`present == 0`) is
INCONCLUSIVE, never a finding. It may simply live nested under another
structure that this flat scan does not reach, and reporting it would be
inventing a defect out of the scanner's own blind spot. Those fields are
COUNTED AND PRINTED so the blind spot is visible rather than silent.

WHERE THE CORPUS IS, NOW THAT IT IS NOT HERE (#1710's treatment, applied)
-------------------------------------------------------------------------
The scan root was the first ancestor directory holding `benchmark-data/ic`.
v1.10.56 moved the published corpus to its own repository, so in this repo that
directory is gone and the gate answered:

    [SKIP] l_doc_field_producer_check: no corpus
           (benchmark-data/ic not found).                            rc 2

That refusal was CORRECT for what it was asked — a check that could not look has
not passed, and `run` in `_gate_dispatch.sh` maps rc 2 to FAIL — but it was asked
the wrong question, and "the corpus is somewhere else" and "somebody pointed me
at a corpus and was wrong" came out as the same word. The FOUR outcomes, which
must not collapse:

    $VIBE_IC_BENCHMARK_DATA set + unreadable   -> UNDETERMINED (rc 2). NEVER
                                                  excused, with or without the
                                                  opt-in below.
    set + present but carrying no `ic/`        -> UNDETERMINED (rc 2). A pointer
                                                  that does not resolve to this
                                                  gate's scan root is a broken
                                                  configuration; guessing a
                                                  different subtree would be a
                                                  gate scanning a tree nobody
                                                  named.
    nothing anywhere + the CALL SITE opted in  -> NO_CORPUS (rc 0). Nothing was
                                                  scanned and NOTHING IS CLAIMED
                                                  to have been scanned.
    nothing anywhere + nobody said so          -> UNDETERMINED (rc 2). Unchanged.

The override is ANNOUNCED on stderr, and the opt-in is a flag the call site
passes — never a default.

WHY THERE IS NO "AND IT MUST BE A GIT CHECKOUT" ROW HERE, unlike
`tracked_symlink_portability_check` and `evidence_citation_resolves_check`: this
gate never reads git's INDEX. It counts VALUES inside documents with an
`rglob`, so a corpus delivered as a tarball or an archive export is a tree it
can honestly answer about. The two gates that DO read the index refuse a loose
directory, because there an empty `git ls-files` is "I could not look" wearing
the shape of "there are none".

TWO ZEROES THAT ARE NOT RESULTS (the same rule, one level in)
-------------------------------------------------------------
An EMPTY RESULT IS NOT A ZERO, and this program had two ways to produce one:

  * `--programs` aimed anywhere without `*_check.py` in it reads ZERO readers,
    so no field can have a finding and the gate prints `[PASS] no NEW
    reader-without-producer`. Nothing was analysed.
  * a corpus directory that exists and holds no L-doc scans ZERO documents, so
    `now` is empty, every recorded entry looks like it "now HAS a producer",
    and the gate FAILs with a reason that is not the truth — or, under
    `--write-baseline`, silently EMPTIES the debt register.

Both are UNDETERMINED (rc 2). A denominator of zero is a refusal, not a verdict.

chip-AGNOSTIC: field names are discovered from the checkers themselves and
counted against whatever corpus is present. No design, PDK or vendor
literal appears here.

USAGE
-----
    python3 l_doc_field_producer_check.py [CORPUS] [--programs DIR]
                                          [--json OUT] [--write-baseline]
                                          [--corpus-may-be-absent]
    VIBE_IC_BENCHMARK_DATA=/path/to/benchmark-data-clone \
        python3 l_doc_field_producer_check.py

EXIT CODES
----------
    0 = PASS, or NO_CORPUS (opted in, and it says nothing was scanned)
    1 = FAIL (new reader-without-producer)
    2 = UNDETERMINED (no corpus, a corpus pointer that is set and wrong, or a
        zero denominator on either side of the comparison)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set

import _corpus_location as _corpus         # sibling program, one seam for all
import _semantic_child_progress as _semantic_progress

# `fields.get("name")` / `f.get("name")` — the shape every L-doc checker uses
# to pull a structured value out of a layer document.
_READ_RE = re.compile(r'fields?\W{0,12}\.get\(\s*["\']([a-z0-9_]{4,40})["\']')

_DEFAULT_CORPUS_REL = "benchmark-data/ic"
_BASELINE_NAME = "l_doc_field_producer_baseline.json"

#: Where a caller may point us at a clone of the published corpus. Taken from
#: `_corpus_location` rather than re-spelled here: one name for one thing, and
#: gates that disagree about where the corpus lives will disagree about whether
#: it was checked.
CORPUS_ENV = _corpus.CORPUS_ENV

#: The pointer names the benchmark-data ROOT (that is the repository that moved);
#: this gate's population is the IC sign-off trees BELOW it, which is the same
#: `ic` suffix `_DEFAULT_CORPUS_REL` carries.
_CORPUS_SUBDIR = "ic"

#: What this gate would have examined, for the NO_CORPUS line. A zero is stated
#: over a NAMED population or it is a silence.
_SCANNED = "published L-doc(s)"

PROGRESS_SCOPE = "issue1710:l-doc-field-producer"
_ACTIVE_PROGRESS = None


def _reader_files(programs: Path) -> List[Path]:
    return sorted(programs.glob("*_check.py"))


def _document_files(corpus: Path) -> List[Path]:
    return sorted(corpus.rglob("L*_*.json"))


def semantic_progress_units(programs: Path, corpus: Path) -> List[str]:
    """Exact finite work manifest for a trusted parent invoking this gate."""
    units: List[str] = []
    for path in _reader_files(programs):
        units.extend(_semantic_progress.file_progress_units(
            path, f"reader:{path.relative_to(programs).as_posix()}"))
    for path in _document_files(corpus):
        units.extend(_semantic_progress.file_progress_units(
            path, f"document:{path.relative_to(corpus).as_posix()}"))
    return units


def _checkpoint(unit: str) -> None:
    if _ACTIVE_PROGRESS is not None:
        _ACTIVE_PROGRESS.checkpoint(unit)


def readers(programs: Path) -> Dict[str, int]:
    """{field: number of checker files that read it}."""
    out: Dict[str, int] = {}
    for p in _reader_files(programs):
        identity = f"reader:{p.relative_to(programs).as_posix()}"
        try:
            text = _semantic_progress.read_text_chunks(
                p, identity, _ACTIVE_PROGRESS)
        except OSError:
            if (_ACTIVE_PROGRESS is not None
                    and _ACTIVE_PROGRESS.enabled):
                raise
            continue
        for name in set(_READ_RE.findall(text)):
            out[name] = out.get(name, 0) + 1
        _checkpoint(_semantic_progress.file_judged_unit(p, identity))
    return out


def corpus_counts(corpus: Path, names: Set[str]):
    """(docs_scanned, {field: present}, {field: populated})."""
    present: Dict[str, int] = {n: 0 for n in names}
    populated: Dict[str, int] = {n: 0 for n in names}
    docs = 0
    for p in _document_files(corpus):
        identity = f"document:{p.relative_to(corpus).as_posix()}"
        try:
            text = _semantic_progress.read_text_chunks(
                p, identity, _ACTIVE_PROGRESS)
        except OSError:
            if (_ACTIVE_PROGRESS is not None
                    and _ACTIVE_PROGRESS.enabled):
                raise
            continue
        try:
            data = json.loads(text)
        except ValueError:
            _checkpoint(_semantic_progress.file_judged_unit(p, identity))
            continue
        if isinstance(data, dict):
            fields = data.get("fields")
            if isinstance(fields, dict):
                docs += 1
                for n in names:
                    if n not in fields:
                        continue
                    present[n] += 1
                    v = fields[n]
                    if v not in (None, "", [], {}):
                        populated[n] += 1
        _checkpoint(_semantic_progress.file_judged_unit(p, identity))
    return docs, present, populated


def audit(programs: Path, corpus: Path) -> dict:
    rd = readers(programs)
    docs, present, populated = corpus_counts(corpus, set(rd))
    findings, inconclusive = [], []
    for name, n_readers in sorted(rd.items()):
        if present.get(name, 0) == 0:
            # Not reachable by this flat scan — a blind spot, not a defect.
            inconclusive.append(name)
            continue
        if populated.get(name, 0) == 0:
            findings.append({"field": name, "readers": n_readers,
                             "present": present[name], "populated": 0})
    return {"program": "l_doc_field_producer_check",
            "docs_scanned": docs, "fields_read": len(rd),
            "findings": findings, "inconclusive": sorted(inconclusive),
            "passed": not findings}


def _load_baseline(p: Path):
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    k = d.get("known") if isinstance(d, dict) else d
    return sorted({str(x) for x in k}) if isinstance(k, list) else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("corpus", nargs="?", default=None)
    ap.add_argument("--programs", default=None)
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="the caller asserts this repo need not carry the "
                         "published corpus. Turns 'no corpus discoverable "
                         "anywhere' from UNDETERMINED into NO_CORPUS (rc 0), "
                         "which STATES that nothing was scanned. It does NOT "
                         f"excuse a pointer that is set and broken: ${CORPUS_ENV} "
                         "aimed at something unreadable, or at a clone with no "
                         f"{_CORPUS_SUBDIR}/ in it, is UNDETERMINED with or "
                         "without this flag.")
    a = ap.parse_args(argv)

    here = Path(__file__).resolve()
    programs = Path(a.programs) if a.programs else here.parent

    # WHERE THE CORPUS IS, ASKED THROUGH THE ONE SEAM THAT ANSWERS IT (#1710).
    # `_corpus_location.resolve` follows $VIBE_IC_BENCHMARK_DATA only when the
    # NAMED path carries no corpus, and announces either way. That asymmetry is
    # deliberate and measured: letting the pointer win over a root that IS
    # readable makes every developer who has it exported run a different gate
    # from CI, and it is a gate scanning a tree nobody named.
    #
    # The fallback name stays the literal relative path the old message printed,
    # so a reader still learns WHAT was looked for when nothing is found.
    named = (Path(a.corpus) if a.corpus else
             next((b / _DEFAULT_CORPUS_REL for b in here.parents
                   if (b / _DEFAULT_CORPUS_REL).is_dir()),
                  Path(_DEFAULT_CORPUS_REL)))
    corpus, origin = _corpus.resolve(named, subdir=_CORPUS_SUBDIR,
                                     gate="l_doc_field_producer_check",
                                     announce=True)
    if not corpus.is_dir():
        # FOUR OUTCOMES, decided in one place: a pointer that is set and wrong
        # is UNDETERMINED (never excused by the opt-in); nothing anywhere is
        # NO_CORPUS only when the CALL SITE said the repo need not carry one;
        # otherwise UNDETERMINED, unchanged.
        return _corpus.refuse("l_doc_field_producer_check", named, corpus,
                              origin, a.corpus_may_be_absent, _SCANNED)

    rep = audit(programs, corpus)

    # ZERO ON EITHER SIDE IS A REFUSAL, NOT A VERDICT. This gate compares two
    # populations, and an empty one makes the comparison vacuous in a way that
    # LOOKS like a result:
    #   * no readers  -> no field can be found, and it prints [PASS];
    #   * no documents-> `now` is empty, so every recorded entry reads as
    #                    "resolved" and the run FAILs for a reason that is false
    #                    — or, with --write-baseline, wipes the register.
    if rep["fields_read"] == 0:
        print(f"UNDETERMINED: no *_check.py under {programs} reads an L-doc "
              f"field, so this gate had NOTHING to look for. Zero readers is "
              f"'I could not look', not 'every field has a producer'.",
              file=sys.stderr)
        return 2
    if rep["docs_scanned"] == 0:
        print(f"UNDETERMINED: {corpus} is a directory but holds no L-doc this "
              f"gate can read (0 of them carry a `fields` object), so 0 "
              f"document(s) were scanned against {rep['fields_read']} field(s) "
              f"read by checkers. A zero denominator cannot say whether a "
              f"field has a producer, and adjudicating the baseline against it "
              f"would report every recorded entry as resolved.", file=sys.stderr)
        return 2

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, indent=2) + "\n")
    bl = Path(a.baseline) if a.baseline else here.parent / _BASELINE_NAME
    now = sorted(f["field"] for f in rep["findings"])

    if a.write_baseline:
        prev = _load_baseline(bl)
        if prev is not None and len(now) > len(prev):
            print(f"[FAIL] refusing to GROW the baseline "
                  f"({len(prev)} -> {len(now)}): a field losing its producer "
                  f"is a regression, not a fact to record.")
            return 1
        # Preserve any TRIAGE already recorded for entries that survive. A
        # register of bare names invites the worst possible repair —
        # fabricating a producer to make an entry disappear — so each entry
        # carries what was actually found when it was investigated.
        prev_triage = {}
        if bl.is_file():
            try:
                prev_triage = (json.loads(bl.read_text()).get("triage")
                               or {})
            except (OSError, ValueError):
                prev_triage = {}
        bl.write_text(json.dumps(
            {"_comment": ("L-doc fields a checker reads that NO real document "
                          "populates (vibe-ic#312 family). MAY ONLY SHRINK — "
                          "each entry is a consumer reading what nobody "
                          "writes. `triage` records what was found when an "
                          "entry was investigated, including entries proven "
                          "to be FALSE POSITIVES of this gate's own rule: "
                          "removing those by inventing a producer would be "
                          "the worst possible repair."),
             "known": now,
             "triage": {k: v for k, v in prev_triage.items() if k in now}},
            indent=2) + "\n")
        print(f"wrote {bl} ({len(now)} entr(ies))")
        return 0

    # The tree actually scanned is NAMED, not implied. Whatever this gate read,
    # it says so — a gate that scans a different tree from the one on its
    # command line is the silence #1710 removed.
    print(f"l_doc_field_producer_check: {rep['docs_scanned']} L-doc(s) under "
          f"{corpus}, {rep['fields_read']} field(s) read by checkers")
    # The blind spot is PRINTED, never silent: a field absent from every
    # document may be nested beyond this flat scan, and claiming it as a
    # defect would be inventing one out of the scanner's own limits.
    print(f"  inconclusive (absent from every doc, may be nested): "
          f"{len(rep['inconclusive'])}")
    base = _load_baseline(bl)
    new = [f for f in now if base is None or f not in set(base)]
    paid = [f for f in (base or []) if f not in set(now)]
    if paid:
        print(f"[FAIL] {len(paid)} recorded field(s) now HAVE a producer — "
              f"shrink the baseline so it cannot become permission:")
        for f in paid:
            print(f"   (resolved) {f}")
    if new:
        print(f"[FAIL] {len(new)} field(s) READ by a checker that NO document "
              f"populates — the consumer sees an empty value, and an empty "
              f"value is indistinguishable from a clean one:")
        for f in rep["findings"]:
            if f["field"] in new:
                print(f"   {f['field']}: {f['readers']} reader(s), present in "
                      f"{f['present']} doc(s), populated in 0")
    if new or paid:
        return 1
    print(f"[PASS] no NEW reader-without-producer ({len(now)} recorded)")
    return 0


def _entrypoint() -> int:
    global _ACTIVE_PROGRESS
    with _semantic_progress.child_progress(PROGRESS_SCOPE) as progress:
        _ACTIVE_PROGRESS = progress
        try:
            return main()
        finally:
            _ACTIVE_PROGRESS = None


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
