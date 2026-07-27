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
A bare vocabulary hit is not a requirement. ``_has_requirement_framing``
applies the same context-window discipline as
``l8_clock_domains_typed_check._is_real_clock_freq``: a match only
counts when a requirement/goal word appears within N characters. This
is what keeps "the upstream project already hit 90% coverage" (a status
report about somebody else's work) from being read as "this design
requires 90% coverage".

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
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "generated_docs_dir",
    "load_l_doc",
    "l_doc_fields",
    "applicability_of",
    "is_extraction_claimed",
    "input_doc_texts",
    "sibling_l_doc_texts",
    "framed_hits",
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
            out.append((path, json.dumps(doc, ensure_ascii=False)))
        except Exception:
            continue
    return out


# ─────────────────────────────────────────────────────────────────────
# Requirement framing
# ─────────────────────────────────────────────────────────────────────

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


def _hit_line(text: str, offsets: List[int], m: "re.Match") -> str:
    """The ORIGINAL line the match sits on.

    Taken from the raw text rather than the normalised copy, because
    normalisation collapses newlines and a disclaimer must be scoped to the row
    that carries it.
    """
    start = offsets[m.start()] if m.start() < len(offsets) else 0
    end = offsets[m.end() - 1] if 0 < m.end() <= len(offsets) else start
    lo = text.rfind("\n", 0, start) + 1
    hi = text.find("\n", end)
    return text[lo:] if hi == -1 else text[lo:hi]


def framed_hits(texts: Iterable[Tuple[Path, str]],
                vocab_re: re.Pattern,
                window: int = 160,
                limit: int = 12) -> List[Dict[str, Any]]:
    """Vocabulary matches that carry requirement framing nearby.

    Mirrors ``l8_clock_domains_typed_check._is_real_clock_freq``: a raw
    vocabulary hit is noise; a hit inside a ±``window``-char neighbourhood
    of a requirement word is a stated requirement.

    Matching runs on the whitespace-normalised text so hard-wrapped
    requirements are found, and results are deduplicated by context so
    the same sentence shipped as both ``phase1/input_doc/x.txt`` and
    ``input/docs/x.rst`` is counted once — an honest evidence count, not
    a copy count. Returns at most ``limit`` records so gate stdout stays
    reviewable.
    """
    out: List[Dict[str, Any]] = []
    seen_ctx: set = set()
    for path, text in texts:
        norm, offsets = _normalize_ws(text)
        for m in vocab_re.finditer(norm):
            lo = max(0, m.start() - window)
            hi = min(len(norm), m.end() + window)
            ctx = norm[lo:hi]
            if not REQUIREMENT_FRAMING_RE.search(ctx):
                continue
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
            if _NON_NORMATIVE_RE.search(_hit_line(text, offsets, m)):
                continue          # the document itself says it is not a requirement
            key = ctx.strip()
            if key in seen_ctx:
                continue
            seen_ctx.add(key)
            orig_start = offsets[m.start()] if m.start() < len(offsets) else 0
            line_no = text.count("\n", 0, orig_start) + 1
            out.append({
                "source": str(path),
                "line": line_no,
                "match": m.group(0).strip()[:120],
                "context": ctx.strip()[:220],
            })
            if len(out) >= limit:
                return out
    return out


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
