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
       target is declared" (#697). An unnameable process is not a skippable
       case: it is the one that makes every later claim unverifiable. Every
       rc 1 is a statement about a library load that HAPPENED: this gate never
       returns 1 without a library it can name.
    2  the question cannot be asked of this run, with the missing input NAMED.
       Two states reach it:
         * no target declared AND no cell library loaded AND the staged PDK,
           if any, was nameable — there was no physical implementation to
           judge. A design that writes down an explicit "not applicable" IS in
           this state and is judged in it, with the written words carried in
           `declared_not_applicable` so the record distinguishes "said so"
           from "never populated the field".
         * a target IS declared and this run records NO cell-library load at
           all (`no_library_load_recorded: true`, `missing_input` naming what
           was absent) — vibe-ic#1002. This was an rc 1 through #710, printing
           "0 librar(ies) across 0 log(s) — nothing to compare" one line under
           its own FAIL. `gate_zero_denominator_refuses_check` is the house
           rule for that shape and it says REFUSE. See the branch itself for
           the corpus measurement that says nothing was hidden by the change.
       A run that DID load libraries without a declared target still exits 1,
       because it cannot show it used the intended process.

WHERE THE DECLARATION IS READ FROM
==================================
`declared_target` reads the canonical L-doc through the tree's shared accessor
(`l_doc_consumer_contract`), so the LEVEL (payload under `fields`) and the
LOCATION (`phase1/generated_docs/`) are the shared contract's answer and not a
private copy in this file. Both were wrong here, independently, and between
them the gate resolved a target on 0 of 106 tracked projects — see
`declared_target.__doc__` for the measurement.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

# WHERE AN L-DOC IS, AND WHERE ITS PAYLOAD IS, ARE NOT THIS FILE'S TO DECIDE.
#
# `l_doc_consumer_contract` is the tree's existing shared L-doc accessor:
# `load_l_doc(project, code)` resolves the canonical emit location by glob (so
# a filename disagreement between `schema.py` and `l_doc_taxonomy.py` cannot
# hide a document), and `l_doc_fields(doc)` returns the payload from EITHER
# schema shape. Both are used here instead of a local re-implementation, so
# this gate cannot drift from every other L-doc consumer.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:                      # pragma: no cover - path setup
    sys.path.insert(0, str(_HERE))
from l_doc_consumer_contract import l_doc_fields, load_l_doc  # noqa: E402

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


#: One CamelCase segment: `Nangate`, an all-caps run (`IHP`), or a lower/digit run.
_CAMEL_SEG_RE = re.compile(r"[A-Z][a-z0-9]*|[A-Z]+(?![a-z])|[a-z][a-z0-9]*")

#: A declared PDK token whose identity is an alphabetic stem plus a node number
#: (`nangate45` -> `nangate`, `freepdk45` -> `freepdk`). The digits are the NODE,
#: not part of the library's name, which is why a library omits them.
_STEM_RE = re.compile(r"^([a-z]+)\d+$")


def leading_segments(name: str) -> Set[str]:
    """The LEADING CamelCase segment of each identifier in ``name``, lowercased.

    `NangateOpenCellLibrary.lef` -> {`nangate`};
    `sky130_fd_sc_hd__tt.lib`    -> {`sky130`, `fd`, `sc`, `hd`, `tt`}.

    Only the LEADING segment of each underscore/dot-separated identifier is
    returned. That restriction is the whole safety argument: a compound library
    name is identified by what it STARTS with, and admitting interior segments
    would re-open exactly the `#709` interior-fragment hole this file closed —
    `Cell` and `Library` are generic and appear in libraries from every vendor.
    """
    out: Set[str] = set()
    for ident in re.split(r"[^A-Za-z0-9]+", name or ""):
        if not ident:
            continue
        segs = _CAMEL_SEG_RE.findall(ident)
        if segs:
            out.add(segs[0].lower())
    return out - STOPWORDS


def shares_stem_identity(declared: Set[str], name: str) -> bool:
    """Does a declared `<stem><node>` token name what this library STARTS with?

    THE DEFECT THIS CLOSES. A PDK is distributed under a directory named for its
    NODE (`nangate45`) while its library is named for its FAMILY
    (`NangateOpenCellLibrary`). `tokens()` does not split CamelCase, so the
    library collapses to one 22-character token `nangateopencelllibrary`, and
    :func:`shares_identity` then fails BOTH of its rules against `nangate45`:
    the BOUNDARY test fails (`nangateopencelllibrary` does not start with
    `nangate45` — the digits are not in the library name) and the SUBSTANCE
    ratio is 9/22 = 0.41, under `MIN_IDENTITY_RATIO`.

    MEASURED, the five PDKs shipped in the EDA image, each against its OWN real
    library filenames — 4 corroborate and exactly one does not:

        asap7       []              corroborated
        gf180mcuD   []              corroborated
        ihp-sg13g2  []              corroborated
        sky130A     []              corroborated
        nangate45   ['nangate45']   FALSE FAIL

    So the post-run audit that exists to PROVE which process ran reported that
    `nangate45` was contradicted by the libraries shipped at
    `/foss/pdks/nangate45/`. The gate was reading correctly and matching wrongly.

    THE RULE, deliberately narrow. The declared token must be exactly an
    alphabetic stem followed by digits, the stem must be at least ``MIN_MATCH``
    characters, and it must EQUAL — not prefix — a LEADING segment of a library
    identifier. `nangate45` -> stem `nangate` == leading segment of
    `NangateOpenCellLibrary`. A stem shorter than MIN_MATCH is refused, which is
    what keeps `sky130` -> `sky` (3) and `scl180` -> `scl` (3) from matching
    anything on the strength of three characters.

    Chip-AGNOSTIC: pure string structure, no PDK/vendor/foundry literal.
    """
    lead = leading_segments(name)
    for d in declared:
        m = _STEM_RE.match(d)
        if not m:
            continue
        stem = m.group(1)
        if len(stem) < MIN_MATCH:
            continue
        if stem in lead:
            return True
    return False


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
                             or shares_stem_identity({c.replace("-", "")}, n)
                             or c.replace("-", "") in n.lower() for n in libs))


#: The two spellings Phase 1 uses for the declaration inside L19.
_L19_KEYS = ("pdk_target", "pdk")

#: A declaration whose whole content is "there is no target". Anchored at the
#: START of the value, so a real declaration cannot be dismissed by the word
#: appearing later in a sentence.
_NOT_APPLICABLE_RE = re.compile(
    r"^\s*(?:n/?a|none|nil|not[\s_-]*applicable|no[\s_-]*pdk)\b", re.IGNORECASE)


def declares_no_target(target: str) -> bool:
    """Is this declaration an explicit statement that there IS no target?

    NOT A COSMETIC TIER. The gate's own docstring reserves rc=2 for "the design
    declares no target at all, so there is nothing to disagree with". A design
    that writes that down explicitly is in exactly that state — writing it down
    is more honest than leaving the field null, and must not be punished for it.
    Measured on the tracked corpus: 12 of the 28 non-empty L19 declarations are
    of this form, every one of them on an IP whose own text says it is not a
    tapeout. Read as targets they produce a FAIL that says the design cannot
    show which process it used, about a design that says it has none.

    A NAMED PDK OUTRANKS THE PREFIX. If the same declaration also names a
    process this repo can check, the sentence does name a target and is judged
    as one — so "N/A, defaults to <named process>" is NOT dismissed here.

    Chip-, PDK- and vendor-AGNOSTIC: the vocabulary is the English of absence,
    and the override consults the same `_NAMED_PDK_RE` table the rest of the
    file already uses.
    """
    if not _NOT_APPLICABLE_RE.match(target or ""):
        return False
    return not _NAMED_PDK_RE.search(target or "")


def _probe(base: Path, kind: str, rel: str) -> Iterator[Tuple[str, dict]]:
    """The one document a probe resolves to, as (source_label, parsed).

    Yields nothing when the probe finds no readable JSON object, so a caller
    can iterate the probes in precedence order without special-casing
    absence. At most one document is ever yielded.
    """
    if kind == "l-doc-canonical":
        p, doc = load_l_doc(base, rel)
        if p is None or not isinstance(doc, dict):
            return
        try:
            yield str(p.relative_to(base)), doc
        except ValueError:                          # pragma: no cover - defensive
            yield p.name, doc
        return
    p = base / rel
    if not p.is_file():
        return
    try:
        doc = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return
    if isinstance(doc, dict):
        yield rel, doc


def declared_target(run: Path) -> Tuple[Optional[str], Optional[str]]:
    """What the design says it targets, and where that was read from.

    Phase 1 already derives this from the input documents and writes it down; this
    reads the record rather than re-deriving it, so the two cannot drift.

    TWO INDEPENDENT DEFECTS MADE THIS READ NOTHING (vibe-ic#736 and this change)
    ===========================================================================
    Measured on the tracked corpus at the time of writing — 106 projects that
    carry a `phase1/generated_docs/L19_CONSTRAINTS_PDK.json`, 20 of which
    declare a non-empty target — this function returned ``(None, None)`` for
    **all 106**. Four of them had loaded cell libraries, so they were told:

        declared_pdk_is_the_pdk_used: FAIL — this run loaded cell libraries
        but declares no PDK target

    The one gate that exists to prove the process was the intended one reported
    that designs which name a process had named none. The other 102 fell to
    rc=2 NOT CHECKED, the tier the module docstring reserves for "the design
    declares no target at all" — a state the reader was manufacturing.

    THE LEVEL. Schema-v2 L-docs are ``{doc_id, doc_name, applicability,
    fields: {...}, schema_version}`` and the payload lives under ``fields``.
    The producer is explicit: `phase1_doc_one_shot_runner._emit_l19_to_l23_
    skeletons` writes ``skeleton["fields"]["pdk_target"] = _pdk_tgt``, and
    `phase1_post_process._skeleton_fields_for` carries `pdk_target` in the L19
    template. Corpus: `pdk_target` occurs **0 times at the top level and 106
    times under `fields`**. A top-level read could not see it, ever.

    THE PATH, and it is why fixing the level alone is not enough. The probe
    table below reached `phase1/merged_docs/` and `phase1/` — the canonical
    emit location is `phase1/generated_docs/`, which `_write_l_doc` and
    `_path_layout.generated_docs_dir` both name. Corpus: 106 L19 documents in
    `generated_docs/`, **1** in `merged_docs/`, 0 directly under `phase1/`.
    `merged_docs` appears in exactly one non-test file in the whole tree — this
    one — so nothing writes it. An envelope-only fix would have moved 1 of 107
    projects and left the gate blind on the other 106, still reporting that
    they name no process.

    Precedence is unchanged for every path that already resolved, and the
    canonical probe is inserted BELOW the two records that predate it, so no
    run that resolves a target today can resolve a different one. Only runs
    that resolved NOTHING can now resolve something. The source label records
    which shape and which file answered, so a reader can see where the value
    came from without re-deriving it.
    """
    for kind, rel, keys in (
        ("record", "phase1/pdk_staging_read.json",
         ("adopted_pdk_target", "staged_identifier")),
        ("l-doc", "phase1/merged_docs/L19_CONSTRAINTS_PDK.json", _L19_KEYS),
        # The canonical emit location. Resolved by the shared loader's glob,
        # not by a hardcoded filename.
        ("l-doc-canonical", "L19", _L19_KEYS),
        ("l-doc", "phase1/L19_CONSTRAINTS_PDK.json", _L19_KEYS),
        ("record", "input/project.json", ("pdk", "target_pdk", "pdk_target")),
    ):
        for base in (run, run / "run"):
            for label, doc in _probe(base, kind, rel):
                # `l_doc_fields` is the tree's shared accessor and returns the
                # payload from EITHER shape. It is applied only to L-doc
                # probes: the two `record` probes are not L-docs and have no
                # envelope to unwrap, so their reads stay exactly as they were.
                payload: Dict[str, Any] = (
                    l_doc_fields(doc) if kind.startswith("l-doc") else doc)
                inner = doc.get("fields") if kind.startswith("l-doc") else None
                # A NULL IN THE ENVELOPE MUST NOT SHADOW A VALUE AT THE ROOT.
                # `l_doc_fields` gives the envelope precedence, which is right
                # for a document that carries the key in both places. But a
                # MERGED document — program-track payload at the root, extras
                # added under `fields` — can carry `pdk_target: null` in the
                # envelope over a real value at the root; 28 of the tracked
                # L1-L13 documents have exactly that root+extras shape. Falling
                # back to the raw document costs one lookup and means this can
                # only ever turn "resolved nothing" into "resolved something",
                # never one value into another. `doc` IS `payload` for the two
                # non-L-doc probes, so their reads are unchanged.
                for k in keys:
                    for scope in (payload, doc):
                        v = scope.get(k)
                        if isinstance(v, str) and v.strip():
                            where = ("fields." if isinstance(inner, dict)
                                     and isinstance(inner.get(k), str)
                                     and inner[k].strip() else "")
                            return v.strip(), f"{label}:{where}{k}"
    return None, None


#: The list Phase 1 writes beside `pdk_target` holding the OTHER process names
#: the design declares ON THE SAME target row. `declared_pdk_target_guard`
#: already honours it (a design that names two targets may be built on either);
#: this gate did not, so the two consumers of one declaration disagreed.
_L19_ALT_KEYS = ("pdk_target_alternates",)


def declared_alternates(run: Path) -> List[str]:
    """The OTHER process names the design declares on its own target row.

    A design may legitimately declare more than one target — "SKY130 primary;
    GF180MCU secondary" is one declaration naming two processes — and a run
    builds ONE of them. Reading only the scalar `pdk_target` makes every build
    of a SECOND declared target look like a contradiction: the gate reports
    that the declaration names a process no loaded library corroborates, which
    is true of the name it read and false of the declaration it came from.

    Same probe order and same envelope handling as `declared_target`, so the
    two cannot resolve from different documents. Returns [] when the key is
    absent, which is every single-target design — those read exactly as before.
    Chip/PDK-AGNOSTIC: the names come from the design's own L-doc."""
    for kind, rel in (("l-doc-canonical", "L19"),
                      ("l-doc", "phase1/L19_CONSTRAINTS_PDK.json")):
        for base in (run, run / "run"):
            for _label, doc in _probe(base, kind, rel):
                payload: Dict[str, Any] = l_doc_fields(doc)
                for k in _L19_ALT_KEYS:
                    for scope in (payload, doc):
                        v = scope.get(k)
                        if isinstance(v, list):
                            out = [str(x).strip() for x in v
                                   if isinstance(x, str) and str(x).strip()]
                            if out:
                                return out
    return []


def loaded_libraries(run: Path, cap: int = 400) -> Tuple[Set[str], int]:
    """Every .lef/.lib basename the tools actually read, from their own logs.

    The tool's log is used rather than the flow's configuration because the
    question is what RAN, and a configuration that was ignored is precisely the
    failure being looked for.

    THE LIMIT OF THIS CHANNEL, MEASURED (vibe-ic#1002)
    -------------------------------------------------
    A published run does not have to keep its tool logs, and most do not. Of
    the 107 tracked run dirs, 9 declare a target and produce ZERO library
    names here; 7 of those carry no ``*.log`` at all. Three of the nine
    nevertheless carry a MAPPED gate-level netlist whose instantiated cell
    names would answer the question — and each of those three CORROBORATES its
    own declaration, so nothing was hidden. The netlist is deliberately NOT
    read here: adding a second evidence channel changes what the gate PASSES as
    well as what it refuses, and that is a separate measured change, not a
    rider on a refusal fix. Until then a run with no tool log gets rc 2 with
    the missing input named, never a verdict.
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

    # AN EXPLICIT "NOT APPLICABLE" IS A DECLARATION THAT THERE IS NO TARGET.
    #
    # It is folded into the no-target state rather than given a branch of its
    # own, so every existing rule applies to it unchanged: with no library load
    # it is rc=2 NOT CHECKED, and with libraries loaded it is still the FAIL
    # below — a design that says it is not a tapeout and then loaded cell
    # libraries has not shown which process it used either.
    #
    # The written value is NOT discarded. It is carried in its own field so a
    # reader can tell "the field was never populated" from "the design said, in
    # so many words, that it has no target" — two different states that would
    # otherwise both print as `declared_target: null`.
    not_applicable = target is not None and declares_no_target(target)
    if not_applicable:
        declared_not_applicable, declared_not_applicable_source = target, source
        target, source = None, None
    else:
        declared_not_applicable = declared_not_applicable_source = None

    rec: Dict[str, object] = {
        "declared_target": target, "declared_source": source,
        "declared_not_applicable": declared_not_applicable,
        "declared_not_applicable_source": declared_not_applicable_source,
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
        rec["reason"] = (
            ("the design declares its PDK target NOT APPLICABLE "
             f"({declared_not_applicable!r}) and no cell library was loaded — "
             "no physical implementation to judge")
            if not_applicable else
            ("the design declares no PDK target and no cell library was "
             "loaded — no physical implementation to judge"))
        _emit(a.json, rec)
        print(f"declared_pdk_is_the_pdk_used: rc=2 NOT CHECKED — {rec['reason']}")
        return 2

    if not libs:
        # A ZERO DENOMINATOR REFUSES; IT DOES NOT FAIL (vibe-ic#1002).
        #
        # This branch used to be rc 1 with the reason "this run's logs record no
        # cell-library load at all ... it is the absence of the evidence the
        # question needs" — a sentence that states a REFUSAL and then returns a
        # VERDICT. `gate_zero_denominator_refuses_check` is the house rule for
        # exactly that shape: a zero beside a POPULATION word is "not a result at
        # all". A FAIL says "I looked and it was wrong"; this branch printed
        # `0 librar(ies) across N log(s) — nothing to compare` on the line under
        # its own FAIL.
        #
        # MEASURED, `tools/d9_corpus_baseline.py --only
        # declared_pdk_is_the_pdk_used_check` on 107 published run dirs: RED 10.
        # NINE of the ten are this branch; the tenth is the contradiction this
        # file was written for and is untouched below. Seven of the nine carry
        # no `*.log` at all — the scan population itself is empty. The other two
        # scanned 9 and 1 logs, both of which are a simulation-soak log and a
        # formal-proof log: a real file population, zero comparanda, which is
        # the same zero denominator arriving by a different route.
        #
        # THE MOTIVATING DEFECT IS NOT SOFTENED, and that is checkable rather
        # than asserted. The docstring's own case is "the place-and-route log
        # named the image's built-in cell library 72 times" — `libs` NON-empty,
        # so it never reaches this branch. The corpus agrees: the one root whose
        # logs DO name libraries that contradict its declaration still exits 1.
        #
        # WHAT THIS COSTS, said out loud rather than left for a reader to find.
        # The prior FAIL was defended (#710) on the theory that a vanished PDK
        # is "just as capable of producing logs that name nothing as logs that
        # name the wrong thing". That theory was never measured; it is measured
        # here, and on this corpus it does not hold: of the nine, none carries a
        # generated artefact that contradicts its own declaration, and three
        # carry a gate-level netlist whose cell names CORROBORATE it. So the
        # nine hid no contradiction — but the netlist is evidence this gate does
        # not read, and that limit is recorded in `loaded_libraries.__doc__`.
        rec["verdict"] = "NOT CHECKED"
        rec["no_library_load_recorded"] = True
        rec["reason"] = ("a PDK target is declared and this run records no "
                         "cell-library load to compare it against, so the "
                         "question this gate asks cannot be asked of this run. "
                         "This is NOT a finding that a different PDK was used, "
                         "and it is NOT a pass: it is a refusal, and the input "
                         "it lacks is named below.")
        rec["missing_input"] = (
            "a recorded cell-library load: no *.log under the run names a "
            ".lef/.lib file")
        _emit(a.json, rec)
        print(f"declared_pdk_is_the_pdk_used: rc=2 NOT CHECKED — {rec['reason']}")
        print(f"    declared : {target}   (from {source})")
        print(f"    staged   : {staged} file(s) under input/pdk/")
        print(f"    MISSING  : a recorded cell-library load — 0 librar(ies) "
              f"named across {scanned} log(s) scanned, nothing to compare")
        return 2

    want = tokens(target)
    hits = sorted({n for n in libs
                   if shares_identity(want, n) or shares_stem_identity(want, n)})
    rec["declared_tokens"] = sorted(want)
    rec["matching_libraries"] = hits

    # A CONTRADICTION OUTRANKS A PARTIAL MATCH (vibe-ic#713). `hits` only says
    # SOME declared token matched SOME library. If the same declaration also
    # names a PDK that nothing loaded corroborates, the two halves of the
    # sentence disagree, and the half that names a different process is the one
    # this gate exists to catch — it cannot be outvoted by a token that happens
    # to match.
    #
    # A CONTRADICTION NEEDS A LOAD TO CONTRADICT. With `libs` empty every named
    # PDK is trivially "uncorroborated", so this test would fire on EVERY run
    # that declares a named process and has not run a tool yet, and would print
    # "no loaded library carries that identity" over `loaded: 0`. That is the
    # unsupported accusation the `if not libs` branch below exists to remove,
    # arriving one branch earlier. The verdict for that state is unchanged —
    # still FAIL, from that branch, with `no_library_load_recorded: true` and
    # the reason that is actually true. So `contradicting_named_pdks: []` here
    # means "no contradiction was ESTABLISHED", and the flag beside it says
    # whether there was any evidence to establish one from.
    #
    # Unreachable before the `declared_target` repair in this same change: the
    # reader resolved nothing, so no run ever got this far.
    contradicted = contradicting_named_pdks(target, libs) if libs else []

    # A CO-DECLARED SECOND TARGET IS NOT A CONTRADICTION.
    #
    # `pdk_target` is a SCALAR cut out of a declaration that may name more than
    # one process ("open-source (SKY130 primary; GF180MCU secondary)"). Phase 1
    # records the co-declared names on the same row in `pdk_target_alternates`,
    # and `declared_pdk_target_guard` already lets a run be built on any of
    # them. This gate read only the scalar, so building the SECOND declared
    # target read as "the declaration names a process no loaded library
    # corroborates" — MEASURED on subservient x gf180mcuD (r7): the run loaded
    # `gf180mcu_fd_sc_mcu7t5v0` throughout, the design declares both, and the
    # gate FAILed on the name that was NOT built. Two consumers of one
    # declaration must not disagree about what it permits.
    #
    # NARROW BY CONSTRUCTION: an alternate only clears a token when a LOADED
    # library corroborates that alternate. A process merely listed and never
    # built clears nothing, and a design with no alternates (every
    # single-target design) takes the identical path it did before.
    alternates = declared_alternates(run) if contradicted else []
    rec["declared_alternates"] = alternates
    corroborated_alt = sorted(
        {a for a in alternates
         if any(shares_identity(tokens(a), n) for n in libs)})
    if contradicted and corroborated_alt:
        rec["contradiction_cleared_by_alternate"] = corroborated_alt
        rec["not_built"] = contradicted
        contradicted = []
        # The libraries that corroborate the BUILT alternate are matches for
        # this declaration too — otherwise the run falls through to "declared a
        # target and no loaded library matches it", which is the same false
        # accusation one branch later.
        alt_hits = sorted({n for n in libs
                           for a in corroborated_alt
                           if shares_identity(tokens(a), n)})
        hits = sorted(set(hits) | set(alt_hits))
        rec["matching_libraries"] = hits

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
        if rec.get("contradiction_cleared_by_alternate"):
            print("    the design declares more than one target; this run built "
                  f"{rec['contradiction_cleared_by_alternate']} and NOT "
                  f"{rec['not_built']} — both are named on the design's own "
                  "target row (pdk_target_alternates), so this is a choice "
                  "among declared targets, not a substitution.")
        rec["not_verified"] = "foundry / process node (not derivable from a library filename)"
        _emit(a.json, rec)
        print(f"declared_pdk_is_the_pdk_used: PASS — {len(hits)} of {len(libs)} loaded "
              f"librar(ies) match the declared target ({source})")
        print(f"    verified: library identity. NOT verified: any foundry or "
              f"process-node claim in the same declaration — a LEF filename "
              f"does not carry either.")
        return 0

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
