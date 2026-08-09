#!/usr/bin/env python3
"""deliverable_verdict_consistency_check.py — a deliverable may not contradict
the orchestrator it claims to summarise.

WHY THIS EXISTS (measured escape, 2026-07-26)
=============================================
On run ``converge_1.5.85_ihp-sg13g2`` the deliverable and the runner disagreed
for 8 hours and nothing noticed:

    RESULT.md            written 01:39   headline verdict = PASS_WITH_WAIVERS
    reports/orchestrator/vibe_ic_one_shot.json   rewritten 09:44   verdict = FAIL
    reports/orchestrator/phase3_one_shot.json    rewritten 09:44   verdict = FAIL
    reports/audit/phase23_completion_audit.json  rewritten 11:03   verdict = FAIL

The 09:44 invocation moved the orchestrator verdict to FAIL. Nobody updated the
deliverable. The run therefore SHIPPED a RESULT.md claiming PASS over its own
FAIL, and every gate stayed green — because the one gate that keys off the
deliverable, ``run_output_completeness_check``, asks only "is RESULT.md PRESENT
and non-stub?". Its own evidence dict already carried
``orchestrator_verdict='FAIL'`` at the moment it returned ``COMPLETE / PASS``.
It had both numbers in hand and never compared them.

THE GENERAL DEFECT (chip-AGNOSTIC, tool-AGNOSTIC)
------------------------------------------------
*A run can end FAIL and still ship a deliverable that says PASS, because nothing
re-reads the orchestrator after the deliverable is written.* The deliverable is
the only artefact a human reads. Every escape of this shape converts a machine
FAIL into a human-visible PASS, which is the exact "checks that lie" class.

WHAT MAKES THIS NOT A RUBBER STAMP
==================================
The check compares TWO INDEPENDENTLY-PRODUCED VALUES:

  value 1  the HEADLINE VERDICT parsed out of the deliverable's own markdown
           — authored by the AGENT, in prose, at synthesis time.
  value 2  the ``verdict`` field of the orchestrator's ``*_one_shot.json``
           — emitted by the RUNNER, in JSON, at compute time.

Different producer, different file, different format, different clock. A
checker that merely re-states the headline (``report(headline)``) cannot satisfy
this program: with both sides sourced from the deliverable the contradiction is
unreachable and the defect-direction test below fails. That mutation is carried
in the test suite precisely so it stays unreachable.

DIRECTION (deliberately ASYMMETRIC — say so, do not hide it)
------------------------------------------------------------
Only the ESCAPE direction fails:

    deliverable claims PASS-polarity  ×  orchestrator says FAIL  ->  FAIL

The opposite direction — a deliverable that reports FAIL over an orchestrator
PASS — is UNDER-claiming. It is recorded as ``DELIVERABLE_STRICTER`` and does
NOT fail, because an agent may legitimately downgrade for a reason the
orchestrator cannot see (an undisclosed PDK substitution, a stale number, an
un-re-derived measurement). Failing that direction would punish honesty and
would make the gate fire on correct reports. Stated here so the asymmetry is a
declared design decision, not an oversight.

WHY ``PASS_WITH_WAIVERS`` vs ``PASS`` IS NOT A CONTRADICTION
------------------------------------------------------------
The comparison is on POLARITY, not on string equality. ``PASS``,
``PASS_WITH_WAIVERS`` and ``PASS_WITH_OPEN_ITEMS`` are all PASS-polarity; only a
PASS/FAIL polarity split is a contradiction. String equality would fire on every
honest run whose deliverable adds a qualifier.

NARROWNESS (why it does not fire on a real corpus)
--------------------------------------------------
A headline verdict is recognised ONLY when the deliverable states one
UNAMBIGUOUSLY, in one of four canonical positions (see ``_HEADLINE_RECOGNISERS``).
Verdict-shaped words inside prose are NOT a headline. If no headline verdict is
stated, or no orchestrator report carries a verdict, the program returns
NOT_APPLICABLE (rc 2 = SKIP) — never a PASS. It is not this program's job to
require that a deliverable carry a headline; only that a stated one be true.

Exit codes
----------
    0  CONSISTENT | DELIVERABLE_STRICTER   (no contradiction)
    1  DELIVERABLE_CONTRADICTS_ORCHESTRATOR
    2  NOT_APPLICABLE (no deliverable / no headline stated / no orchestrator
       verdict) — a genuine SKIP. ``flow_compliance_check._eval_gate_worker``
       maps rc 2 to "skip", NOT to a PASS in the numerator.

chip-AGNOSTIC + tool-AGNOSTIC + pure: reasons over markdown text and JSON
fields only. No IC, vendor, PDK or SKU literal appears as logic.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Verdict vocabulary.
# ---------------------------------------------------------------------------
# A verdict TOKEN is exactly PASS/FAIL, optionally qualified. Anything else is
# not a verdict for this program's purposes — deliberately narrow, so prose
# words ("COMPLETE", "CONVERGED", "PRODUCTION-READY") never become a headline.
_TOKEN_RE = re.compile(r"^(PASS|FAIL)(_[A-Z0-9]+(?:_[A-Z0-9]+)*)?$")

# Markdown decoration stripped before a token/label comparison. Applied
# repeatedly until stable so `**\`FAIL\`**` reduces to `FAIL`.
_DECO_CHARS = "`*_~\"' \t"

# The label a canonical headline line carries, with the qualifiers a report
# legitimately puts in front of it.
_LABEL_RE = re.compile(
    r"^(?:final|overall|headline|run|top[- ]?level)?\s*verdict$", re.IGNORECASE)

# Leading list / quote markers stripped before recognising a labelled line.
_LIST_PREFIX_RE = re.compile(r"^\s{0,8}(?:[-*+>]\s+|\d+[.)]\s+)?")

# Heading numbering, e.g. "## 0. Verdict" -> "Verdict".
_HEADING_NUM_RE = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s+")

# How far below a `## Verdict` heading a bare token still counts as the
# headline. Bounded so a distant token in a later section can never be adopted.
_SECTION_LOOKAHEAD_LINES = 6

_ORCH_REPORT_PREFERENCE = (
    "reports/orchestrator/vibe_ic_one_shot.json",
    "reports/vibe_ic_one_shot.json",
)
_ORCH_REPORT_GLOBS = (
    "reports/orchestrator/*_one_shot.json",
    "reports/*_one_shot.json",
    # vibe-ic c5b333d87 — per-phase orchestrator verdicts nest one level deeper:
    # `report_path` routes `analog_one_shot.json` to reports/phase3/ (its
    # _REPORT_CATEGORY is "phase3", not "orchestrator"), so the analog run
    # verdict escaped the two globs above and an analog FAIL could not block a
    # PASS deliverable. This one-level-deep glob picks up any phase-nested
    # `*_one_shot.json`; resolve()-dedup below folds the orchestrator overlap.
    "reports/*/*_one_shot.json",
)

# vibe-ic#883 — THE COMPLETION AUDIT IS ALSO A RUN-LEVEL VERDICT, AND IT WAS
# INVISIBLE HERE.
#
# This module's docstring has always named `reports/audit/
# phase23_completion_audit.json` in its evidence table (see the 2026-07-26
# escape above: the audit ALSO said FAIL). It was never read. `grep -c` for
# that filename over this file returned 1, and that single hit was the prose.
#
# The escape that proves it, measured 2026-08-08 on the SHIPPED tree
# `benchmark-data/ic/caravel_user_project/v1.9.43_sky130A`:
#
#     RESULT.md                                    headline = PASS_WITH_WAIVERS
#     reports/orchestrator/vibe_ic_one_shot.json   verdict  = PASS_WITH_WAIVERS
#     reports/audit/phase23_completion_audit.json  verdict  = FAIL
#                                                  (P5 F10 M10 W2)
#
# Because an AGGREGATE report existed, `read_orchestrator_verdict` returned on
# the first preference hit and never reached any other candidate. Both values it
# compared were PASS-polarity, so it returned CONSISTENT / exit 0 — on the exact
# deliverable-over-FAIL shape this program exists to catch. That false
# certificate stood 6 days in a public repo and was retired by a human, not by
# this gate.
#
# Note the direction of the disagreement is not arbitrary: `benchmark_evidence_
# publish._audit_verdict` treats this same file as AUTHORITATIVE. So two
# programs disagreed about what decides convergence, and only the weaker one was
# wired as a gate.
#
# The fix applies this module's OWN existing rule — "a deliverable may never be
# LAXER than the record" — to the audit as well: the audit joins the candidate
# set, and a FAIL audit is never overridden by a PASS aggregate. The asymmetry
# is preserved exactly as declared above: an audit that is more LENIENT than the
# orchestrator changes nothing, because under-claiming is the honest direction.
_AUDIT_REPORT_RELS = (
    "reports/audit/phase23_completion_audit.json",
    "reports/audit/*_completion_audit.json",
)

_EXIT = {
    "CONSISTENT": 0,
    "DELIVERABLE_STRICTER": 0,
    "DELIVERABLE_CONTRADICTS_ORCHESTRATOR": 1,
    "NOT_APPLICABLE": 2,
    # Non-fatal and rc-IDENTICAL to the SKIP it replaces, so CI behaviour is
    # unchanged: this makes the OUTPUT honest, it does not start failing runs.
    # A gate that began failing here would be adjudicating a claim it has
    # just said it cannot adjudicate.
    "UNCHECKED_SUCCESS_CLAIM": 2,
    # 2026-08-08 — an explicit, evidenced waiver downgrades the escape
    # direction. See WAIVER_KEY below: this is NOT a general "trust the
    # deliverable" bypass (that would reopen exactly the #escape this whole
    # check exists to close) — it requires a human-authored waivers.json
    # entry naming WHY the orchestrator record is stale, at the same
    # >=WAIVER_MIN-character evidentiary bar every other local waiver in
    # this codebase uses (project_outputs_in_tree_check.py,
    # otp_image_nonzero_check.py, and 2 others share the identical pattern).
    "DELIVERABLE_CONTRADICTS_ORCHESTRATOR_WAIVED": 0,
}

# A waiver here is NOT "trust any later deliverable" — that would be the
# exact timestamp-based bypass this check's own docstring warns against (a
# careless or malicious re-write of RESULT.md after the fact would sail
# through unchecked). It is a human, per-run, evidenced disclosure: the
# waiver text must say WHY the cited orchestrator record is known-stale
# (typically: it captured a FIRST attempt that halted before a since-fixed
# defect, and a LATER, independently re-derived verification superseded it —
# the exact shape this module's own docstring calls "correct the
# orchestrator" for). Same key across `waivers.json`'s single JSON object as
# every other local-waiver check in this file's family.
WAIVER_KEY = "deliverable_verdict_predates_reverification"
WAIVER_MIN = 60


def _waiver_count(project: Path) -> int:
    p = project / "waivers.json"
    if not p.exists():
        return 0
    try:
        d = json.loads(p.read_text())
    except Exception:
        return 0
    v = d.get(WAIVER_KEY)
    if isinstance(v, str):
        return 1 if len(v.strip()) >= WAIVER_MIN else 0
    if isinstance(v, list):
        return sum(1 for s in v
                   if isinstance(s, str) and len(s.strip()) >= WAIVER_MIN)
    return 0


# ---------------------------------------------------------------------------
# Pure helpers.
# ---------------------------------------------------------------------------
def _strip_deco(s: str) -> str:
    """Strip markdown emphasis/quoting from both ends until stable."""
    prev = None
    cur = s.strip()
    while cur != prev:
        prev = cur
        cur = cur.strip(_DECO_CHARS)
    return cur


def normalise_token(raw: str) -> Optional[str]:
    """`‘pass with waivers’ / `PASS-WITH-WAIVERS` / `**FAIL**` -> canonical
    token, or None if the text is not a verdict token."""
    t = _strip_deco(raw)
    if not t:
        return None
    t = re.sub(r"[\s\-]+", "_", t).upper().strip("_")
    return t if _TOKEN_RE.match(t) else None


def _head_before_annotation(value: str) -> str:
    """The verdict value up to the first ANNOTATION separator.

    A real headline routinely annotates its verdict on the same line:
    ``**Overall verdict:** `PASS_WITH_WAIVERS` — `halted_at: None`, 142.1 s``.
    The verdict is the leading fragment; the em-dash / parenthesis / comma
    clause after it is commentary. Splitting there keeps the recogniser narrow
    (the value must still reduce to a bare token) while accepting the form a
    real deliverable actually uses.
    """
    return re.split(r"\s+[—–]\s+|\s+--?\s+|\s*[(,;]", value, maxsplit=1)[0]


def polarity(token: Optional[str]) -> Optional[str]:
    """PASS / FAIL polarity of a canonical token. Qualifiers do not change it —
    PASS_WITH_WAIVERS is still a PASS claim to a human reader."""
    if not token:
        return None
    return "PASS" if token.startswith("PASS") else "FAIL"


# ---------------------------------------------------------------------------
# VALUE 1 — the deliverable's own headline verdict (AGENT-produced, markdown).
# ---------------------------------------------------------------------------
def _r_heading_token(line: str) -> Optional[str]:
    """`# \\`FAIL\\`` / `### **PASS**` — a heading whose whole text is a token."""
    m = re.match(r"^\s{0,3}(#{1,6})\s+(.*)$", line)
    if not m:
        return None
    return normalise_token(m.group(2))


def _r_labelled_line(line: str) -> Optional[str]:
    """`**Verdict:** PASS` / `- Final verdict = FAIL` /
    ``**Overall verdict:** `PASS_WITH_WAIVERS` — halted_at: None``.

    The value must OPEN with a bare verdict token; anything after an annotation
    separator is commentary on the verdict, not part of it. Prose
    ("Verdict: the run did not converge") therefore does not match.

    A body that OPENS with a backtick is a quotation of someone else's verdict
    field inside a code span — e.g. a report discussing
    ``` `verdict: "PASS"` ``` from a gate's JSON — and is NOT this deliverable
    declaring its own headline. Rejected. (Measured need: a corpus deliverable
    quotes a sub-gate's verdict in exactly that shape.)
    """
    body = _LIST_PREFIX_RE.sub("", line, count=1).strip()
    if not body or body.startswith("`"):
        return None
    m = re.match(r"^(.{1,40}?)\s*(?::|=|—|--)\s*(.+)$", body)
    if not m:
        return None
    if not _LABEL_RE.match(_strip_deco(m.group(1))):
        return None
    return normalise_token(_head_before_annotation(m.group(2)))


def _r_table_row(line: str) -> Optional[str]:
    """`| **Verdict** | PASS |` — a two-cell table row."""
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return None
    cells = [c for c in s.strip("|").split("|")]
    if len(cells) != 2:
        return None
    if not _LABEL_RE.match(_strip_deco(cells[0])):
        return None
    return normalise_token(cells[1])


def _r_section_lead_emphasis(line: str) -> Optional[str]:
    """Inside a `## VERDICT` section: a first content line that OPENS with an
    emphasised verdict token, then continues in prose —

        ## VERDICT

        **PASS_WITH_WAIVERS.** Independently re-derived from raw artifacts:

    The emphasised span must reduce to a bare token ON ITS OWN. That is what
    keeps this narrow: a corpus deliverable whose verdict section opens
    ``**DOC -> RTL: PASS (GENERATED, 100%).**`` is REJECTED, because the bold
    span is a scoped sub-claim, not a headline verdict. Only used under a
    heading that already announced itself as the verdict.
    """
    m = re.match(r"^\s*(\*\*|__)(.{1,40}?)\1", line)
    if not m:
        return None
    return normalise_token(m.group(2).strip().rstrip("."))


_HEADLINE_RECOGNISERS = (
    ("heading_token", _r_heading_token),
    ("labelled_line", _r_labelled_line),
    ("table_row", _r_table_row),
)


def _is_verdict_heading(line: str) -> bool:
    """`## 0. Verdict` — a section heading that ANNOUNCES the verdict."""
    m = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
    if not m:
        return False
    text = _HEADING_NUM_RE.sub("", _strip_deco(m.group(1)))
    return bool(_LABEL_RE.match(_strip_deco(text)))


_PROSE_SUCCESS_RE = re.compile(
    r"\b(PRODUCTION[- ]?READY|FULLY[- ]?CONVERGED|SIGN[- ]?OFF[- ]?CLEAN"
    r"|TAPE[- ]?OUT[- ]?READY|ALL\s+GATES\s+PASS)\b", re.IGNORECASE)


def _prose_success_claim(text: str) -> Optional[str]:
    """A PASS-polarity SUCCESS CLAIM stated in prose, or None.

    NOT a headline and never treated as one — this exists only so that an
    unadjudicable claim standing beside a FAILing orchestrator is DISCLOSED
    rather than silently skipped. The vocabulary is a short closed list of
    phrases this project's own reports actually emit, not an open-ended
    confidence detector: `benchmark_verify_report` prints
    "PRODUCTION-READY (all gates pass)", which is where the measured instance
    came from.
    """
    m = _PROSE_SUCCESS_RE.search(text or "")
    return m.group(0) if m else None


def extract_headline_verdict(text: str) -> Dict[str, object]:
    """FIRST unambiguous headline-verdict declaration in the deliverable.

    Returns ``{token, polarity, line_no, line, recogniser}`` — every field None
    when the deliverable states no headline verdict (which is NOT an error; see
    the module docstring on narrowness).
    """
    lines = text.splitlines()
    pending_section_from = -1     # line index of a `## Verdict` heading
    for i, line in enumerate(lines):
        for name, fn in _HEADLINE_RECOGNISERS:
            tok = fn(line)
            if tok:
                return {"token": tok, "polarity": polarity(tok),
                        "line_no": i + 1, "line": line.strip()[:300],
                        "recogniser": name}
        # `## Verdict` announces a section; a bare token just below it is the
        # headline (bounded lookahead, so a far-away token is never adopted).
        if _is_verdict_heading(line):
            pending_section_from = i
            continue
        if pending_section_from >= 0:
            if i - pending_section_from > _SECTION_LOOKAHEAD_LINES:
                pending_section_from = -1
            elif line.strip():
                tok = normalise_token(line) or _r_section_lead_emphasis(line)
                if tok:
                    return {"token": tok, "polarity": polarity(tok),
                            "line_no": i + 1, "line": line.strip()[:300],
                            "recogniser": "verdict_section"}
                pending_section_from = -1   # section opened with prose, not a token
    return {"token": None, "polarity": None, "line_no": None,
            "line": None, "recogniser": None}


# ---------------------------------------------------------------------------
# VALUE 2 — the orchestrator's verdict (RUNNER-produced, JSON).
#
# Sourced from a DIFFERENT producer than value 1 on purpose. Nothing in this
# function may read the deliverable; that independence is what makes the
# comparison meaningful, and the test suite carries a mutation that violates it.
# ---------------------------------------------------------------------------
def _load_verdict_json(p: Path) -> Optional[dict]:
    try:
        if not (p.is_file() and p.stat().st_size > 0):
            return None
        d = json.loads(p.read_text(errors="replace"))
    except Exception:
        return None
    return d if isinstance(d, dict) and d.get("verdict") else None


def _audit_files_present(run_dir: Path) -> List[Path]:
    """Every path the audit COULD have been read from, readable or not.

    vibe-ic#897. `_load_verdict_json` collapses missing / empty / truncated /
    malformed / wrong-key into one `None`, so "there was no audit" and "the
    audit is corrupt" arrived identically — and the gate printed "agrees in
    polarity" having consulted one record while believing it had consulted two.
    Five separate one-file edits each silenced the second opinion at rc=0.
    Presence is therefore established SEPARATELY from parseability.
    """
    out: List[Path] = []
    for pat in _AUDIT_REPORT_RELS:
        out.extend(sorted(run_dir.glob(pat)))
    return out


def _read_completion_audit(run_dir: Path) -> Optional[Tuple[Path, dict]]:
    """The STRICTEST phase-completion audit this run wrote, or ``None``.

    vibe-ic#883. Separate from the ``*_one_shot.json`` family on purpose: the
    audit is written by a DIFFERENT producer at a DIFFERENT time than the
    orchestrator, which is what makes it an independent second opinion rather
    than a restatement — the same property the docstring above requires of the
    deliverable-vs-orchestrator pair.
    """
    seen: Dict[str, Tuple[Path, dict]] = {}
    for pat in _AUDIT_REPORT_RELS:
        for p in sorted(run_dir.glob(pat)):
            d = _load_verdict_json(p)
            if d:
                seen.setdefault(str(p.resolve()), (p, d))
    if not seen:
        return None
    # Same strictest-wins rule as the phase reports: FAIL sorts first.
    return min(seen.values(), key=lambda pd: (
        polarity(normalise_token(str(pd[1]["verdict"]))) != "FAIL", str(pd[0])))


def _not_laxer_than_audit(
        chosen: Dict[str, object],
        audit: Optional[Tuple[Path, dict]],
) -> Dict[str, object]:
    """Never let a PASS-polarity record override a FAIL completion audit.

    vibe-ic#883. This is the module's own declared rule ("it may never be
    laxer") extended to a record it already cited but never read. Deliberately
    ONE-DIRECTIONAL, matching the asymmetry declared in the module docstring: a
    LENIENT audit never overrides a strict orchestrator, because under-claiming
    is the honest direction and punishing it would make the gate fire on correct
    reports.

    The override is always DISCLOSED — ``source`` records that the audit
    displaced the orchestrator, and ``displaced`` keeps the value that lost, so
    a reader can see a choice was made instead of inferring one.
    """
    # The carrier key is PRIVATE and must never survive into the reported
    # evidence dict — tests and consumers compare that dict field-by-field.
    present = chosen.pop("_audit_candidates", None) or []
    if audit is None:
        # #897: an audit file that EXISTS but did not parse is not the same as
        # no audit at all. Say so in the evidence, so a reader can see the
        # second opinion was attempted and lost rather than never sought.
        if present:
            chosen["audit_report"] = str(present[0])
            chosen["audit_verdict"] = None
            chosen["audit_unreadable"] = [str(p) for p in present]
        return chosen
    p, d = audit
    audit_pol = polarity(normalise_token(str(d["verdict"])))
    chosen["audit_report"] = str(p)
    chosen["audit_verdict"] = str(d["verdict"])
    if audit_pol != "FAIL" or chosen.get("polarity") == "FAIL":
        return chosen
    return {
        "report": str(p),
        "verdict": str(d["verdict"]),
        "polarity": audit_pol,
        "verdict_note": d.get("verdict_note"),
        "halted_at": d.get("halted_at"),
        "source": "completion_audit_stricter_than_orchestrator",
        "displaced": {"report": chosen.get("report"),
                      "verdict": chosen.get("verdict")},
        "audit_report": str(p),
        "audit_verdict": str(d["verdict"]),
    }


def read_orchestrator_verdict(run_dir: Path) -> Dict[str, object]:
    """The RUN-LEVEL verdict the runner recorded.

    Preference order — the aggregate report first (a deliverable's headline
    summarises the RUN, so the run-level aggregate is its counterpart), then,
    when there is no aggregate, the STRICTEST of the per-phase reports. The
    chosen path is always reported so the comparison is auditable, and when the
    per-phase reports disagreed every candidate is reported too.

    WHY NOT THE NEWEST (2026-08-04)
    ===============================
    This used to take ``max(st_mtime)``. A modification time is not a
    measurement of this run, for two independent reasons, and either one alone
    is fatal:

    1. **The judge writes into the tree it judges.** This gate is registered
       under ``flow_compliance_check``, which is a producer as well as a judge:
       driving one project rewrites 17 tracked files and adds 25 (measured
       2026-08-04; that measurement is what ``--read-only`` was added for). The
       orchestrator reports are inside that set. So the umbrella can change
       WHICH report this gate selects, purely by having looked — and with two
       reports of opposite polarity, the same tree yields FAIL or PASS
       depending on the order the auditor happened to touch them.

    2. **On a fresh checkout there are no distinct mtimes at all.** git stamps
       every file with the checkout time, so ``m > best[0]`` is false for every
       candidate after the first and "newest" silently degrades to
       glob-then-alphabetical order. The value read like a time and carried no
       information.

    The replacement removes the filesystem from the decision entirely. Among
    candidates the run itself wrote, the STRICTEST is taken: a run in which any
    phase recorded FAIL did have a phase fail, whatever the mtimes say. A
    deliverable may be STRICTER than the orchestrator (that lane already exits
    0); it may never be laxer, and picking the lax candidate out of a
    disagreeing set is exactly how it becomes laxer without anyone choosing to.
    Ties inside one polarity are broken by path so a fresh clone and a live run
    give the same answer.
    """
    # vibe-ic#883: gathered BEFORE the aggregate early-return below, because
    # that early-return is precisely the mechanism that hid a FAIL audit behind
    # a PASS aggregate.
    audit = _read_completion_audit(run_dir)
    _audit_present = _audit_files_present(run_dir)

    for rel in _ORCH_REPORT_PREFERENCE:
        d = _load_verdict_json(run_dir / rel)
        if d:
            out = {"report": str(run_dir / rel), "verdict": str(d["verdict"]),
                   "polarity": polarity(normalise_token(str(d["verdict"]))),
                   "verdict_note": d.get("verdict_note"),
                   "halted_at": d.get("halted_at"), "source": "aggregate"}
            out["_audit_candidates"] = _audit_present
            return _not_laxer_than_audit(out, audit)

    seen: Dict[str, Tuple[Path, dict]] = {}
    for pat in _ORCH_REPORT_GLOBS:
        for p in sorted(run_dir.glob(pat)):
            d = _load_verdict_json(p)
            if d:
                # `resolve()`: the two globs can name ONE physical file through
                # two paths, and a file counted twice is not a disagreement.
                seen.setdefault(str(p.resolve()), (p, d))
    cands = sorted(seen.values(), key=lambda pd: str(pd[0]))
    if not cands:
        return {"report": None, "verdict": None, "polarity": None,
                "verdict_note": None, "halted_at": None, "source": None}
    # FAIL sorts before PASS, so `min` is the strictest. Deterministic and
    # independent of anything the auditor can perturb.
    p, d = min(cands, key=lambda pd: (
        polarity(normalise_token(str(pd[1]["verdict"]))) != "FAIL",
        str(pd[0])))
    pols = {polarity(normalise_token(str(x["verdict"]))) for _, x in cands}
    out = {"report": str(p), "verdict": str(d["verdict"]),
           "polarity": polarity(normalise_token(str(d["verdict"]))),
           "verdict_note": d.get("verdict_note"),
           "halted_at": d.get("halted_at"), "source": "strictest_phase"}
    if len(pols) > 1:
        # DISCLOSED, not silently resolved: the evidence has to name what the
        # comparison was NOT made against, or a reader cannot tell that a
        # choice was made at all.
        out["source"] = "strictest_phase_of_disagreeing"
        out["candidates"] = [
            {"report": str(q), "verdict": str(x["verdict"])} for q, x in cands]
    return _not_laxer_than_audit(out, audit)


# ---------------------------------------------------------------------------
# The comparison.
# ---------------------------------------------------------------------------
@dataclass
class ConsistencyReport:
    run_dir: str
    deliverable: str
    state: str
    verdict: str                # PASS | FAIL | SKIP | DISCLOSED
    reason: str
    headline: Dict[str, object] = field(default_factory=dict)
    orchestrator: Dict[str, object] = field(default_factory=dict)
    blocking: List[str] = field(default_factory=list)

    @property
    def rc(self) -> int:
        return _EXIT.get(self.state, 2)


def check(run_dir: Path, *, result: Optional[Path] = None) -> ConsistencyReport:
    run_dir = Path(run_dir)
    deliverable = Path(result) if result is not None else run_dir / "RESULT.md"

    orch = read_orchestrator_verdict(run_dir)

    if not deliverable.is_file():
        return ConsistencyReport(
            str(run_dir), str(deliverable), "NOT_APPLICABLE", "SKIP",
            f"no deliverable at {deliverable} — presence is "
            f"run_output_completeness_check's question, not this one's",
            {}, orch)
    try:
        text = deliverable.read_text(errors="replace")
    except OSError as exc:
        return ConsistencyReport(
            str(run_dir), str(deliverable), "NOT_APPLICABLE", "SKIP",
            f"deliverable unreadable: {exc}", {}, orch)

    head = extract_headline_verdict(text)

    if head["token"] is None:
        # "No canonical headline" and "no PASS-polarity claim at all" are
        # different states, and reporting them with the same word is how a
        # deliverable claiming success over a failing run reads as clean.
        #
        # MEASURED (vibe-ic#445) on a published cell: RESULT.md states
        # "OVERALL: PRODUCTION-READY" while the same cell's own
        # final_summary.md says "FAIL=12 — blocking; do not claim PASS", and
        # this gate returned SKIP. Correctly, by its own contract — but
        # SILENTLY, which is the part that was wrong.
        #
        # The verdict VOCABULARY stays narrow, deliberately: a prose adjective
        # still never becomes a headline and can never produce a FAIL here.
        # What changes is that an unchecked SUCCESS CLAIM standing next to a
        # failing orchestrator is DISCLOSED instead of vanishing.
        claim = _prose_success_claim(text)
        if claim is not None and orch.get("polarity") == "FAIL":
            return ConsistencyReport(
                str(run_dir), str(deliverable), "UNCHECKED_SUCCESS_CLAIM",
                "DISCLOSED",
                f"{deliverable.name} states no CANONICAL headline verdict, so "
                f"this gate cannot adjudicate it — but it does assert "
                f"{claim!r} while the orchestrator "
                f"({orch.get('report')}) reads {orch.get('verdict')!r}. That "
                f"claim is UNCHECKED, not verified. Give the deliverable a "
                f"scoped canonical headline (e.g. 'Verdict: PASS' for the "
                f"scope the claim actually covers) so a machine can judge it; "
                f"widening this gate's verdict vocabulary to admit prose "
                f"adjectives is refused — that would let any confident "
                f"sentence become a headline.",
                head, orch)
        return ConsistencyReport(
            str(run_dir), str(deliverable), "NOT_APPLICABLE", "SKIP",
            f"{deliverable.name} states no unambiguous headline verdict — "
            f"nothing to contradict (this gate requires a stated headline to be "
            f"TRUE; it does not require one to exist)", head, orch)

    if orch["verdict"] is None:
        return ConsistencyReport(
            str(run_dir), str(deliverable), "NOT_APPLICABLE", "SKIP",
            f"no orchestrator report under {run_dir}/reports carries a "
            f"'verdict' field — no independent value to compare against",
            head, orch)

    if orch["polarity"] is None:
        return ConsistencyReport(
            str(run_dir), str(deliverable), "NOT_APPLICABLE", "SKIP",
            f"orchestrator verdict {orch['verdict']!r} in "
            f"{orch['report']} is not a PASS/FAIL token — no polarity to "
            f"compare", head, orch)

    hp, op = head["polarity"], orch["polarity"]

    if hp == "PASS" and op == "FAIL":
        reason = (
            f"VERDICT_CONTRADICTION: {deliverable.name}:{head['line_no']} "
            f"claims {head['token']} while {Path(str(orch['report'])).name} "
            f"records verdict={orch['verdict']!r}. The deliverable is the only "
            f"artefact a human reads; it may not report a PASS over the "
            f"orchestrator's FAIL.")
        rep = ConsistencyReport(
            str(run_dir), str(deliverable),
            "DELIVERABLE_CONTRADICTS_ORCHESTRATOR", "FAIL", reason, head, orch)
        rep.blocking.append(
            f"deliverable  {deliverable}:{head['line_no']}  "
            f"[{head['recogniser']}]  {head['line']!r}  -> {head['token']}")
        rep.blocking.append(
            f"orchestrator {orch['report']}  verdict={orch['verdict']!r}"
            + (f"  halted_at={orch['halted_at']!r}" if orch["halted_at"] else "")
            + (f"\n             verdict_note={orch['verdict_note']!r}"
               if orch["verdict_note"] else ""))
        rep.blocking.append(
            "ACTION: re-derive the deliverable's headline FROM the orchestrator "
            "verdict read LAST, or correct the orchestrator — but the two may "
            "not ship disagreeing.")
        if _waiver_count(run_dir) > 0:
            rep.state = "DELIVERABLE_CONTRADICTS_ORCHESTRATOR_WAIVED"
            rep.verdict = "PASS"
            rep.reason = (
                f"{reason} WAIVED under '{WAIVER_KEY}' in waivers.json — "
                f"the contradiction is disclosed, not hidden; see "
                f"rep.blocking for the underlying evidence this waiver "
                f"covers.")
        return rep

    if hp == "FAIL" and op == "PASS":
        return ConsistencyReport(
            str(run_dir), str(deliverable), "DELIVERABLE_STRICTER", "PASS",
            f"{deliverable.name}:{head['line_no']} reports {head['token']} while "
            f"{Path(str(orch['report'])).name} records {orch['verdict']!r} — the "
            f"deliverable UNDER-claims. Not a contradiction in the escape "
            f"direction: an agent may downgrade for a reason the orchestrator "
            f"cannot see. Recorded, not failed.", head, orch)

    # vibe-ic#897 — DO NOT SAY "AGREES" WHEN A SECOND OPINION WAS LOST.
    # An audit file that exists but did not parse (missing `verdict` key,
    # empty, truncated, malformed) used to collapse into the same `None` as
    # "there is no audit", and this line still claimed agreement — having read
    # ONE record while the run shipped two. Five one-file edits each silenced
    # it at rc=0. The verdict stays PASS (an unreadable record is not evidence
    # of contradiction, and failing here would adjudicate a question this gate
    # has just said it cannot put) but the claim is now HONEST about what it
    # actually compared, and the unreadable path is named.
    if orch.get("audit_unreadable"):
        return ConsistencyReport(
            str(run_dir), str(deliverable), "CONSISTENT", "DISCLOSED",
            f"{deliverable.name}:{head['line_no']} headline {head['token']} "
            f"agrees in polarity with "
            f"{Path(str(orch['report'])).name} verdict {orch['verdict']!r} "
            f"({hp}) — but the completion audit at "
            f"{', '.join(orch['audit_unreadable'])} EXISTS AND DID NOT PARSE, "
            f"so the second opinion this gate exists to consult was NOT read. "
            f"Comparison made against one record, not two.", head, orch)

    return ConsistencyReport(
        str(run_dir), str(deliverable), "CONSISTENT", "PASS",
        f"{deliverable.name}:{head['line_no']} headline {head['token']} agrees "
        f"in polarity with {Path(str(orch['report'])).name} verdict "
        f"{orch['verdict']!r} ({hp})", head, orch)


def report_to_dict(rep: ConsistencyReport) -> dict:
    return {"run_dir": rep.run_dir, "deliverable": rep.deliverable,
            "state": rep.state, "verdict": rep.verdict, "reason": rep.reason,
            "headline": rep.headline, "orchestrator": rep.orchestrator,
            "blocking": rep.blocking, "rc": rep.rc}


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Refuse a deliverable whose headline verdict contradicts "
                    "the orchestrator JSON it claims to summarise.")
    ap.add_argument("run_dir")
    ap.add_argument("--result", default=None,
                    help="deliverable path (default <run_dir>/RESULT.md)")
    ap.add_argument("--json", default=None, help="write the verdict JSON here")
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"ERROR: not a directory: {run_dir}")
        return 2

    rep = check(run_dir, result=Path(args.result) if args.result else None)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(report_to_dict(rep), indent=2, ensure_ascii=False) + "\n")

    if rep.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR":
        print(f"FAIL: deliverable_verdict_consistency_check — {rep.reason}")
        for b in rep.blocking:
            print(f"  - {b}")
    elif rep.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR_WAIVED":
        print(f"PASS_WITH_WAIVER: deliverable_verdict_consistency_check — "
              f"{rep.reason}")
        for b in rep.blocking:
            print(f"  - {b}")
    else:
        tag = {"PASS": "PASS", "SKIP": "SKIP",
           "DISCLOSED": "DISCLOSED"}[rep.verdict]
        print(f"{tag}: deliverable_verdict_consistency_check — {rep.reason}")
    return rep.rc


if __name__ == "__main__":
    raise SystemExit(main())
