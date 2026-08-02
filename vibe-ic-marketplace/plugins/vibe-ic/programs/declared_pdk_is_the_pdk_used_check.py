#!/usr/bin/env python3
"""declared_pdk_is_the_pdk_used_check — the PDK that ran must be the PDK declared.

WHY THIS EXISTS
===============
A run whose staged PDK went missing did not stop. It used the open PDK baked into
the EDA image and completed four consecutive rounds, each producing a full report
and a step table, on a process the design does not target.

Measured: the run root held no `input/pdk/` at all, while that same run's Phase 1
had recorded a proprietary `adopted_pdk_target` read from the design's own input
documents. The place-and-route log named the image's built-in cell library 72 times
and the declared library zero times. Nothing in the flow said a word, and a reported
"PASS 4 -> 27" improvement across those rounds was measured against a different
process than the one before it.

THE GUARD FOR THIS ALREADY EXISTED, AND THE DEFECT DISABLED IT
`pdk_consistency_check.py` is written for exactly this class — "the synthesis tool
targeted a different PDK than the one specified". It takes `--pdk-lib` as a REQUIRED
argument, so with no PDK staged there is nothing to pass it and it never runs. The
repo's own wiring baseline records the state as benign triage:

    pdk_consistency_check.py: rc=2 SKIPs / refuses without its input — --pdk-lib

For most checkers "no input, nothing to check" is right. For this one the missing
input IS the finding. A guard that is switched off by the very condition it exists
to catch has never been able to catch it.

WHAT THIS ASKS INSTEAD
======================
A question that cannot be disabled by the defect, because both halves are always
present in a real run:

    the design DECLARES a target process   (Phase 1 writes it, from the input docs)
    the tools LOADED some cell library     (the logs name every .lef/.lib they read)

    do they agree?

No PDK staged, with a target declared, is a FAIL — not a skip. That is the whole
point. rc=2 is reserved for the one case where the question genuinely cannot be
asked: the design declares no target at all, so there is nothing to disagree with.

Chip-, PDK- and vendor-AGNOSTIC. Both sides are read from the run at runtime; no
identifier of any process, foundry or design is written here.

EXIT
    0  the libraries the tools loaded are consistent with the declared target
    1  they are not — including "a target is declared and no PDK is staged"
    2  no target declared AND no cell library loaded — there was no physical
       implementation to judge. A run that DID load libraries without a declared
       target exits 1, because it cannot show it used the intended process.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

LIB_RE = re.compile(r"[A-Za-z0-9_./+-]+\.(?:lef|lib)\b")
# A declared target is prose ("Some Foundry ABC123-X1.2"), a loaded library is a
# filename ("abc123xyz_sc_hd.lef"). Comparing them needs the alphanumeric runs they
# share, not string equality — so reduce both to lowercase tokens of >=3 chars.
TOKEN_RE = re.compile(r"[a-z0-9]{3,}")

# Tokens that carry no identity: every PDK has cells and corners.
STOPWORDS = {
    "the", "and", "for", "lib", "lef", "gds", "cdl", "spi", "sch", "typ", "min",
    "max", "std", "cell", "cells", "stdcell", "tech", "merged", "liberty",
    "library", "libs", "pdk", "process", "node", "foundry", "technology", "kit",
    "design", "target", "open", "source", "version", "rev",
}


# A declared token must be at least this long before a substring match counts.
# Three characters produce accidental hits between unrelated names; four does not,
# on every pair measured here.
MIN_MATCH = 4


def tokens(text: str) -> Set[str]:
    return {t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOPWORDS}


def shares_identity(declared: Set[str], name: str) -> bool:
    """Does this library filename carry any of the declared target's identity?

    Exact token equality is too strict in both directions, because the two sides are
    written by different authors for different purposes: a declared target is prose
    a human wrote ("Some Foundry ZQ42-K3 / SL1.9c"), while a library is a filename a
    vendor generated ("zq42k3_sc_hd__tt_025C.lib"). The identifying run of
    characters survives; the punctuation and word boundaries around it do not.

    So a declared token counts when it is contained in a library token or vice
    versa, subject to MIN_MATCH. Generic vocabulary is removed first — every PDK on
    earth has cells, a tech file and corners, so those words identify nothing.
    """
    lib = tokens(name)
    for d in declared:
        if len(d) < MIN_MATCH:
            continue
        for l in lib:
            if d in l or (len(l) >= MIN_MATCH and l in d):
                return True
    return False


def declared_target(run: Path) -> Tuple[Optional[str], Optional[str]]:
    """What the design says it targets, and where that was read from.

    Phase 1 already derives this from the input documents and writes it down; this
    reads the record rather than re-deriving it, so the two cannot drift.
    """
    for rel, keys in (
        ("phase1/pdk_staging_read.json", ("adopted_pdk_target", "staged_identifier")),
        ("phase1/merged_docs/L19_CONSTRAINTS_PDK.json", ("pdk_target", "pdk")),
        ("phase1/L19_CONSTRAINTS_PDK.json", ("pdk_target", "pdk")),
        ("input/project.json", ("pdk", "target_pdk", "pdk_target")),
    ):
        for base in (run, run / "run"):
            p = base / rel
            if not p.is_file():
                continue
            try:
                d = json.loads(p.read_text(errors="replace"))
            except (OSError, ValueError):
                continue
            for k in keys:
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip(), f"{rel}:{k}"
    return None, None


def loaded_libraries(run: Path, cap: int = 400) -> Tuple[Set[str], int]:
    """Every .lef/.lib basename the tools actually read, from their own logs.

    The tool's log is used rather than the flow's configuration because the
    question is what RAN, and a configuration that was ignored is precisely the
    failure being looked for.
    """
    names: Set[str] = set()
    scanned = 0
    for log in sorted(run.rglob("*.log"))[:cap]:
        if "/plugin_work/" in str(log) or "/plugin_" in str(log):
            continue                       # the plugin's own tree is not the run
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        scanned += 1
        for m in LIB_RE.findall(text):
            names.add(m.rsplit("/", 1)[-1])
    return names, scanned


def staged_pdk_files(run: Path) -> int:
    n = 0
    for base in (run, run / "run"):
        d = base / "input" / "pdk"
        if d.is_dir():
            n += sum(1 for _ in d.rglob("*") if _.is_file())
    return n


def staged_library_names(run: Path) -> Set[str]:
    """Basenames of the .lef/.lib the design staged for itself.

    THE STRONGEST AVAILABLE EVIDENCE, and the reason this beats matching the
    declared prose. A declared target is a human sentence ("Some Foundry
    HP-style-name") while a vendor's cell library is named on its own convention
    ("m…pm180su_typ.lib") — the two can share no whole word at all and still be
    the same PDK. The first version of this file compared them by token and
    FAILED a run that had loaded the staged liberty by its exact filename. A
    check that rejects correct work is worse than the one it replaced.

    When files are staged, compare filenames to filenames. Prose matching stays
    only for the case where nothing is staged and the PDK comes from the image.
    """
    out: Set[str] = set()
    for base in (run, run / "run"):
        d = base / "input" / "pdk"
        if not d.is_dir():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.suffix.lower() in (".lef", ".lib"):
                out.add(f.name)
    return out


def _stem(name: str) -> str:
    return name.rsplit(".", 1)[0]


def matches_staged(loaded: str, staged: Set[str]) -> bool:
    """Is this loaded library one of the staged ones?

    Exact basename, or a staged stem that the loaded name extends. The flow
    legitimately writes derived copies — a tech LEF re-emitted with a top-metal
    correction keeps the staged stem and appends to it — and those are still the
    staged PDK, not a foreign one.
    """
    # Case-insensitively: a vendor ships `HP…-S1.9cS.lib` and a flow writes
    # `hp…-s1.9cs.lib`; they are the same file and only the shell disagrees.
    low = loaded.lower()
    staged_low = {x.lower() for x in staged}
    if low in staged_low:
        return True
    ls = _stem(low)
    return any(ls.startswith(_stem(x)) and len(_stem(x)) >= 8 for x in staged_low)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)

    run = a.run_dir
    target, source = declared_target(run)
    libs, scanned = loaded_libraries(run)
    staged = staged_pdk_files(run)

    rec: Dict[str, object] = {
        "declared_target": target, "declared_source": source,
        "staged_pdk_files": staged, "logs_scanned": scanned,
        "libraries_loaded": sorted(libs)[:40],
    }

    if not target:
        # AN UNANSWERABLE QUESTION IS NOT A PASS. The first cut returned rc=2 here
        # and would have waved through the exact runs that motivated this file:
        # they declare no target BECAUSE the declaration was lost, and they went on
        # to place and route against whatever library was at hand.
        #
        # Measured across five consecutive rounds of one design: the round that
        # still carried its declaration also carried its PDK and used it. Every
        # later round had an EMPTY declared target and no staged PDK — the record
        # of which process the design needs disappeared, and nothing noticed.
        #
        # So the split is on whether physical work happened, not on whether the
        # question is convenient to answer. A run that loaded cell libraries and
        # cannot say which process it targeted has not demonstrated anything about
        # its PDK, and must not report that it has.
        if libs:
            rec["verdict"] = "FAIL"
            rec["reason"] = ("this run loaded cell libraries but declares no PDK "
                             "target, so it cannot show that it implemented against "
                             "the intended process")
            _emit(a.json, rec)
            print(f"declared_pdk_is_the_pdk_used: FAIL — {rec['reason']}")
            print(f"    staged : {staged} file(s) under input/pdk/")
            print(f"    loaded : {len(libs)} distinct librar(ies) across {scanned} log(s)")
            for n in sorted(libs)[:8]:
                print(f"        {n}")
            return 1
        rec["verdict"] = "NOT CHECKED"
        rec["reason"] = ("the design declares no PDK target and no cell library was "
                         "loaded — no physical implementation to judge")
        _emit(a.json, rec)
        print("declared_pdk_is_the_pdk_used: rc=2 NOT CHECKED — no declared target "
              "and no library loaded")
        return 2

    want = tokens(target)
    staged_names = staged_library_names(run)
    if staged_names:
        hits = sorted({n for n in libs if matches_staged(n, staged_names)})
        rec["compared_against"] = "staged filenames"
        rec["staged_libraries"] = len(staged_names)
    else:
        # Nothing staged: the PDK can only have come from the image, so the
        # declared prose is the only reference left.
        hits = sorted({n for n in libs if shares_identity(want, n)})
        rec["compared_against"] = "the declared target's own words"
        rec["declared_tokens"] = sorted(want)
    rec["matching_libraries"] = hits
    rec["foreign_libraries"] = sorted(set(libs) - set(hits))

    if hits:
        rec["verdict"] = "PASS"
        _emit(a.json, rec)
        print(f"declared_pdk_is_the_pdk_used: PASS — {len(hits)} of {len(libs)} loaded "
              f"librar(ies) match the declared target, compared against "
              f"{rec['compared_against']} ({source})")
        for n in hits[:6]:
            print(f"        {n}")
        # Not a failure: a flow legitimately reads a foreign library for an
        # unrelated step. Reported so a substitution creeping in alongside the
        # right PDK is visible rather than averaged away by the PASS.
        if rec["foreign_libraries"]:
            print(f"    also loaded, not from the declared PDK "
                  f"({len(rec['foreign_libraries'])}):")
            for n in rec["foreign_libraries"][:6]:
                print(f"        {n}")
        return 0

    rec["verdict"] = "FAIL"
    if staged == 0:
        rec["reason"] = ("a PDK target is declared and NO PDK is staged under "
                         "input/pdk/. The flow ran on whatever library was available "
                         "instead of stopping.")
    else:
        rec["reason"] = ("a PDK is staged and the libraries the tools loaded do not "
                         "match the declared target — the staged PDK was not the one "
                         "used.")
    _emit(a.json, rec)
    print(f"declared_pdk_is_the_pdk_used: FAIL — {rec['reason']}")
    print(f"    declared : {target}   (from {source})")
    print(f"    staged   : {staged} file(s) under input/pdk/")
    print(f"    loaded   : {len(libs)} distinct librar(ies) across {scanned} log(s), "
          f"none matching")
    for n in sorted(libs)[:8]:
        print(f"        {n}")
    return 1


def _emit(path: Optional[Path], rec: Dict[str, object]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
