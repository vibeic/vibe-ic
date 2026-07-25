#!/usr/bin/env python3
"""l_doc_evidence_util.py — the "evidence path + read-back value" primitive.

WHY THIS MODULE EXISTS
======================
The motivating defect (2026-07): the global completeness check modelled a
layer as complete when a token appeared in ANY layer. A hard macro's supply
pin was present in L1_DATASHEET (7x) and L2_FRS (8x), so the check said
CAPTURED — while L21_POWER_INTENT, the layer the BACKEND actually consumes,
contained it 0 times. The PDN was built with no rail, synthesis tied the pin
off, a SIGNAL net landed on a POWER terminal and TritonRoute aborted the whole
detailed route. 3278 nets, 0 routed, discovered five steps downstream.

The principle every gate built on this module embodies:

    A layer is complete when the requirement is present IN THE LAYER THAT
    CONSUMES IT, in an ACTIONABLE form — not when a token appears somewhere.

The corollary this module implements is the *verdict* half of that principle:

    A status/verdict/margin a layer ASSERTS is only real when it traces to an
    evidence path — a file that exists in this project — AND to a value that
    can still be READ BACK out of that file. A verdict with no evidence path,
    or an evidence path with no read-back value, is a false certificate.

Everything here is chip-AGNOSTIC and design-AGNOSTIC: no design name, no PDK
name, no vendor part number, no pin/signal literal. Claims are discovered from
the layer's OWN key names and bound to the layer's OWN evidence records.

Pure-function module; the only I/O is reading files the caller already
resolved inside the project root.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "NO_INFORMATION_TOKENS",
    "is_no_information",
    "is_populated",
    "load_json",
    "find_layer_files",
    "generated_docs_roots",
    "resolve_under_project",
    "value_readable_in_file",
    "iter_evidence_records",
    "evidence_for_subject",
    "EvidenceVerdict",
    "verify_evidence_binding",
    "has_number_with_unit",
    "extract_numbers",
]


# ---------------------------------------------------------------------------
# "No information" vocabulary.
#
# Deliberately ONLY the no-information side is enumerated — never the positive
# verdict side. Enumerating positive verdicts ("PASS", "CLEAN", "SIGNED_OFF")
# would be a whitelist that a novel verdict string silently escapes. Treating
# everything that is NOT a declared absence of information as a CLAIM is the
# fail-closed direction: a new verdict word is caught, not waved through.
#
# These are flow-state words, not design/vendor/PDK tokens.
# ---------------------------------------------------------------------------
NO_INFORMATION_TOKENS = frozenset({
    "", "-", "--", "?", "n/a", "na", "n.a.", "none", "null", "nil",
    "tbd", "tba", "todo", "unknown", "unspecified", "unset",
    "pending", "not_run", "not-run", "not run", "notrun",
    "not_yet_extracted", "not-yet-extracted", "not yet extracted",
    "not_applicable", "not-applicable", "not applicable",
    "not_extracted", "not-extracted", "not extracted",
    "empty", "placeholder",
})


def is_no_information(value: Any) -> bool:
    """True when `value` declares an ABSENCE of information rather than a
    claim. None / empty containers / a no-information token all qualify."""
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return False
    if isinstance(value, str):
        return value.strip().lower() in NO_INFORMATION_TOKENS
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def is_populated(value: Any) -> bool:
    """Inverse of `is_no_information` — the value carries a claim."""
    return not is_no_information(value)


def load_json(path: Path) -> Optional[Any]:
    """Read a JSON file, returning None on any read/parse failure."""
    try:
        return json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None


def find_layer_files(project: Path, stem: str) -> List[Path]:
    """Locate every instance of the L-doc `stem` (e.g. "L24_SIGNOFF") under
    `project`.

    Covers the flat layout (`phase1/generated_docs/<stem>.json`) and the SoC
    per-sub-block layout (`phase1/generated_docs/<block>/<stem>.json`), plus
    any non-canonical `generated_docs` root. Deterministically ordered.
    """
    seen: Dict[str, Path] = {}

    def _collect(patterns) -> None:
        for pat in patterns:
            try:
                hits = project.glob(pat)
            except (OSError, ValueError):
                continue
            for hit in hits:
                if hit.is_file():
                    seen.setdefault(str(hit.resolve()), hit)

    # Canonical layout first. A full post-phase-3 project tree can hold
    # 100k+ files, and this gate runs under a 60s subprocess budget — so the
    # recursive fallback only runs when the canonical location came up empty.
    _collect((f"phase1/generated_docs/{stem}.json",
              f"phase1/generated_docs/*/{stem}.json"))
    if not seen:
        _collect((f"*/generated_docs/{stem}.json",
                  f"*/generated_docs/*/{stem}.json",
                  f"**/generated_docs/{stem}.json",
                  f"**/generated_docs/*/{stem}.json"))
    return [seen[k] for k in sorted(seen)]


def generated_docs_roots(project: Path) -> List[Path]:
    """Every `generated_docs` directory in the project, canonical-first.

    Same 60s-budget reasoning as `find_layer_files`: the recursive glob is a
    fallback, not the default path.
    """
    roots: List[Path] = []
    canonical = project / "phase1" / "generated_docs"
    if canonical.is_dir():
        roots.append(canonical.resolve())
        for sub in sorted(canonical.iterdir()):
            if sub.is_dir():
                roots.append(sub.resolve())
        return roots
    seen = set()
    try:
        for d in project.glob("**/generated_docs"):
            if d.is_dir():
                r = d.resolve()
                if r not in seen:
                    seen.add(r)
                    roots.append(r)
    except (OSError, ValueError):
        pass
    return roots


# ---------------------------------------------------------------------------
# Evidence-path resolution
# ---------------------------------------------------------------------------
_MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
_MAX_BASENAME_SCAN = 20000


def resolve_under_project(project: Path, raw: str) -> Optional[Path]:
    """Resolve an evidence path string to an EXISTING file inside `project`.

    An evidence path that escapes the project root is refused (returns None):
    a certificate whose proof lives outside the run is not reproducible
    evidence. Tries, in order: project-relative, project/phase1-relative,
    absolute-but-inside-project, then a basename search inside the project.
    """
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None
    # Evidence records in this codebase are sometimes keyed
    # "<path>:<line>" or "<path>#<anchor>" — strip a trailing locator.
    base = re.sub(r"[:#]\d+(?:-\d+)?$", "", raw)

    try:
        proj = project.resolve()
    except OSError:
        return None

    candidates: List[Path] = [
        proj / base,
        proj / "phase1" / base,
    ]
    p = Path(base)
    if p.is_absolute():
        candidates.append(p)

    for cand in candidates:
        try:
            r = cand.resolve()
        except OSError:
            continue
        if not r.is_file():
            continue
        try:
            r.relative_to(proj)
        except ValueError:
            continue  # outside the project → not reproducible evidence
        return r

    # Last resort: a bare basename recorded without its directory. Bounded —
    # this walks the whole project tree, and the gate runs under a 60s
    # subprocess budget on trees that can hold 100k+ files.
    name = Path(base).name
    if name and name != base:
        return None
    if not name or "*" in name or "?" in name:
        return None
    try:
        for i, hit in enumerate(proj.glob(f"**/{name}")):
            if i >= _MAX_BASENAME_SCAN:
                break
            if hit.is_file():
                return hit.resolve()
    except (OSError, ValueError):
        pass
    return None


def _numeric_variants(value: Any) -> List[str]:
    """String forms a number could plausibly appear as in a report."""
    out: List[str] = []
    s = str(value).strip()
    if s:
        out.append(s)
    try:
        f = float(s)
    except (TypeError, ValueError):
        return out
    if f.is_integer():
        out.append(str(int(f)))
        out.append(f"{int(f)}.0")
    out.append(f"{f:g}")
    out.append(repr(f))
    # de-dup, preserve order
    seen, uniq = set(), []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def value_readable_in_file(path: Path, value: Any) -> bool:
    """True when `value` can still be READ BACK out of `path`.

    This is the half of the contract that a bare "I looked at report X" claim
    cannot satisfy: the layer must name the number/string it took from the
    report, and that token must still be findable there. If the report changes
    and the number no longer appears, the certificate stops validating —
    which is precisely the point.
    """
    if is_no_information(value):
        return False
    try:
        if path.stat().st_size > _MAX_EVIDENCE_BYTES:
            return False
        text = path.read_text(errors="replace")
    except OSError:
        return False
    low = text.lower()
    for variant in _numeric_variants(value):
        v = variant.strip().lower()
        if not v:
            continue
        if v in low:
            return True
    return False


# ---------------------------------------------------------------------------
# Evidence-record iteration
# ---------------------------------------------------------------------------
# Evidence appears in two shapes in this codebase, both handled here:
#
#   (A) the phase-1 extraction_evidence map — {"<source path>": [{"literal":
#       "...", "label": "..."}]}. The key is the path; `literal` is the
#       read-back value.
#   (B) an inline sibling binding — {"drc_status": "...", "drc_evidence":
#       {"report": "<path>", "value": <number>}}.
#
# Both reduce to the same triple: (subject, path, read-back value).
# ---------------------------------------------------------------------------
_PATH_KEYS = ("report", "report_path", "path", "file", "source",
              "source_file", "source_report", "evidence_path", "from",
              "artifact")
_VALUE_KEYS = ("value", "literal", "read_value", "measured", "count",
               "number", "quote", "text", "metric_value", "violations")
_LABEL_KEYS = ("label", "metric", "subject", "field", "gate", "name",
               "description")


def _as_records(node: Any) -> List[Dict[str, Any]]:
    if isinstance(node, dict):
        return [node]
    if isinstance(node, (list, tuple)):
        return [x for x in node if isinstance(x, dict)]
    return []


def iter_evidence_records(
    doc: Dict[str, Any],
    container: Any,
) -> List[Tuple[str, Any, str]]:
    """Flatten an evidence container into `(path_hint, value, label)` triples.

    `container` may be the shape-(A) map, the shape-(B) dict, a list of
    either, or a bare path string. Never raises.
    """
    out: List[Tuple[str, Any, str]] = []

    def _from_record(rec: Dict[str, Any], path_hint: str) -> None:
        p = path_hint
        for k in _PATH_KEYS:
            v = rec.get(k)
            if isinstance(v, str) and v.strip():
                p = v.strip()
                break
        val: Any = None
        for k in _VALUE_KEYS:
            if k in rec and is_populated(rec.get(k)):
                val = rec.get(k)
                break
        label_bits: List[str] = []
        for k in _LABEL_KEYS:
            v = rec.get(k)
            if isinstance(v, str) and v.strip():
                label_bits.append(v.strip())
        out.append((p, val, " ".join(label_bits)))

    if isinstance(container, str):
        out.append((container, None, ""))
        return out
    if isinstance(container, list):
        for item in container:
            if isinstance(item, dict):
                _from_record(item, "")
            elif isinstance(item, str):
                out.append((item, None, ""))
        return out
    if isinstance(container, dict):
        # Shape (A): keys are source paths mapping to record lists.
        looks_like_path_map = any(
            isinstance(k, str) and ("/" in k or "\\" in k or "." in k)
            and isinstance(v, (list, dict))
            for k, v in container.items()
        )
        if looks_like_path_map:
            for k, v in container.items():
                recs = _as_records(v)
                if recs:
                    for rec in recs:
                        _from_record(rec, str(k))
                else:
                    out.append((str(k), v if is_populated(v) else None, ""))
            return out
        # Shape (B): a single inline binding record.
        _from_record(container, "")
    return out


def evidence_for_subject(
    doc: Dict[str, Any],
    subject: str,
    local_scope: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, Any, str]]:
    """Collect the evidence triples BOUND to `subject`.

    `subject` is the claim's own base name, derived from the layer's key
    (e.g. key ``drc_status`` → subject ``drc``). Binding matters: an evidence
    record proving DRC is not evidence for LVS. A triple counts for `subject`
    only when the subject token appears in the record's path hint, its label,
    or the sibling key it was found under.

    Sources searched, in order:
      1. sibling keys in the claim's own dict named for the subject
         (``<subject>_evidence`` / ``<subject>_report`` / ``evidence`` ...)
      2. the doc-level ``extraction_evidence`` map
      3. a doc-level ``evidence`` / ``evidence_paths`` container
    """
    subj = (subject or "").strip().lower()
    triples: List[Tuple[str, Any, str]] = []
    # Word-ish boundary, so a two-letter subject like "em" binds to
    # "em_budget" / "reports/em.rpt" but NOT to "temperature" or "system".
    # A loose substring match would let unrelated evidence validate a claim,
    # which is the same "a token appears somewhere" fallacy this batch exists
    # to kill.
    subj_re = (re.compile(r"(?<![a-z0-9])" + re.escape(subj) + r"(?![a-z0-9])")
               if subj else None)

    def _subject_bound(path_hint: str, label: str, key_hint: str) -> bool:
        if subj_re is None:
            return True
        hay = f"{path_hint} {label} {key_hint}".lower()
        return bool(subj_re.search(hay))

    # (1) sibling keys in the claim's own scope
    if isinstance(local_scope, dict):
        for k, v in local_scope.items():
            if not isinstance(k, str) or is_no_information(v):
                continue
            kl = k.lower()
            is_evidence_key = (
                "evidence" in kl or "report" in kl or "proof" in kl
                or kl.endswith("_source") or kl.endswith("_path")
            )
            if not is_evidence_key:
                continue
            for (p, val, lab) in iter_evidence_records(doc, v):
                if _subject_bound(p, lab, k):
                    triples.append((p, val, lab or k))

    # (2)/(3) doc-level evidence containers
    for container_key in ("extraction_evidence", "evidence", "evidence_paths"):
        container = doc.get(container_key)
        if is_no_information(container):
            continue
        for (p, val, lab) in iter_evidence_records(doc, container):
            if _subject_bound(p, lab, container_key):
                triples.append((p, val, lab))

    return triples


class EvidenceVerdict:
    """Outcome of verifying one claim's evidence binding."""

    OK = "ok"
    NO_EVIDENCE = "no_evidence"
    PATH_UNRESOLVED = "path_unresolved"
    NO_READBACK_VALUE = "no_readback_value"
    VALUE_NOT_IN_FILE = "value_not_in_file"

    def __init__(self, status: str, detail: str) -> None:
        self.status = status
        self.detail = detail

    @property
    def ok(self) -> bool:
        return self.status == self.OK

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"EvidenceVerdict({self.status!r}, {self.detail!r})"


def verify_evidence_binding(
    project: Path,
    doc: Dict[str, Any],
    subject: str,
    local_scope: Optional[Dict[str, Any]] = None,
) -> EvidenceVerdict:
    """Verify that `subject`'s claim traces to a resolvable evidence path AND
    a value that can still be read back out of it.

    Returns the FIRST failing reason when nothing validates, so the caller can
    report precisely which half of the contract is missing — the four failure
    modes are deliberately distinguished because they demand different fixes.
    """
    triples = evidence_for_subject(doc, subject, local_scope)
    if not triples:
        return EvidenceVerdict(
            EvidenceVerdict.NO_EVIDENCE,
            f"no evidence record bound to '{subject}'")

    worst = EvidenceVerdict(
        EvidenceVerdict.NO_EVIDENCE,
        f"no evidence record bound to '{subject}'")
    saw_path = False
    saw_resolved: Optional[Path] = None
    for (path_hint, value, _label) in triples:
        resolved = resolve_under_project(project, path_hint) if path_hint else None
        if path_hint:
            saw_path = True
        if resolved is None:
            if path_hint and worst.status == EvidenceVerdict.NO_EVIDENCE:
                worst = EvidenceVerdict(
                    EvidenceVerdict.PATH_UNRESOLVED,
                    f"'{subject}' cites evidence path {path_hint!r} which does "
                    f"not resolve to a file inside the project")
            continue
        saw_resolved = resolved
        if is_no_information(value):
            worst = EvidenceVerdict(
                EvidenceVerdict.NO_READBACK_VALUE,
                f"'{subject}' cites {path_hint!r} but records no read-back "
                f"value — 'I looked at the report' is not evidence of WHAT "
                f"was read")
            continue
        if value_readable_in_file(resolved, value):
            return EvidenceVerdict(
                EvidenceVerdict.OK,
                f"'{subject}' ← {path_hint} (read-back {value!r} verified)")
        worst = EvidenceVerdict(
            EvidenceVerdict.VALUE_NOT_IN_FILE,
            f"'{subject}' claims read-back {value!r} from {path_hint!r} but "
            f"that value does not occur in the file")
    if not saw_path and saw_resolved is None:
        return EvidenceVerdict(
            EvidenceVerdict.NO_EVIDENCE,
            f"'{subject}' has evidence records but none names a path")
    return worst


# ---------------------------------------------------------------------------
# Actionability primitives
# ---------------------------------------------------------------------------
# A number alone is not actionable ("aging margin: 10" — ten what?). A unit
# alone is not actionable either. The pair is. The unit pattern below is
# generic (letters / % / ° / µ / Ω / slashes / carets), NOT an enumeration of
# particular units, so it stays design- and domain-agnostic.
_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_NUM_UNIT_RE = re.compile(
    r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?[ \t]*"
    r"(%|°[A-Za-z]?|[A-Za-zµμΩ][A-Za-zµμΩ0-9/·^\-]*)"
)

# English function words that can FOLLOW a number in prose without being a
# unit. Without this, "-40 to 125" reads as "40 <unit 'to'>" and a bounds
# string with no unit at all is accepted as actionable — caught by this
# module's own negative-control test. This is general-language vocabulary,
# never a design/PDK/vendor token, and it is an EXCLUSION list rather than a
# whitelist of units, so a novel or exotic unit is still accepted.
_NON_UNIT_WORDS = frozenset({
    "to", "and", "or", "of", "in", "at", "the", "a", "an", "is", "are",
    "was", "were", "by", "from", "up", "down", "over", "under", "about",
    "approx", "approximately", "through", "thru", "then", "than", "with",
    "for", "on", "off", "per_the", "as", "into", "onto", "upto", "vs",
    "versus", "typ_or", "x",
})


def extract_numbers(value: Any) -> List[float]:
    """Every number appearing in `value` (scalar, string, list or dict)."""
    out: List[float] = []
    if isinstance(value, bool):
        return out
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        for m in _NUM_RE.finditer(value):
            try:
                out.append(float(m.group(0)))
            except ValueError:
                pass
        return out
    if isinstance(value, dict):
        for v in value.values():
            out.extend(extract_numbers(v))
        return out
    if isinstance(value, (list, tuple)):
        for v in value:
            out.extend(extract_numbers(v))
        return out
    return out


def has_number_with_unit(value: Any) -> bool:
    """True when `value` carries a number bound to a unit — the minimum shape
    a downstream derate/budget consumer could actually apply.

    Accepts the typed dict form ({"value": 10, "unit": "%"}) as well as the
    string form ("10 %", "-40 degC", "1e6 h").
    """
    if isinstance(value, dict):
        keys = {str(k).lower() for k in value.keys()}
        has_val = any(k in keys for k in ("value", "min", "max", "typ",
                                          "nominal", "budget", "margin"))
        has_unit = any("unit" in k for k in keys)
        if has_val and has_unit:
            nums = extract_numbers({k: v for k, v in value.items()
                                    if "unit" not in str(k).lower()})
            return bool(nums)
        return any(has_number_with_unit(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(has_number_with_unit(v) for v in value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return False  # bare number, no unit → not actionable
    if isinstance(value, str):
        for m in _NUM_UNIT_RE.finditer(value):
            unit = m.group(1).strip().lower()
            if unit and unit not in _NON_UNIT_WORDS:
                return True
        return False
    return False
