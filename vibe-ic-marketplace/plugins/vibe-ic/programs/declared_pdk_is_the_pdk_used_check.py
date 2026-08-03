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
    1  they are not — including "a target is declared and no PDK is staged",
       and including "a PDK is staged that Phase 1 could not NAME, and no
       target is declared" (#697), and "a target is declared and this run
       recorded no library load at all" (`no_library_load_recorded: true` in the
       JSON record, #710). An unnameable process is not a skippable case: it is
       the one that makes every later claim unverifiable. The no-load case is a
       FAIL because nothing was demonstrated, NOT because a different PDK was
       shown to have been used — the two are reported apart so a caller is never
       told a load happened when none did.
    2  no target declared AND no cell library loaded AND the staged PDK, if
       any, was nameable — there was no physical implementation to judge. A
       run that DID load libraries without a declared target exits 1, because
       it cannot show it used the intended process.
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

#: How much of the longer token the shorter one must cover before the two count
#: as the same identifier. vibe-ic#709: without it, a 4-character prefix of an
#: 11-character family name declared that family. 0.6 accepts the punctuation
#: case the docstring below justifies (`zq42` of `zq42k3`, 0.67) and rejects a
#: foundry-length prefix (`abc1` of `abc123xy456`, 0.36).
MIN_IDENTITY_RATIO = 0.6


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

    CONTAINMENT ALONE IS NOT IDENTITY (vibe-ic#709). Bare `d in l` let any
    declared token of >= 4 characters match by appearing ANYWHERE inside a
    library token, so an arbitrary interior fragment — or a 4-character foundry
    prefix shared by every family that vendor ships — passed as a declaration of
    the specific library that ran. Measured on a synthetic 11-character family:
    both `c123` (interior) and `abc1` (prefix) were accepted as declaring
    `abc123xy456`.

    Two conditions now, and both are needed:

      BOUNDARY  the shorter token must sit at the START or the END of the
                longer one, never in its interior. This is what the punctuation
                argument above actually justifies: a human writing "ZQ42-K3"
                tokenises to `zq42` + `k3` against a vendor's `zq42k3`, and
                `zq42` is a PREFIX. It never justifies matching a run of
                characters from the middle.
      SUBSTANCE the shorter must cover at least `MIN_IDENTITY_RATIO` of the
                longer, so the match names most of the identifier rather than a
                fragment of it. `zq42` of `zq42k3` is 4/6; `abc1` of
                `abc123xy456` is 4/11.

    Chip-AGNOSTIC: pure string structure. No PDK, vendor or family literal.
    """
    lib = tokens(name)
    for d in declared:
        if len(d) < MIN_MATCH:
            continue
        for l in lib:
            if l == d:
                return True
            short, long = (d, l) if len(d) < len(l) else (l, d)
            if len(short) < MIN_MATCH:
                continue
            if not (long.startswith(short) or long.endswith(short)):
                continue                      # interior fragment: not identity
            if len(short) / len(long) >= MIN_IDENTITY_RATIO:
                return True
    return False


#: PDKs whose NAME is itself an identifier — the open ones this repo ships
#: support for. A declaration that names one of these is not vague prose; it is
#: a specific claim about which process ran, and it is checkable.
_NAMED_PDK_RE = re.compile(
    r"\b(sky130[a-z]?|gf180mcu[a-z]?|gf180|sg13g2|ihp[- ]?sg13g2|"
    r"asap7|freepdk\d+|nangate45|scl180)\b", re.IGNORECASE)


def contradicting_named_pdks(target: str, libs: List[str]) -> List[str]:
    """Named PDKs the declaration claims that NO loaded library corroborates.

    vibe-ic#709/#713 — the gate PASSed as soon as ANY declared token matched a
    loaded library, so a declaration could name a completely different process
    and still pass on the strength of an unrelated token in the same sentence.
    Measured: `"<family> on an open-source sky130 130nm process"` PASSed against
    libraries from `<family>` — the declaration says an open-source process ran,
    a different one did, and this gate exists for exactly that.

    Only NAMED PDKs are judged, because only they are checkable from a library
    filename. A foundry or a node in the same sentence ("Foundry R, 55nm") is
    not derivable from a LEF name, and the caller DISCLOSES that rather than
    letting a PASS imply it was verified.

    Chip-AGNOSTIC: the table is this repo's own open-PDK vocabulary, already
    spelled the same way in `phase1_doc_one_shot_runner._OPEN_PDK_TOKEN_RE`. No
    commercial PDK, vendor or part number appears.
    """
    claimed = {m.group(1).lower().replace(" ", "-")
               for m in _NAMED_PDK_RE.finditer(target or "")}
    if not claimed:
        return []
    return sorted(c for c in claimed
                  if not any(shares_identity({c.replace("-", "")}, n)
                             or c.replace("-", "") in n.lower() for n in libs))


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
            if not isinstance(d, dict):
                continue
            # THE L-DOC SCHEMA NESTS THE VALUE UNDER `fields`.
            #
            # Schema-v2 L-docs are `{doc_id, doc_name, applicability, fields:
            # {...}, schema_version: 2, ...}` — the payload lives in `fields`,
            # NOT at the top level. Reading only the top level made this gate
            # blind to the canonical shape phase 1 emits, and the failure was
            # SILENT AND INVERTED: with a real target declared and the right
            # library loaded, `declared_target()` returned None and the gate
            # exited 1 with "loaded cell libraries but declares NO PDK target".
            # The one gate that exists to prove the process was the intended
            # one reported that the design had named no process at all.
            #
            # Top level is tried FIRST so any flat producer keeps its exact
            # precedence; `fields` is a fallback, so no currently-passing run
            # can change verdict. The source label records which shape matched,
            # so a reader can see where the value came from.
            for scope, label in ((d, ""), (d.get("fields"), "fields.")):
                if not isinstance(scope, dict):
                    continue
                for k in keys:
                    v = scope.get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip(), f"{rel}:{label}{k}"
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


def unnameable_staged_pdk(run: Path) -> bool:
    """Did Phase 1 stage a PDK it could not NAME?

    Phase 1 writes this verdict down itself. Reading its record rather than
    re-deriving it keeps the two from drifting, exactly as `declared_target`
    does. Absent record -> False: a run that predates the field is judged on
    the evidence it does carry, not on a missing one.
    """
    for rel in ("phase1/pdk_staging_read.json",
                "reports/phase1/pdk_staging_read.json"):
        for base in (run, run / "run"):
            p = base / rel
            if not p.is_file():
                continue
            try:
                d = json.loads(p.read_text(errors="replace"))
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and d.get("staged_pdk_unnameable") is True:
                return True
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)

    run = a.run_dir
    target, source = declared_target(run)
    libs, scanned = loaded_libraries(run)
    staged = staged_pdk_files(run)
    unnameable = unnameable_staged_pdk(run)

    rec: Dict[str, object] = {
        "declared_target": target, "declared_source": source,
        "staged_pdk_files": staged, "logs_scanned": scanned,
        "unnameable_staged_pdk": unnameable,
        "libraries_loaded": sorted(libs)[:40],
    }

    # A PDK THAT CANNOT BE NAMED MUST NOT BECOME AN UNNAMED INPUT.
    #
    # Measured: a real run staged a PDK, read 27 enablement files from it,
    # derived no identifier from any of them, wrote `staged_identifier: null`
    # — and carried on. With no declared target the branch below then
    # returned rc=2 NOT CHECKED whenever no library happened to be named in a
    # log, so the one condition that makes the question unanswerable also
    # excused the answer. That is the same shape as the `--pdk-lib` skip this
    # file was written to remove, one level up.
    #
    # So: staged-and-unnameable is a FAIL on its own evidence. It is checked
    # BEFORE the declared-target branches because it is not a statement about
    # agreement — there is nothing to agree with — it is a statement that the
    # run cannot say which process it used.
    if unnameable and not target:
        rec["verdict"] = "FAIL"
        rec["reason"] = ("a PDK is staged under input/pdk/ that Phase 1 could "
                         "not name, and no target is declared — this run "
                         "cannot say which process it implemented against")
        _emit(a.json, rec)
        print(f"declared_pdk_is_the_pdk_used: FAIL — {rec['reason']}")
        print(f"    staged : {staged} file(s) under input/pdk/, identifier NOT DERIVABLE")
        print(f"    loaded : {len(libs)} distinct librar(ies) across {scanned} log(s)")
        return 1

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
    hits = sorted({n for n in libs if shares_identity(want, n)})
    rec["declared_tokens"] = sorted(want)
    rec["matching_libraries"] = hits

    # A CONTRADICTION OUTRANKS A PARTIAL MATCH (vibe-ic#713). `hits` only says
    # SOME declared token matched SOME library. If the same declaration also
    # names a PDK that nothing loaded corroborates, the two halves of the
    # sentence disagree, and the half that names a different process is the one
    # this gate exists to catch — it cannot be outvoted by a token that happens
    # to match.
    contradicted = contradicting_named_pdks(target, libs)
    rec["contradicting_named_pdks"] = contradicted
    if contradicted:
        rec["verdict"] = "FAIL"
        rec["reason"] = (
            f"the declaration names {contradicted}, which no loaded library "
            f"corroborates" + (f", while other token(s) match {hits}" if hits else ""))
        _emit(a.json, rec)
        print(f"declared_pdk_is_the_pdk_used: FAIL — the declared target names "
              f"{', '.join(contradicted)}, and no loaded library carries that "
              f"identity ({source})", file=sys.stderr)
        if hits:
            print(f"    a DIFFERENT token in the same declaration matches "
                  f"{len(hits)} librar(ies) — a partial match does not settle a "
                  f"declaration that names another process.", file=sys.stderr)
        return 1

    if hits:
        rec["verdict"] = "PASS"
        rec["no_library_load_recorded"] = False
        # WHAT THIS PASS DOES NOT COVER, said out loud. The match is on library
        # IDENTITY. A foundry or a process node in the same declaration is not
        # derivable from a LEF filename, so it was not checked — and a PASS that
        # stays silent about that reads as though it had been.
        rec["verified"] = "library identity only"
        rec["not_verified"] = "foundry / process node (not derivable from a library filename)"
        _emit(a.json, rec)
        print(f"declared_pdk_is_the_pdk_used: PASS — {len(hits)} of {len(libs)} loaded "
              f"librar(ies) match the declared target ({source})")
        print(f"    verified: library identity. NOT verified: any foundry or "
              f"process-node claim in the same declaration — a LEF filename "
              f"does not carry either.")
        return 0

    if not libs:
        # A CHECK MUST NOT STATE A CONCLUSION ITS OWN EVIDENCE CONTRADICTS.
        #
        # Both reasons below assert that some OTHER library was used instead —
        # "the flow ran on whatever library was available", "the staged PDK was
        # not the one used". Each is a claim about a load that happened. With
        # `libs` empty NO load was recorded at all, so the run's own logs carry
        # neither sentence. Measured on a real run: a design that had just
        # declared its target and staged 11521 enablement files, with no tool
        # step yet, was told "the staged PDK was not the one used" over
        # `loaded : 0 distinct librar(ies)` printed on the very next line.
        #
        # THE VERDICT DOES NOT SOFTEN. It stays FAIL, for the reason this file
        # exists: a run that declares a process and cannot show a single library
        # load has not demonstrated it implemented against that process, and the
        # motivating defect — a staged PDK that silently went missing — is just
        # as capable of producing logs that name nothing as logs that name the
        # wrong thing. Only the REASON changes, from an unsupported accusation
        # to the true one, plus a machine-readable field so a caller can tell
        # "not established yet" from "established, and it was the wrong PDK"
        # without parsing prose.
        rec["verdict"] = "FAIL"
        rec["no_library_load_recorded"] = True
        rec["reason"] = ("a PDK target is declared and this run's logs record no "
                         "cell-library load at all, so which process the tools "
                         "used cannot be established from this run. This is not "
                         "evidence that a different PDK was used — it is the "
                         "absence of the evidence the question needs.")
        _emit(a.json, rec)
        print(f"declared_pdk_is_the_pdk_used: FAIL — {rec['reason']}")
        print(f"    declared : {target}   (from {source})")
        print(f"    staged   : {staged} file(s) under input/pdk/")
        print(f"    loaded   : 0 librar(ies) across {scanned} log(s) — nothing to compare")
        return 1

    rec["verdict"] = "FAIL"
    rec["no_library_load_recorded"] = False
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
