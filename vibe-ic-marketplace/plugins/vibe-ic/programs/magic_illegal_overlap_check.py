#!/usr/bin/env python3
"""magic_illegal_overlap_check — read the EXTRACTION tool's own error channel and gate it at zero, before LVS.

ENFORCEMENT: blocking

WHAT WAS MISSING
================
Magic's extractor refuses to connect two tile types that the technology says
must not touch, and when it finds such geometry it emits, verbatim (its own
format string, `tclmagic.so`)::

    Illegal overlap between %s and %s (types do not connect)

and files the offending rectangle as a FEEDBACK AREA. The transcript then says
`%d problems occurred.  See feedback entries.` — the tool is pointing at a
channel, not at itself. Nothing in this plugin read that channel. Measured on
origin/main at 397b3f25f, in the container::

    $ grep -rEil "illegal.{0,3}overlap" vibe-ic-marketplace/plugins/vibe-ic/
    FILE COUNT: 0
    $ grep -rEl "feedback\\.txt" .          # magic's feedback dump, whole repo
    COUNT: 0

`magic_extract_spice_emit` validates that the TCL we EMIT contains `extract all`
and `ext2spice lvs` — the commands we SENT. The four LVS-side programs
(`lvs_report_check`, `lvs_tapeout_signoff_check`, `lvs_verdict_tokens`,
`lvs_power_aware_extract_tcl`) all read netgen's verdict. Between the two there
was no reader of what magic said BACK.

WHY THAT MATTERS AND NOT ONLY IN THEORY
=======================================
An illegal overlap is a statement that the extractor could not decide what the
layout means at that rectangle. Whatever `.subckt` it went on to write is a
netlist for a design the layout does not describe. netgen then compares that
netlist against the gate netlist and can report `Circuits match uniquely` — a
clean LVS certificate over an extraction that told us, in its own words, that it
did not understand the layout. The design is dead and the report is clean.

The runner already guards the FLOOD case (`_LVS_EXT_ERROR_FAIL_CEILING`, 1000
parsed from the `N errors` summary line). That is a different question, read off
a different channel, at a different threshold: it asks "did the extraction
collapse", from the transcript, at 1000. This asks "did the extractor refuse a
rectangle", from the feedback areas, at 0 — the threshold LibreLane's
`Checker.IllegalOverlap` uses, and the only defensible one, because ONE
undecidable rectangle is one place the netlist is fiction.

THE TWO TRAPS, AND WHERE EACH IS HANDLED
========================================
1. ABSENT IS NOT ZERO. `feedback save` writes an EMPTY file when there are no
   feedback areas — verified against magic 8.3.681 in the container image: with
   `feedback count` == 0 the saved file is 0 bytes and exists. So an empty file
   is a MEASURED zero and an absent file is an UNMEASURED nothing, and the two
   are not the same fact. This gate FAILs (`EXTRACTION_FEEDBACK_ABSENT`)
   whenever an extraction demonstrably ran and its feedback file is not there.
   It reports rc 2 — the repo's disclosed VACUOUS code — only when there is no
   extraction in scope at all, i.e. there is no run for the question to be about.
   The difference is decided on EVIDENCE OF AN EXTRACTION (the transcript, the
   recipe, or the extracted netlist), never on the absence of the answer.

2. TWO INDEPENDENT COUNTS, AND THEY MUST AGREE. The file is counted twice:
   `string_count` is the raw marker occurrences over the whole text (LibreLane's
   `count_occurences`), and `structural_count` is the marker occurrences inside
   the messages of records this module actually PARSED — a `feedback add "…"
   <style>` line carrying a bounding box, which is magic's own save format::

       box 20 20 35 40
       feedback add "Illegal overlap between nwell and pdiff" pale

   `structural_count` is a subset of `string_count` by construction, so they
   agree iff every marker in the file sits inside a record the parser could
   read. A truncated dump, a `feedback add` whose `box` line was lost, or a save
   format this parser does not know all break that equality — and each of those
   is a case where the structural view would UNDERCOUNT and could report a clean
   0 over a file that says otherwise. A disagreement is therefore an ERROR
   finding in its own right (`FEEDBACK_COUNT_DISAGREEMENT`) and the verdict is
   taken from the LARGER of the two. `record_count` — the number of overlap
   feedback AREAS — is published beside them because that is the number an
   engineer acts on, but it is never the number the gate is decided from.

NOT DETERMINED BEATS A GUESS. A feedback file that exists and cannot be read, or
one whose text contains the marker while no record parses at all, yields a FAIL
with a `null` metric — never a 0. Publishing 0 for a count nobody took is the
same defect one layer up.

THE METRIC
==========
Published through `step_metrics.emit` — the repo's one metrics channel, whose
first rule is that a metric is emitted by the program that COMPUTED it and never
re-parsed from a log — into `reports/metrics/31.json`::

    "31__drv__magic_illegal_overlap__violation_count": 0
    "31__drv__magic_illegal_overlap__record_count": 0
    "31__drv__magic_illegal_overlap__determined": true

The `violation_count` tail is what `step_metrics.DIRECTIONS` reads, so a run-to-
run `diff` grades a rise as `worse` rather than `undeclared`. When the count is
NOT DETERMINED the value is `null` and `determined` is `false`, so a differ can
never read "we could not look" as "it was clean".

WIRING
======
* `phase3_one_shot_runner._run_extraction_lvs` spawns this gate INLINE, between
  the magic extraction and netgen, and returns a FAIL StepResult on a non-zero
  exit — so an extraction that produced illegal overlaps cannot reach netgen at
  all, let alone a clean sign-off report. That is what `ENFORCEMENT: blocking`
  above is claiming, and `flow_gate_enforcement_audit` is what checks the claim.
* `flow/phase1_phase2_phase3.yaml` step 31 declares it in `gate.all_of`,
  positioned BEFORE the `lvs_report_check` clause, so the compliance audit reads
  the same evidence in the same order.

chip-AGNOSTIC: no IC, vendor, PDK or process literal appears or can affect any
branch. The only tool literal is magic's own message text, which is what the
channel IS.

Unit-tested in `programs/tests/test_magic_illegal_overlap_check.py`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _vacuous_exit as _ve  # noqa: E402
import step_metrics as _sm  # noqa: E402

GATE = "magic_illegal_overlap_check"

#: The flow step this gate belongs to — Physical Verification (DRC+LVS+ERC).
FLOW_STEP = 31

#: Magic's own literal, from its format string
#: `Illegal overlap between %s and %s (types do not connect)`. Matched
#: CASE-SENSITIVELY and deliberately: it is the tool's text, not a description
#: of it, and a case-insensitive match would also count prose that merely talks
#: about the check. A case-insensitive count is taken as well, purely so that a
#: future magic that changed the spelling is VISIBLE (`MARKER_CASE_DRIFT`)
#: rather than silently reported as clean.
MARKER = "Illegal overlap"

#: Zero, and it is not a tunable. One rectangle the extractor refused to decide
#: is one place the emitted netlist describes a design that is not the layout.
THRESHOLD = 0

#: Where the extraction step lives, and the feedback dumps it may carry.
#: `extract_feedback.txt` is what this repo's recipe writes; `feedback.txt` is
#: the LibreLane-shaped name, accepted so a tree produced by that flow is read
#: rather than reported as absent.
EXTRACTED_REL = "phase3/stage3/extracted"
FEEDBACK_NAMES: Tuple[str, ...] = ("extract_feedback.txt", "feedback.txt")

#: Evidence that an extraction RAN. Any one of these makes an absent feedback
#: file a FAIL rather than a vacuous skip. Globs, relative to the extraction
#: directory: the transcript the recipe tees, the recipe itself, and the
#: extracted netlist.
EXTRACTION_EVIDENCE_GLOBS: Tuple[str, ...] = (
    "ext2spice.log", "ext2spice_*.tcl", "*_extracted.sp", "*_extracted.spice",
)

#: THE SECOND CHANNEL, and the reason it is here rather than left implicit.
#: What is MEASURED about magic 8.3.681 in this image: the binary carries the
#: exact format string `Illegal overlap between %s and %s (types do not
#: connect)`, it reports `%d problems occurred.  See feedback entries.`, and
#: `feedback save` writes the areas in the `box` + `feedback add` pairs this
#: module parses. What is NOT measured here: a LIVE reproduction of an illegal
#: overlap landing in the feedback list, because magic's `paint` resolves type
#: conflicts at paint time — five deliberately contradictory pairs (ndiff/pdiff,
#: ndiffc/pdiffc, poly/ndiff, ntap/ptap, nwell/pwell) all extracted with
#: `feedback count` 0 — and the real trigger is a GDS/CIF read of a conflicting
#: layout, which needs a design this repo does not carry.
#:
#: That gap has ONE failure direction: if a magic build ever reported illegal
#: overlaps to the transcript and NOT to the feedback list, a feedback-only gate
#: would read an empty dump and PASS. So the transcript is read too, as an
#: independent channel, and a marker in one that is missing from the other is a
#: loud disagreement rather than a quiet zero.
TRANSCRIPT_NAMES: Tuple[str, ...] = ("ext2spice.log", "extract.log")

#: Magic's own statement of how many feedback areas it filed. This is the TOOL'S
#: denominator for the dump we are about to read, and it is what turns "the dump
#: is empty" from an assumption into a comparison.
_PROBLEMS_RE = re.compile(r"^\s*(\d+)\s+problems?\s+occurred\b", re.M)

#: A PUBLISHED LVS VERDICT IS ALSO EVIDENCE THAT AN EXTRACTION RAN, and closes
#: the one way an rc-2 vacuous pass could otherwise be manufactured: delete the
#: extraction directory and the gate has "nothing to be about" while
#: `reports/phase3/lvs.rpt` still certifies a match. The implication runs one
#: way and is not arguable — an LVS report means a netlist was compared, that
#: netlist came from an extraction, and that extraction had a feedback channel.
#: If the channel cannot be found, the illegal-overlap count for a design that
#: already holds an LVS certificate is NOT DETERMINED, which is the exact shape
#: this gate exists to refuse. Project-relative, not extraction-relative.
LVS_VERDICT_RELS: Tuple[str, ...] = (
    "reports/phase3/lvs.rpt", "reports/phase3/lvs.json",
    "reports/phase3/lvs_verdict.json",
)

_BOX_RE = re.compile(r"^\s*box\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*$")
_FEEDBACK_RE = re.compile(r'^\s*feedback\s+add\s+"((?:[^"\\]|\\.)*)"(?:\s+(\S+))?\s*$')


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
class Record:
    """One parsed magic feedback area: a message plus the box that located it."""

    __slots__ = ("message", "style", "box", "line")

    def __init__(self, message: str, style: str,
                 box: Optional[Tuple[int, int, int, int]], line: int) -> None:
        self.message = message
        self.style = style
        self.box = box
        self.line = line

    def as_dict(self) -> Dict[str, Any]:
        return {"message": self.message, "style": self.style,
                "box": list(self.box) if self.box else None, "line": self.line}


def parse_feedback(text: str) -> Tuple[List[Record], List[str]]:
    """Parse a magic `feedback save` dump into records, plus structural defects.

    The save format is a pair of lines per area — a `box` giving the rectangle
    followed by `feedback add "<message>" <style>` — verified against magic
    8.3.681. A `feedback add` that arrives with no preceding `box` is recorded
    with `box=None` AND reported as a structural defect: it is exactly the
    truncation shape that would let the structural arm undercount, and this
    module refuses to be the place where that goes unnoticed.

    Unrecognised non-blank, non-comment lines are reported too. Nothing here
    decides a verdict; it only says what could and could not be read.
    """
    records: List[Record] = []
    defects: List[str] = []
    pending: Optional[Tuple[int, int, int, int]] = None
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m_box = _BOX_RE.match(line)
        if m_box:
            if pending is not None:
                defects.append(
                    f"line {n}: a second `box` follows an unconsumed one — the "
                    f"rectangle at line {n - 1} names no feedback area")
            pending = (int(m_box.group(1)), int(m_box.group(2)),
                       int(m_box.group(3)), int(m_box.group(4)))
            continue
        m_fb = _FEEDBACK_RE.match(line)
        if m_fb:
            if pending is None:
                defects.append(
                    f"line {n}: `feedback add` carries no bounding box — the "
                    f"dump is truncated or is not magic `feedback save` output")
            records.append(Record(_unescape(m_fb.group(1)),
                                  m_fb.group(2) or "", pending, n))
            pending = None
            continue
        defects.append(f"line {n}: unrecognised in a feedback dump: "
                       f"{line.strip()[:120]!r}")
    if pending is not None:
        defects.append(
            "the dump ends with a `box` that names no feedback area — "
            "truncated output")
    return records, defects


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")


def count_marker(text: str) -> int:
    """Raw marker occurrences — LibreLane's `count_occurences(f, marker)` arm."""
    return text.count(MARKER)


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def extraction_dir(project: Path, under: Optional[str] = None) -> Path:
    return (project / under) if under else (project / EXTRACTED_REL)


def find_feedback_files(ext_dir: Path) -> List[Path]:
    return [p for p in (ext_dir / name for name in FEEDBACK_NAMES)
            if p.is_file()]


def read_transcripts(ext_dir: Path) -> Tuple[int, Optional[int], List[str]]:
    """``(marker_occurrences, areas_magic_says_it_filed, files_read)``.

    The area count is the MAXIMUM over the `N problems occurred` lines, not the
    sum: a hierarchical extraction emits one line per cell and summing them
    would over-count a total that is then compared against one flat dump. The
    maximum is a LOWER BOUND on what the dump must contain, which is the safe
    direction — it under-claims rather than raising a false alarm, and it still
    catches the case that matters (magic filed areas, the dump has fewer).
    """
    marker = 0
    areas: Optional[int] = None
    read: List[str] = []
    if not ext_dir.is_dir():
        return marker, areas, read
    for name in TRANSCRIPT_NAMES:
        path = ext_dir / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        read.append(name)
        marker += text.count(MARKER)
        for m in _PROBLEMS_RE.finditer(text):
            areas = max(areas or 0, int(m.group(1)))
    return marker, areas, read


def extraction_evidence(project: Path, ext_dir: Path) -> List[str]:
    """Artefacts proving an extraction RAN. Empty means nothing to be about.

    Two independent sources, and the second is the one that cannot be removed
    by deleting a directory: the extraction's own leavings under `ext_dir`, and
    any LVS verdict the project already published (see `LVS_VERDICT_RELS`).
    """
    seen: List[str] = []
    if ext_dir.is_dir():
        for pattern in EXTRACTION_EVIDENCE_GLOBS:
            for p in sorted(ext_dir.glob(pattern)):
                if p.is_file() and p.name not in FEEDBACK_NAMES:
                    seen.append(p.name)
    for rel in LVS_VERDICT_RELS:
        if (project / rel).is_file():
            seen.append(rel)
    return sorted(set(seen))


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #
def check(project: Path, under: Optional[str] = None) -> Dict[str, Any]:
    """Decide the gate over `project`. Returns the report document.

    `passed`/`skipped` are the two booleans `_vacuous_exit` routes the exit code
    and the printed verdict from, so the word and the number cannot disagree.
    """
    ext_dir = extraction_dir(project, under)
    rel_dir = under or EXTRACTED_REL
    evidence = extraction_evidence(project, ext_dir)
    files = find_feedback_files(ext_dir)

    base: Dict[str, Any] = {
        "gate": GATE, "flow_step": FLOW_STEP, "threshold": THRESHOLD,
        "marker": MARKER, "project": str(project),
        "extraction_dir": rel_dir,
        "extraction_evidence": evidence,
        "feedback_files": [p.name for p in files],
        "findings": [],
        "metrics": _metrics(None, None, determined=False),
    }

    # ── Nothing to be about: no extraction here at all. ──────────────────────
    if not files and not evidence:
        base["passed"] = True
        base["skipped"] = True
        base["summary"] = {
            "skipped": True, "reason": "no_extraction_in_scope",
            "files_found": 0,
        }
        base["reason"] = (
            f"no extraction artefact and no feedback dump under {rel_dir} — "
            f"there is no extraction for this gate to be about. This is NOT a "
            f"statement that the extraction was clean.")
        return base

    # ── Trap 1: an extraction ran and its error channel is not there. ────────
    if not files:
        base["passed"] = False
        base["skipped"] = False
        base["findings"].append({
            "rule": "EXTRACTION_FEEDBACK_ABSENT", "severity": "ERROR",
            "message": (
                f"an extraction RAN for this project (evidence: "
                f"{', '.join(evidence)}"
                + ("; note that an LVS verdict is itself proof a netlist was "
                   "extracted and compared" if any(
                       e in LVS_VERDICT_RELS for e in evidence) else "")
                + f") but under {rel_dir} none of "
                f"{', '.join(FEEDBACK_NAMES)} is present, so magic's feedback "
                f"channel was never dumped or was lost. `feedback save` writes "
                f"an EMPTY file when there are no feedback areas, so a clean "
                f"extraction leaves a 0-byte file HERE — an absent file is "
                f"therefore not a measured zero, it is an unmeasured nothing. "
                f"The illegal-overlap count is NOT DETERMINED and no LVS "
                f"verdict downstream of this extraction can be trusted. Add "
                f"`feedback save <dir>/{FEEDBACK_NAMES[0]}` to the extraction "
                f"recipe and re-extract."),
        })
        # The dump is gone, but the OTHER channel may still be here — and when
        # it is, the failure can name the actual overlaps instead of only the
        # missing file. Both are ERROR and both FAIL; this is about handing
        # triage the count it can act on rather than a second "look elsewhere".
        t_count, t_areas, t_read = read_transcripts(ext_dir)
        base["transcripts_read"] = t_read
        if t_count > 0:
            base["findings"].insert(0, {
                "rule": "MAGIC_ILLEGAL_OVERLAP", "severity": "ERROR",
                "message": (
                    f"the extraction TRANSCRIPT ({', '.join(t_read)}) carries "
                    f"{t_count} occurrence(s) of {MARKER!r}, against a "
                    f"threshold of {THRESHOLD}. The feedback dump that would "
                    f"give each one a rectangle is absent, so this count is a "
                    f"FLOOR — the transcript is a log, not the tool's own area "
                    f"list. Re-extract with `feedback save` to localise them."),
            })
            base["counts"] = {"string_count": 0, "structural_count": 0,
                              "record_count": 0, "case_insensitive_count": 0,
                              "transcript_count": t_count,
                              "areas_reported_by_tool": t_areas,
                              "records_parsed": 0, "gate_count": t_count,
                              "determined": False}
        base["summary"] = {"skipped": False, "reason": "feedback_absent",
                           "files_found": 0}
        base["reason"] = (
            "extraction feedback channel absent — NOT DETERMINED"
            + (f"; the transcript alone shows at least {t_count} illegal "
               f"overlap(s)" if t_count else ""))
        return base

    # ── Read and count. ──────────────────────────────────────────────────────
    string_count = 0
    structural_count = 0
    record_count = 0
    ci_count = 0
    per_file: List[Dict[str, Any]] = []
    overlaps: List[Dict[str, Any]] = []
    unreadable: List[str] = []
    structural_defects: List[str] = []

    for path in files:
        try:
            text = path.read_text(errors="replace")
        except OSError as exc:
            unreadable.append(f"{path.name}: {exc.__class__.__name__}: {exc}")
            continue
        f_string = count_marker(text)
        f_ci = len(re.findall(re.escape(MARKER), text, re.IGNORECASE))
        records, defects = parse_feedback(text)
        f_records = [r for r in records if MARKER in r.message]
        f_structural = sum(r.message.count(MARKER) for r in records)
        string_count += f_string
        ci_count += f_ci
        structural_count += f_structural
        record_count += len(f_records)
        structural_defects += [f"{path.name}: {d}" for d in defects]
        overlaps += [dict(r.as_dict(), file=path.name) for r in f_records]
        per_file.append({
            "file": path.name, "bytes": len(text),
            "string_count": f_string, "structural_count": f_structural,
            "record_count": len(f_records),
            "records_parsed": len(records),
            "structural_defects": len(defects),
        })

    base["per_file"] = per_file
    base["overlaps"] = overlaps[:50]
    base["structural_defects"] = structural_defects[:50]

    # Every candidate file unreadable: the channel exists and we cannot read it.
    if unreadable and not per_file:
        base["passed"] = False
        base["skipped"] = False
        base["findings"].append({
            "rule": "EXTRACTION_FEEDBACK_UNREADABLE", "severity": "ERROR",
            "message": (f"the extraction feedback dump exists but could not be "
                        f"read ({'; '.join(unreadable)}) — the illegal-overlap "
                        f"count is NOT DETERMINED, which is not zero."),
        })
        base["summary"] = {"skipped": False, "reason": "feedback_unreadable",
                           "files_found": len(files)}
        base["reason"] = "extraction feedback unreadable — NOT DETERMINED"
        return base
    for u in unreadable:
        base["findings"].append({
            "rule": "EXTRACTION_FEEDBACK_UNREADABLE", "severity": "ERROR",
            "message": f"{u} — NOT DETERMINED for this file, not zero."})

    determined = not unreadable

    # ── Trap 2: the two counts must agree, and a mismatch is loud. ───────────
    if structural_count > string_count:
        # Structural is a subset of the raw text by construction; if this ever
        # fires the parser is manufacturing occurrences. Tripwire, not a live
        # filter — its measured blast radius today is zero, and it exists so
        # that a future parser change cannot quietly invert the safe direction.
        base["findings"].append({
            "rule": "COUNT_INVARIANT_BROKEN", "severity": "ERROR",
            "message": (f"structural_count={structural_count} exceeds "
                        f"string_count={string_count}, which is impossible for "
                        f"a subset — the parser is over-counting and neither "
                        f"number can be trusted."),
        })
        determined = False
    elif structural_count != string_count:
        base["findings"].append({
            "rule": "FEEDBACK_COUNT_DISAGREEMENT", "severity": "ERROR",
            "message": (
                f"the two counts DISAGREE: the raw text carries {string_count} "
                f"occurrence(s) of {MARKER!r} but only {structural_count} sit "
                f"inside a feedback record this module could parse "
                f"({record_count} record(s) over "
                f"{sum(p['records_parsed'] for p in per_file)} parsed). "
                f"{len(structural_defects)} structural defect(s) were seen"
                + (f": {structural_defects[0]}" if structural_defects else "")
                + ". The structural view UNDERCOUNTS here, so a gate reading "
                "it alone would report a cleaner extraction than the file "
                "describes. The verdict below is taken from the LARGER of "
                "the two."),
        })

    # A dump the parser could only partly read, whose unreadable part carries
    # no marker, still PASSES — the raw-string arm reads the WHOLE file and does
    # not depend on the parser, so nothing with the marker in it can hide behind
    # a parse defect. It must not pass SILENTLY, though: a PASS over a dump this
    # module could not fully read is a weaker statement than a PASS over one it
    # could, and the report has to say which it is.
    if structural_defects:
        base["findings"].append({
            "rule": "FEEDBACK_PARTIALLY_UNPARSED", "severity": "WARNING",
            "message": (
                f"{len(structural_defects)} line(s) of the feedback dump are "
                f"not in the `box` + `feedback add \"…\" <style>` save format "
                f"this module parses (first: {structural_defects[0]}). The "
                f"raw-text count covers them regardless — it does not use the "
                f"parser — so no marker can hide here; but the structural view "
                f"of this dump is incomplete and any PASS below rests on the "
                f"string arm alone."),
        })

    # ── CHANNEL 2: the transcript, and the tool's own count of its areas. ───
    transcript_count, areas_reported, transcripts_read = read_transcripts(
        ext_dir)
    records_parsed = sum(p["records_parsed"] for p in per_file)
    base["transcripts_read"] = transcripts_read

    if transcript_count > 0 and string_count == 0:
        base["findings"].append({
            "rule": "CHANNEL_DISAGREEMENT", "severity": "ERROR",
            "message": (
                f"the extraction TRANSCRIPT carries {transcript_count} "
                f"occurrence(s) of {MARKER!r} ({', '.join(transcripts_read)}) "
                f"while the feedback dump carries none. The two channels "
                f"disagree about the same extraction, so the dump did not "
                f"capture what the tool said. Counted from the transcript."),
        })
    if areas_reported is not None and records_parsed < areas_reported:
        base["findings"].append({
            "rule": "FEEDBACK_DUMP_INCOMPLETE", "severity": "ERROR",
            "message": (
                f"magic reported `{areas_reported} problems occurred.  See "
                f"feedback entries.` but the dump this gate read holds only "
                f"{records_parsed} feedback record(s). The tool's own count of "
                f"what it filed exceeds what was saved, so the dump is "
                f"truncated, stale, or was written before the areas were — the "
                f"illegal-overlap count taken from it is a floor, not a "
                f"measurement, and a 0 from it would be meaningless."),
        })
        determined = False

    if ci_count != string_count:
        base["findings"].append({
            "rule": "MARKER_CASE_DRIFT", "severity": "WARNING",
            "message": (
                f"a case-insensitive search finds {ci_count} occurrence(s) of "
                f"{MARKER!r} against {string_count} case-sensitive — the tool "
                f"may have changed the spelling of its own message, in which "
                f"case this gate is reading a channel that has moved. Reported "
                f"rather than silently absorbed."),
        })

    count = max(string_count, structural_count, transcript_count)
    base["counts"] = {
        "string_count": string_count,
        "structural_count": structural_count,
        "record_count": record_count,
        "case_insensitive_count": ci_count,
        "transcript_count": transcript_count,
        "areas_reported_by_tool": areas_reported,
        "records_parsed": records_parsed,
        "gate_count": count,
        "determined": determined,
    }
    base["metrics"] = _metrics(count if determined else None,
                               record_count if determined else None,
                               determined=determined)

    if not determined:
        base["passed"] = False
        base["skipped"] = False
        base["summary"] = {"skipped": False, "reason": "count_not_determined",
                           "files_found": len(per_file)}
        base["reason"] = (
            f"the illegal-overlap count is NOT DETERMINED over "
            f"{len(per_file)} feedback file(s) — see findings. NOT DETERMINED "
            f"is not zero and cannot certify an extraction.")
        return base

    if count > THRESHOLD:
        base["passed"] = False
        base["skipped"] = False
        base["findings"].insert(0, {
            "rule": "MAGIC_ILLEGAL_OVERLAP", "severity": "ERROR",
            "message": (
                f"the extractor reported {count} illegal overlap(s), against a "
                f"threshold of {THRESHOLD}. Counted from: feedback dump "
                f"string={string_count} structural={structural_count} "
                f"({record_count} area(s)), transcript={transcript_count} — "
                f"the verdict takes the LARGEST, so a channel that lost them "
                f"cannot lower it. Each one is geometry the extractor refused to "
                f"connect, so the `.subckt` it went on to write describes a "
                f"design the layout does not. An LVS run over that netlist can "
                f"report a unique match and mean nothing. Fix the layout at "
                f"the reported rectangle(s) and re-extract; do not compare."),
        })
        base["summary"] = {"skipped": False, "reason": "illegal_overlaps",
                           "files_found": len(per_file)}
        base["reason"] = (f"{count} illegal overlap(s) in the extraction "
                          f"feedback (threshold {THRESHOLD})")
        return base

    base["passed"] = True
    base["skipped"] = False
    base["summary"] = {"skipped": False, "reason": "clean",
                       "files_found": len(per_file)}
    base["reason"] = (
        f"0 illegal overlap(s) across BOTH channels: {len(per_file)} feedback "
        f"file(s) ({', '.join(p['file'] for p in per_file)}, {records_parsed} "
        f"record(s) parsed, raw and structural counts agreeing at 0) and "
        + (f"{len(transcripts_read)} transcript(s) "
           f"({', '.join(transcripts_read)}, 0 marker occurrences"
           + (f", tool reported {areas_reported} feedback area(s) and the dump "
              f"holds {records_parsed}" if areas_reported is not None else "")
           + ")" if transcripts_read else
           "NO transcript in scope, so that channel is silent here rather than "
           "clean")
        + ". This is a MEASURED zero — the dump exists and was read.")
    return base


def _metrics(count: Optional[int], records: Optional[int], *,
             determined: bool) -> Dict[str, Any]:
    """The published metric. `None`, never 0, when the count was not taken."""
    p = f"{_sm.normalize_step(FLOW_STEP)}__drv__magic_illegal_overlap"
    return {
        f"{p}__violation_count": count,
        f"{p}__record_count": records,
        f"{p}__determined": determined,
    }


def publish_metrics(project: Path, report: Dict[str, Any]) -> Optional[Path]:
    """Emit the metric through the repo's one metrics channel. Best effort."""
    try:
        return _sm.emit(project, FLOW_STEP, dict(report["metrics"]),
                        domain="drv")
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Gate magic's extraction feedback channel at zero illegal "
                    "overlaps, between extraction and LVS.")
    ap.add_argument("project_dir")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the report document here")
    ap.add_argument("--under", default=None,
                    help=f"extraction directory relative to the project "
                         f"(default {EXTRACTED_REL})")
    ap.add_argument("--no-metrics", action="store_true",
                    help="do not write reports/metrics/<step>.json")
    a = ap.parse_args(argv)

    project = Path(a.project_dir).resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return _ve.RC_VACUOUS

    report = check(project, a.under)

    if not a.no_metrics:
        written = publish_metrics(project, report)
        report["metrics_file"] = str(written) if written else None

    if a.json_out:
        out = Path(a.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    passed, skipped = bool(report["passed"]), bool(report["skipped"])
    print(_ve.verdict_line(GATE, passed, skipped,
                           _ve.skip_reason(report.get("summary"))),
          file=sys.stdout if passed and not skipped else sys.stderr)
    if report.get("reason"):
        print(f"  {report['reason']}",
              file=sys.stdout if passed and not skipped else sys.stderr)
    for f in report["findings"]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}",
              file=sys.stderr)
    for o in report.get("overlaps", [])[:10]:
        print(f"    {o['file']}:{o['line']} box={o['box']} {o['message']}",
              file=sys.stderr)
    if skipped:
        _ve.announce_vacuous(GATE, _ve.skip_reason(report.get("summary")))
    return _ve.exit_code(passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
