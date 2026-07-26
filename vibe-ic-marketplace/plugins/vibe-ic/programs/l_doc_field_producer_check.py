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

chip-AGNOSTIC: field names are discovered from the checkers themselves and
counted against whatever corpus is present. No design, PDK or vendor
literal appears here.

USAGE
-----
    python3 l_doc_field_producer_check.py [CORPUS] [--programs DIR]
                                          [--json OUT] [--write-baseline]

EXIT CODES
----------
    0 = PASS      1 = FAIL (new reader-without-producer)      2 = SKIP
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Set

# `fields.get("name")` / `f.get("name")` — the shape every L-doc checker uses
# to pull a structured value out of a layer document.
_READ_RE = re.compile(r'fields?\W{0,12}\.get\(\s*["\']([a-z0-9_]{4,40})["\']')

_DEFAULT_CORPUS_REL = "benchmark-data/ic"
_BASELINE_NAME = "l_doc_field_producer_baseline.json"


def readers(programs: Path) -> Dict[str, int]:
    """{field: number of checker files that read it}."""
    out: Dict[str, int] = {}
    for p in sorted(programs.glob("*_check.py")):
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for name in set(_READ_RE.findall(text)):
            out[name] = out.get(name, 0) + 1
    return out


def corpus_counts(corpus: Path, names: Set[str]):
    """(docs_scanned, {field: present}, {field: populated})."""
    present: Dict[str, int] = {n: 0 for n in names}
    populated: Dict[str, int] = {n: 0 for n in names}
    docs = 0
    for p in sorted(corpus.rglob("L*_*.json")):
        try:
            data = json.loads(p.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        fields = data.get("fields")
        if not isinstance(fields, dict):
            continue
        docs += 1
        for n in names:
            if n not in fields:
                continue
            present[n] += 1
            v = fields[n]
            if v not in (None, "", [], {}):
                populated[n] += 1
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
    a = ap.parse_args(argv)

    here = Path(__file__).resolve()
    programs = Path(a.programs) if a.programs else here.parent
    corpus = (Path(a.corpus) if a.corpus else
              next((b / _DEFAULT_CORPUS_REL for b in here.parents
                    if (b / _DEFAULT_CORPUS_REL).is_dir()), None))
    if corpus is None or not corpus.is_dir():
        print(f"[SKIP] l_doc_field_producer_check: no corpus "
              f"({a.corpus or _DEFAULT_CORPUS_REL} not found).")
        return 2

    rep = audit(programs, corpus)
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

    print(f"l_doc_field_producer_check: {rep['docs_scanned']} L-doc(s), "
          f"{rep['fields_read']} field(s) read by checkers")
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


if __name__ == "__main__":
    raise SystemExit(main())
