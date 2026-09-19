#!/usr/bin/env python3
"""l24_signoff_requirements_extract.py — R-0915-38.

WHAT THIS EXTRACTS
==================
L24_SIGNOFF's REQUIREMENTS, from the design's own input documents: which
sign-off checks the input says must be run, what it says they must achieve,
at which corners, and WHERE IT SAYS SO (document + line + the line itself).

WHY REQUIREMENTS AND NOT STATUSES
---------------------------------
L24's field template is `drc_status`, `lvs_status`, `sta_status`,
`ir_drop_status`, `antenna_status`, `tapeout_gates[]`. Those are OUTCOMES,
produced in phase 3. Phase 1 runs before DRC, LVS and STA exist, so a phase-1
extractor that filled them would be publishing a certificate for a check that
has not run — and `l24_signoff_evidence_backed_check` is built precisely to
refuse that: it treats every `*_status` / `status` / `verdict` / `result` key
at any depth as a CLAIM requiring an in-project evidence path plus the value
read back. Filling them here would turn the layer from inert to FAILING.

So nothing this module writes uses those key names. The requirement rows live
in `signoff_requirements`, keyed `check` / `requirement` / `corners` /
`threshold` / `citation`, and the outcome fields stay null for phase 3 to
answer. The two halves then meet in the gate: extracted requirement on one
side, the run's own report on the other.

WHAT IS NEVER INVENTED
----------------------
A check the input does not mention is emitted as a row with
`stated: false, requirement: null` AND the scan that looked for it — the
documents read and the terms searched. An absent requirement is reported as a
searched-and-not-found, never as a silent omission and never as a default.
A check the input DOES mention but for which no requirement word is
recognisable keeps `requirement: null` with `stated: true` and the citation,
so a reader sees the sentence and can judge it; the extractor does not guess
what "DRC" alone was supposed to demand.

CORNERS ARE ATTRIBUTED CONSERVATIVELY. A corner token counts as a check's
corner only when it appears inside that check's own clause. MEASURED on spm, a
line reads "TT corner / 10 ns ... sign-off (DRC/LVS/Antenna 全 clean)" — the
corner is stated BEFORE the checks, and extending the clause backwards to
catch it would drag the PREVIOUS check's requirement word in with it ("LVS
clean、STA met" would make STA `clean`, which is the bug this clause logic
exists to fix). So the corner is not attributed, `all_citations` points a
reader at every line that named the check, and the extractor under-claims
rather than inventing a requirement the input did not state for that check.

chip-AGNOSTIC: no design, PDK, vendor, node or signal name appears here. The
check vocabulary is L24's own — its `extraction_hints` name "DRC / LVS / STA /
antenna / IR-drop status per gate" and "the tapeout gate list" — plus EM and
the tapeout precheck named in the ruling.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = ["SIGNOFF_CHECKS", "extract_signoff_requirements",
           "report_tokens_for", "signoff_record_paths_for", "find_flow_def"]

#: check -> (the word-bounded spellings that NAME it in an input document,
#:           the tokens that name its REPORT in a run tree).
#: Order is the emission order of the rows. The report tokens are what
#: `l24_signoff_evidence_backed_check` matches against report filenames and
#: their `program` / `gate` fields, so the two halves of R-0915-38 — what the
#: input requires and what the run measured — are bound by ONE table.
SIGNOFF_CHECKS: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("DRC", ("DRC", "design rule check"), ("drc",)),
    ("LVS", ("LVS", "layout versus schematic", "layout vs schematic"),
     ("lvs",)),
    ("antenna", ("antenna",), ("antenna",)),
    ("STA", ("STA", "static timing analysis", "timing sign-off",
             "timing signoff"), ("sta", "timing")),
    ("IR_drop", ("IR-drop", "IR drop", "IR_drop", "voltage drop"),
     ("ir_drop", "ir")),
    ("EM", ("EM", "electromigration", "electro-migration"),
     ("em", "electromigration")),
    ("tapeout_precheck", ("tapeout precheck", "tape-out precheck",
                          "tapeout pre-check", "tapeout checklist",
                          "tape-out checklist"),
     ("tapeout_precheck", "tapeout_checklist")),
    # R-0915-52. SI is its OWN check, judged BY NAME and only when the input
    # states one. Before this row the flow's SI reports had no requirement of
    # their own to answer, so `si_mcf_sta.json` — whose stem ends in the token
    # `sta` — was read as a reading of the STA requirement instead. An SI
    # envelope is not a timing sign-off, and a design that never asks for one
    # must not be failed by it.
    #
    # The spellings are deliberately the NAMES and not the bare initialism:
    # a word-bounded, case-insensitive `SI` matches the English word "si" in
    # nothing, but it does match a stray `si` token in a table, a filename or
    # a unit, and a check that fires on that is inventing a requirement.
    ("SI", ("signal integrity", "signal-integrity", "crosstalk",
            "cross-talk"),
     ("si", "si_crosstalk", "si_mcf_sta", "crosstalk")),
)


def report_tokens_for(check: str) -> Tuple[str, ...]:
    """The run-tree report tokens for one check name, or ()."""
    for name, _spellings, tokens in SIGNOFF_CHECKS:
        if name == check:
            return tokens
    return ()


# ── R-0915-52: the flow's DECLARED sign-off record for a check ─────────────
#
# WHY THIS EXISTS. `l24_signoff_evidence_backed_check` judged a stated
# requirement by scanning every `reports/**/*.json` whose stem or
# `program`/`gate`/`subject`/`check` field carried one of the tokens above,
# and took EACH one's verdict. MEASURED on the r19 subservient run
# (gf180mcuD, 2026-09-15): the input states "STA ... setup + hold >= 0", the
# run's post-route sign-off STA PASSED, and the gate still reported
#
#   the input REQUIRES STA ... and this run measured it as 'fail' in
#   reports/phase3/si_mcf_sta.json, 'fail' in reports/phase3/sta/pre_pnr_summary.json
#
# Neither of those is a sign-off reading of STA. `pre_pnr_summary.json` is
# step 10's PRE-LAYOUT ESTIMATE, which R-0915-28 already rules is superseded
# by a passing post-route sign-off; `si_mcf_sta.json` is step 27's SIGNAL
# INTEGRITY envelope, which answers a different question and now has its own
# check row above. The token was standing in for the record.
#
# WHAT REPLACES IT, AND WHY IT IS DERIVED. A requirement is judged by the
# record the FLOW declares as that check's sign-off: the step whose own name
# says it is the sign-off step, and the `reports/**/*.json` it declares in
# `required_outputs`. Both halves come from
# `flow/phase1_phase2_phase3.yaml` — the flow is the single source of truth
# for which step publishes what, and a hand list here would drift away from it
# the first time a step's outputs changed.
#
# MEASURED on the flow at 800cecb34: six steps name themselves sign-off
# (23, 28, 36, 37.4, 39, M4), and after intersecting their declared reports
# with each check's tokens exactly ONE check resolves to a declared record —
# STA, to step 23's four `reports/phase3/sta/*.json`. Every other check
# (DRC, LVS, antenna, IR_drop, EM, tapeout_precheck, SI) derives none and
# keeps the token scan it has today. The change is therefore scoped to the
# defect by construction, not by a special case.
FLOW_DEF_FILENAME = "phase1_phase2_phase3.yaml"

#: A step whose NAME declares it the sign-off step for its own subject.
_SIGNOFF_STEP_NAME_RE = re.compile(r"sign[-\s]?off", re.I)
#: `required_outputs` states alternates as "<a> OR <b>".
_OUTPUT_ALT_RE = re.compile(r"\s+OR\s+")
#: Cache keyed on (resolved path, mtime, size) so a test that rewrites a
#: fixture flow sees the rewrite.
_RECORD_CACHE: Dict[Any, Dict[str, Tuple[str, ...]]] = {}


def find_flow_def() -> Path:
    """Locate `flow/phase1_phase2_phase3.yaml` for the installed plugin.

    Mirrors the unified-layout half of `flow_compliance_check._find_flow_def`,
    restated for the same reason `waivers_schema_check.find_flow_def` restates
    it: that module `sys.exit(2)`s at import time when PyYAML is missing, and
    this one must keep answering when it is.
    """
    here = Path(__file__).resolve()
    for ancestor in (here.parent.parent,
                     here.parent.parent.parent,
                     here.parent.parent.parent.parent):
        cand = ancestor / "flow" / FLOW_DEF_FILENAME
        if cand.is_file():
            return cand
    return here.parent.parent / "flow" / FLOW_DEF_FILENAME


def _path_names_token(rel: str, tokens: Sequence[str]) -> bool:
    """Does this project-relative report path NAME one of these tokens?

    Word-bounded against the whole path with `/`, `_`, `-` and `.` acting as
    boundaries, so `reports/phase3/sta/post_route_summary.json` names `sta`
    (the directory does) while `reports/phase3/status_board.json` does not.
    """
    low = rel.lower()
    for tok in tokens:
        if re.search(r"(?<![a-z0-9])" + re.escape(tok.lower())
                     + r"(?![a-z0-9])", low):
            return True
    return False


def _declared_records(flow_def: Path) -> Dict[str, Tuple[str, ...]]:
    """check -> the project-relative sign-off records the FLOW declares.

    Fail-SOFT and empty: no PyYAML, an unreadable or unparseable flow, or a
    flow with no sign-off step all give `{}`, and the caller keeps the token
    scan it already had. A derivation that raised would take down a gate that
    merely wanted to ask a question.
    """
    try:
        import yaml  # noqa: PLC0415 — optional, and absent is not fatal here
    except ImportError:
        return {}
    try:
        stat = flow_def.stat()
        key = (str(flow_def), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return {}
    cached = _RECORD_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        data = yaml.safe_load(flow_def.read_text(encoding="utf-8",
                                                 errors="replace"))
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list):
        return {}

    declared: List[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if not _SIGNOFF_STEP_NAME_RE.search(str(step.get("name") or "")):
            continue
        for entry in step.get("required_outputs") or []:
            for alt in _OUTPUT_ALT_RE.split(str(entry)):
                alt = alt.strip()
                # A sign-off READING is a machine-readable verdict, so only
                # the JSON half of a declared pair counts; an `.rpt` is the
                # tool's transcript and carries no verdict field to read.
                if not alt.startswith("reports/") or not alt.endswith(".json"):
                    continue
                # The same exclusion `_reports_for_check` already applies:
                # `reports/audit/` is the completion audit's OWN bookkeeping,
                # and a requirement backed by the audit that is judging it
                # would be circular. Excluding it here means the checks whose
                # only sign-off-named publisher writes there (tapeout_precheck,
                # via step 36's reports/audit/tapeout_checklist.json) derive no
                # declared record and keep the scan they have today — which is
                # the behaviour-preserving direction.
                if alt.startswith("reports/audit/"):
                    continue
                declared.append(alt)

    out: Dict[str, Tuple[str, ...]] = {}
    for check, _spellings, tokens in SIGNOFF_CHECKS:
        hits = tuple(dict.fromkeys(
            p for p in declared if _path_names_token(p, tokens)))
        if hits:
            out[check] = hits
    _RECORD_CACHE[key] = out
    return out


def signoff_record_paths_for(check: str,
                             flow_def: Optional[Path] = None
                             ) -> Tuple[str, ...]:
    """The project-relative reports the FLOW declares as `check`'s sign-off.

    Empty when the flow declares none — which is the honest answer for every
    check whose sign-off is not published by a step that names itself sign-off
    — and the caller then judges the check the way it did before.
    """
    path = Path(flow_def) if flow_def is not None else find_flow_def()
    return _declared_records(path).get(check, ())

#: The requirement a line STATES, as the input's own word. Ordered: the first
#: match wins, so the specific numeric forms are tried before the bare words.
_REQUIREMENT_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("zero_violations", r"(?<![a-z0-9])(?:0|zero)\s*(?:violation|error|drc|"
                        r"vio)\w*"),
    ("percent_clean", r"100\s*%\s*clean"),
    ("clean", r"(?<![a-z0-9])clean(?![a-z0-9])"),
    ("met", r"(?<![a-z0-9])met(?![a-z0-9])"),
    ("all_zero", r"(?<![a-z0-9])(?:全\s*0|all\s+zero)(?![a-z0-9])"),
    ("pass", r"(?<![a-z0-9])pass(?:ed)?(?![a-z0-9])"),
)

#: A corner named on the line. Uppercase process-corner tokens only; these are
#: PDK-independent names, not a node or vendor.
_CORNER_RE = re.compile(r"(?<![A-Za-z0-9])(SS|TT|FF|SF|FS)(?![A-Za-z0-9])")

#: A stated numeric threshold with a unit.
_THRESHOLD_RE = re.compile(
    r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)\s*(ns|ps|mV|V|%|uW|mW|mA|uA)"
    r"(?![A-Za-z0-9])", re.IGNORECASE)

_DOC_SUFFIXES = (".md", ".markdown", ".txt", ".rst", ".adoc", ".asciidoc")

_DRC_ENGINES = (("magic", re.compile(r"\bmagic\b", re.I)),
                ("klayout", re.compile(r"\bklayout\b", re.I)))


def _engines_of(check: str, clause: str) -> List[str]:
    """Return explicitly named engines for a check's own clause."""
    if check != "DRC":
        return []
    return [name for name, pattern in _DRC_ENGINES if pattern.search(clause)]


def _word_bounded(term: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term)
                      + r"(?![A-Za-z0-9])", re.IGNORECASE)


def _input_documents(project: Path) -> List[Path]:
    docs = project / "input" / "docs"
    if not docs.is_dir():
        return []
    return sorted(p for p in docs.rglob("*")
                  if p.is_file() and p.suffix.lower() in _DOC_SUFFIXES)


def _clause_for(line: str, match: re.Match) -> str:
    """The span of the line that belongs to THIS check's mention.

    MEASURED, and the reason this function exists: an input line reading
    "DRC clean, LVS clean, STA met" states THREE different requirements, and a
    reader that scans the whole line hands the first one it finds to all
    three — so STA came back `clean`, which the input never says. The clause
    runs from this check's token to the next check's token on the same line,
    or to the end of it.
    """
    end = len(line)
    for _check, spellings, _tokens in SIGNOFF_CHECKS:
        for spelling in spellings:
            for other in _word_bounded(spelling).finditer(line):
                if match.start() < other.start() < end:
                    end = other.start()
    return line[match.start():end]


def _requirement_of(clause: str) -> Optional[str]:
    low = clause.lower()
    for name, pattern in _REQUIREMENT_PATTERNS:
        if re.search(pattern, low, re.IGNORECASE):
            return name
    return None


def _threshold_of(line: str) -> Optional[Dict[str, Any]]:
    m = _THRESHOLD_RE.search(line)
    if not m:
        return None
    return {"value": float(m.group(1)), "unit": m.group(2)}


def _scoped_timing_corner_clause(line: str, headings: Sequence[str]) -> Optional[str]:
    """An implicit STA requirement needs timing scope and an explicit mandate.

    A multi-corner phrase alone names no check. Descendant headings may refine
    timing into libraries/periods/corners, but an unrelated section cannot
    borrow an earlier timing heading. This carries requirements, never results.
    """
    anchor = re.compile(r"\b(?:SDC|timing|clock(?:ing)?)\b", re.I)
    refinement = re.compile(r"\b(?:librar(?:y|ies)|periods?|corners?)\b", re.I)
    import _prose_polarity as polarity
    excluded = re.compile(r"\b(?:examples?|historical|previous)\b|範例|例如|歷史", re.I)
    if any(excluded.search(heading) or polarity.is_denied(heading)
           for heading in headings):
        return None
    active = False
    for heading in headings:
        if anchor.search(heading):
            active = True
        elif active and not refinement.search(heading):
            active = False
    if not active:
        return None
    clause = re.split(r"[。;；]", line, maxsplit=1)[0]
    if not re.search(r"\bmulti[- ]corner\s+sign[- ]?off\b", clause, re.I):
        return None
    # Never infer a timing check from a clause explicitly naming another one.
    if any(_word_bounded(term).search(clause)
           for check, terms, _ in SIGNOFF_CHECKS if check != "STA" for term in terms):
        return None
    if polarity.is_denied(clause) or excluded.search(clause):
        return None
    if not re.search(r"\b(?:must|shall|required)\b|均須|必須", clause, re.I):
        return None
    if not _CORNER_RE.search(clause):
        return None
    if _requirement_of(clause) is None and "通過" not in clause:
        return None
    return clause


def extract_signoff_requirements(project: Path) -> Optional[Dict[str, Any]]:
    """L24's requirement rows plus the scan that produced them, or None.

    Returns None — leaving the caller to emit whatever it would have emitted
    — when the question cannot be answered honestly: no project, or no
    readable input document. An empty corpus is a scan with no denominator.
    """
    if project is None:
        return None
    project = Path(project)
    docs = _input_documents(project)
    if not docs:
        return None

    scanned: List[str] = []
    lines_by_doc: List[Tuple[str, List[str]]] = []
    for doc in docs:
        try:
            text = doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Unreadable is not absent; refuse the whole extraction.
            return None
        try:
            rel = doc.relative_to(project).as_posix()
        except ValueError:
            rel = doc.name
        scanned.append(rel)
        lines_by_doc.append((rel, text.splitlines()))

    rows: List[Dict[str, Any]] = []
    stated_count = 0
    for check, spellings, _report_tokens in SIGNOFF_CHECKS:
        patterns = [_word_bounded(s) for s in spellings]
        hits: List[Dict[str, Any]] = []
        for rel, lines in lines_by_doc:
            headings: List[Tuple[int, str]] = []
            in_fence = False
            for lineno, line in enumerate(lines, start=1):
                if re.match(r"^\s*(```|~~~)", line):
                    in_fence = not in_fence
                heading = re.match(r"^\s*(#{1,6})\s+(.+)", line) if not in_fence else None
                if heading:
                    depth = len(heading.group(1))
                    headings = [(d, text) for d, text in headings if d < depth]
                    headings.append((depth, heading.group(2)))
                match = next((m for m in (p.search(line) for p in patterns)
                              if m), None)
                implicit = (_scoped_timing_corner_clause(line, [text for _, text in headings])
                            if check == "STA" and match is None and not in_fence else None)
                if match is None and implicit is None:
                    continue
                clause = implicit if implicit is not None else _clause_for(line, match)
                hits.append({
                    "document": rel,
                    "line": lineno,
                    # Bounded so one pathological line cannot dominate the
                    # layer; the citation is a pointer, not a copy.
                    "text": line.strip()[:400],
                    "clause": clause.strip()[:200],
                    "requirement": (_requirement_of(clause) or
                                    ("pass" if implicit is not None and "通過" in clause else None)),
                    # Corners are read from the CLAUSE too, for the same
                    # reason: a corner named beside a different check on the
                    # same line is not this check's corner.
                    "corners": sorted(set(_CORNER_RE.findall(clause))),
                "threshold": _threshold_of(clause),
                    "engines": _engines_of(check, clause),
                })
        if not hits:
            rows.append({
                "check": check,
                "stated": False,
                "requirement": None,
                "corners": [],
                "threshold": None,
                "citation": None,
                "searched": {"spellings": list(spellings),
                             "documents": list(scanned)},
            })
            continue
        stated_count += 1
        # The citation is the first hit that actually STATES a requirement;
        # failing that, the first hit at all — so a reader always lands on the
        # most informative sentence the input offers.
        best = next((h for h in hits if h["requirement"]), hits[0])
        rows.append({
            "check": check,
            "stated": True,
            "requirement": best["requirement"],
            "corners": sorted({c for h in hits for c in h["corners"]}),
                "threshold": best["threshold"],
            "engines": sorted({engine for h in hits
                               for engine in h.get("engines", [])}),
            "citation": {"document": best["document"], "line": best["line"],
                         "text": best["text"], "clause": best["clause"]},
            "occurrences": len(hits),
            "all_citations": [{"document": h["document"], "line": h["line"]}
                              for h in hits[:20]],
        })

    return {
        "signoff_requirements": rows,
        "signoff_requirements_scan": {
            "documents_scanned": scanned,
            "documents_scanned_count": len(scanned),
            "checks_searched": [c for c, _s, _r in SIGNOFF_CHECKS],
            "checks_stated": stated_count,
            "extracted_by": ("l24_signoff_requirements_extract"
                             ".extract_signoff_requirements"),
        },
    }
