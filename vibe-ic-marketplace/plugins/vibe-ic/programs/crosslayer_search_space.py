#!/usr/bin/env python3
"""crosslayer_search_space.py — the CROSS-LAYER PPA search space, and the
citation that authorises every lever in it.

WHAT THIS IS FOR
----------------
Every knob the open flows search is a place-and-route knob: ORFS AutoTuner
tunes utilisation, aspect ratio, cell padding, placement density and CTS
clustering; LibreLane ships nine fixed synthesis presets a human picks between.
Nothing searches RTL, and nothing searches micro-architecture, because a tuner
cannot rewrite a design.

An agent that has read the specification can. That is the whole claim, and it
carries a hazard the tuner does not have: rewriting the design to win a score
is the exact shape of a cheat. Two things keep it honest, and this program is
the first of them.

    THIS program   decides WHICH levers may be searched, and refuses any lever
                   the specification has not left free.
    the equivalence gate (`crosslayer_rewrite_equivalence.py`) decides whether
                   a candidate produced by those levers is still the same chip.

THE RULE, AND IT IS NOT NEGOTIABLE
----------------------------------
A micro-architectural choice is a search dimension ONLY where the specification
never pinned it. If the spec names a pipeline depth, an encoding, a latency or
a structure, that is a REQUIREMENT, and a search that changes it is not
searching -- it is building a different product. So every lever admitted here
carries one of:

    spec_sentence   a citation, PATH:LINE plus the literal text, of the
                    sentence in the design's OWN input documents that leaves
                    this structure to the implementation
    no_design_change  the lever does not touch the design at all (a synthesis
                    strategy re-maps the same RTL), so no permission is needed
                    and none is claimed

and a lever with neither is EXCLUDED with `UNDECLARED`. Silence is not
permission. A lever the spec PINS is EXCLUDED with `PINNED` and the pinning
sentence is quoted, so a reader can see the refusal was measured rather than
assumed.

Where a design says both -- a freedom sentence and a pinning sentence for the
same lever -- PINNED WINS. Searching a lever on a contested reading is how a
search quietly becomes a redesign.

READS ONLY THE DESIGN INPUT (§4.05)
-----------------------------------
The only files opened are the design's own input documents. No oracle, no
harness, no golden model, no reference RTL, no benchmark expectation.

NOT_MEASURED IS NOT AN EMPTY SPACE
----------------------------------
"the documents say this design pins everything" and "no document could be read"
are opposite findings and never share a verdict:

    rc 0   a space was produced (it may legitimately be empty)
    rc 2   NOT_MEASURED -- no readable input document, so nothing was decided

CLI
    python3 crosslayer_search_space.py <project_dir> [--docs-dir ...]
        [--json reports/crosslayer_search_space.json] [--require-nonempty]
    python3 crosslayer_search_space.py <project_dir> --verify <space.json>
    main(argv) -> int   0 ok / 1 refused / 2 NOT_MEASURED

Chip-AGNOSTIC: the lever vocabulary is ordinary digital-design terminology and
the freedom vocabulary is ordinary specification language. No design name, no
module name, no PDK and no vendor appears anywhere in this file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The ONE negation vocabulary and the ONE sentence reach (vibe-ic#712, #790).
# `classify_line` decides what a SENTENCE authorises, so a sentence that denies
# its own marker is the one reading it must not get wrong. See `marker_denials`
# for why the consult cannot be a bare `is_denied(line)` here.
from _prose_polarity import (  # type: ignore  # noqa: E402
    is_denied as _is_denied, sentence_scope as _sentence_scope)

PROGRAM = "crosslayer_search_space"
DEFAULT_JSON_REL = "reports/crosslayer_search_space.json"

# Where a design's own input documents live, in the order the flow stages them.
DEFAULT_DOC_DIRS = ("input/docs", "input_doc", "phase1/input_doc",
                    "phase1/generated_docs", "docs")
# `.rst` is in this list because a design in this corpus ships its
# specification as reStructuredText, and without it the scan found zero
# documents. It reported NOT_MEASURED rather than an empty search space,
# which is the behaviour working — but the right fix is to read the file.
DOC_SUFFIXES = (".md", ".txt", ".markdown", ".rst", ".adoc")

STATUS_FREE = "FREE"
STATUS_PINNED = "PINNED"
STATUS_UNDECLARED = "UNDECLARED"
STATUS_BOUNDED = "BOUNDED"
STATUS_NO_DESIGN_CHANGE = "NO_DESIGN_CHANGE"

KIND_SPEC_SENTENCE = "spec_sentence"
KIND_NO_DESIGN_CHANGE = "no_design_change"

# --- the vocabulary --------------------------------------------------------
# A specification says "the implementation may choose this" in a small number of
# ways, and this corpus is written in two languages. These are the phrasings
# MEASURED in the design documents this flow ingests, not a guess at what a
# specification might say. Adding a phrasing is a one-line change with a test.
_FREEDOM_MARKERS = (
    r"不指定", r"不約束", r"不限制", r"不規定",
    r"自選", r"自由選擇", r"由實作", r"由\s*Plugin",
    r"does\s+not\s+specify", r"does\s+not\s+constrain",
    r"does\s+not\s+mandate", r"not\s+specified",
    r"free\s+to\s+choose", r"implementation[-\s]defined",
    r"left\s+to\s+the\s+implementation", r"any\s+functionally\s+equivalent",
)

# A specification PINS a structure by REQUIRING A PARTICULAR VALUE for it.
# A modal verb on its own is NOT a pin, and reading it as one was measured to
# be wrong: a multiplier spec whose body says
#     "但**必須**:`y` 第 `i` 個位元給入後,在有限且確定的 cycle 數內,`p` 對應位元被輸出"
# ("must produce the bit within a finite and determinate number of cycles")
# states a WELL-FORMEDNESS requirement and names no latency at all, while the
# same document says four lines later "❌ 不指定 latency cycle 數". Treating the
# modal as a pin refused the very lever the document had explicitly freed. So a
# pin needs BOTH the requirement language AND a concrete value.
_PINNING_MARKERS = (
    r"必須", r"應為", r"固定為", r"固定", r"規定為",
    r"\bshall\b", r"\bmust\b", r"\bis\s+fixed\b",
    r"\brequired\s+to\s+be\b", r"\bexactly\b",
)

# A concrete value: a number, or an equality/assignment to one. Without one, a
# requirement sentence constrains behaviour but does not fix a structure.
_CONCRETE_VALUE_RE = re.compile(r"(?<![\w.])\d+(?![\w.])")

# A BOUND is neither freedom nor a pin: "latency <= 4096 cycles" leaves the
# structure to the implementation *within a ceiling*. Recording it as a pin
# would refuse a lever the specification opened; recording it as plain freedom
# would drop a constraint the candidate has to meet. It is its own status, and
# the ceiling travels with the lever so the search can be held to it.
_BOUND_MARKERS = (
    r"上限", r"最大", r"至多", r"不超過",
    r"\bupper\s+bound\b", r"\bat\s+most\b", r"\bmax(?:imum)?\b",
    r"\bno\s+more\s+than\b", r"≤", r"<=",
)
_BOUND_VALUE_RE = re.compile(
    r"(?:≤|<=|上限|最大|至多|不超過|at\s+most|max(?:imum)?|no\s+more\s+than)"
    r"[^0-9]{0,12}(\d+)", re.IGNORECASE)

# Lever -> the words a sentence must also contain for that sentence to be about
# this lever. Ordinary digital-design vocabulary; nothing design-specific.
_LEVER_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "pipelining": (r"pipeline", r"管線", r"latency", r"延遲",
                   r"cycle\s*數", r"\bcycles?\b"),
    "state_encoding": (r"encoding", r"encode", r"編碼", r"\bFSM\b",
                       r"state\s*(?:數量|count)", r"狀態"),
    "arithmetic_architecture": (r"演算法", r"algorithm", r"arithmetic",
                                r"adder", r"multiplier", r"加法器", r"乘法器",
                                r"unroll", r"iterative", r"round\s+function"),
    "module_hierarchy": (r"hierarchy", r"階層", r"sub-?module", r"子模組",
                         r"internal\s+signal", r"內部訊號", r"命名",
                         r"naming", r"結構", r"structure"),
}

# The value domain each lever offers a search. Domains are DECLARATIVE: this
# program decides what may be searched, never what the search should try first.
_LEVER_DOMAIN: Dict[str, Dict[str, object]] = {
    "pipelining": {
        "layer": "rtl",
        "kind": "integer_offset",
        "domain": "additional pipeline stages on the output path, 0..N",
        "equivalence_mode": "latency_offset",
        "note": ("a candidate at +N stages is compared against the baseline "
                 "delayed by N; the offset is declared and cited, never "
                 "inferred"),
    },
    "state_encoding": {
        "layer": "rtl",
        "kind": "categorical",
        "domain": "binary | gray | one-hot | johnson",
        "equivalence_mode": "cycle_exact",
        "note": "port behaviour is unchanged, so the strict miter applies",
    },
    "arithmetic_architecture": {
        "layer": "arithmetic",
        "kind": "categorical",
        "domain": ("ripple-carry | carry-lookahead | carry-select | "
                   "carry-save | shift-add | unrolled"),
        "equivalence_mode": "cycle_exact",
        "note": ("the one layer an existing tool touches at all, and only "
                 "narrowly (OpenROAD replace_arith_modules, on critical "
                 "paths, post-synthesis)"),
    },
    "module_hierarchy": {
        "layer": "microarchitecture",
        "kind": "categorical",
        "domain": "flat | split-by-function | split-by-datapath-stage",
        "equivalence_mode": "cycle_exact",
        "note": "hierarchy is flattened by the miter, so it cannot hide a change",
    },
    "synthesis_strategy": {
        "layer": "synthesis",
        "kind": "categorical",
        "domain": "AREA 0..3 | DELAY 0..4",
        "equivalence_mode": "cycle_exact",
        "note": ("the RTL is not touched; nine presets exist in the open flow "
                 "and a human picks one, which is not a search"),
    },
}

# Levers that change no RTL, so they need no specification permission. They are
# still RECORDED with their reason — an unjustified entry and a
# justified-by-construction entry must not look the same in the artefact.
_NO_DESIGN_CHANGE_LEVERS = ("synthesis_strategy",)

_FREEDOM_RE = re.compile("|".join(_FREEDOM_MARKERS), re.IGNORECASE)
_PINNING_RE = re.compile("|".join(_PINNING_MARKERS), re.IGNORECASE)
_BOUND_RE = re.compile("|".join(_BOUND_MARKERS), re.IGNORECASE)
_LEVER_RE = {k: re.compile("|".join(v), re.IGNORECASE)
             for k, v in _LEVER_KEYWORDS.items()}


# ---------------------------------------------------------------------------
# pure helpers — the tests drive these directly, no filesystem needed
# ---------------------------------------------------------------------------
#: The three status markers, by the name `marker_denials` reports them under.
_STATUS_MARKER_RE: Dict[str, "re.Pattern[str]"] = {
    "free": _FREEDOM_RE, "pin": _PINNING_RE, "bound": _BOUND_RE,
}


def _read_line(line: str) -> Tuple[Dict[str, Dict[str, object]],
                                   Dict[str, str]]:
    """Both halves of reading ONE line of spec text, in one pass:

        [0] `{lever: {"status": ..., "bound": int|None}}` — what it ASSERTS
        [1] `{"free"|"pin"|"bound": <denial word>}`       — which of its status
                                                            markers its own
                                                            sentence DENIES

    ONE function, two public views (`classify_line`, `marker_denials`), because
    the second decides the first. Computing them in two places is how one
    vocabulary becomes two — the divergence `_prose_polarity` exists to end.

    -- WHAT IT ASSERTS ------------------------------------------------------
    A line counts for a lever only when it carries BOTH a freedom / pin / bound
    marker AND a word that is about that lever. Requiring both is what stops a
    generic "the implementation may choose" sentence from authorising every
    lever in the design at once.

    Precedence on a single line is PIN > BOUND > FREE, because a sentence that
    both frees a structure and puts a ceiling on it has done the more specific
    thing, and a sentence that fixes a value has overridden both.

    -- WHAT ITS SENTENCE DENIES (vibe-ic#712) -------------------------------
    EVERY STATUS MARKER ON THE LINE IS BLANKED BEFORE THE CONSULT — not just
    the one being judged — and that is the whole subtlety of doing this here.
    Half this file's vocabulary is negative BY CONSTRUCTION — `不指定`,
    `不超過`, `does not specify`, `not specified`, `no more than` — so a bare
    `is_denied(line)` would report every freedom and every ceiling sentence as
    denied and this program would admit no lever at all. That would be a call
    that ALWAYS fires, which is no better than the call that never fires
    `prose_polarity_consulted_check` warns about.

    Blanking only the marker under test is not enough either, and that failure
    is MEASURED, not hypothetical. On this file's own fixture

        - ❌ 不指定 pipeline 深度與精確 latency(僅上限 4096 cycles)

    the bound marker `上限` is clean, but the FREEDOM marker `不指定` three
    words earlier lends it a `不`, the ceiling is dropped, the line reads FREE
    and the 4096 cap disappears — caught by
    `test_measured_ceiling_is_BOUNDED_and_carries_its_number`. One
    vocabulary's built-in negation must not become another's denial. What is
    asked, therefore, is whether a denial sits OUTSIDE EVERY marker, inside the
    sentence the marker sits in: that is what turns "must be exactly 4 cycles"
    into "must NOT be exactly 4 cycles", and "at most 4096" into "there is NO
    upper bound".

    The reach is `_prose_polarity.sentence_scope` — the repo's single rule for
    how far a sentence reaches — applied to the line, so a line carrying two
    sentences does not let one lend its polarity to the other. No private scope
    rule is defined here; three private copies of one is how this class of
    divergence happened before.

    WHICH WAY A MISREAD COSTS, because it is not symmetric and a reader should
    not have to work it out. Suppressing a denied FREE or a denied BOUND
    removes permission, which is the direction this program already errs in
    ("Silence is not permission"). Suppressing a PIN removes a refusal, so a
    FALSE denial on a pin could admit a lever the spec fixed — but only where
    some OTHER line frees the same lever, i.e. only where the document already
    contradicts itself, and the admitted lever must still survive
    `crosslayer_rewrite_equivalence`. Against that stands the measured cost of
    NOT consulting: this file's own `_PINNING_MARKERS` comment records a modal
    read as a pin refusing "the very lever the document had explicitly freed",
    and a denied modal is that same defect with the denial spelled out.

    Every suppression is CITED, never silent: `scan_document` collects them and
    `main` publishes them as `polarity_refusals`. "No sentence said this" and
    "a sentence said it and was denied" are opposite findings.
    """
    # --- polarity: which markers this line's own sentence retracts ---------
    denied: Dict[str, str] = {}
    # Length-preserving, so the offsets `sentence_scope` returns for the
    # ORIGINAL line index this text unchanged.
    chars = list(line)
    for rx in _STATUS_MARKER_RE.values():
        for m in rx.finditer(line):
            for i in range(m.start(), m.end()):
                chars[i] = " "
    blanked = "".join(chars)
    for kind, rx in _STATUS_MARKER_RE.items():
        m = rx.search(line)
        if not m:
            continue
        lo, hi = _sentence_scope(line, m.start(), m.end())
        word = _is_denied(blanked[lo:hi])
        if word:
            denied[kind] = word

    # --- what is left standing --------------------------------------------
    out: Dict[str, Dict[str, object]] = {}
    free = bool(_FREEDOM_RE.search(line)) and "free" not in denied
    pin = (bool(_PINNING_RE.search(line))
           and bool(_CONCRETE_VALUE_RE.search(line)) and "pin" not in denied)
    bm = _BOUND_VALUE_RE.search(line)
    bound = int(bm.group(1)) if bm else None
    bounded = (bool(_BOUND_RE.search(line)) and bound is not None
               and "bound" not in denied)
    if not (free or pin or bounded):
        return out, denied
    for lever, rx in _LEVER_RE.items():
        if not rx.search(line):
            continue
        if pin:
            out[lever] = {"status": STATUS_PINNED, "bound": None}
        elif bounded:
            out[lever] = {"status": STATUS_BOUNDED, "bound": bound}
        else:
            out[lever] = {"status": STATUS_FREE, "bound": None}
    return out, denied


def classify_line(line: str) -> Dict[str, Dict[str, object]]:
    """`{lever: {"status": ..., "bound": int|None}}` for one line of spec text.

    A marker its own sentence DENIES asserts nothing; see `_read_line`, which
    is where both this answer and that judgement are computed."""
    return _read_line(line)[0]


def marker_denials(line: str) -> Dict[str, str]:
    """`{"free"|"pin"|"bound": <the denial word>}` for every status marker on
    this line whose OWN SENTENCE denies it. See `_read_line`."""
    return _read_line(line)[1]


def scan_document(text: str, rel_path: str,
                  refusals: Optional[List[Dict[str, object]]] = None
                  ) -> List[Dict[str, object]]:
    """Every (lever, status, citation) this document supports.

    `refusals`, when given, also collects every line whose status marker its own
    sentence DENIES, with the same citation shape. A suppressed statement that
    left no trace would be indistinguishable from a document that never made it
    — the silent direction `_prose_polarity` names — so the caller publishes
    these next to the space it emitted."""
    hits: List[Dict[str, object]] = []
    for n, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if refusals is not None:
            for kind, word in sorted(marker_denials(stripped).items()):
                # Only a marker that would OTHERWISE have said something is a
                # refusal worth publishing: a lever-less line asserts nothing
                # either way and would flood the record.
                if not any(rx.search(stripped) for rx in _LEVER_RE.values()):
                    continue
                refusals.append({
                    "marker": kind, "denial": word,
                    "path": rel_path, "line": n,
                    "literal": stripped[:300]})
        for lever, info in classify_line(stripped).items():
            hits.append({"lever": lever, "status": info["status"],
                         "bound": info["bound"],
                         "path": rel_path, "line": n,
                         "literal": stripped[:300]})
    return hits


def resolve_levers(hits: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    """Fold the per-line hits into one verdict per lever.

    Precedence across a whole document set is PINNED > BOUNDED > FREE. The
    asymmetry is deliberate: a document that fixes a structure in one paragraph
    and waves at freedom in another has NOT authorised a search, and resolving
    that tie the other way is how a search turns into a redesign. A ceiling
    likewise survives a freedom sentence elsewhere — it is the tighter of the
    two statements and the candidate still has to meet it."""
    rank = {STATUS_FREE: 0, STATUS_BOUNDED: 1, STATUS_PINNED: 2}
    verdict: Dict[str, Dict[str, object]] = {}
    for h in hits:
        lever = str(h["lever"])
        cur = verdict.get(lever)
        if cur is None:
            verdict[lever] = {"status": h["status"], "bound": h.get("bound"),
                              "citations": [h]}
            continue
        if rank[str(h["status"])] > rank[str(cur["status"])]:
            verdict[lever] = {"status": h["status"], "bound": h.get("bound"),
                              "citations": [h]}
        elif h["status"] == cur["status"]:
            cur["citations"].append(h)          # type: ignore[union-attr]
            if cur.get("bound") is None:
                cur["bound"] = h.get("bound")
            elif h.get("bound") is not None:
                # the TIGHTEST declared ceiling is the one that binds
                cur["bound"] = min(int(cur["bound"]), int(h["bound"]))
    return verdict


def build_space(verdict: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    """The search space: one entry per lever, admitted or refused, with why."""
    levers: List[Dict[str, object]] = []
    for lever, meta in sorted(_LEVER_DOMAIN.items()):
        if lever in _NO_DESIGN_CHANGE_LEVERS:
            levers.append({
                "lever": lever, "admitted": True,
                "status": STATUS_NO_DESIGN_CHANGE,
                "justification_kind": KIND_NO_DESIGN_CHANGE,
                "justification": (
                    "this lever re-maps the same RTL and changes no design "
                    "behaviour, so no specification permission is required "
                    "and none is claimed"),
                "citations": [], **meta})
            continue
        v = verdict.get(lever)
        if v is None:
            levers.append({
                "lever": lever, "admitted": False,
                "status": STATUS_UNDECLARED,
                "justification_kind": None,
                "justification": (
                    "no sentence in the design's own input documents leaves "
                    "this structure to the implementation. Silence is not "
                    "permission, so this lever is NOT searched."),
                "citations": [], **meta})
            continue
        if v["status"] == STATUS_BOUNDED:
            levers.append({
                "lever": lever, "admitted": True,
                "status": STATUS_BOUNDED,
                "justification_kind": KIND_SPEC_SENTENCE,
                "bound": v.get("bound"),
                "justification": (
                    "the specification leaves this structure to the "
                    "implementation but declares a ceiling; the lever is "
                    "searchable and every candidate must also meet the "
                    "ceiling quoted below."),
                "citations": v["citations"], **meta})
            continue
        if v["status"] == STATUS_PINNED:
            levers.append({
                "lever": lever, "admitted": False,
                "status": STATUS_PINNED,
                "justification_kind": KIND_SPEC_SENTENCE,
                "justification": (
                    "the specification PINS this structure; it is a "
                    "requirement, not a search dimension."),
                "citations": v["citations"], **meta})
            continue
        levers.append({
            "lever": lever, "admitted": True,
            "status": STATUS_FREE,
            "justification_kind": KIND_SPEC_SENTENCE,
            "justification": (
                "the design's own input documents leave this structure to the "
                "implementation; the sentence is cited below."),
            "citations": v["citations"], **meta})
    admitted = [l for l in levers if l["admitted"]]
    return {
        "program": PROGRAM,
        "levers": levers,
        "admitted_count": len(admitted),
        "refused_count": len(levers) - len(admitted),
        "admitted_levers": [l["lever"] for l in admitted],
        **_pnr_exclusion(),
    }


# ---------------------------------------------------------------------------
# the PnR levers this program withholds -- and WHO owns them, MEASURED
# ---------------------------------------------------------------------------
#: The program that emits the place-and-route space. Named once.
PNR_OWNER = "ppa_pnr_search_space.py"

#: The names withheld when the owner cannot be asked. This list is a FALLBACK,
#: not the source of truth: when the owner is present its own lever table is
#: used, so the two cannot drift apart in the direction that matters (a lever
#: named here that the owner never emits is a lever no program owns).
_PNR_LEVERS_FALLBACK = (
    "core_utilisation", "core_aspect_ratio", "cell_padding",
    "placement_density", "cts_cluster_size", "cts_cluster_diameter",
    "routing_layer_adjust", "clock_period")


def _pnr_exclusion() -> Dict[str, object]:
    """Which PnR levers are withheld, and the reason -- CHECKED as it is written.

    THE DEFECT THIS REPLACES. This program used to publish, as the reason for
    withholding eight levers:

        "these are the place-and-route knobs the PnR-only search already owns"

    and MEASURED on the tree that shipped it, there was no PnR-only search: no
    program emitted a space containing those levers, so the sentence named an
    owner that did not exist and a reader who went looking found nothing. That
    is the same failure as a stub excuse that outlives its cause -- a sentence
    about another program, published as a fact, never checked.

    So the owner is looked for at the moment the sentence is written. If it is
    there its own lever names are used and the reason cites it; if it is not,
    the reason SAYS the levers are unowned rather than claiming an owner.

    AND DELEGATION IS NOT UNCONDITIONAL, WHICH THE SENTENCE ALSO HAS TO SAY.
    One of the delegated knobs -- the design-for-ECO spare-cell density -- is
    admitted by its owner only BOUNDED BELOW once a design declares a spare/ECO
    requirement, because setting it to zero deletes the cells that make a bug
    found after tape-out fixable by a metal-only ECO instead of a base-layer
    respin. A handoff row that lists it beside ten unconditional knobs reads as
    "freely searchable, elsewhere", and a reader who follows that record into
    the owner without a declaration or a `--project` gets exactly the unbounded
    lever this campaign closed. So the levers carrying a precondition are named
    SEPARATELY, and -- like the owner's name and the lever names -- they are
    MEASURED from the owner's own table (`eco_bounded`) rather than re-typed
    here. A list re-typed here is a list that stops being true the first time
    the owner adds a twelfth lever.
    """
    owner = Path(__file__).resolve().parent / PNR_OWNER
    if not owner.is_file():
        return {
            "pnr_levers_excluded_on_purpose": list(_PNR_LEVERS_FALLBACK),
            "pnr_owner": None,
            "pnr_exclusion_reason": (
                f"these place-and-route knobs are not searched here, and "
                f"{PNR_OWNER} is NOT present on this tree, so no program "
                f"emits a space containing them. They are UNOWNED, not "
                f"delegated — checked when this sentence was written."),
        }
    conditional: List[str] = []
    try:
        sys.path.insert(0, str(owner.parent))
        import ppa_pnr_search_space as _pnr             # noqa: WPS433
        names = sorted(str(l["lever"]) for l in _pnr.LEVERS)
        conditional = sorted(str(l["lever"]) for l in _pnr.LEVERS
                             if l.get("eco_bounded"))
    except Exception:                                   # pragma: no cover
        names = sorted(_PNR_LEVERS_FALLBACK)
    row: Dict[str, object] = {
        "pnr_levers_excluded_on_purpose": names,
        "pnr_owner": PNR_OWNER,
        "pnr_levers_delegated_with_a_precondition": conditional,
        "pnr_exclusion_reason": (
            f"these are the place-and-route knobs {PNR_OWNER} owns and emits "
            f"a space for; a cross-layer arm that also moved them would not "
            f"be measuring the cross-layer contribution. The owner was "
            f"checked for, and its own lever names are the ones listed."),
    }
    if conditional:
        row["pnr_precondition_reason"] = (
            f"{conditional} is delegated but NOT unconditionally. Spare/ECO "
            "cells are what make a bug found after tape-out fixable by a "
            "metal-only ECO instead of a base-layer respin, so setting this "
            f"knob to zero removes a property a tape-out-bound design is "
            f"required to have. {PNR_OWNER} therefore admits it only BOUNDED "
            "BELOW once a design declares a design-for-ECO requirement, and "
            "refuses to publish a space at all for a design the flow routed to "
            "a chip terminal with no such declaration. Driving that owner "
            "without `--eco-declaration` or `--project` is what produced a "
            "published candidate that had deleted every spare/ECO cell in the "
            "design. Read from the owner's own lever table, not re-typed here.")
    return row


def audit_space(space: Dict[str, object]) -> List[str]:
    """Every way an emitted space could be dishonest. Empty list = clean.

    This is the self-check that makes the program's own output falsifiable: an
    admitted lever with no justification is precisely the defect the whole file
    exists to prevent, so it is asserted rather than trusted."""
    problems: List[str] = []
    levers = space.get("levers")
    if not isinstance(levers, list):
        return ["the space carries no `levers` list — nothing to audit."]
    for l in levers:
        name = l.get("lever", "<unnamed>")
        if not l.get("admitted"):
            continue
        kind = l.get("justification_kind")
        if kind == KIND_NO_DESIGN_CHANGE:
            if name not in _NO_DESIGN_CHANGE_LEVERS:
                problems.append(
                    f"{name}: claims `no_design_change` but it is not one of "
                    f"the levers that leave the RTL untouched.")
            continue
        if kind != KIND_SPEC_SENTENCE:
            problems.append(
                f"{name}: admitted with justification_kind={kind!r}; an "
                f"admitted lever must be justified by a cited specification "
                f"sentence or by leaving the design untouched.")
            continue
        cites = l.get("citations") or []
        if not cites:
            problems.append(
                f"{name}: admitted as {STATUS_FREE} with ZERO citations. A "
                f"lever nobody can point at is a lever nobody authorised.")
            continue
        for c in cites:
            if not all(k in c for k in ("path", "line", "literal")):
                problems.append(
                    f"{name}: a citation is missing path/line/literal, so a "
                    f"reader cannot go and check it.")
    return problems


def _iter_docs(project: Path, docs_dirs: List[str]) -> List[Tuple[str, Path]]:
    found: List[Tuple[str, Path]] = []
    seen = set()
    for d in docs_dirs:
        base = project / d
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if f.is_file() and f.suffix.lower() in DOC_SUFFIXES:
                rel = str(f.relative_to(project))
                if rel not in seen:
                    seen.add(rel)
                    found.append((rel, f))
    return found


def _write(project: Path, rel: str, payload: Dict) -> Path:
    out = project / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit the cross-layer PPA search space, with the "
                    "specification citation that authorises every lever.")
    ap.add_argument("project_dir")
    ap.add_argument("--docs-dir", action="append", default=None,
                    help="Directory of the design's own input documents "
                         "(repeatable). Defaults to the flow's staging dirs.")
    ap.add_argument("--json", default=DEFAULT_JSON_REL)
    ap.add_argument("--require-nonempty", action="store_true",
                    help="Exit 1 when the specification admits no lever. Off "
                         "by default: a design that pins everything is a real "
                         "finding, not an error.")
    ap.add_argument("--verify", default=None,
                    help="Audit an existing space JSON instead of emitting "
                         "one, and re-resolve every citation against the "
                         "files on disk.")
    args = ap.parse_args(argv)
    project = Path(args.project_dir).resolve()

    if args.verify:
        vp = Path(args.verify)
        if not vp.is_absolute():
            vp = project / vp
        if not vp.is_file():
            print(f"[{PROGRAM}] NOT_MEASURED: {vp} does not exist — an audit "
                  f"that cannot read its subject is not a clean audit.",
                  file=sys.stderr)
            return 2
        try:
            space = json.loads(vp.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            print(f"[{PROGRAM}] NOT_MEASURED: {vp} is unreadable: {exc}",
                  file=sys.stderr)
            return 2
        problems = audit_space(space)
        for l in space.get("levers", []):
            if not l.get("admitted"):
                continue
            for c in l.get("citations") or []:
                f = project / str(c.get("path", ""))
                if not f.is_file():
                    problems.append(
                        f"{l.get('lever')}: citation {c.get('path')}:"
                        f"{c.get('line')} does not resolve from {project}.")
                    continue
                lines = f.read_text(encoding="utf-8",
                                    errors="replace").splitlines()
                i = int(c.get("line", 0)) - 1
                if i < 0 or i >= len(lines):
                    problems.append(
                        f"{l.get('lever')}: citation {c.get('path')}:"
                        f"{c.get('line')} is past the end of the file.")
                elif lines[i].strip()[:300] != str(c.get("literal", "")):
                    problems.append(
                        f"{l.get('lever')}: citation {c.get('path')}:"
                        f"{c.get('line')} no longer says what was quoted.")
        for p in problems:
            print(f"[{PROGRAM}] REFUSED: {p}", file=sys.stderr)
        print(f"[{PROGRAM}] audit: {len(problems)} problem(s)")
        return 1 if problems else 0

    docs_dirs = args.docs_dir or list(DEFAULT_DOC_DIRS)
    docs = _iter_docs(project, docs_dirs)
    if not docs:
        payload = {
            "program": PROGRAM, "status": "NOT_MEASURED",
            "searched_dirs": docs_dirs,
            "explanation": (
                "no readable input document was found under any of the "
                "searched directories, so NOTHING was decided about any "
                "lever. This is not an empty search space — an empty space "
                "would mean the documents were read and pinned everything."),
        }
        _write(project, args.json, payload)
        print(f"[{PROGRAM}] NOT_MEASURED: no input document under "
              f"{docs_dirs}", file=sys.stderr)
        return 2

    hits: List[Dict[str, object]] = []
    refusals: List[Dict[str, object]] = []
    for rel, f in docs:
        try:
            hits.extend(scan_document(
                f.read_text(encoding="utf-8", errors="replace"), rel,
                refusals))
        except OSError as exc:
            print(f"[{PROGRAM}] warning: {rel} unreadable: {exc}",
                  file=sys.stderr)
    space = build_space(resolve_levers(hits))
    space["status"] = "MEASURED"
    space["documents_read"] = [rel for rel, _ in docs]
    # vibe-ic#712: a statement READ AND REFUSED on polarity is a finding, and a
    # different one from a statement never made. It is published rather than
    # dropped so a reader can see which sentences were retracted and by which
    # word, and go and look at the line.
    space["polarity_refusals"] = refusals
    problems = audit_space(space)
    space["self_audit_problems"] = problems
    p = _write(project, args.json, space)

    print(f"[{PROGRAM}] admitted {space['admitted_count']} lever(s): "
          f"{', '.join(space['admitted_levers']) or '(none)'}")
    for l in space["levers"]:
        if not l["admitted"]:
            print(f"[{PROGRAM}]   REFUSED {l['lever']}: {l['status']}")
    for r in refusals:
        print(f"[{PROGRAM}]   POLARITY {r['path']}:{r['line']} — "
              f"'{r['denial']}' denies the {r['marker']} marker, so this "
              f"sentence asserts nothing")
    print(f"[{PROGRAM}] report: {p}")
    if problems:
        for pr in problems:
            print(f"[{PROGRAM}] SELF-AUDIT FAILED: {pr}", file=sys.stderr)
        return 1
    if args.require_nonempty and space["admitted_count"] == 0:
        print(f"[{PROGRAM}] refused: the specification admits no lever.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":                          # pragma: no cover
    raise SystemExit(main())
