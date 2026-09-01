#!/usr/bin/env python3
"""_analog_a_check_common.py — v1.6.35 shared helpers for the
A1-A8 deterministic artefact-presence + substance gates.

Each gate (`analog_a{1..8}_*_check.py`) imports a small set of
helpers from here:
  * `block_list_path(project)`     → the analog_block_list.json this
                                       project actually carries, or `None`.
  * `load_block_list(project)`     → list[str] of declared block names,
                                       or `None` when no analog work.
  * `select_blocks(blocks, name?)` → restrict to a single block when
                                       `--block <name>` is given.
  * `iter_blocks(args, project)`   → yield (block, ...) per CLI options.
  * `emit_report(...)` / `cli_main(...)` are intentionally NOT here —
    each gate has its own audit logic and exit semantics.

VACUOUS_PASS contract (chip-AGNOSTIC):
  * `analog_block_list.json` absent from EVERY candidate root
    (`phase3/analog/` — where the analog runner writes it — and
    `phase1/analog/` — where the flow declares it and where
    `migrate_to_layout_p` moves it) or empty → exit 0 +
    "VACUOUS_PASS: no analog blocks declared".
  * Per-block, when called WITHOUT `--block`: report verdict per
    project (combine all blocks).
  * Per-block, when called WITH `--block <name>` AND the block's
    canonical artefact is missing: exit 2 + stderr message naming
    the upstream skill, so analog_one_shot_runner emits WAIVED
    (back-compat with the v1.6.34 runner behaviour).
  * Per-block, when artefact is present but stub: exit 1 (FAIL).

INCOMPLETE contract (project mode only):
  * When SOME declared blocks carry the step's artefact and others
    carry none, the step is NOT done. `emit_incomplete` reports
    verdict INCOMPLETE, names every uncovered block, and exits 1.
    The all-blocks-missing case keeps its VACUOUS_PASS (the "the
    skill has not run yet, defer to it" contract) and `--block` mode
    keeps its exit-2 WAIVED deferral untouched.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence, Tuple


# ── where the block list actually lives ───────────────────────────────────
# Two producers write `analog_block_list.json` at two different roots and
# BOTH are legitimate:
#   * the analog runner writes it under `_pl.analog_dir` == `phase3/analog/`;
#   * `flow/phase1_phase2_phase3.yaml` declares EVERY A-step's applicability
#     `condition: files_exist: ["phase1/analog/analog_block_list.json"]`, and
#     `migrate_to_layout_p.py` moves a top-level `analog/analog_block_list.json`
#     to exactly that phase1 path.
# Until this change this helper read the phase3 path ONLY. A project laid out
# as its own flow declares therefore made the A-step CONDITION true (the step
# is applicable and must be gated) while every A-gate answered
# "VACUOUS_PASS: block list missing" — a gate certifying a step it never
# measured. Measured on a synthetic project carrying only the phase1 list and
# a 34-byte `layout.mag` stub: `analog_a5_layout_check` rc=0 VACUOUS_PASS,
# while the byte-identical project with the list at the phase3 path gave rc=1
# FAIL (A5_LAYOUT_TOO_SMALL).
#
# Probing both roots can only ever move a gate from VACUOUS_PASS(0) to real
# gating (0 or 1) — it never turns a red gate green. Canonical (runner) root
# first so runner-produced projects resolve to byte-identical paths.
# The sibling readers `mixed_signal_cosim_check` (:252-253),
# `mixed_signal_signoff_check` (:69-72) and `analog_block_list_emit_check`
# (:59-61) already probe multiple roots; this brings the A1-A9 gates in line.
_BLOCK_LIST_ROOTS = ("phase3/analog", "phase1/analog")

BLOCK_LIST_ABSENT_REASON = (
    "no analog_block_list.json under " +
    " or ".join(f"{r}/" for r in _BLOCK_LIST_ROOTS) +
    ", or it declares no blocks; gate inapplicable."
)


def block_list_path(project: Path) -> Optional[Path]:
    """First `analog_block_list.json` that exists across the candidate
    roots, or None when the project carries none. Canonical runner root
    (`phase3/analog/`) wins over the flow-declared root (`phase1/analog/`)
    so a runner-produced project keeps resolving exactly as before."""
    for root in _BLOCK_LIST_ROOTS:
        cand = project / root / "analog_block_list.json"
        if cand.is_file():
            return cand
    return None


def load_block_list(project: Path) -> Optional[List[str]]:
    """Return list of declared analog block names, or None when no
    analog block list exists at ANY candidate root. Empty list when a
    file exists but declares no blocks.
    """
    path = block_list_path(project)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    blocks = data.get("blocks") if isinstance(data, dict) else data
    if not isinstance(blocks, list):
        return []
    out: List[str] = []
    for entry in blocks:
        if isinstance(entry, str) and entry:
            out.append(entry)
        elif isinstance(entry, dict):
            name = entry.get("name") or entry.get("block")
            if isinstance(name, str) and name:
                out.append(name)
    return out


# ── ORGANIC #676 — analog class-N/A predicate ──────────────────────────────
# The 3 analog P0 gates (analog_flow_compliance_check /
# analog_digital_interface_check / analog_a6_block_pv_check) used to hard-FAIL
# whenever analog_block_list.json carried ANY block — even a phantom
# `low_confidence` block fabricated from a digital keyword ("POR") on a
# pure-digital SoC classified `analog_applicable=false` /
# `verification_track=generic_full_stack`. The SIBLING analog gates already
# self-skip as N/A on a non-analog IC; these 3 lacked any class awareness.
# This shared predicate gives all three the SAME class-N/A read so a digital
# SoC SKIPs (N/A) instead of FAILing.
#
# §4.05 no-leak: returns True (→ N/A skip) ONLY when the IC is positively
# classified non-analog AND every declared block is low_confidence (a phantom
# keyword hit). A REAL analog IC (has_analog:true / analog_applicable:true) or
# a high-confidence (spec-backed) block returns False → still gated.
# chip-AGNOSTIC: reads the IC-class verdict + the per-block low_confidence tag;
# no chip / vendor / class literal.

def _ic_class_says_non_analog(project: Path) -> bool:
    """True iff the IC is positively classified as NON-analog, via
    reports/ic_class.json (`has_analog:false`) and/or the registry
    verification flags (`analog_applicable:false` /
    `verification_track=="generic_full_stack"`). Fail-closed: if no class
    verdict is available at all, returns False (the IC is NOT assumed
    non-analog — existing gating is never weakened)."""
    for rel in ("reports/ic_class.json",
                "reports/phase1/ic_class.json"):
        p = project / rel
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        # Direct, explicit non-analog signal.
        if data.get("has_analog") is False:
            return True
        if data.get("is_pure_analog") is True or data.get("is_mixed_signal") is True:
            return False
        # Registry-backed verification flags (analog_applicable /
        # verification_track) for the detected class.
        ic_class = data.get("ic_class")
        if isinstance(ic_class, str) and ic_class:
            try:
                import ic_class_profile as _icp
                flags = _icp.class_verification_flags(ic_class)
                if (flags.get("analog_applicable") is False
                        and flags.get("verification_track")
                        == "generic_full_stack"):
                    return True
            except Exception:
                pass
    return False


def _all_blocks_low_confidence(project: Path) -> bool:
    """True iff EVERY declared analog block is tagged `low_confidence:true`
    (a phantom keyword hit, never a spec-backed block). An empty list returns
    False here — the caller's existing empty-list VACUOUS path handles that.
    A list with ANY high-confidence (spec-backed) block returns False so a real
    analog IC is still gated.

    Resolves the list through `block_list_path` — the SAME resolution
    `load_block_list` uses. If it read only the phase3 root while
    `load_block_list` probed both, a pure-digital SoC declaring phantom
    low_confidence blocks at the phase1 root would newly hard-FAIL instead of
    taking the ORGANIC #676 N/A skip."""
    path = block_list_path(project)
    if path is None:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return False
    blocks = data.get("blocks") if isinstance(data, dict) else data
    if not isinstance(blocks, list) or not blocks:
        return False
    for entry in blocks:
        if not isinstance(entry, dict):
            return False  # bare-string block → treat as confident → gate it
        if entry.get("low_confidence") is not True:
            return False
    return True


def analog_class_is_na(project: Path) -> bool:
    """ORGANIC #676 — True iff the analog P0 gates should SKIP (N/A) on this
    IC: it is positively classified NON-analog AND every block declared in
    analog_block_list.json is a low_confidence (phantom) keyword hit. Both
    conditions are required so the skip is defence-in-depth, never a blanket
    bypass: a real analog IC fails (1), a confident analog block fails (2)."""
    return _ic_class_says_non_analog(project) and _all_blocks_low_confidence(project)


# ── per-block artefact resolution across the phase-distributed layout ──────
# `_path_layout` splits the analog block dirs by phase — A1's spec under
# `phase1/analog/<block>/`, A2-A4's frontend artefacts under
# `phase2/analog/<block>/`, A5-A9's backend artefacts under
# `phase3/analog/<block>/` — and `flow/phase1_phase2_phase3.yaml` declares each
# A-step's `required_outputs` at exactly those prefixes. The analog RUNNER,
# however, writes every block artefact under the single canonical
# `_pl.analog_dir` (== `phase3/analog/`); that is why `flow_compliance_check`
# carries an explicit canonical-analog-dir tolerance for its `files_exist`
# globs (`_glob_rel`, "v0.2.55 — canonical-analog-dir tolerance").
#
# The A1-A4 gates hardcoded `phase3/analog/` only. A project laid out exactly
# as its OWN flow declares — or migrated by `migrate_to_layout_p.py`, which
# moves A1's spec to `phase1/analog/` and A2-A4's artefacts to
# `phase2/analog/` — therefore made every gate report its artefact MISSING and
# self-skip, measuring nothing. Probe the canonical runner dir FIRST so
# runner-produced projects resolve to byte-identical paths, then fall back to
# the flow-declared phase dir. chip-AGNOSTIC: pure path resolution.
_DECLARED_ANALOG_ROOT = {
    1: "phase1/analog",
    2: "phase2/analog",
    3: "phase3/analog",
}
_CANONICAL_ANALOG_ROOT = "phase3/analog"


def block_dir_candidates(project: Path, block: str,
                         declared_phase: int) -> List[Path]:
    """Ordered candidate DIRECTORIES for one block's A-step artefacts:
    the canonical runner dir first, then the flow-declared phase dir.
    Callers that resolve a GLOB (`*.sp`, `*.gds`) rather than a fixed
    filename need the dir, not a file path."""
    cands = [project / _CANONICAL_ANALOG_ROOT / block]
    declared = _DECLARED_ANALOG_ROOT.get(declared_phase)
    if declared and declared != _CANONICAL_ANALOG_ROOT:
        cands.append(project / declared / block)
    return cands


def block_artefact_candidates(project: Path, block: str, filename: str,
                              declared_phase: int) -> List[Path]:
    """Ordered candidate paths for one per-block A-step artefact:
    the canonical runner dir first, then the flow-declared phase dir."""
    return [d / filename
            for d in block_dir_candidates(project, block, declared_phase)]


def resolve_block_artefact(project: Path, block: str, filename: str,
                           declared_phase: int) -> tuple:
    """Return `(path, found)`. `path` is the first candidate that exists;
    when none exists it is the CANONICAL path, so a MISSING finding keeps
    naming the same `rel_path` these gates have always reported."""
    cands = block_artefact_candidates(project, block, filename,
                                      declared_phase)
    for cand in cands:
        if cand.is_file():
            return cand, True
    return cands[0], False


def select_blocks(blocks: List[str],
                  block_filter: Optional[str]) -> List[str]:
    """When `--block <name>` is given, restrict to that block (even
    if not in the list — the runner may have created an out-of-list
    block dir during a re-run). Otherwise return all declared blocks.
    """
    if block_filter:
        return [block_filter]
    return blocks


def make_argparser(gate_name: str, doc: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=gate_name, description=doc,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path,
                    help="project root (the dir holding analog/, reports/...)")
    ap.add_argument("--json", default=None,
                    help="write JSON verdict to this path")
    ap.add_argument("--block", default=None,
                    help="restrict check to a single block (used by "
                         "analog_one_shot_runner)")
    return ap


# ── STRUCTURE-ONLY disclosure tier ────────────────────────────────────────
# THE RULE, with no tool, step or block name in it:
#
#   A step that produced its declared artefact, but produced it from a library
#   default because no bound input determined its content, is neither complete
#   nor absent. It is dispositioned in its own tier: never counted as an
#   executed pass, never counted as missing, and always named on the ONE
#   summary line a reader reads.
#
# WHY IT IS NOT `MISSING`: the artefact exists, it is well-formed, every
# downstream consumer can read it, and re-running the step will not produce a
# different one. Calling it missing would send a reader to look for work that
# has already been done as well as the inputs allow.
#
# WHY IT IS NOT A PASS: the artefact's content came from a default, so any
# number measured on it is a number about the default. A pass here would let a
# library topology be reported as a designed one.
#
# WHY IT IS NOT A FAIL: nothing is wrong. The bounded inputs did not determine
# the content, and inventing content to fill the gap is precisely the failure
# this whole track exists to prevent. Failing an honest ceiling teaches the
# next run to stop being honest.
#
# The disclosure travels as a line-start stdout token, the same shape as this
# repo's existing `VACUOUS_PASS:` sentinel, so `flow_compliance_check` can read
# it from a gate that PASSED and from a gate that failed for an unrelated
# reason, without either one having to change its exit code.
STRUCTURE_ONLY_TOKEN = "STRUCTURE_ONLY:"

#: The `design_content` value that means "structure came from a library, no
#: bound input reached the content".
DESIGN_CONTENT_STRUCTURE_ONLY = "structure_only"

#: ...and the value that means at least one bound input reached it.
DESIGN_CONTENT_SIZED = "structure_and_geometry"

# ── AND THE PRICE OF SAYING NOTHING ───────────────────────────────────────
# THE RULE, with no tool, step or block name in it:
#
#   An artefact that declines to say what it contains must not certify the
#   step it is the evidence for.
#
# WHY IT HAD TO BE ADDED. The tier above gives an honest ceiling its own
# disposition, which is the right answer and also, on its own, an INVERTED
# INCENTIVE: measured on the adversarial round, deleting the disclosure fields
# from an artefact — which is the shape of every artefact written before the
# fields existed, and of every stale one — made it CERTIFY, while disclosing
# honestly earned the lesser tier. Silence was strictly cheaper than
# disclosure, so the change rewarded exactly the behaviour it exists to remove.
#
# The two answers below NAME a content. Everything else is the artefact
# declining to answer, and all of it is treated the same way:
#
#   * the field absent entirely  — the pre-disclosure and stale shape;
#   * the field present and empty;
#   * a "no record upstream" token — an honest statement of ignorance is
#     still not a statement of content. If it certified, a producer could buy
#     a pass by writing the token instead of by inheriting the answer, and
#     silence would be cheap again under a new name.
#
# NOT A CONTRADICTION OF THE TIER ABOVE. `structure_only` DISCLOSES, so it
# still certifies — in its own tier, never as a plain pass. The ordering that
# matters is preserved end to end: a run that discloses a library default
# scores ABOVE a run that says nothing, and a run that invents content scores
# below both.
DESIGN_CONTENT_DISCLOSED = (DESIGN_CONTENT_STRUCTURE_ONLY,
                            DESIGN_CONTENT_SIZED)


def content_disclosed(value) -> bool:
    """True iff *value* NAMES what an artefact contains.

    Deliberately a whitelist. A blacklist of the known "no answer" tokens
    would certify the next token nobody has thought of yet, and the whole
    point of this predicate is that an unrecognised answer is not an answer.
    """
    return isinstance(value, str) and value in DESIGN_CONTENT_DISCLOSED


# ── the three answers a CONSUMER has to tell apart ────────────────────────
# Every consumer that grades a measurement asks the same question of the
# artefact it grades, so they ask it through one function. Copied predicates
# drift, and a consumer that classified this differently from the gate of
# record would re-open the gap by another door.
CONTENT_DESIGN_BOUND = "design_bound"
CONTENT_STRUCTURE_ONLY = DESIGN_CONTENT_STRUCTURE_ONLY
CONTENT_UNDISCLOSED = "undisclosed"


def classify_design_content(value) -> str:
    """One of :data:`CONTENT_DESIGN_BOUND`, :data:`CONTENT_STRUCTURE_ONLY`,
    :data:`CONTENT_UNDISCLOSED`.

    The ORDER these rank in is the whole point, and it is the same everywhere:
    design-bound is a measurement of the design; structure-only is a
    measurement of a library default, disclosed; undisclosed is neither, and
    it must never outrank the one that told the truth.
    """
    if value == DESIGN_CONTENT_SIZED:
        return CONTENT_DESIGN_BOUND
    if value == DESIGN_CONTENT_STRUCTURE_ONLY:
        return CONTENT_STRUCTURE_ONLY
    return CONTENT_UNDISCLOSED


#: The name of the record itself. Named ONCE so a reader of any consumer can
#: find every site that touches it, and so the key path below is built from the
#: same string the producers write.
DESIGN_CONTENT_FIELD = "design_content"

#: Where the record sits when nothing says otherwise: at the document's top
#: level, which is the shape of every artefact a consumer grades.
CONTENT_TOP_LEVEL_KEYS = (DESIGN_CONTENT_FIELD,)


def _chain_entry(entry) -> tuple:
    """Normalise one chain element to ``(path, key_path)``.

    A bare path means the record is at the top level. A ``(path, keys)`` pair
    names a NESTED one — the A3 producer stamps its record inside the
    `_provenance` object it writes beside the netlist, and a helper that could
    only read a top-level field would have had to keep its own reader for that
    artefact, which is the copied predicate this module exists to remove.
    Both shapes are then read by the SAME whitelist; only WHERE the value is
    found differs, never WHICH answers count as an answer.
    """
    if isinstance(entry, tuple):
        path, keys = entry
        return path, tuple(keys)
    return entry, CONTENT_TOP_LEVEL_KEYS


def content_class_of_artefact(path, keys=CONTENT_TOP_LEVEL_KEYS) -> str:
    """:func:`classify_design_content` of the `design_content` recorded in the
    JSON artefact at *path*, reached by walking *keys*. An unreadable or
    non-object artefact classifies UNDISCLOSED — it said nothing, whatever the
    reason, and so does a document that does not carry the key path at all."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8",
                                              errors="replace"))
    except (json.JSONDecodeError, OSError):
        return CONTENT_UNDISCLOSED
    for key in keys:
        if not isinstance(doc, dict):
            return CONTENT_UNDISCLOSED
        doc = doc.get(key)
    return classify_design_content(doc)


# ── WHEN THE ARTEFACT A CONSUMER GRADES CARRIES NO RECORD OF ITS OWN ──────
# THE RULE, with no tool, step or block name in it, and it is the rule that
# was already stated for the PRODUCERS, applied to a CONSUMER:
#
#   An artefact derived from another artefact INHERITS the upstream record of
#   what that artefact CONTAINS. A consumer that grades a derived artefact
#   whose producer did not republish the record reads the upstream record
#   itself — it never infers one, and it never treats the absence of one as
#   evidence of design content.
#
# WHY A CONSUMER NEEDS THIS AND THE GATE OF RECORD DOES NOT. A gate that
# grades the corner artefact reads that artefact's OWN `design_content`, full
# stop; the field is right there. A gate that signs off a Liberty, or a
# post-layout comparison, grades a file into which no producer has ever
# written the field. Asking that file its own question would classify EVERY
# tree undisclosed — including one whose upstream says plainly that the
# content is design-bound — and a rule that fails the honest tree is not the
# rule this track is defending.
#
# WHY IT CANNOT BECOME A LOOPHOLE. The chain is ORDERED nearest-first and
# every link is read through :func:`classify_design_content`, the same
# whitelist the gate of record uses. A link that names no content is skipped,
# not accepted; when no link in the chain names one the answer is
# UNDISCLOSED, exactly as if the chain had one element. So the chain can only
# ever find an answer that a producer actually wrote down, and silence at
# every link still costs.
#
# WHY THE CHAIN IS SHORT, deliberately. Each consumer's chain ends at the
# artefact the GATE OF RECORD for that content reads. Extending it past that
# point would let a consumer certify a tree its own gate of record refuses on
# content grounds — two gates disagreeing about one artefact, which is the
# drift `classify_design_content` exists to prevent.

def content_class_inherited(paths) -> tuple:
    """``(content_class, source_path_or_None)`` for an ordered, nearest-first
    chain of candidate artefacts.

    The FIRST artefact in *paths* whose ``design_content`` NAMES a content
    decides, and its path is returned beside the answer so a reader is told
    where it came from. When no artefact in the chain names one the answer is
    :data:`CONTENT_UNDISCLOSED` and the path is ``None`` — there is nothing to
    cite, which is the point.

    An artefact's OWN record outranks anything it inherits: the record is a
    statement about what THAT file contains, and only its producer can make
    it.
    """
    for cand in paths:
        if cand is None:
            continue
        raw, keys = _chain_entry(cand)
        p = Path(raw)
        if not p.is_file():
            continue
        klass = content_class_of_artefact(p, keys)
        if klass != CONTENT_UNDISCLOSED:
            return klass, p
    return CONTENT_UNDISCLOSED, None


# ── WHY "NEAREST-FIRST" WAS NOT ENOUGH, AND WHAT REPLACES IT ──────────────
# THE RULE, with no tool, step or block name in it:
#
#   A DERIVED artefact may CONFIRM or LOWER the content its baseline records.
#   It may never RAISE it. What a comparison is a comparison OF is decided by
#   the thing it is compared against, not by the file that reports the
#   comparison.
#
# WHAT THE PREVIOUS ROUND CLAIMED, AND THE MEASUREMENT THAT REFUTED IT. The
# chain above was documented as ordered nearest-first "so this gate can never
# certify a tree its own gate of record refuses". Stopping at the gate of
# record's artefact is not the same as being BOUNDED BY it. Measured, on a
# tree whose corner artefact was SILENT and whose derived artefact carried the
# design-bound token:
#
#   analog_a4_corner_sweep_check        rc 1 FAIL  (A4_DESIGN_CONTENT_UNDECLARED)
#   analog_a7_post_layout_resim_check   rc 0 PASS  — a bare design-bound pass,
#                                                    no disclosure sentinel
#
# because :func:`content_class_inherited` SKIPS a link that names nothing and
# takes the first link that names something — so the nearer link decides even
# when it outranks the farther one. The nearer link is the one an AI step
# authors; the farther one is the one a deterministic producer writes. Ordering
# alone therefore put the AI-authored file ABOVE the gate of record, which is
# the exact inversion this whole track exists to remove.
#
# RE-ORDERING THE CHAIN DOES NOT FIX IT EITHER, and that is worth stating so
# the cheap fix is not tried again: with the baseline first, a SILENT baseline
# is still skipped and the derived claim still decides. The fix has to be a
# CEILING, not an order.
#
# WHY LOWERING IS STILL ALLOWED. `structure_only` under a design-bound
# baseline is a producer disclosing something WEAKER than it was entitled to
# claim. Refusing that would make honesty cost again, which is the inverted
# incentive one level up.
CONTENT_RANK = {
    CONTENT_UNDISCLOSED: 0,
    CONTENT_STRUCTURE_ONLY: 1,
    CONTENT_DESIGN_BOUND: 2,
}


def content_rank(klass: str) -> int:
    """Where *klass* sits in the one ordering every consumer shares:
    design-bound > structure-only (disclosed) > undisclosed."""
    return CONTENT_RANK.get(klass, 0)


class BoundedContent(NamedTuple):
    """What a consumer of a DERIVED artefact may certify, and why.

    ``klass``          the content class the consumer may certify at.
    ``source``         the artefact whose record ``klass`` came from, or
                       ``None`` when nothing named a content.
    ``ceiling``        the class the BASELINE — the gate of record's own
                       subject — supports.
    ``ceiling_source`` the baseline artefact that said so, or ``None`` when no
                       baseline artefact exists or none named a content.
    ``refused``        the derived artefact's own claim when it EXCEEDED the
                       ceiling and was refused, else ``None``. Carried so the
                       finding can name the disagreement instead of reporting a
                       bare silence the reader can see is contradicted on disk.
    """
    klass: str
    source: Optional[Path]
    ceiling: str
    ceiling_source: Optional[Path]
    refused: Optional[str]


def content_class_bounded(baseline_paths: Sequence,
                          derived_paths: Sequence = ()) -> BoundedContent:
    """The content class a derived artefact may certify at.

    *baseline_paths* is the chain the GATE OF RECORD for this content reads;
    its record is the CEILING. *derived_paths* are artefacts whose own producer
    may republish the record; theirs may confirm or lower the ceiling and can
    never raise it.

    Both chains are read through :func:`content_class_inherited`, i.e. through
    the same whitelist the gate of record uses, so neither can find an answer a
    producer did not actually write down.
    """
    ceiling, ceiling_src = content_class_inherited(baseline_paths)
    claim, claim_src = content_class_inherited(derived_paths)

    if claim == CONTENT_UNDISCLOSED:
        # The ordinary case: nothing deterministic writes the field into the
        # derived artefact, so it inherits, exactly as before.
        return BoundedContent(ceiling, ceiling_src, ceiling, ceiling_src, None)
    if content_rank(claim) > content_rank(ceiling):
        return BoundedContent(ceiling, ceiling_src, ceiling, ceiling_src,
                              claim)
    # Confirms, or discloses something weaker than it was entitled to claim.
    return BoundedContent(claim, claim_src, ceiling, ceiling_src, None)


# ── ONE RULE PER ARTEFACT, NOT ONE PER GATE ──────────────────────────────
# THE INVARIANT, with no tool, step or block name in it:
#
#   Two gates that certify ONE artefact must not disagree about it. Whatever
#   else they check, they answer the content question through ONE site.
#
# WHY THIS IS A SHARED CONSTANT AND NOT A COPIED ONE. Measured: the FLOW
# declares one program as the gate for the post-layout step and the A-track
# runner runs another over the same file. One had the content rule and the
# other did not, so the flow-declared gate returned rc 0 PASS with a
# BYTE-IDENTICAL console and `--json` artefact on the design-bound, the
# structure-only AND the silent tree, while the runner's gate read
# PASS / PASS_STRUCTURE_ONLY / FAIL over those same three. On the silent tree
# they disagreed outright. A per-gate constant is how that happened; a shared
# one is why it cannot happen again silently, and
# `test_two_gates_over_one_artefact_agree` is why it cannot happen again
# quietly.

#: The gate of record for design content is the corner sweep. EVERY consumer's
#: baseline chain ends at its artefact — that is what makes the ceiling the
#: same ceiling everywhere.
CONTENT_GATE_OF_RECORD_ARTEFACT = "corner_results.json"

#: The derived artefact of the post-layout comparison step. Nothing
#: deterministic writes `design_content` into it — it is authored by an AI
#: skill — which is precisely why its claim is bounded rather than trusted.
PRE_VS_POST_DERIVED_ARTEFACT = "pre_vs_post.json"


def pre_vs_post_content(block_dir) -> BoundedContent:
    """THE content rule for `pre_vs_post.json`, for every gate that certifies
    it. *block_dir* is the per-block analog directory holding both artefacts.
    """
    d = Path(block_dir)
    return content_class_bounded(
        [d / CONTENT_GATE_OF_RECORD_ARTEFACT],
        [d / PRE_VS_POST_DERIVED_ARTEFACT])


# ── WHEN A COMPARISON COMPARES EVERY NUMBER AGAINST ITSELF ────────────────
# THE RULE, with no tool, step or block name in it:
#
#   A measurement that reports NO CHANGE AT ALL, on every quantity it measured,
#   has produced the one result that is indistinguishable from not having
#   measured a second time. It may certify only if it NAMES the second
#   measurement's own artefact, and that artefact RESOLVES ON THE DISK the gate
#   is reading. A named file that is not there is a claim, not evidence.
#
# WHY NO EXISTING RULE CAN SEE IT. The consumer of this artefact is a
# DEGRADATION gate: it computes `|post - pre| / |pre|` and tiers the answer.
# Fed a file whose post column is a COPY of its pre column it can only ever
# compute 0 %, which is its MOST ACCEPTABLE tier — so the copied artefact scores
# strictly better than every honest one, and the gate is at its weakest exactly
# where it is asked to mean the most. The zero-compared rule does not see it
# either: a copy is not `items_compared == 0`, it is N comparisons of a number
# against itself, and it reports N. Nor does the content rule above: that one
# asks WHAT was compared, and the copy answers it perfectly well — the circuit
# is named, its baseline is design-bound, and both halves of every row are that
# circuit's. What is missing is not the subject, it is the SECOND MEASUREMENT.
#
# MEASURED, on a converged tree whose `post_value` equalled `pre_value` on all
# nine specs and whose own note said the post column was inherited:
#
#     the gate the flow declares     rc 0  PASS  — 9 specs, max degradation 0.0 %
#     the gate the step runner runs  rc 0  PASS  — 1/1 block(s) clean
#
# WHY THE TRIGGER IS EXACTLY ZERO AND NOTHING WIDER — the narrowness is the
# deliberate part, and it is a measurement rather than a preference:
#
#   * A WIDER TRIGGER WOULD NEED A THRESHOLD, and a threshold is the heuristic
#     this rule exists not to be. "Every delta is suspiciously small" cannot be
#     stated without picking a number that some honest layout is under.
#   * THE ONE THRESHOLD-FREE WIDENING DOES NOT EXIST IN FLOATING POINT. "Every
#     spec drifted by the SAME amount" sounds exact and is not: measured on this
#     repo's own shared cross-gate fixture, two specs both authored to drift
#     1 % compute to 1.0000000000000009 % and 0.9999999999999963 %. An equality
#     test over those never fires; a tolerance test is a threshold again.
#
# SO, PLAINLY, WHAT THIS DOES NOT CATCH: a fabricator who perturbs the post
# column instead of copying it — writes 0.0001 %, or any other non-zero
# difference, on every spec — produces numbers this rule cannot distinguish
# from a measurement, because at that point the artefact is not a copy of
# anything and nothing in the file is self-refuting. Catching THAT needs the
# evidence requirement to be UNCONDITIONAL rather than triggered, which is a
# different change with a different blast radius: it fails every honest artefact
# whose post column came from a modelled parasitic bump rather than an extracted
# netlist, and those exist on disk today and disclose themselves honestly. What
# this rule does close is the case where the artefact's OWN NUMBERS say no
# second measurement happened — and that case cannot be argued about.
#
# WHY THE EVIDENCE MUST RESOLVE. A string is free. Requiring the named artefact
# to be a real, non-empty file inside the project raises the price of the copy
# from "write a note" to "produce the extraction", and it is the same shape as
# every other rule here: a claim is graded against something a producer actually
# wrote, never against itself.

#: The keys a post-layout comparison may name its second measurement under.
#: `post_layout_file` is the spelling the authoring skill's own documented
#: example uses; the others name the extraction directly. Read as a WHITELIST,
#: for the same reason `content_disclosed` is one.
POST_LAYOUT_EVIDENCE_KEYS = (
    "extracted_netlist",
    "post_layout_netlist",
    "post_layout_corner_results",
    "post_layout_file",
)

#: The object producers in this tree already stamp their provenance record
#: into — the same `_provenance` convention `NETLIST_CONTENT_KEYS` reads one
#: artefact over. Nested first, top level second; a second convention for the
#: same kind of claim is how two readers of one record come to disagree.
PROVENANCE_KEY = "_provenance"


class PostLayoutEvidence(NamedTuple):
    """What a comparison artefact NAMED as its post-layout measurement, and
    which of those names is a file on disk.

    ``resolved``  the first named artefact that resolves, or ``None``.
    ``key``       the key path that named it (e.g. ``_provenance.
                  extracted_netlist``), or ``None``.
    ``rejected``  ``(key, raw, why)`` for every name that did NOT resolve, so a
                  finding can say what was claimed instead of only that nothing
                  was.
    """
    resolved: Optional[Path]
    key: Optional[str]
    rejected: Tuple[Tuple[str, str, str], ...]


def _evidence_claims(doc) -> List[Tuple[str, str]]:
    """Ordered ``(key_path, raw_value)`` claims of post-layout evidence."""
    out: List[Tuple[str, str]] = []
    prov = doc.get(PROVENANCE_KEY) if isinstance(doc, dict) else None
    for prefix, obj in ((f"{PROVENANCE_KEY}.", prov), ("", doc)):
        if not isinstance(obj, dict):
            continue
        for k in POST_LAYOUT_EVIDENCE_KEYS:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                out.append((prefix + k, v.strip()))
            elif isinstance(v, (list, tuple)):
                for i, e in enumerate(v):
                    if isinstance(e, str) and e.strip():
                        out.append((f"{prefix}{k}[{i}]", e.strip()))
    return out


def _resolve_evidence(raw: str, block_dir: Path,
                      project: Optional[Path]) -> Tuple[Optional[Path], str]:
    """``(path, "")`` when *raw* names real post-layout evidence, else
    ``(None, reason)``.

    Every disqualifier below is a way of naming something that is NOT a second
    measurement, and each was reachable: a path that is simply absent; a file
    created empty to satisfy an existence check; a path outside the project,
    which would let any file anywhere on the host stand in; and the two
    artefacts of the comparison ITSELF — the comparison document and the
    pre-layout baseline it is compared against. Neither of those is post-layout
    evidence, and both are guaranteed to exist wherever this rule runs.
    """
    p = Path(raw)
    cands: List[Path] = [p] if p.is_absolute() else [block_dir / raw]
    if not p.is_absolute() and project is not None:
        cands.append(Path(project) / raw)

    hit: Optional[Path] = None
    for cand in cands:
        try:
            rp = cand.resolve()
        except OSError:                                   # pragma: no cover
            continue
        if rp.is_file():
            hit = rp
            break
    if hit is None:
        return None, "no such file"

    try:
        if hit.stat().st_size <= 0:
            return None, "resolves to an EMPTY file"
    except OSError:                                       # pragma: no cover
        return None, "unreadable"

    if project is not None:
        try:
            hit.relative_to(Path(project).resolve())
        except ValueError:
            return None, "resolves OUTSIDE the project"

    for own, what in ((PRE_VS_POST_DERIVED_ARTEFACT,
                       "the comparison artefact itself"),
                      (CONTENT_GATE_OF_RECORD_ARTEFACT,
                       "the PRE-layout baseline it is compared against")):
        try:
            if hit == (Path(block_dir) / own).resolve():
                return None, f"resolves to {what}"
        except OSError:                                   # pragma: no cover
            continue
    return hit, ""


def post_layout_evidence(block_dir, project=None,
                         doc=None) -> PostLayoutEvidence:
    """THE post-layout-evidence rule for `pre_vs_post.json`, for every gate
    that certifies it. *block_dir* is the per-block analog directory; *doc* is
    the already-parsed artefact when the caller has it.
    """
    d = Path(block_dir)
    if doc is None:
        try:
            doc = json.loads((d / PRE_VS_POST_DERIVED_ARTEFACT).read_text(
                encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            doc = {}
    rejected: List[Tuple[str, str, str]] = []
    for key, raw in _evidence_claims(doc):
        got, why = _resolve_evidence(raw, d, project)
        if got is not None:
            return PostLayoutEvidence(got, key, tuple(rejected))
        rejected.append((key, raw, why))
    return PostLayoutEvidence(None, None, tuple(rejected))


class ZeroDeltaVerdict(NamedTuple):
    """Whether a comparison compared every number against itself, and whether
    it named post-layout evidence that resolves.

    ``certifies`` is False for exactly one combination — degenerate AND
    unevidenced — so an honest all-zero measurement that carries its provenance
    still passes, and a non-degenerate one is untouched.
    """
    degenerate: bool
    compared: int
    evidence: PostLayoutEvidence

    @property
    def certifies(self) -> bool:
        return (not self.degenerate) or self.evidence.resolved is not None


def pre_vs_post_zero_delta(block_dir, pairs, project=None,
                           doc=None) -> ZeroDeltaVerdict:
    """THE zero-delta rule for `pre_vs_post.json`, for every gate that
    certifies it.

    *pairs* is the ``(pre, post)`` sequence the CALLING gate actually compared,
    so the two gates over this artefact stay bounded by the same reading of it.
    The comparison is DEGENERATE when at least one pair was compared and NO
    pair's post value differs from its pre value.

    Computed from the VALUES, never from a `delta_pct` the artefact declares
    about itself: one of the two gates prefers the declared field, so a rule
    reading it would let an author write `delta_pct: 1.7` beside a copied pair
    and put the two gates back into disagreement about one file.
    """
    seq = [(a, b) for a, b in pairs]
    degenerate = bool(seq) and all(b == a for a, b in seq)
    ev = (post_layout_evidence(block_dir, project=project, doc=doc)
          if degenerate else PostLayoutEvidence(None, None, ()))
    return ZeroDeltaVerdict(degenerate, len(seq), ev)


def zero_delta_refusal_detail(verdict: ZeroDeltaVerdict) -> str:
    """The ONE sentence both gates refuse with, so a reader who sees it from
    either of them is told the same thing and sent to the same fix."""
    ev = verdict.evidence
    if ev.rejected:
        claimed = "; ".join(f"`{k}` -> `{raw}` ({why})"
                            for k, raw, why in ev.rejected)
        said = (f"the artefact NAMES post-layout evidence that does not "
                f"resolve: {claimed}")
    else:
        said = (f"the artefact names no post-layout evidence at all "
                f"(looked for {list(POST_LAYOUT_EVIDENCE_KEYS)}, at "
                f"`{PROVENANCE_KEY}.<key>` and at the top level)")
    return (f"every one of the {verdict.compared} compared spec(s) has a post "
            f"value IDENTICAL to its pre value, so the measured degradation is "
            f"0.0 % everywhere — the one result a copy of the pre-layout column "
            f"produces, and the most acceptable tier this gate has — and "
            f"{said}. An all-zero comparison is a legitimate measurement only "
            f"when it can name the post-layout artefact its post column was "
            f"simulated from and that artefact is on disk; point one of those "
            f"keys at the extracted netlist (or the post-layout corner result) "
            f"and this certifies.")


#: The sidecar the A3 producer writes BESIDE the netlist, and the key path to
#: the record inside it. Nothing writes JSON into a SPICE deck, so the whole
#: answer for `<block>.sp` is this file's — the same reason the hardmacro
#: package's answer is the corner artefact's.
NETLIST_PROVENANCE_ARTEFACT = "netlist_provenance.json"
NETLIST_CONTENT_KEYS = ("_provenance", DESIGN_CONTENT_FIELD)


def netlist_content(block_dir) -> BoundedContent:
    """THE content rule for `<block>.sp`, for every gate that certifies it.
    *block_dir* is the per-block analog directory holding the netlist and the
    producer's sidecar.

    WHY THIS CHAIN HAS ONE LINK AND NO CEILING ARTEFACT, which is the one way
    it differs from its two siblings. The netlist is the ROOT of this record:
    `analog_real_corner_sweep.upstream_design_content` reads THIS file to stamp
    `corner_results.json`, so the gate of record's own subject is DERIVED from
    it. Giving A3 a ceiling taken from the corner artefact would invert the
    direction of the whole rule — a downstream artefact bounding the upstream
    one it was copied from — and would let a re-run of A4 raise or lower what
    A3 shipped. Nothing may raise this record because nothing upstream of it
    exists; the producer that resolved the parameters is the only writer, and
    it is read here through the same whitelist as everything else, so a sidecar
    that is absent, unreadable, empty, or carrying a token that names no
    content is UNDISCLOSED exactly as it is everywhere else.

    A skill-authored netlist carries no sidecar at all, and that is UNDISCLOSED
    rather than exempt. The exemption that already exists beside this
    (`_provenance_ref_fail` stays silent without a sidecar) is about refusing to
    punish the ABSENCE OF A CLAIM; this rule is about refusing to CERTIFY on
    one. Exempting silence here is precisely how silence became cheaper than
    disclosure.
    """
    return content_class_bounded(
        [(Path(block_dir) / NETLIST_PROVENANCE_ARTEFACT,
          NETLIST_CONTENT_KEYS)])


def hardmacro_content(block_dir) -> BoundedContent:
    """THE content rule for the packaged hardmacro (LEF / Liberty / GDS /
    Verilog), for every gate that certifies it. *block_dir* is the per-block
    ANALOG directory — not the hardmacro directory: nothing in the package
    carries `design_content`, so the whole answer is the baseline's, and asking
    the package its own question would classify every tree undisclosed and fail
    the honest one too.
    """
    return content_class_bounded(
        [Path(block_dir) / CONTENT_GATE_OF_RECORD_ARTEFACT])


def structure_only_disclosure(gate_name: str, blocks: list,
                              artefact: str, detail: str = "") -> None:
    """Print the STRUCTURE-ONLY disclosure. Two properties this has to hold,
    both learned the hard way from the sibling `VACUOUS_PASS:` sentinel:

    * Called REGARDLESS of the gate's verdict. A step can fail for one unit
      and still have produced a library-default artefact for another; both
      facts are true and a reader needs both.
    * Called LAST, and kept SHORT. The consumer of a gate's output keeps a
      fixed-width TAIL of each stream (300 chars), so a disclosure printed
      first, or printed long, is a disclosure the consumer never sees — which
      is the same defect one layer down: a signal that exists and is not read.
      Measured: a 330-char line emitted before the verdict line vanished
      entirely from the compliance summary.
    """
    if not blocks:
        return
    names = ", ".join(str(b) for b in blocks)
    if len(names) > 60:
        names = f"{names[:57]}..."
    # ONE line, and the LAST line. The long-form reason lives in the JSON
    # report and in the compliance summary's own explanatory block; putting it
    # here would push the token itself out of the consumer's 300-char tail.
    print(f"{STRUCTURE_ONLY_TOKEN} {len(blocks)} {artefact} artefact(s) "
          f"({names}) came from a library default, not a bound input "
          f"[{gate_name}]")


def write_report(json_path: Optional[str], report: dict) -> None:
    if not json_path:
        return
    out = Path(json_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


def vacuous_pass(gate_name: str, args, reason: str,
                 reason_class: Optional[str] = None) -> int:
    """Print + emit JSON + return 0. Used when no analog blocks
    declared at all (project-level VACUOUS_PASS)."""
    report = {
        "gate": gate_name,
        "verdict": "VACUOUS_PASS",
        "reason": reason,
        "findings": [],
    }
    if reason_class:
        report["reason_class"] = reason_class
    write_report(args.json, report)
    print(f"VACUOUS_PASS: {reason}")
    return 0


def artefact_missing_for_block(gate_name: str, args, block: str,
                               artefact_rel: str, skill: str) -> int:
    """Per-block --block mode: artefact not yet emitted. Exit 2 so
    analog_one_shot_runner translates this to WAIVED. stderr names
    the skill for the runner to surface to the caller. JSON report
    is still written when --json is given so a flow audit can pick
    up the deferred state.
    """
    report = {
        "gate": gate_name,
        "verdict": "WAIVED",
        "block": block,
        "missing_artefact": artefact_rel,
        "suggested_skill": skill,
        "reason": (f"artefact `{artefact_rel}` not yet emitted; caller "
                   f"should invoke skill `{skill}`"),
        "findings": [],
    }
    write_report(args.json, report)
    print(f"WAIVED: block={block} missing `{artefact_rel}` — "
          f"invoke skill `{skill}`", file=sys.stderr)
    return 2


def emit_pass(gate_name: str, args, summary: dict,
              pass_token: str = "PASS") -> int:
    """A genuine pass, with the TIER on the verdict word.

    ``pass_token`` is the same seam ``_vacuous_exit.verdict_line`` already
    provides for the gates outside this family, and it exists for the same
    reason: a reader of the ONE line a gate prints must be able to tell a
    measurement of this design from a measurement of a library default,
    without opening the JSON. It applies only to a genuine pass — a failing
    run still reads FAIL, and a run that examined nothing still reads
    VACUOUS_PASS.
    """
    report = {
        "gate": gate_name,
        "verdict": pass_token,
        **summary,
        "findings": [],
    }
    write_report(args.json, report)
    print(f"{pass_token}: {gate_name} — "
          f"{summary.get('blocks_pass', 0)}/"
          f"{summary.get('blocks_checked', 0)} block(s) clean")
    return 0


def emit_incomplete(gate_name: str, args, missing: list, summary: dict,
                    skill: str) -> int:
    """Project mode, PARTIAL block coverage: some declared blocks carry the
    step's artefact, others carry none. Exit 1.

    Before this existed, the project-mode tail of every A1-A4 gate fell
    through to `emit_pass`, so a run in which the upstream skill produced an
    artefact for 1 of N declared blocks was certified `PASS` — the step was
    reported done while N-1 declared blocks had been measured on nothing.
    The flow declaration cannot catch this: each A-step declares a single
    GLOB (`phase2/analog/*/topology.md`) and `flow_compliance_check` satisfies
    a glob entry on its FIRST match, so per-block coverage is knowable only
    here.

    INCOMPLETE is deliberately distinct from FAIL: a block with NO artefact is
    unmeasured work, not a measured defect. Both are non-zero, so neither can
    certify the step done. The all-blocks-missing VACUOUS_PASS (defer to the
    skill) and the `--block` exit-2 WAIVED deferral are untouched.
    """
    blocks = []
    for f in missing:
        b = f.get("block")
        if b and b not in blocks:
            blocks.append(b)
    report = {
        "gate": gate_name,
        "verdict": "INCOMPLETE",
        **summary,
        "incomplete_blocks": blocks,
        "suggested_skill": skill,
        "reason": (f"{len(blocks)} of {summary.get('blocks_checked', 0)} "
                   f"declared analog block(s) produced no artefact for this "
                   f"step; invoke skill `{skill}` for them"),
        "findings": missing,
    }
    write_report(args.json, report)
    print(f"INCOMPLETE: {gate_name} — "
          f"{summary.get('blocks_pass', 0)}/"
          f"{summary.get('blocks_checked', 0)} declared block(s) covered; "
          f"no artefact for: {', '.join(blocks) or '?'} "
          f"(invoke skill `{skill}`)", file=sys.stderr)
    for f in missing[:8]:
        print(f"  [{f.get('block', '?')}] {f.get('rule', '?')}: "
              f"{f.get('detail', '')}", file=sys.stderr)
    if len(missing) > 8:
        print(f"  ... and {len(missing) - 8} more", file=sys.stderr)
    return 1


def emit_fail(gate_name: str, args, findings: list, summary: dict) -> int:
    report = {
        "gate": gate_name,
        "verdict": "FAIL",
        **summary,
        "findings": findings,
    }
    write_report(args.json, report)
    print(f"FAIL: {gate_name} — "
          f"{len(findings)} finding(s):", file=sys.stderr)
    for f in findings[:8]:
        block = f.get("block", "?")
        rule = f.get("rule", "?")
        detail = f.get("detail", "")
        print(f"  [{block}] {rule}: {detail}", file=sys.stderr)
    if len(findings) > 8:
        print(f"  ... and {len(findings) - 8} more", file=sys.stderr)
    return 1
