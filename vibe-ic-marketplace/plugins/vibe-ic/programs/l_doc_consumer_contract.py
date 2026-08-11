#!/usr/bin/env python3
"""
l_doc_consumer_contract.py — shared derivation helpers for the
SEMANTIC L-doc completeness gates (batch layergate-7: L20 / L22 / L23).

WHY THIS MODULE EXISTS
======================
The global check ``phase1_doc_input_completeness_check`` models
completeness as "does this vendor token appear in ANY layer". A hard
macro's supply pin name appeared in L1_DATASHEET (7x) and L2_FRS (8x),
so the check reported CAPTURED — while L21_POWER_INTENT, the layer the
BACKEND actually consumes, contained it 0 times. The PDN was built with
no rail for it, synthesis tied the pin off, a SIGNAL net landed on a
POWER terminal and TritonRoute aborted the entire detailed route:
3278 nets, 0 routed, discovered five steps downstream.

The principle every gate built on this module embodies:

    A layer is complete when the requirement is present IN THE LAYER
    THAT CONSUMES IT, in an actionable form — not when a token appears
    somewhere.

DERIVATION, NOT RECOGNITION
===========================
Every predicate here reads the design's OWN inputs: its own
``phase1/input_doc/*`` and ``input/docs/*`` text, its own sibling
L-docs, its own emitted backend artifacts. Nothing keys on a design
name, a PDK name, a vendor part number or a design-specific pin
literal. The only literals are the vocabulary of the *technology*
(the word "scan chain", the word "coverage", the "%" sign) — the same
class of literal ``l8_clock_domains_typed_check`` already uses for
"MHz".

REQUIREMENT FRAMING
===================
A bare vocabulary hit is not a requirement. ``framed_hits`` applies the
same context-window discipline as
``l8_clock_domains_typed_check._is_real_clock_freq``: a match only
counts when a requirement/goal word appears nearby. This is what keeps
"the upstream project already hit 90% coverage" (a status report about
somebody else's work) from being read as "this design requires 90%
coverage".

NEARBY MEANS "IN THE SAME SENTENCE", and the character count is only a
budget on how much text is examined (vibe-ic#1021). It used to be the
rule, and a flat count crosses full stops: a bare mention in one
sentence borrowed a ``requires`` from the next and became a
requirement. The reach is ``_prose_polarity.sentence_scope`` — the
house rule, imported, not a fourth private copy.

SINGLE DETERMINISTIC TRACK
==========================
These gates have NO AI second track. That is deliberate. The L21
post-mortem recorded ``ai_captured_tokens_count: 0`` — an advertised
dual-track that contributed nothing to the 52 tokens the deterministic
track flagged, i.e. one track wearing two hats. Rather than ship a
second track that produces nothing, these gates declare one track and
are honest about it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "generated_docs_dir",
    "load_l_doc",
    "l_doc_fields",
    "applicability_of",
    "is_extraction_claimed",
    "input_doc_texts",
    "sibling_l_doc_texts",
    "framed_hits",
    "project_relative_source",
    "OUTSIDE_PROJECT_PREFIX",
    "signoff_qualifier",
    "requirement_absent",
    "requirement_out_of_scope",
    "waiver_rationale",
    "numeric_target",
    "nonempty_str",
    "write_report",
    "REQUIREMENT_FRAMING_RE",
]


# ─────────────────────────────────────────────────────────────────────
# L-doc access
# ─────────────────────────────────────────────────────────────────────

def generated_docs_dir(project: Path) -> Path:
    return project / "phase1" / "generated_docs"


def load_l_doc(project: Path, code: str) -> Tuple[Optional[Path], Optional[dict]]:
    """Load the L-doc whose filename starts with ``<code>_``.

    Returns (path, parsed) or (None, None). Tolerates the schema.py /
    l_doc_taxonomy.py filename disagreement (schema.py maps L20 ->
    L20_DFT_SCAN.json while the emitter writes L20_DFT_SCAN_TOPOLOGY.json)
    by globbing the code prefix rather than hardcoding either name.
    """
    gd = generated_docs_dir(project)
    if not gd.is_dir():
        return None, None
    for hit in sorted(gd.glob(f"{code}_*.json")):
        if not hit.is_file():
            continue
        try:
            return hit, json.loads(hit.read_text(encoding="utf-8",
                                                 errors="ignore"))
        except Exception:
            return hit, None
    return None, None


def l_doc_fields(doc: Optional[dict]) -> dict:
    """Return the layer's payload.

    The emitter nests the payload under ``fields``; some protocol
    synthesizers write it flat. Accept both without guessing.
    """
    if not isinstance(doc, dict):
        return {}
    inner = doc.get("fields")
    if isinstance(inner, dict):
        merged = {k: v for k, v in doc.items() if k != "fields"}
        merged.update(inner)
        return merged
    return doc


# --------------------------------------------------------------------------
# L9's top-level port contract — ONE accessor, because there are FOUR keys.
#
# The layer's port list has accumulated aliases: `top_ports` (what the
# promoter and full_stack_tb_gen write today), `ports` (the promoter's own
# alias), `top_level_ports` (the original schema-v1 key) and
# `top_module_pins` (the legacy compat name). `l9_rtl_pin_consistency_check`
# already had to learn to read the UNION of all four — its docstring records
# that reading one key gave a correct RTL top NO verification at all, and that
# field runs were dual-writing the same pins into two keys to clear the gate.
#
# It fixed that FOR ITSELF. `phase1_k5_quality_check` then re-declared the
# same tuple, and a third consumer never got the lesson: it still reads the
# single legacy alias, so on a layer written with the canonical key it sees an
# EMPTY port list — and, being a generator rather than a gate, it does not
# report a skip. It emits a plausible-looking artefact built from nothing.
#
# The direction key has the same split: records are written `{"name","dir",
# "width"}` by the promoter, while a consumer testing `port["mode"]` reads a
# missing key and classifies EVERY port — including every output — as an
# input. That failure is worse than the empty one, because the artefact is
# populated and passes a presence check.
#
# So both live here, once, and consumers import them.
_L9_PORT_KEYS = (
    "top_ports",          # canonical (promoter + TB-gen + emitters)
    "ports",              # promoter alias
    "top_level_ports",    # original schema-v1 key
    "top_module_pins",    # legacy compat alias
)

# Every spelling of the direction field seen across the writers above.
_L9_DIR_KEYS = ("dir", "mode", "direction")


def l9_port_direction(port: Any) -> str:
    """``"out"``, ``"inout"`` or ``"in"`` for one L9 port record.

    Reads whichever direction key the record carries. Defaults to ``"in"``
    only when the record names NO direction at all — the same default the
    callers already applied, so a record that was classified correctly before
    still is.
    """
    if not isinstance(port, dict):
        return "in"
    for k in _L9_DIR_KEYS:
        raw = port.get(k)
        if raw is None:
            continue
        v = str(raw).strip().lower()
        if not v:
            continue
        if v.startswith("inout") or v == "bidir":
            return "inout"
        if v.startswith("out"):
            return "out"
        if v.startswith("in"):
            return "in"
    return "in"


def l9_top_ports(l9: Optional[dict]) -> list:
    """L9's top-level port records: the UNION of every known key, deduped by
    name, first occurrence winning.

    Mirrors `l9_rtl_pin_consistency_check.extract_l9_ports` deliberately — a
    consumer and the gate that certifies it must not disagree about what the
    layer says. Returns ``[]`` for a layer that declares no ports anywhere,
    so a caller can tell "declared nothing" from "declared something I could
    not read"; before this accessor those two were indistinguishable.
    """
    if not isinstance(l9, dict):
        return []
    # Accept the RAW document as well as an already-unwrapped payload. The
    # emitter nests under `fields` (schema v2) and other writers stay flat; a
    # consumer that reads only the top level sees NOTHING on the nested form
    # and cannot tell that from "declares no ports". That is the same defect
    # class the PDK-target gate was carrying, and it is why this lives in the
    # shared contract rather than in each caller.
    l9 = l_doc_fields(l9)
    lists: list = []
    for key in _L9_PORT_KEYS:
        v = l9.get(key)
        if isinstance(v, list):
            lists.append(v)
    dtop = l9.get("dtop_top_level")
    if isinstance(dtop, dict) and isinstance(dtop.get("ports"), list):
        lists.append(dtop["ports"])
    out: list = []
    seen: set = set()
    for lst in lists:
        for rec in lst:
            if not isinstance(rec, dict):
                continue
            name = str(rec.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(rec)
    return out


def applicability_of(doc: Optional[dict]) -> str:
    if not isinstance(doc, dict):
        return "UNKNOWN"
    val = doc.get("applicability")
    return str(val).strip().upper() if val is not None else "UNKNOWN"


def is_extraction_claimed(doc: Optional[dict]) -> bool:
    """True when the layer claims its content was actually extracted.

    A layer that honestly self-reports ``NOT_YET_EXTRACTED`` and asserts
    nothing is an honest skeleton. A layer that claims EXTRACTED, or
    carries non-empty ``extraction_evidence``, is asserting its content
    is real and is therefore held to the consumer contract.

    DO NOT FUSE THIS WITH ``_STATUS_FOUND_NOTHING`` (vibe-ic#377)
    ------------------------------------------------------------
    The L16/L17/L18 gates carry a local ``_STATUS_FOUND_NOTHING`` set that
    reads the SAME producer field, and it looks like a second spelling of
    this predicate. It is not, and unifying them would be a semantic error.
    They are two DIFFERENT binary projections of a THREE-valued producer
    state -- NOT-RUN / RAN-AND-EMPTY / RAN-AND-FOUND:

        this predicate asks   "did extraction run and assert a result?"
        that set asks         "did extraction report an EMPTY result?"

    The proof that they are not complements is a state on which BOTH are
    False: ``NOT_YET_EXTRACTED`` (this returns False by its own exclusion
    list; that set deliberately omits the token, because a skeleton whose
    extraction has not run yet and which carries content is not a
    contradiction). Complements cannot both be False on the same input.
    ``EXTRACTION_FOUND_NOTHING`` is legitimately True for BOTH questions,
    and that overlap is the answer to two questions, not drift.

    Measured on the tracked corpus before writing this (2554 tracked L-doc
    JSONs across 106 projects): 2022 sit in the third state on which both
    are False, and the two predicates' domains are DISJOINT -- an AST walk
    of all 3348 tracked .py files finds this function referenced only by the
    L20/L22/L23 gates and that set only by the L16/L17/L18 gates, with no
    dynamic-dispatch site touching either name. Zero tracked documents are
    read by both, so a fusion would be justified by a vacuous measurement.
    ``test_issue377_producer_status_vocabulary.py`` pins the invariant.
    """
    if not isinstance(doc, dict):
        return False
    status = str(doc.get("extraction_status") or "").strip().upper()
    if status and status not in ("NOT_YET_EXTRACTED", "", "PENDING",
                                 "NOT_EXTRACTED", "SKIPPED"):
        return True
    ev = doc.get("extraction_evidence")
    if isinstance(ev, dict) and ev:
        return True
    if isinstance(ev, list) and ev:
        return True
    return False


# ─────────────────────────────────────────────────────────────────────
# The design's OWN input text
# ─────────────────────────────────────────────────────────────────────

_INPUT_GLOBS = (
    "phase1/input_doc/*",
    "input/docs/*",
    "input/*.md",
    "phase1/input_prompt/*",
)

# Binary / model files that are inputs but not prose. Reading a 4MB
# cell model as "requirement text" is how a gate invents requirements.
_SKIP_SUFFIXES = {".gds", ".lef", ".lib", ".db", ".png", ".pdf", ".gz",
                  ".zip", ".vcd", ".fst", ".bin", ".hex"}
_MAX_BYTES = 4_000_000


def _readable_text(p: Path) -> Optional[str]:
    if not p.is_file():
        return None
    if p.suffix.lower() in _SKIP_SUFFIXES:
        return None
    try:
        if p.stat().st_size > _MAX_BYTES:
            return None
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def input_doc_texts(project: Path) -> List[Tuple[Path, str]]:
    """Every prose input the design itself shipped, deduplicated.

    Path A runs normalise vendor docs into ``phase1/input_doc/*.txt``;
    Path B runs keep the prompt under ``phase1/input_prompt``; several
    campaign shapes also keep the pristine originals under
    ``input/docs/``. Read all of them — the requirement can be stated in
    any input the design provided.
    """
    out: List[Tuple[Path, str]] = []
    seen: set = set()
    for pat in _INPUT_GLOBS:
        for p in sorted(project.glob(pat)):
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            txt = _readable_text(p)
            if txt:
                out.append((p, txt))
    return out


def sibling_l_doc_texts(project: Path, codes: Iterable[str]
                        ) -> List[Tuple[Path, str]]:
    """Serialised text of sibling L-docs, for cross-layer detection.

    This is the direct L21 probe: the requirement is demonstrably
    present in SOME layer, just not the one that consumes it.
    """
    out: List[Tuple[Path, str]] = []
    for code in codes:
        path, doc = load_l_doc(project, code)
        if path is None or doc is None:
            continue
        try:
            # vibe-ic#476 — INDENT IS LOAD-BEARING, not cosmetic.
            #
            # `_hit_line` finds "the line the match sits on" by scanning for
            # newlines, and both `framed_hits` and `signoff_qualifier` document
            # themselves as LINE-SCOPED — the correction that made "proximity is
            # not membership" true. A compact `json.dumps` emits NO newline, so on
            # this path every hit's "line" was the WHOLE DOCUMENT.
            #
            # Measured over the tracked corpus: 2448 of 2448 sibling texts across
            # 106 projects were single-line, running from 192 to 1_420_065
            # characters. One unrelated field saying "informative" anywhere in a
            # 1.4 MB blob therefore disclaimed every requirement in it.
            out.append((path, json.dumps(doc, ensure_ascii=False, indent=2)))
        except Exception:
            continue
    return out


# ─────────────────────────────────────────────────────────────────────
# Requirement framing
# ─────────────────────────────────────────────────────────────────────
#
# THE FRAMING NEIGHBOURHOOD IS THE SENTENCE, NOT A CHARACTER COUNT (#1021).
# ------------------------------------------------------------------------
# `framed_hits` used to look for framing anywhere within +/-`window`
# characters of the matched term, and that window CROSSED FULL STOPS: a hit in
# one sentence borrowed its framing from the next. MEASURED on the published
# corpus, in a root's own input:
#
#   "... the 14 bold pins can be used to expose debug related signals
#    (e.g. JTAG interface). USB IF requires for certification that security
#    and privacy consideration and precaution has been taken ..."
#
# The `requires` belongs to a sentence about SECURITY CERTIFICATION. It reached
# back across the full stop and promoted a parenthetical mention of a debug
# signal into a stated DFT requirement, reddening a published project.
#
# THE REACH IS THE HOUSE ONE, IMPORTED AND NOT RE-IMPLEMENTED.
# `_prose_polarity.sentence_scope` is the repo's single rule for "the sentence
# a match sits in", symmetric in both directions since #790, and its
# `before`/`after` are a BUDGET rather than the rule — so passing `window` for
# both makes the new neighbourhood exactly the INTERSECTION of the old window
# and the sentence. The change can therefore only ever narrow what is admitted;
# it can never admit something the flat window did not.
#
# LIMIT, STATED RATHER THAN HIDDEN. The scope is computed on the
# WHITESPACE-NORMALISED copy, because that is the text the match was found in
# and because normalisation is what makes ".\n" readable as the break ". " at
# all. Normalisation has by then already collapsed "\n\n" and "\n- ", two of
# `SENTENCE_BREAKS`'s five members, so those two cannot fire on this substrate.
# MEASURED before it was left out: recovering them from the offset map moves
# l20 from 47 surviving hits to 43, l23 from 8 to 9 (a dedup split, not a new
# hit) and l22 from 1 to 1 — and moves ZERO roots on all four consumers. A
# recovery with no measured effect is machinery that can only drift, so it is
# recorded here instead of shipped.

# Words that turn a vocabulary mention into a stated requirement for
# THIS design. Technology-neutral; contains no design/PDK/vendor token.
#
# MEASURED CALIBRATION (2026-07-25, fleet sweep): an earlier draft
# accepted a bare ``>`` as framing. reStructuredText link syntax
# (``...stages-v>`_.``), markdown blockquotes and ``->`` arrows put a
# ``>`` in almost every technical document, so the gate read a STATUS
# sentence — "<upstream project> has achieved verification stage V2S ...
# over 90% code and functional coverage hit" — as a requirement for the
# design under test. Only the two-character comparison operators count.
# This is the same class of parser-garbage filter as
# ``l8_clock_domains_typed_check``'s sub-kHz reject.
REQUIREMENT_FRAMING_RE = re.compile(
    r"\b(?:shall|must|require[sd]?|requirement|mandator|goal|target|"
    r"objective|criteria|criterion|at\s+least|no\s+less\s+than|minimum|"
    r"min\.|exit\s+criteria|sign-?off|acceptance|budget|"
    r"specif(?:y|ied|ication))\b"
    r"|(?:>=|≥|⩾)",
    re.IGNORECASE,
)


def _normalize_ws(text: str) -> Tuple[str, List[int]]:
    """Collapse whitespace runs to a single space, keeping an offset map.

    Requirements are routinely hard-wrapped: "…verify the core with
    100%\\ncoverage." An adjacency regex written with ``[^.\\n]`` misses
    that and then matches some unwrapped status sentence instead — the
    gate ends up citing the wrong evidence for the right verdict.
    Normalising first makes adjacency wrap-insensitive; ``offsets`` maps
    every normalised index back to the original so reported line numbers
    still point at the real file.
    """
    out_chars: List[str] = []
    offsets: List[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_space:
                continue
            out_chars.append(" ")
            offsets.append(i)
            prev_space = True
        else:
            out_chars.append(ch)
            offsets.append(i)
            prev_space = False
    return "".join(out_chars), offsets


# ORGANIC — a hit whose own context DISCLAIMS normative force is not a
# stated requirement. Measured on spm x GF180MCU: `l22` blocked Step P0 on
#
#   | Toggle / branch coverage(資訊性) | >= 95% | 同 random run;非 sign-off gate |
#
# The row says, in the design's own words, INFORMATIONAL and NOT a sign-off
# gate. REQUIREMENT_FRAMING_RE matched the `>=` and had no way to see that.
# A gate that fires on a legitimately-complete design is a bug in the gate.
#
# DELIBERATELY NARROW. This matches a disclaimer of normative force, NOT
# negation in general — `must NOT exceed 5 ns` is a real requirement that
# contains a negation, and a blanket negation guard (the plugin has one:
# `_FOUNDRY_NEGATION_RE`, which includes bare 不/否) would silently delete it.
_NON_NORMATIVE_RE = re.compile(
    r"非\s*sign-?off|非簽核|非签核|不是\s*sign-?off"
    r"|資訊性|资讯性|informational|informative"
    r"|僅供參考|仅供参考"
    r"|\bnot\s+a\s+(?:sign-?off\s+)?gate\b"
    r"|\bnon-?normative\b"
    r"|\bfor\s+reference\s+only\b"
    r"|\badvisory\s+only\b",
    re.IGNORECASE)

# The SOFTER half of the same vocabulary. These phrases mark a target as
# not-a-sign-off-condition, but they are too weak to justify DROPPING the
# row from a gate's requirement evidence: `advisory` alone can be an
# ordinary noun ("see the advisory notes"), and `not a sign-off` without
# the word `gate` is a fragment. Kept SEPARATE from `_NON_NORMATIVE_RE`
# so widening the non-blocking vocabulary can never widen what a gate
# silently discards.
#
# WHY THIS LIVES HERE. It used to be a PRIVATE tuple inside the L22
# coverage-goal emitter, and the two lists DRIFTED in both directions:
# the emitter marked `advisory` non-blocking while the gate did not, and
# the gate discarded `非簽核` / `for reference only` / `non-normative`
# while the emitter did not recognise them at all. One vocabulary, one
# home.
_SOFT_NON_SIGNOFF_RE = re.compile(
    r"\bnon-?\s?sign-?off\b"
    r"|\bnot\s+a\s+sign-?off\b"
    r"|\badvisory\b"
    r"|\bfor\s+information\b",
    re.IGNORECASE)


def signoff_qualifier(line: str) -> Optional[str]:
    """The phrase by which this LINE disclaims sign-off force, or None.

    LINE-SCOPED BY CONTRACT — the caller passes one line, never a
    neighbourhood. A document disclaims the row it is written on;
    proximity is not membership. Scanning a +/-window here re-introduces
    exactly the bug `framed_hits` was corrected for: MEASURED, a table
    whose first row said `advisory` marked the NEXT row's explicit
    `sign-off` requirement non-blocking.

    Returns the matched phrase (not just a bool) so a consumer can record
    it as evidence and a human can audit the call.
    """
    if not line:
        return None
    for rx in (_NON_NORMATIVE_RE, _SOFT_NON_SIGNOFF_RE):
        m = rx.search(line)
        if m:
            return m.group(0).strip()
    return None


# ─────────────────────────────────────────────────────────────────────
# "The document says the requirement DOES NOT EXIST"  (vibe-ic#1011)
# ─────────────────────────────────────────────────────────────────────
#
# THE ADJACENT-BUT-DIFFERENT CASE. `signoff_qualifier` above answers "the
# document says this row is not BINDING". This answers "the document says the
# requirement is not THERE" — and a gate that cannot tell the two apart counts
# a sentence DENYING a requirement as evidence that one was stated. MEASURED on
# the 107 published run dirs: 25 of `l20_dft_scan_topology_actionable_check`'s
# F2 findings, 16 of them this shape, in the roots' own words —
#
#   "IEEE 802.3-2005 does NOT specify JTAG / scan-chain / on-chip BIST ..."
#   "There is no scan chain, no JTAG, and no boundary-scan path ..."
#   "Neither <bus A> ... nor <bus B> ... defines a JTAG / scan / BIST ..."
#   "no PDK, floor-plan, SDC, UPF, or DFT artifact at the protocol level"
#
# ABSENCE IS NOT PROHIBITION, AND THAT IS THE WHOLE RULER
# ------------------------------------------------------
# `_NON_NORMATIVE_RE` already records why a BLANKET negation guard is wrong:
# "`must NOT exceed 5 ns` is a real requirement that contains a negation". So
# this predicate keys on the SHAPE, not on the presence of a negation word:
#
#   ABSENCE (drop)      a negation bound to a DECLARATION verb, or an
#                       existential "there is no" / a bare "no" standing in
#                       front of the matched term
#                       -> the document declared NOTHING
#   PROHIBITION (keep)  a DEONTIC MODAL + not — shall not, must not, may not,
#                       should not, will not, cannot
#                       -> the document declared something, negatively
#
# The auxiliary set in (a) is exactly the INDICATIVE ones (do/does/did/is/are/
# was/were/has/have/had/been). Every deontic modal is absent from it BY
# CONSTRUCTION, so "must not exceed 5 ns" and "the design shall not expose the
# scan chain" can never match. `_PROHIBITION_RE` is not a subtraction bolted on
# afterwards; it exists so a test can PIN that separation and so a future
# widening of the auxiliary set has something that goes red.
#
# THE REACH WAS LINE, AND IS NOW THE SENTENCE — BECAUSE THE FRAMING MOVED
# ----------------------------------------------------------------------
# #1020 measured all three reaches over the published corpus and chose LINE,
# and its stated reason was NOT that a sentence is the wrong unit. It was that
# a sentence-scoped denial could be OUT-FLANKED: `REQUIREMENT_FRAMING_RE`'s
# window crossed full stops, so 6 hits on 4 roots survived a sentence-scoped
# denial only because the framing that admitted them had been borrowed back
# ACROSS the full stop from the very sentence that denied them. Its own words:
# "a denial scoped narrower than the window can always be out-flanked by the
# framing that admitted the hit."
#
# #1021 bounded the framing window to the sentence, which is the other end of
# that same defect. RE-MEASURED afterwards, over every published run dir, at
# both reaches, driving the real `framed_hits` loop and swapping only the reach:
#
#     framing FLAT      denial LINE  12 roots      denial SENTENCE  16 roots
#     framing SENTENCE  denial LINE  10 roots      denial SENTENCE  10 roots
#
# The counterexample is GONE — the 4 roots on which the two reaches disagreed
# no longer disagree, because the second sentence can no longer borrow the
# first's `specify`. The reaches now differ by 3 hits on ONE root, all in the
# same direction: SENTENCE keeps 3 that LINE drops, and hand-opening them shows
# LINE was WRONG on all three. They sit on a JSON `"content"` megaline where a
# denial belonging to a DIFFERENT sentence retracted them — the exact shape
# #1020 recorded as L23's two wrong drops and named as the limit it could not
# fix from where it stood.
#
# So SENTENCE is taken, and it is the SAFE direction as well as the correct
# one: on this corpus it is a strict SUPERSET of what LINE keeps. Zero hits are
# dropped by the sentence reach that the line reach kept, so no root can go
# quietly clean because of it. It also restores the property #1020 wanted and
# could not have — the framing that ADMITS a hit and the predicates that DROP
# it are now scoped by ONE rule, applied to ONE span. Neither can out-flank the
# other, in either direction.
#
# CLAUSE stays rejected, on #1020's measurement and unchanged by any of this:
# "no PDK, floor-plan, SDC, UPF, or DFT artifact at the protocol level" leaves
# the term in the clause " or DFT artifact at the protocol level", five clauses
# from the cue that denies it.
#
# `_NON_NORMATIVE_RE` DELIBERATELY DID NOT MOVE, and the asymmetry is measured
# rather than an oversight. Its counterexample is a MARKDOWN TABLE — "a
# disclaimer on one table row silences a real requirement on the NEXT one" —
# and table rows are separated by a NEWLINE, not by a full stop. A sentence
# reach does not separate them; the line reach is the only one that does. It
# keeps the scope its own measurement bought.
#
# ONE VOCABULARY, NOT A FOURTH COPY. The words that mean "no" are imported from
# `_prose_polarity` (vibe-ic#712 — "three private copies of it is how the
# divergence happened"), and `blank_bracketed` comes with them, so a qualifier
# in brackets cannot carry a document's polarity. What is local here is the
# SHAPE test, because absence-vs-prohibition is a distinction that module does
# not draw and four other modules do not want drawn for them.
# Only `blank_bracketed` is imported, and it is CALLED. `DENIAL_CORE_RE` was
# imported here too, as a fast reject, and is deliberately gone: the branches
# below already require its words, the predicate runs at most `limit` times per
# call so there was no measured speed to buy, and an import whose only consumer
# was the test asserting the import is the "a call that can never fire is a
# green light rather than a check" shape this repo names in
# `prose_polarity_consulted_check._NOT_PROSE`. The anti-fork guard that matters
# is the test asserting every single-word cue below is already in
# `_prose_polarity.NEGATION_RE`, and that does not need an alias to hold.
# `sentence_scope` joins it for #1021: it is the house REACH, the counterpart
# of the house VOCABULARY, and the same argument applies — a second copy of
# "where does a sentence end" is how the first divergence happened. It is
# CALLED, on the framing neighbourhood and on both drop predicates' spans, so
# it is not an import whose only consumer is the test asserting the import.
from _prose_polarity import (                                    # noqa: E402
    blank_bracketed as _blank_bracketed,
    sentence_scope as _sentence_scope,
)

#: Verbs by which a document DECLARES a requirement. Negate one of these and
#: the sentence says nothing was declared at all.
_DECLARATION_VERB = (
    r"(?:specif\w*|defin\w*|list\w*|mandat\w*|requir\w*|includ\w*|provid\w*|"
    r"implement\w*|expos\w*|support\w*|describ\w*|document\w*|address\w*|"
    r"cover\w*|contain\w*|declar\w*|impos\w*|prescrib\w*|enable\w*|"
    r"carr(?:y|ies|ied)|ha(?:s|ve|d)|appl(?:y|ies|icable)|part\s+of|present)"
)

#: A deontic modal + negation is a REQUIREMENT, never an absence. Kept as its
#: own pattern so the separation is testable rather than merely implied by the
#: auxiliary list in `_REQUIREMENT_ABSENT_RE`.
_PROHIBITION_RE = re.compile(
    r"\b(?:shall|must|should|may|will|would|can|could|might)\s*n(?:o|')?t\b"
    r"|\bcannot\b|\bshan't\b|\bmustn't\b",
    re.IGNORECASE)

_REQUIREMENT_ABSENT_RE = re.compile(
    # (a) NEGATED DECLARATION — "does NOT specify", "are not defined",
    #     "is not required to implement". INDICATIVE auxiliaries only.
    r"\b(?:do(?:es)?|did|is|are|was|were|ha(?:s|ve|d)|been)\s+"
    r"n(?:o|')t\b(?:\s+\w+){0,3}\s+" + _DECLARATION_VERB +
    # (b) EXISTENTIAL — "there is no", "there are no such"
    r"|\bthere\s+(?:is|are|was|were|exists?)\s+(?:\w+\s+){0,2}\bno\b"
    # (c) CORRELATIVE — "Neither <A> nor <B> defines a JTAG / scan / BIST".
    #     `neither`/`nor` are NOT in `_prose_polarity`'s vocabulary and are
    #     deliberately NOT pushed there: that module is read by four other
    #     modules whose counts would move for a shape only this predicate
    #     needs. Recorded as the one local addition, not smuggled in.
    r"|\bneither\b[^.]{0,200}?\bnor\b"
    # (d) BARE PARTICIPLE — "not specified at the protocol level",
    #     "not part of the standard", "not applicable".
    r"|\bnot\s+(?:specified|defined|required|mandated|applicable|documented|"
    r"described|covered|addressed|supported|exposed|present|"
    r"part\s+of|in\s+scope|within\s+scope)\b",
    re.IGNORECASE)

#: A BARE `no` is the loosest cue in the whole vocabulary, so it is the ONLY
#: one required to GOVERN the match POSITIONALLY: it counts only when it stands
#: BEFORE the matched term. "no JTAG support" denies the term; "JTAG ... no"
#: does not, and letting a later `no` reach backwards is #790's silent
#: direction — the caller publishes less than it read and nothing goes red.
_BARE_NO_RE = re.compile(r"\bno\b", re.IGNORECASE)

#: ... and NEVER when it heads a comparative. `REQUIREMENT_FRAMING_RE` reads
#: `no less than` as FRAMING, so treating the same three words as a denial
#: would let this predicate delete the very rows that predicate admits.
_NO_COMPARATIVE_RE = re.compile(
    r"\bno\s+(?:less|fewer|more|greater|later|earlier|longer|shorter|worse|"
    r"better|higher|lower)\b",
    re.IGNORECASE)

#: How far back a bare `no` may reach. A clause, not a sentence: the shapes it
#: has to catch are "no PDK, floor-plan, SDC, UPF, or DFT artifact" (43 chars
#: from cue to term) and "No standard DFT / JTAG path" (14). MEASURED — the
#: widest bare-`no` span among the 107 published run dirs is 56 characters.
_BARE_NO_REACH = 80


def requirement_absent(line: str, term_offset: Optional[int] = None
                       ) -> Optional[str]:
    """The phrase by which this SPAN says the requirement DOES NOT EXIST.

    SPAN-SCOPED BY CONTRACT — the caller passes ONE span and never a
    neighbourhood, and since #1021 that span is the SENTENCE the term sits in,
    which is the same span the framing was looked for in. See the block above
    for the re-measurement that retired the line reach, and note that
    :func:`signoff_qualifier` deliberately did NOT move with it: its
    counterexample is a table row, and rows end at a newline rather than a
    full stop.

    ``term_offset`` is where the matched vocabulary term sits INSIDE ``line``.
    It is optional so the predicate stays callable on a bare line (and so the
    positional half simply does not apply then), but a caller that has it gets
    the bare-`no` shape, which is the one cue that must stand in front of the
    term it denies.

    Returns the matched PHRASE rather than a bool, so a consumer can record it
    as evidence and a human can audit the call — the same reason
    :func:`signoff_qualifier` does.
    """
    if not line:
        return None
    # Bracketed spans carry qualifiers, not the statement's polarity (#711).
    # Length-preserving, so `term_offset` stays valid.
    hay = _blank_bracketed(line)

    m = _REQUIREMENT_ABSENT_RE.search(hay)
    if m:
        return m.group(0).strip()[:120]

    if term_offset is None:
        return None
    lo = max(0, term_offset - _BARE_NO_REACH)
    span = hay[lo:term_offset]
    for cand in _BARE_NO_RE.finditer(span):
        tail = span[cand.start():]
        if _NO_COMPARATIVE_RE.match(tail):
            continue
        if _PROHIBITION_RE.search(span[max(0, cand.start() - 12):cand.end()]):
            continue
        return span[cand.start():].strip()[:120] or "no"
    return None


# ─────────────────────────────────────────────────────────────────────
# "The document says the requirement IS SOMEBODY ELSE'S"  (vibe-ic#1021)
# ─────────────────────────────────────────────────────────────────────
#
# THE THIRD IDIOM, AND IT IS NOT REACHABLE BY EITHER OF THE FIRST TWO.
# `signoff_qualifier` answers "the document says this row is not BINDING".
# `requirement_absent` answers "the document says the requirement is not
# THERE". Neither asks the question two published roots' own L7 notes answer,
# VERBATIM and identically:
#
#     "Chip-level JTAG/scan/BIST remain Source/Sink-silicon concerns"
#     "Chip-level JTAG/scan/BIST remain Source / panel-TCON silicon concerns"
#
# That is "this requirement belongs to somebody ELSE'S silicon". It is not a
# denial — it does not say the requirement does not exist, and it CONTAINS NO
# NEGATION WORD AT ALL, so `requirement_absent` cannot reach it at ANY reach,
# correctly, because that is not the question that predicate asks. It is not a
# non-normative disclaimer either: nothing about it says "informational".
#
# A GATE ASKS ABOUT ITS OWN LAYER. `l20_dft_scan_topology_actionable_check`'s
# question is "did THIS design's inputs state a DFT requirement THIS design's
# L20 is missing?" A sentence that assigns the requirement to a different
# party's silicon is an answer of NO to that question, in the design's own
# words — and a gate that reads it as YES blocks a published project for
# stating its scope correctly.
#
# DELIBERATELY NARROW, AND IN THE SAME SHAPE AS ITS TWO NEIGHBOURS: it keys on
# a closed vocabulary of OWNERSHIP TRANSFER, not on the general idea of scope.
# "the scope of this specification includes a JTAG TAP" is a REQUIREMENT that
# contains the word scope, exactly as "must NOT exceed 5 ns" is a requirement
# that contains a negation — the trap `_NON_NORMATIVE_RE` already records. So
# the bare word `scope` is never a cue; only an EXCLUSION from a scope is
# ("out of scope", "outside the scope", "beyond the scope"), and only a
# transfer of ownership is (a linking verb bound to `concern` / `matter` /
# `responsibility`, or an explicit hand-off verb).
#
# WHAT IS DELIBERATELY NOT IN IT, having been measured and rejected:
#   * `up to` — "the link runs at up to 5 Gb/s" is a rate, not a deferral, and
#     it occurs in that sense far more often than in this one.
#   * `vendor-specific` / `implementation-defined` — these DO mark a deferral
#     ("PHY vendors add scan + BIST in vendor-specific register space"), but
#     they equally often qualify a register map INSIDE a stated requirement.
#     Adding them drops hits on roots the corpus gives no way to adjudicate as
#     wrong, so they stay out until a root forces the question.
#   * the bare word `scope` in any position — see above.
_OUT_OF_SCOPE_RE = re.compile(
    # (a) EXCLUSION FROM A SCOPE. Note that every one of these is spellable
    #     with NO negation word, which is the whole gap this predicate fills.
    r"\b(?:out\s+of|outside(?:\s+of)?|beyond)\s+(?:the\s+)?scope\b"
    # (b) OWNERSHIP TRANSFER by a linking verb bound to an ownership noun —
    #     "remain <somebody>'s concerns", "is a matter for the integrator".
    #     Bounded, and it may not cross a full stop: the sentence that hands
    #     the requirement away is the sentence that must contain the term.
    r"|\b(?:remains?|stays?|is|are|was|were|be)\b[^.]{0,80}?"
    r"\b(?:concerns?|matters?|responsibilit(?:y|ies)|prerogatives?)\b"
    # (c) EXPLICIT HAND-OFF. "left to the SoC integrator", "deferred to the
    #     implementer". The verb alone carries it; no owner noun needed.
    r"|\b(?:left|deferred|delegated|relegated|devolved|handed\s+off)\s+to\b"
    r"|\bresponsibility\s+of\b|\ba\s+matter\s+for\b",
    re.IGNORECASE)


def requirement_out_of_scope(line: str, term_offset: Optional[int] = None
                             ) -> Optional[str]:
    """The phrase by which this SPAN defers the requirement to SOMEBODY ELSE.

    SPAN-SCOPED BY CONTRACT, on the same span as :func:`requirement_absent` —
    the sentence the matched term sits in, which is also the sentence the
    framing was looked for in. That equality is load-bearing: a predicate that
    DROPS a hit at a narrower reach than the framing that ADMITTED it can be
    out-flanked, which is the defect #1020 hit from the other end and #1021
    fixed.

    ``term_offset`` is accepted for signature parity with its two neighbours so
    a caller can hold all three the same way; it is unused, because unlike a
    bare `no` every cue here is a multi-word phrase that cannot be produced by
    an unrelated word happening to share the span.

    Returns the matched PHRASE rather than a bool, for the same reason
    :func:`signoff_qualifier` and :func:`requirement_absent` do: a drop a human
    can audit from the gate's own report.
    """
    if not line:
        return None
    # Bracketed spans carry qualifiers, not the statement's polarity (#711),
    # and the same is true of its ownership. Length-preserving.
    m = _OUT_OF_SCOPE_RE.search(_blank_bracketed(line))
    return m.group(0).strip()[:120] if m else None


def _hit_line(text: str, offsets: List[int],
              m: "re.Match") -> Tuple[str, int]:
    """``(the ORIGINAL line the match sits on, where the match starts in it)``.

    Taken from the raw text rather than the normalised copy, because
    normalisation collapses newlines and a disclaimer must be scoped to the row
    that carries it.

    The OFFSET is what lets `requirement_absent` ask whether a bare `no` stands
    IN FRONT OF the term, which is the difference between "no JTAG support" and
    a `no` that merely shares the row. Returned alongside the line rather than
    re-derived by the caller, because `str.find` on the line would locate the
    FIRST occurrence of the vocabulary and the match is not always the first.
    """
    start = offsets[m.start()] if m.start() < len(offsets) else 0
    end = offsets[m.end() - 1] if 0 < m.end() <= len(offsets) else start
    lo = text.rfind("\n", 0, start) + 1
    hi = text.find("\n", end)
    return (text[lo:] if hi == -1 else text[lo:hi]), start - lo


def framed_hits(texts: Iterable[Tuple[Path, str]],
                vocab_re: re.Pattern,
                window: int = 160,
                limit: int = 12,
                include_non_normative: bool = False,
                drop_denied: bool = False,
                drop_out_of_scope: bool = False,
                reject: Optional[Callable[[str, str], bool]] = None
                ) -> List[Dict[str, Any]]:
    """Vocabulary matches that carry requirement framing IN THEIR OWN SENTENCE.

    Mirrors ``l8_clock_domains_typed_check._is_real_clock_freq``: a raw
    vocabulary hit is noise; a hit whose neighbourhood carries a requirement
    word is a stated requirement. ``window`` is the BUDGET for that
    neighbourhood; the neighbourhood itself is the intersection of that budget
    with the SENTENCE the term sits in (vibe-ic#1021 — before that it was the
    flat budget, and a hit in one sentence could borrow its framing from the
    next). See the block above ``REQUIREMENT_FRAMING_RE`` for the measurement.

    Matching runs on the whitespace-normalised text so hard-wrapped
    requirements are found, and results are deduplicated by context so
    the same sentence shipped as both ``phase1/input_doc/x.txt`` and
    ``input/docs/x.rst`` is counted once — an honest evidence count, not
    a copy count. Returns at most ``limit`` records so gate stdout stays
    reviewable.

    ``include_non_normative`` — TWO CONSUMERS, TWO POLICIES, ONE PREDICATE.
    A GATE asks "did the design state a requirement my layer is missing?",
    so a row the document itself disclaims is not evidence and is dropped:
    that is the default, and with the default OFF the returned records are
    byte-identical to what every gate already embeds in its report.
    An EMITTER asks "what did the design DECLARE?", and a declared-but-
    informational target is still declared — dropping it makes a consumer
    read the layer as having no goal at all, which is this repo's
    false-certificate class. Such a consumer passes True: the disclaimed
    hit is RETAINED and every record additionally carries

        non_normative  bool — the hit's OWN LINE disclaims normative force
        line_text      str  — that line, so the consumer can apply its own
                              policy without re-deriving the scope

    The predicate stays shared either way; only the policy differs. An
    emitter with a private predicate emits goals the gate does not accept.

    ``drop_denied`` — OPT-IN, AND IT DEFAULTS OFF FOR A REASON (vibe-ic#1011).
    A hit whose own line says the requirement DOES NOT EXIST is not evidence
    that one was stated; see :func:`requirement_absent`. This is OFF by
    default so that turning it on is a decision a consumer makes and a
    measurement backs, never a silent global move of a SHARED predicate: the
    four programs with a call site here (`l20_dft_scan_topology_actionable_
    check`, `l22_verification_plan_measurable_check`,
    `l23_security_requirements_typed_check`, `l22_coverage_goal_emit`) are
    asking four different questions of four different vocabularies.

    MEASURED, on all 107 published run dirs, which is what the default
    encodes. For L20 it drops 74 of 153 framed hits and takes 34 roots with a
    hit down to 12, keeping every root that states a requirement positively.

    THE OTHER THREE ARE NOT SWITCHED ON, AND ONE OF THEM SAYS WHY. L22's two
    consumers move by 0 hits, so the flag would buy them nothing. L23 moves by
    2 — and both are WRONG DROPS, which is the finding that fixes the default
    in place rather than a reason to shrug. Its layer texts are long
    multi-paragraph prose blobs on one JSON line (836 and 831 chars), and in
    them a `does not have` belonging to a different sentence reaches the
    matched term:

        "... a TBB is part of a Root of Trust that does not have Shielded
         Locations."          -> retracts `Root of Trust`, 200 chars away
        "... they do not have the same value as TPM_GENERATED_VALUE ..."
                              -> retracts `attestation`, 400 chars away

    Line scope is right for the layers whose text is one statement per line
    and wrong for a layer that puts a whole spec section on one; a flag that
    lets each consumer answer that for itself is the only honest shape,
    because the same reach is correct for one and incorrect for the other.
    L23's real requirements are also written as PROHIBITIONS ("the key shall
    not be readable"), which `requirement_absent` separates from absence by
    construction — but that separation is not what would hurt it here, and
    saying so is the point of having measured.

    ``drop_denied`` records on the opt-in path only, like the field above:

        denied         str|None — the phrase by which the line denies it,
                                  present so the drop is auditable from the
                                  gate's own report rather than re-derived

    ``drop_out_of_scope`` — THE THIRD IDIOM, AND IT IS ALSO OPT-IN
    (vibe-ic#1021). A hit whose own sentence hands the requirement to a
    DIFFERENT party's silicon is not evidence that THIS design was required to
    carry it; see :func:`requirement_out_of_scope`. Separate from
    ``drop_denied`` rather than folded into it, because they are two different
    questions — "the requirement does not exist" and "the requirement is not
    mine" — and a consumer that wants one may not want the other. MEASURED
    across all four consumers before it was wired: only `l20` moves, by the two
    roots whose L7 notes carry the idiom verbatim; `l22`'s two consumers and
    `l23` move by 0 hits, so switching them on would buy them nothing and is
    not done. Records ``out_of_scope`` on the opt-in path, for the same
    auditability reason as ``denied``.

    ``reject`` — THE VOCABULARY'S OWNER DECIDES WHAT ITS OWN TOKENS MEAN
    (vibe-ic#1021). Called as ``reject(matched_text, sentence)`` and, when it
    returns True, the match is not a member of the vocabulary at all and is
    dropped before dedup, before the limit and before either drop predicate.
    This exists because polarity is NOT the only way a framed hit can be
    spurious: `l20`'s ``m?bist`` matches a ``BIST Activate`` frame type in one
    root's inputs and a ``BIST`` message type in another's, which are payloads
    a protocol defines on the wire, sitting inside genuine ``shall``
    sentences. No framing, denial or
    scope ruler can discriminate those, because nothing about them is
    mis-framed, denied or deferred — the TOKEN simply means something else in
    that document.

    IT IS A HOOK AND NOT A SHARED RULE BECAUSE THE COLLISION IS NOT SHARED.
    Four programs pass four different vocabularies here; a protocol message
    name collides with exactly one of them. Encoding l20's collision list in
    this module would put DFT vocabulary in the shared contract and move the
    other three consumers for a shape none of them has.

    WHY IT RUNS HERE AND NOT ON THE RETURNED RECORDS. A caller could filter
    afterwards, and that would be wrong in the silent direction: ``limit``
    truncates first, so a root whose first ``limit`` hits are all rejects would
    be reported as having ZERO hits while real ones went unread. Rejecting
    inside the loop means the limit counts what survived.

    The ``sentence`` handed over is the FULL framing neighbourhood, not the
    truncated ``context`` field the record carries for reporting — the reason
    this is a hook rather than a post-filter a second time.
    """
    out: List[Dict[str, Any]] = []
    seen_ctx: set = set()
    for path, text in texts:
        norm, offsets = _normalize_ws(text)
        for m in vocab_re.finditer(norm):
            # THE SENTENCE, BUDGETED AT ±`window` — not the flat ±`window`
            # (vibe-ic#1021). `sentence_scope`'s before/after ARE a budget by
            # its own contract, so this is exactly the intersection of the two
            # and can only ever narrow what the flat window admitted.
            lo, hi = _sentence_scope(norm, m.start(), m.end(),
                                     before=window, after=window)
            ctx = norm[lo:hi]
            if not REQUIREMENT_FRAMING_RE.search(ctx):
                continue
            if reject is not None and reject(m.group(0), ctx):
                continue          # not a member of this vocabulary at all
            # Scope the disclaimer to the hit's OWN LINE, not to the ±window.
            # Gatekeeper finding: with a 160-char neighbourhood, a disclaimer
            # on one table row silences a real requirement on the NEXT one.
            # Measured on
            #     | Toggle coverage(informational) | >= 95% | not a sign-off gate |
            #     | Setup slack                    | >= 0 ns | sign-off gate      |
            # the second row alone yields 1 hit and the pair yields 0 — the
            # sign-off requirement vanished because of its neighbour. A
            # document disclaims the row it is written on; proximity is not
            # membership.
            hit_line, term_offset = _hit_line(text, offsets, m)
            non_normative = bool(_NON_NORMATIVE_RE.search(hit_line))
            if non_normative and not include_non_normative:
                continue          # the document itself says it is not a requirement
            # THE DROP PREDICATES READ THE SAME SPAN THE FRAMING WAS FOUND IN
            # (vibe-ic#1021). Handing them `ctx` rather than re-deriving a
            # reach is what makes "neither half can out-flank the other"
            # structural rather than a claim: it is one span, computed once.
            # `_NON_NORMATIVE_RE` above is the ONE deliberate exception — its
            # counterexample is a table row, and rows end at a newline.
            denied = (requirement_absent(ctx, m.start() - lo)
                      if drop_denied else None)
            if denied:
                continue          # the document itself says it does not exist
            out_of_scope = (requirement_out_of_scope(ctx, m.start() - lo)
                            if drop_out_of_scope else None)
            if out_of_scope:
                continue          # the document itself says it is somebody else's
            key = ctx.strip()
            if key in seen_ctx:
                continue
            seen_ctx.add(key)
            orig_start = offsets[m.start()] if m.start() < len(offsets) else 0
            line_no = text.count("\n", 0, orig_start) + 1
            rec = {
                "source": str(path),
                "line": line_no,
                "match": m.group(0).strip()[:120],
                "context": ctx.strip()[:220],
            }
            if include_non_normative:
                # Added ONLY on the opt-in path so a gate's report JSON
                # keeps exactly the shape it ships today.
                rec["non_normative"] = non_normative
                rec["line_text"] = hit_line.strip()[:220]
            if drop_denied:
                # Likewise opt-in only. Always None on a returned record —
                # a denied hit never gets this far — but present so a report
                # states which policy produced it, rather than leaving a
                # reader to infer the ruler from the count.
                rec["denied"] = denied
            if drop_out_of_scope:
                rec["out_of_scope"] = out_of_scope
            out.append(rec)
            if len(out) >= limit:
                return out
    return out


# ─────────────────────────────────────────────────────────────────────
# Provenance that survives leaving the machine it was produced on
# ─────────────────────────────────────────────────────────────────────

# Structurally impossible to mistake for a path, and it reuses the
# angle-bracket convention `shipped_path_portability_check` already
# treats as "a placeholder, not a value".
OUTSIDE_PROJECT_PREFIX = "<outside-project>"


def project_relative_source(source: Any, project: Path) -> Tuple[str, bool]:
    """Turn a provenance path into one that means the same thing anywhere.

    Returns ``(source, outside_project)``.

    WHY THIS IS NOT DONE IN ``framed_hits``
    ---------------------------------------
    ``framed_hits`` returns ``str(path)`` — an ABSOLUTE path, because
    ``input_doc_texts`` globs a project directory the caller resolved.
    That is correct for its GATE callers: a gate writes its hits into a
    report under ``reports/``, and a report is a RUN RECORD whose job is
    to say where the run happened. It is wrong for its EMITTER callers,
    which write the value into an L document — a DESIGN artefact that the
    flow reads back, diffs across runs and compares between designs. An
    absolute path there records the checkout and the machine, so two runs
    of the same design from different directories produce different L
    documents and neither is comparable to the other.

    Same predicate, two consumers, two policies — the same split
    ``framed_hits(include_non_normative=...)`` already makes. So the
    relativisation lives here, next to the code that produced the
    absolute path, and every emitter opts in; the gates' report JSON
    keeps exactly the shape it ships today.

    WHAT IS RECORDED WHEN THE PATH CANNOT BE RELATIVISED
    ----------------------------------------------------
    An input can legitimately live outside the project root (a shared
    corpus, a symlink farm, a path handed in by an orchestrator). Three
    options were on the table:

      * emit the absolute path — the defect itself, just narrower;
      * emit nothing — the goal keeps its number but loses every trace of
        where the number came from, and a reader cannot tell a
        provenance-less goal from a fabricated one. This repo's whole
        failure class is a value that cannot be traced back;
      * emit an EXPLICIT MARKER plus the file's own basename.

    The third is chosen. The basename is a property of the DOCUMENT and
    is identical on every machine; only the directory chain above it is
    machine-specific, and that is exactly the part dropped. The marker
    ``<outside-project>/`` makes the degradation impossible to read as a
    real relative path, and the returned ``outside_project`` flag lets a
    consumer branch on it without string-sniffing. Provenance is degraded
    — two different out-of-project files with the same basename become
    indistinguishable — but it is degraded VISIBLY, which is the whole
    difference from dropping it.

    That policy is not invented here. ``l_doc_evidence_util
    .resolve_under_project`` is this function's READ-side counterpart, and
    it already REFUSES an evidence path that escapes the project root —
    "a certificate whose proof lives outside the run is not reproducible
    evidence". An absolute out-of-project path would therefore be silently
    unresolvable to the reader; an explicit marker at least says so.

    ``line`` is deliberately NOT touched by any of this: a line number is
    a property of the file's contents, not of the machine it sits on.
    """
    if source is None:
        return "", False
    raw = str(source).strip()
    if not raw:
        return "", False

    p = Path(raw)
    if not p.is_absolute():
        # Already relative — normalised through the path flavour so the
        # emitted separator is always `/` and the value never records which
        # OS produced it. This does NOT launder backslashes out of a string:
        # on POSIX a backslash is a legal filename character and rewriting
        # it would corrupt a real name.
        return p.as_posix(), False

    for base in _relativisation_bases(project):
        try:
            return p.relative_to(base).as_posix(), False
        except ValueError:
            continue
    # A resolved comparison catches a symlinked project root or a path
    # carrying `..` segments, which the lexical attempt above cannot.
    try:
        rp = p.resolve()
        for base in _relativisation_bases(project):
            try:
                return rp.relative_to(base.resolve()).as_posix(), False
            except (ValueError, OSError):
                continue
    except (OSError, RuntimeError):
        pass
    return f"{OUTSIDE_PROJECT_PREFIX}/{p.name}", True


def _relativisation_bases(project: Path) -> List[Path]:
    """The project root, lexical form first, resolved form second.

    Two forms because the caller may hand in either: ``main()`` resolves
    its ``project_dir`` while an in-process caller often does not, and a
    glob result is prefixed with whichever form was globbed.
    """
    bases = [project]
    try:
        rp = project.resolve()
        if rp != project:
            bases.append(rp)
    except (OSError, RuntimeError):
        pass
    return bases


# ─────────────────────────────────────────────────────────────────────
# Actionable-form predicates
# ─────────────────────────────────────────────────────────────────────

_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def numeric_target(value: Any) -> Optional[float]:
    """Extract a number a downstream gate could COMPARE against.

    ``95`` → 95.0, ``"95%"`` → 95.0, ``">= 95 %"`` → 95.0.
    ``True`` → None (a boolean is not a threshold).
    ``"high"`` / ``"full"`` / ``"implicit"`` → None. Prose is not a
    target: nothing downstream can falsify it.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = _NUM_RE.search(value)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
    return None


def nonempty_str(value: Any, min_len: int = 1) -> bool:
    return isinstance(value, str) and len(value.strip()) >= min_len


# ─────────────────────────────────────────────────────────────────────
# Waivers + reporting
# ─────────────────────────────────────────────────────────────────────

def waiver_rationale(project: Path, waiver_id: str,
                     min_chars: int = 40) -> Optional[str]:
    """Return the rationale iff waivers.json carries `waiver_id` with a
    rationale of at least `min_chars`. A short rationale is not a waiver."""
    for cand in [project / "waivers.json", *project.glob("**/waivers.json")]:
        if not cand.is_file():
            continue
        try:
            data = json.loads(cand.read_text(encoding="utf-8",
                                             errors="ignore"))
        except Exception:
            continue
        entries: List[dict] = []
        if isinstance(data, list):
            entries = [e for e in data if isinstance(e, dict)]
        elif isinstance(data, dict):
            for key in ("waivers", "entries", "items"):
                v = data.get(key)
                if isinstance(v, list):
                    entries = [e for e in v if isinstance(e, dict)]
                    break
            else:
                v = data.get(waiver_id)
                if isinstance(v, str) and len(v.strip()) >= min_chars:
                    return v.strip()
                if isinstance(v, dict):
                    entries = [dict(v, id=waiver_id)]
        for e in entries:
            if str(e.get("id") or e.get("key") or "").strip() != waiver_id:
                continue
            for field in ("rationale", "reason", "justification", "note"):
                txt = e.get(field)
                if isinstance(txt, str) and len(txt.strip()) >= min_chars:
                    return txt.strip()
    return None


def write_report(project: Path, gate: str, payload: dict) -> Optional[Path]:
    """Persist a machine-readable finding record.

    Failure (c) of the L21 post-mortem: none of the 52 flagged gaps was
    ever distilled back into the program, so the recovery stayed a
    one-off. A gate that only prints to stdout cannot be distilled.
    Writing the findings as JSON is what makes
    ``benchmark-enhancement-capture`` able to absorb them.
    """
    try:
        out_dir = project / "reports" / "phase1"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{gate}.json"
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        return out
    except Exception:
        return None
