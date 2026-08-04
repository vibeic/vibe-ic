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
       it cannot show it used the intended process. A design that writes down
       an explicit "not applicable" IS in this state and is judged in it, with
       the written words carried in `declared_not_applicable` so the record
       distinguishes "said so" from "never populated the field".

PROVENANCE COMES FROM THE RESOLVED LOAD PATH, NOT FROM A LIBRARY FILENAME
=========================================================================
This gate's own PASS record said what it could not answer:

    verified     : "library identity only"
    not_verified : "foundry / process node (not derivable from a library filename)"

That sentence is true of a FILENAME and it was the whole of the evidence,
because `loaded_libraries` kept `m.rsplit("/", 1)[-1]` and threw the directory
chain away. The tool had already resolved the full path — the kit's own
directory is in every load line it wrote — and the gate discarded it before
deciding anything.

MEASURED on this repo's own tracked corpus, one project (`benchmark-data/ic/
caravel_user_project`): the gate reported

    PASS — 2 of 2 loaded librar(ies) match the declared target

while a grep of that same run resolves **5** distinct library load paths, every
one of them under a single kit directory. Two of the three it missed are timing
corners; the third is the TECHNOLOGY LEF — `.tlef`, the file that describes the
metal stack, which `LIB_RE` did not match at all. So the most process-identifying
load in the run was invisible to the gate whose job is to identify the process,
and "2 of 2" printed a sample as if it were a population.

WHAT THIS CHANGE DOES AND DOES NOT RECOVER THERE, precisely: keeping the path
and matching `.tlef` takes that project from 2 to 3 out of the 5, all three from
its `*.log` files. The two corner libraries are named only in that project's
`.rpt` and `.tcl` artefacts, which this program deliberately does not read — a
configuration that was ignored is the failure being looked for, so it must not
be trusted as evidence of a load. For those the change is not a recovery but a
denominator: the record now states how many load paths were examined, out of how
many log files, out of how many exist, instead of leaving a reader to assume.

Three things change, and they are one rule:

  * the RESOLVED PATH is kept and is what provenance is decided from. A load
    corroborates the declaration by its filename OR by the directory the tool
    resolved — the second is the stronger fact, and it is the only one available
    for a kit whose libraries are named for a family rather than a process.
  * a named process in a load-path directory that the declaration does NOT name,
    and no declared alternate names, is a FAIL (`foreign_named_pdk_roots`). This
    is the direction the defect at the top of this file runs in and the one
    `contradicting_named_pdks` structurally cannot see, because a proprietary
    declaration names nothing checkable for it to test.
  * every count is printed against its denominator, and both truncations this
    program applies — the 400-log scan cap and the 40-entry record list — are
    flagged (`logs_found`, `logs_scan_truncated`, `libraries_examined`,
    `libraries_loaded_truncated`). A partial sample must not read as a full one.

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

#: `.tlef` is a LEF — the TECHNOLOGY LEF, the one file in the set that describes
#: the metal stack itself. It was outside this pattern, so the single most
#: process-identifying load in a run was invisible to the gate that exists to
#: identify the process. Measured on the tracked corpus below. `t?lef` is a
#: FILE-FORMAT suffix, not a PDK literal, so the file stays chip-AGNOSTIC.
LIB_RE = re.compile(r"[A-Za-z0-9_./+-]+\.(?:t?lef|lib)\b")
# A declared target is prose ("Some Foundry ABC123-X1.2"), a loaded library is a
# filename ("abc123xyz_sc_hd.lef"). Comparing them needs the alphanumeric runs they
# share, not string equality — so reduce both to lowercase tokens of >=3 chars.
TOKEN_RE = re.compile(r"[a-z0-9]{3,}")

# Tokens that carry no identity: every PDK has cells and corners.
STOPWORDS = {
    # `tlef` joins `lef`/`lib` for the same reason they are here: it is a file
    # format, and every kit that ships one ships it under that suffix.
    "the", "and", "for", "lib", "lef", "tlef", "gds", "cdl", "spi", "sch", "typ", "min",
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

    Only NAMED PDKs are judged, because only they are checkable from the run's
    own load evidence. A foundry or a node in the same sentence ("Foundry R,
    55nm") is not derivable from a load path either, and the caller DISCLOSES
    that rather than letting a PASS imply it was verified.

    ``libs`` is now the evidence STRINGS, basename AND resolved-path provenance,
    not basenames alone. A kit whose filenames never spell it out is corroborated
    by the directory it was read from, which is what stops this from reporting a
    contradiction against a load that plainly corroborates the declaration.

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


def loaded_libraries(run: Path, cap: int = 400) -> Tuple[Set[str], int, int]:
    """Every RESOLVED library load path the tools read, from their own logs.

    The tool's log is used rather than the flow's configuration because the
    question is what RAN, and a configuration that was ignored is precisely the
    failure being looked for.

    THE PATH IS THE EVIDENCE, AND IT WAS BEING THROWN AWAY
    =====================================================
    This returned `m.rsplit("/", 1)[-1]` — the BASENAME — and discarded the
    directory chain the tool had just resolved. A basename is a name a vendor
    chose; the resolved path is where the bytes came from, which is the only
    thing in the run that answers "which process kit did this tool read".

    Two consequences, both measured:

      * A library whose filename carries no process identity at all
        (`NangateOpenCellLibrary.lef`, `merged.lef`, `cells.lib`) contributed
        NOTHING, even when the directory that held it named the process
        outright. `shares_stem_identity` exists in this file solely to
        reconstruct, from CamelCase guesswork on a filename, an identity the
        path was carrying literally one component up.
      * Distinct load paths that happen to share a basename collapsed into one
        entry, so the count the gate reported was a count of NAMES, not of
        LOADS — and the same basename read out of two different kits (a staged
        copy and the image's built-in) is exactly the substitution this file
        was written to catch, reduced to a single indistinguishable string.

    Returns (resolved paths, logs scanned, logs eligible). The last two are
    returned SEPARATELY and reported separately because the `cap` silently
    truncates: `scanned` was printed as though it were the whole run.

    Chip-AGNOSTIC: no process, foundry or vendor literal — only path structure.
    """
    eligible = [p for p in sorted(run.rglob("*.log"))
                # the plugin's own tree is not the run
                if "/plugin_work/" not in str(p) and "/plugin_" not in str(p)]
    paths: Set[str] = set()
    scanned = 0
    for log in eligible[:cap]:
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        scanned += 1
        for m in LIB_RE.findall(text):
            paths.add(m)
    return paths, scanned, len(eligible)


def basename_of(path: str) -> str:
    """The filename at the end of a resolved load path."""
    return path.rsplit("/", 1)[-1]


def provenance_of(path: str, run_tokens: Set[str], run_abs: str = "") -> str:
    """The directory chain of a load path, with the RUN's own filing removed.

    WHY ANYTHING IS REMOVED. Provenance means "where did these bytes come
    from", and the answer is only informative for the part of the path the RUN
    did not author. A run directory is very often named for a process
    (`<design>_<process>/`, `clean_run_<...>_<process>_<date>/` — this repo's own
    corpus is full of both). If the whole path counted, a run stored under such a
    directory would corroborate its own declaration out of its own folder name.
    The reasoning would be circular and the gate would report that it had
    confirmed the kit when it had confirmed the filing system.

    Two removals, and they cover the two ways a path can be the run's own:

      CONTAINMENT  a load that resolves INSIDE the run directory carries no
                   provenance at all. The flow put those bytes there — a staged
                   copy, a per-round working tree — so the directory names are
                   the flow's, not a kit's. Such a load is still judged, by its
                   FILENAME, exactly as it was before this function existed.
                   MEASURED: without this, a per-round directory named for the
                   process corroborated two memory-macro loads whose filenames
                   carry no process identity, out of a folder the run made.
      NAME         a component whose every identity token is also a token of the
                   run root's own absolute path. Containment cannot see this one:
                   tools log CONTAINER paths (`/run/<name>/...`), so the host run
                   root never appears as a prefix even though it is the same
                   directory.

    A component that carries no identity tokens at all (`..`, `lef`, a
    two-character directory) is kept and simply contributes nothing downstream.
    Case is preserved, because `shares_stem_identity` reads CamelCase segments.

    Chip-AGNOSTIC: pure path structure, no PDK/vendor/foundry literal.
    """
    if run_abs and (path == run_abs or path.startswith(run_abs.rstrip("/") + "/")):
        return ""                    # the run's own tree is not provenance
    head = path.rsplit("/", 1)[0] if "/" in path else ""
    if not head:
        return ""
    keep = []
    for comp in head.split("/"):
        if not comp:
            continue
        t = tokens(comp)
        if t and t <= run_tokens:
            continue                 # this component identifies the run, not a kit
        keep.append(comp)
    return "/".join(keep)


def run_path_tokens(run: Path) -> Set[str]:
    """Identity tokens of the run root's own absolute path."""
    try:
        return tokens(str(run.resolve()))
    except OSError:                                 # pragma: no cover - defensive
        return tokens(str(run))


def foreign_named_pdk_roots(target: str, alternates: List[str],
                            provenances: Dict[str, str]) -> Dict[str, str]:
    """Named PDKs a LOAD PATH names that the declaration does not account for.

    THE OTHER DIRECTION, AND THE ONE THE MOTIVATING DEFECT IS IN.
    `contradicting_named_pdks` asks whether everything the DECLARATION names was
    corroborated by a load. It cannot see the reverse — a run that reached into
    a kit the declaration never mentions — because a declaration written as
    prose about a proprietary process names no checkable PDK at all, so that
    function returns [] and the gate falls through to whatever the filenames
    happened to match.

    That is precisely the run this file's header describes: the staged kit went
    missing, the tools read the open kit baked into the image, and the flow
    completed. From a BASENAME that substitution is invisible whenever the
    vendor's filenames do not spell the kit out. From the resolved path it is
    not invisible at all — the kit's own directory is in every load line.

    ACCOUNTED-FOR is deliberately generous, because a false accusation here is
    worse than a missed one: a root is cleared when the declaration or ANY
    co-declared alternate names it, when the two names are the same identifier
    under `shares_identity` in EITHER direction (so a declaration of the family
    covers a load from the lettered variant of that family, and a bare kit name
    covers the vendor-prefixed spelling of it), or when a declared token carries
    its identity. Only a root that survives all of that is reported.

    ``provenances`` maps each distinct provenance string to one resolved load
    path that carries it. Returns {named pdk: that example load path}, so the
    finding always ships the evidence that produced it.

    Chip-AGNOSTIC: the vocabulary is `_NAMED_PDK_RE`, this repo's existing
    open-PDK table, already used by `contradicting_named_pdks`.
    """
    def _norm(s: str) -> str:
        return s.lower().replace(" ", "-").replace("-", "")

    accounted = set()
    for text in [target or ""] + list(alternates or []):
        accounted |= {_norm(m.group(1)) for m in _NAMED_PDK_RE.finditer(text)}
    want = tokens(target or "")

    out: Dict[str, str] = {}
    for prov in sorted(provenances):
        for m in _NAMED_PDK_RE.finditer(prov):
            name = _norm(m.group(1))
            if name in out or name in accounted:
                continue
            if any(shares_identity({name}, a) or shares_identity({a}, name)
                   for a in accounted):
                continue
            if shares_identity(want, name) or shares_stem_identity(want, name):
                continue
            out[name] = provenances[prov]
    return out


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
    libs, scanned, logs_found = loaded_libraries(run)
    staged = staged_pdk_files(run)
    unnameable = unnameable_staged_pdk(run)

    # PROVENANCE, PER RESOLVED LOAD PATH. `basenames` keeps the old signal for
    # any consumer that wants it; `prov` is the directory chain the tool reached
    # into, with the run's own path components removed (see `provenance_of`).
    run_tokens = run_path_tokens(run)
    try:
        run_abs = str(run.resolve())
    except OSError:                                 # pragma: no cover - defensive
        run_abs = str(run)
    basenames = {p: basename_of(p) for p in libs}
    prov = {p: provenance_of(p, run_tokens, run_abs) for p in libs}
    # distinct provenance -> one example load path that carries it
    prov_examples: Dict[str, str] = {}
    for p in sorted(libs):
        prov_examples.setdefault(prov[p], p)
    prov_examples.pop("", None)

    # A SAMPLE MUST NOT READ AS A POPULATION. Every count the record and the
    # printed lines quote is stated against the total it was drawn from, and the
    # two truncations this program applies — the 400-log scan cap and the 40-entry
    # record list — are flagged instead of being invisible. The gate that reported
    # "2 of 2 loaded librar(ies) match" on a run whose logs resolve five distinct
    # load paths was not lying about the 2; it was silent about the denominator.
    logs_truncated = logs_found > scanned
    listed = sorted(libs)[:40]

    def _examined() -> str:
        """The one sentence every verdict prints, denominators included."""
        s = (f"{len(libs)} distinct resolved load path(s) "
             f"/ {len(set(basenames.values()))} distinct filename(s), "
             f"from {scanned} of {logs_found} log file(s)")
        return s + (" — SAMPLE: the log scan hit its cap, this is not the "
                    "whole run" if logs_truncated else "")

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
        "logs_found": logs_found, "logs_scan_truncated": logs_truncated,
        "unnameable_staged_pdk": unnameable,
        # `libraries_loaded` is now RESOLVED LOAD PATHS, and it is a SAMPLE:
        # `_total` is the population it was drawn from and `_truncated` says
        # whether the list below it is the whole of that population.
        "libraries_loaded": listed,
        "libraries_examined": len(libs),
        "libraries_loaded_truncated": len(libs) > len(listed),
        "libraries_loaded_basenames": sorted(set(basenames.values())),
        "load_path_provenances": sorted(prov_examples),
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
        print(f"    examined : {_examined()}")
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
            print(f"    examined : {_examined()}")
            for n in listed[:8]:
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

    want = tokens(target)

    # PROVENANCE IS DECIDED FROM THE RESOLVED LOAD PATH, NOT FROM A FILENAME.
    #
    # A load corroborates the declaration when the declared identity is in the
    # FILENAME (what this gate used to be able to see) or in the DIRECTORY CHAIN
    # the tool resolved (what it threw away). The path is the stronger evidence
    # of the two: a filename is a name a vendor chose and need not carry the kit
    # at all, while the directory is where the bytes came from.
    #
    # This can only ADD corroboration, never remove it — every filename match
    # that passed before still passes, byte for byte. What it adds is the case
    # the old gate could not answer: a kit whose libraries are named for the
    # FAMILY and not the process, read out of a directory that names the process
    # outright. `shares_stem_identity` was reconstructing that identity from
    # CamelCase guesswork on the filename; the path states it.
    def _matches(p: str) -> Tuple[bool, bool]:
        base, pv = basenames[p], prov[p]
        on_name = shares_identity(want, base) or shares_stem_identity(want, base)
        on_path = bool(pv) and (shares_identity(want, pv)
                                or shares_stem_identity(want, pv))
        return on_name, on_path

    match = {p: _matches(p) for p in libs}
    hits = sorted(p for p in libs if any(match[p]))
    by_path_only = sorted(p for p in libs if match[p][1] and not match[p][0])
    rec["declared_tokens"] = sorted(want)
    rec["matching_libraries"] = hits
    rec["matching_libraries_total"] = len(hits)
    rec["matched_by_load_path_only"] = by_path_only

    # The evidence strings the named-PDK tests read: BOTH halves of every load.
    evidence = sorted({basenames[p] for p in libs} | {prov[p] for p in libs if prov[p]})

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
    contradicted = contradicting_named_pdks(target, evidence) if libs else []

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
    # Read once and reused by the foreign-root test below, which needs the same
    # "what did the design actually declare" answer. `contradicted` no longer
    # gates the read, because a run can have a foreign root with no contradiction.
    alternates = declared_alternates(run) if libs else []
    rec["declared_alternates"] = alternates
    corroborated_alt = sorted(
        {a for a in alternates
         if any(shares_identity(tokens(a), n) for n in evidence)})
    if contradicted and corroborated_alt:
        rec["contradiction_cleared_by_alternate"] = corroborated_alt
        rec["not_built"] = contradicted
        contradicted = []
        # The libraries that corroborate the BUILT alternate are matches for
        # this declaration too — otherwise the run falls through to "declared a
        # target and no loaded library matches it", which is the same false
        # accusation one branch later.
        alt_hits = sorted({p for p in libs
                           for a in corroborated_alt
                           if shares_identity(tokens(a), basenames[p])
                           or (prov[p] and shares_identity(tokens(a), prov[p]))})
        hits = sorted(set(hits) | set(alt_hits))
        rec["matching_libraries"] = hits
        rec["matching_libraries_total"] = len(hits)

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

    # A KIT THE DECLARATION NEVER MENTIONS, READ FROM ITS OWN DIRECTORY.
    #
    # This is the reverse of `contradicting_named_pdks` and it is the direction
    # the defect at the top of this file actually runs in. That test asks whether
    # everything the DECLARATION names was corroborated; it is silent whenever
    # the declaration names nothing checkable — which is every design whose
    # target is proprietary prose. So a run that declared such a target and then
    # read a recognisable open kit out of the image reached the `hits` branch
    # below on whatever its filenames happened to match, and PASSed.
    #
    # From a basename that substitution is invisible unless the vendor spelled
    # the kit into every filename. From the resolved path it is in every load
    # line the tool wrote. This test is only possible at all because the path is
    # now kept.
    #
    # It is checked AFTER `contradicted` (that finding is more specific: the
    # declaration's own words are unsupported) and BEFORE `hits`, because a
    # filename match must not outvote a directory that names another process —
    # the same precedence argument #713 made for contradictions.
    foreign = (foreign_named_pdk_roots(target, alternates, prov_examples)
               if libs else {})
    rec["foreign_named_pdk_roots"] = foreign
    if foreign:
        rec["verdict"] = "FAIL"
        rec["reason"] = (
            "the tools read cell libraries out of "
            + ", ".join(f"{k} ({v})" for k, v in sorted(foreign.items()))
            + " — a process kit the declaration does not name, and no declared "
              "alternate names either. The declaration and the load path "
              "disagree about which process this run implemented against.")
        _emit(a.json, rec)
        print(f"declared_pdk_is_the_pdk_used: FAIL — {rec['reason']}",
              file=sys.stderr)
        print(f"    declared : {target}   (from {source})", file=sys.stderr)
        print(f"    examined : {_examined()}", file=sys.stderr)
        for k, v in sorted(foreign.items()):
            print(f"        {k}  <-  {v}", file=sys.stderr)
        return 1

    if hits:
        rec["verdict"] = "PASS"
        rec["no_library_load_recorded"] = False
        # WHAT THIS PASS DOES NOT COVER, said out loud. A foundry or a process
        # node in the same declaration is derivable from neither a filename nor
        # a load path, so it was not checked — and a PASS that stays silent
        # about that reads as though it had been.
        #
        # WHICH EVIDENCE ANSWERED is now recorded too. "library identity only"
        # is kept verbatim for the case it was written for — a match the
        # FILENAME alone supports — so a reader (and this file's own tests) can
        # still tell that state apart. When the directory the tool resolved
        # carried the identity, that is the stronger fact and it is named.
        rec["verified"] = ("library identity + load-path provenance"
                           if by_path_only else "library identity only")
        rec["provenance_source"] = ("load path" if by_path_only
                                    else "library filename")
        if rec.get("contradiction_cleared_by_alternate"):
            print("    the design declares more than one target; this run built "
                  f"{rec['contradiction_cleared_by_alternate']} and NOT "
                  f"{rec['not_built']} — both are named on the design's own "
                  "target row (pdk_target_alternates), so this is a choice "
                  "among declared targets, not a substitution.")
        rec["not_verified"] = ("foundry / process node (not derivable from a "
                               "library filename)")
        _emit(a.json, rec)
        print(f"declared_pdk_is_the_pdk_used: PASS — {len(hits)} of {len(libs)} "
              f"resolved library load path(s) match the declared target ({source})")
        print(f"    examined : {_examined()}")
        if by_path_only:
            print(f"    provenance: LOAD PATH — {len(by_path_only)} of these "
                  f"carry the declared identity in the directory the tool "
                  f"resolved, not in the filename, e.g. {by_path_only[0]}")
        print(f"    verified: library identity"
              + (" + load-path provenance" if by_path_only else "")
              + ". NOT verified: any foundry or process-node claim in the same "
                "declaration — neither a filename nor a load path carries "
                "either.")
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
        print(f"    examined : {_examined()} — nothing to compare")
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
    print(f"    examined : {_examined()}, none matching")
    for n in listed[:8]:
        print(f"        {n}")
    return 1


def _emit(path: Optional[Path], rec: Dict[str, object]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
