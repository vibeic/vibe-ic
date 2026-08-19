#!/usr/bin/env python3
"""magic_extract_feedback_check.py — read the EXTRACTION tool's error channel.

THE HOLE THIS FILLS
===================
Magic's SPICE extraction has two output channels. One is the netlist. The
other is ``feedback.txt`` — the file Magic writes when the geometry it was
asked to extract does not make electrical sense. The most consequential entry
in it is ``Illegal overlap``: two device or interconnect layers overlapping in
a way the technology cannot resolve, which in many cases IS an undetected
short. The netlist is still emitted; it is simply a netlist of a circuit that
cannot exist.

This plugin read only the first channel. MEASURED on the tree this landed
against (``git rev-parse origin/main`` -> 0d7b6428a)::

    $ grep -rEil 'illegal.{0,3}overlap' .            # whole plugin, sans .git
    (no output)                       FILE COUNT: 0
    $ grep -rEil 'feedback\\.txt' vibe-ic-marketplace/plugins/vibe-ic/
    (no output)                       FILE COUNT: 0

``magic_extract_spice_emit.py`` validates that the TCL we EMIT contains
``extract all`` and ``ext2spice lvs`` — the commands we sent, never the
complaints that came back. The four LVS-side programs read netgen's verdict
and only netgen's verdict: ``lvs_report_check`` (0 hits for `feedback`),
``lvs_tapeout_signoff_check`` (7 `netgen`, 0 `feedback`), ``lvs_verdict_tokens``
(65 `netgen`, 0 `feedback`), ``lvs_power_aware_extract_tcl`` (3 `netgen`, and
its one `overlap` is a PDN comment). So an extraction that produced illegal
overlaps reached a clean LVS sign-off report with nothing in the flow ever
having opened the file that said so.

ENFORCEMENT: advisory
=====================
That declaration is about ONE thing — whether `phase3_one_shot_runner` spawns
this gate INLINE and lets its exit status reach a control-flow decision. It
does not, so `flow_gate_enforcement_audit` would classify it AUDIT_ONLY no
matter what this docstring said, and declaring `blocking` would be a
contradiction the audit correctly rejects. Silence is not a decision here
(#886), so the decision is stated.

The gate is NOT inert: `flow_compliance_check` runs step 31's `gate.all_of`
and a non-zero exit fails that step, which is exactly the enforcement level of
the LVS sign-off gate standing immediately behind it. Parity with the gate it
protects is the point — an extraction error channel read less seriously than
the LVS verdict it precedes would not close the hole.

WHY IT IS NOT IN `_DECLARED_SIGNOFF_GATES`. That table is the inline, genuinely
blocking one, and `_run_declared_signoff_gate` routes rc 2 to `BLOCKED` —
non-green — by design (#544: a declared sign-off that returned no verdict is
not neutral). Every input this program can be pointed at in this repository
takes the rc-2 NOT-CHECKED path (see BLAST RADIUS below), so adding the row
today would move runs to BLOCKED over an extraction they never performed — a
false alarm bought with no detection. The row belongs there once a run
actually extracts; until then the honest wiring is the one declared above.

The count of runs that would flip is NOT DETERMINED here. `phase3_one_shot_
runner` documents a blast-radius sweep over "14 published phase-3 run-roots
under benchmark-data/ic"; `git ls-files benchmark-data` returns 0 files at
this head, so that corpus is not in this repository and the sweep could not be
re-run. What is measured is stated below; the number of externally-published
runs affected is not, and is not guessed.

WHAT UPSTREAM DOES, AND THE ONE THING IT DOES NOT
=================================================
LibreLane (@ bf8cc13c; corroborated line-for-line against the installed
distribution in the EDA image) counts the string at ``steps/magic.py:642``,
re-counts it from parsed bounding boxes at ``:659-666``, classifies it at
``common/drc.py:263-268``, publishes ``magic__illegal_overlap__count``, and
gates it at threshold 0 with ``Checker.IllegalOverlap``
(``steps/checker.py:216-234``) between ``Magic.SpiceExtraction`` and
``Checker.LVS`` (``flows/classic.py:111-114``). That is the design this
program adopts, and the wiring position it copies.

Two places it is deliberately STRICTER, both of them this repo's standing
"could not look" == "looked and it was fine" defect:

1. ABSENT IS NOT ZERO.  ``MetricChecker.run`` (checker.py) ends::

       else:
           self.warn(
               f"The {self.metric_description} metric was not found. "
               f"Are you sure the relevant step was run?"
           )
       return {}, {}

   An absent metric WARNS and returns clean. So does an absent feedback file,
   one level up, if the extraction step never ran. Here, an extraction run
   whose feedback file is missing or unreadable is rc 1 with its OWN finding
   (``FEEDBACK_ABSENT`` / ``FEEDBACK_UNREADABLE``), distinct in code and in
   message from the overlap finding itself. The only path to "nothing to say"
   is NO extraction run anywhere in scope, which is rc 2 and is DISCLOSED as
   NOT CHECKED, never as a pass.

2. THE TWO COUNTS MUST AGREE, OUT LOUD.  Upstream computes the string count,
   publishes it, then silently OVERWRITES the metric with the parsed count at
   ``magic.py:666`` — and on a parse failure keeps whichever it had, warning
   only. The two counts answer the same question by different routes and are
   not equivalent: ``count_occurences`` is ``grep -c``, i.e. it counts LINES
   containing the substring, so two ``feedback add`` records emitted on one
   line count 1 by string and 2 by structure. A disagreement means one of the
   two readings of the error channel is wrong, and which one is not knowable
   from here. This program reports BOTH, fails on the disagreement
   (``COUNT_DISAGREEMENT``), and takes ``max()`` for the verdict — never the
   smaller of two numbers it has just admitted it cannot reconcile.

   A feedback file that cannot be PARSED is likewise rc 1
   (``FEEDBACK_UNPARSEABLE``) and not a silent fallback to the string count: a
   channel we could not read is not a channel that said zero.

WHAT COUNTS AS AN EXTRACTION RUN
================================
The rc 1 / rc 2 split above rests entirely on this predicate, so it is
structural and named rather than inferred. A directory is an extraction run
when it holds at least one of Magic's own extraction products:

* ``feedback.txt``            — the channel itself
* ``cif_scale.txt``           — written beside it by LibreLane's
                                ``Magic.SpiceExtraction`` and by nothing else
* ``*.ext``                   — Magic's raw extraction database
* a ``.spice``/``.sp``/``.cir`` file whose header carries Magic's own
  ``ext2spice`` provenance line (``... file created from <cell>.ext ...``)

A ``.spef`` is NOT in that list and must not be: SPEF here comes from the
router's RC extraction, which has no ``feedback.txt`` and never emits one.
Treating it as a Magic run would manufacture a ``FEEDBACK_ABSENT`` failure on
every routed design in the corpus.

THE SCOPE CANNOT BE USED TO BLIND THE GATE
==========================================
The flow wires this with ``--under phase3/stage3``, the declared home of the
extraction artefacts. A scoped gate is silenceable without editing a line of
its own code — point the scope somewhere an extraction never lands and it
returns rc 2 forever. So when the SCOPED scan finds NO extraction run at all,
the whole project is rescanned, and any run found outside the scope is
``SCOPE_MISSES_EXTRACTION``, rc 1, named. It fires only in the blinding case:
a scope that found runs is never rescanned, so a correctly-scoped project pays
nothing for it and sees no extra findings. A ``--under`` path that does not
exist takes the same route — it is not an error by itself (a Phase-1/2-only
project has no ``phase3/stage3``), but it cannot buy silence over an
extraction that happened elsewhere.

BLAST RADIUS, MEASURED RATHER THAN ASSERTED
===========================================
Over the tracked tree at this head: ``git ls-files`` matches 0 files named
``feedback.txt``, 0 named ``cif_scale.txt`` and 0 with a ``.ext`` suffix, and
``git ls-files benchmark-data`` returns 0 — the run corpus that older
docstrings sweep against is not in this repository, so "no run changes
verdict" is asserted about what is HERE and about nothing else.

What is here was swept, as the broadest available false-positive test: the
program was pointed at the repository root and at the plugin root as if each
were a project, with and without the ``--under phase3/stage3`` the flow wires.
All four invocations return rc 2 NOT_CHECKED with ``extraction_run_count: 0``
— including over the tracked ``.spice`` and ``.spef`` fixtures under
``programs/tests/fixtures``, none of which is mistaken for a Magic extraction
run. Zero false positives, and zero verdicts moved.

The gate becomes load-bearing the moment a run actually extracts, which is the
point at which it must already be wired.

WHY rc 2 IS TOLERABLE HERE AND IS NOT ELSEWHERE
===============================================
``flow_compliance_check._check_program_exit_zero`` credits rc 2 from a
``program_exit_zero`` gate as a disclosed VACUOUS_PASS unconditionally, so rc 2
turns this step green. That is correct for "this project ran no extraction" —
there is genuinely no extraction to gate, and the LVS gates beside this one
still have to account for the netlist. It would NOT be correct for "extraction
ran and its error channel is missing", which is why that case is rc 1 and not
rc 2. The two are separated by the predicate above and by nothing softer.

METRIC
======
Published through ``step_metrics.emit`` — the schema whose rule 1 is "emitted
by the computer of the number, never re-parsed from a log" — into
``reports/metrics/31.json`` as::

    31__extraction__illegal_overlap_count           # the verdict number, or null
    31__extraction__illegal_overlap_string_count
    31__extraction__illegal_overlap_parsed_count
    31__extraction__feedback_file_count
    31__extraction__run_count

``illegal_overlap_count`` is ``null``, NOT 0, when nothing was read. A metrics
consumer that cannot tell "zero overlaps" from "no measurement" reproduces the
exact defect this program exists to close, one layer further out. The JSON
report additionally carries the number under upstream's own key
``magic__illegal_overlap__count`` so the two flows' numbers can be diffed
directly.

chip-AGNOSTIC: no IC, vendor, PDK, node or process literal appears here or can
affect the verdict. The only tool-specific strings are Magic's own feedback
grammar and the literal ``Illegal overlap`` it emits.

CLI
===
    magic_extract_feedback_check.py <project> [--json out.json]
    magic_extract_feedback_check.py <project> --under phase3/stage3/extracted
    magic_extract_feedback_check.py <project> --feedback path/to/feedback.txt

Exit codes:
    0 = PASS      (every extraction run in scope read clean at threshold 0)
    1 = FAIL      (overlaps found, or a channel that could not be read/parsed,
                   or the two counts disagree)
    2 = NOT CHECKED (no Magic SPICE-extraction run in scope; disclosed, and
                   the metric is emitted as null)

Unit-tested in ``programs/tests/test_magic_extract_feedback_check.py``.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_text as atomic_write_text  # noqa: E402
import step_metrics as _sm  # noqa: E402

PROGRAM = "magic_extract_feedback_check"
VERSION = "1.0.0"
FLOW_STEP = 31

RC_OK = 0
RC_VIOLATION = 1
RC_NOT_CHECKED = 2

# Magic's own literal. Upstream matches it case-sensitively
# (`count_occurences(f, "Illegal overlap")` and `"Illegal overlap" in rule`),
# and so does this, so the two counts are comparable by construction.
ILLEGAL_OVERLAP = "Illegal overlap"

# Threshold is 0 and is NOT configurable. Upstream exposes
# ERROR_ON_ILLEGAL_OVERLAPS as an off switch; a knob that turns a
# short-detector off is the shape this repo removes, not the shape it adds.
THRESHOLD = 0

FEEDBACK_NAMES = ("feedback.txt",)
FEEDBACK_SUFFIX = ".feedback.txt"

_EXTRACTION_MARKER_NAMES = ("cif_scale.txt",)
_EXTRACTION_MARKER_SUFFIXES = (".ext",)
_SPICE_SUFFIXES = (".spice", ".sp", ".cir")
# Magic's ext2spice writes this provenance line at the head of every netlist it
# emits, e.g. "* NGSPICE file created from top.ext - technology: <tech>".
_EXT2SPICE_PROVENANCE = re.compile(r"file created from\s+\S+\.ext\b", re.I)

_SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules",
              ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache"}


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    details: str = ""


@dataclass
class FeedbackRead:
    """One feedback file, read both ways."""
    path: str
    string_count: Optional[int] = None
    parsed_count: Optional[int] = None
    parse_error: Optional[str] = None
    read_error: Optional[str] = None
    rules: List[str] = field(default_factory=list)

    @property
    def count(self) -> Optional[int]:
        """The verdict number: the LARGER of two counts that may disagree."""
        vals = [v for v in (self.string_count, self.parsed_count)
                if v is not None]
        return max(vals) if vals else None


# --------------------------------------------------------------------------- #
# Channel 1 — the string count (upstream `count_occurences`, i.e. `grep -c`)
# --------------------------------------------------------------------------- #
def count_lines_containing(text: str, needle: str = ILLEGAL_OVERLAP) -> int:
    """Number of LINES containing `needle`. Deliberately line-wise, not
    occurrence-wise: this is the count upstream publishes, and reproducing its
    exact semantics is what makes a disagreement with the parsed count
    meaningful instead of a definitional artefact."""
    return sum(needle in line for line in text.splitlines())


# --------------------------------------------------------------------------- #
# Channel 2 — the parsed count (port of librelane DRC.from_magic_feedback)
# --------------------------------------------------------------------------- #
def parse_magic_feedback(text: str) -> Tuple[int, List[str]]:
    """Walk Magic's feedback grammar; return (illegal-overlap bounding-box
    count, the distinct rule strings seen).

    The grammar, as Magic emits it and as librelane's
    ``common/drc.py:from_magic_feedback`` consumes it, is a flat token stream::

        box <llx> <lly> <urx> <ury>
        feedback add "<rule text>" <style>

    Each ``feedback add`` attaches to the most recently selected ``box``.
    Counting is per attached bounding box, matching upstream's
    ``sum(len(v.bounding_boxes) for v in ... if "Illegal overlap" in
    v.description)``.

    Raises ValueError on any malformed construct. It does NOT recover: a
    feedback stream this cannot walk is one whose overlap count is unknown,
    and an unknown count must not be reported as a number.
    """
    lex = shlex.shlex(text, posix=True)
    lex.wordchars = lex.wordchars + "-+."
    try:
        components = list(lex)
    except ValueError as e:            # unbalanced quote, etc.
        raise ValueError(f"cannot tokenize feedback: {e}") from e

    count = 0
    rules: List[str] = []
    have_box = False
    i = 0
    while i < len(components):
        instruction = components[i]
        i += 1
        if instruction == "box":
            if len(components) - i < 4:
                raise ValueError(
                    "invalid syntax: 'box' command has less than 4 arguments")
            i += 4
            have_box = True
        elif instruction == "feedback":
            if i >= len(components):
                raise ValueError("feedback not given subcommand")
            subcmd = components[i]
            i += 1
            if subcmd != "add":
                raise ValueError(
                    f"unsupported feedback subcommand {subcmd!r}")
            if len(components) - i < 2:
                raise ValueError(
                    "invalid syntax: 'feedback add' command has less than "
                    "2 arguments")
            rule = components[i]
            i += 2                     # rule, then style
            if not have_box:
                raise ValueError(
                    "attempted to add feedback without a box selected")
            if rule not in rules:
                rules.append(rule)
            if ILLEGAL_OVERLAP in rule:
                count += 1
        # Any other leading token is a Magic command this grammar does not
        # model (`load`, `select`, ...). Skipping it is what upstream's
        # while-loop does too: it pops and ignores.
    return count, rules


def read_feedback(path: Path) -> FeedbackRead:
    r = FeedbackRead(path=str(path))
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        r.read_error = f"{type(e).__name__}: {e}"
        return r
    r.string_count = count_lines_containing(text)
    try:
        r.parsed_count, r.rules = parse_magic_feedback(text)
    except ValueError as e:
        r.parse_error = str(e)
    return r


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def _iter_files(root: Path):
    for p in root.rglob("*"):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.is_file():
            yield p


def is_feedback_file(p: Path) -> bool:
    return p.name in FEEDBACK_NAMES or p.name.endswith(FEEDBACK_SUFFIX)


def is_extraction_product(p: Path) -> bool:
    """A Magic SPICE-extraction product. See the module docstring for why a
    `.spef` is deliberately not one."""
    if is_feedback_file(p):
        return True
    if p.name in _EXTRACTION_MARKER_NAMES:
        return True
    if p.suffix in _EXTRACTION_MARKER_SUFFIXES:
        return True
    if p.suffix.lower() in _SPICE_SUFFIXES:
        try:
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                for _ in range(8):
                    line = fh.readline()
                    if not line:
                        break
                    if _EXT2SPICE_PROVENANCE.search(line):
                        return True
        except OSError:
            return False
    return False


def discover(scope: Path) -> Tuple[Dict[Path, List[Path]], List[Path]]:
    """Return ({run_dir: [feedback files in it]}, [all feedback files]).

    A run dir is any directory holding at least one extraction product.
    """
    runs: Dict[Path, List[Path]] = {}
    feedback: List[Path] = []
    for p in _iter_files(scope):
        if not is_extraction_product(p):
            continue
        runs.setdefault(p.parent, [])
        if is_feedback_file(p):
            runs[p.parent].append(p)
            feedback.append(p)
    return ({d: sorted(v) for d, v in sorted(runs.items())}, sorted(feedback))


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
def audit(project: Path, under: Optional[str] = None,
          explicit: Optional[List[str]] = None
          ) -> Tuple[List[Finding], Dict[str, Any]]:
    findings: List[Finding] = []
    stats: Dict[str, Any] = {
        "scope": under or ".",
        "run_count": 0,
        "feedback_file_count": 0,
        "illegal_overlap_count": None,
        "string_count": None,
        "parsed_count": None,
        "runs_without_feedback": [],
        "reads": [],
        "checked": False,
        "scope_exists": True,
    }

    if explicit:
        paths = [Path(p) if Path(p).is_absolute() else project / p
                 for p in explicit]
        runs: Dict[Path, List[Path]] = {}
        feedback: List[Path] = []
        for p in paths:
            runs.setdefault(p.parent, [])
            if p.is_file():
                runs[p.parent].append(p)
                feedback.append(p)
            elif p.exists():
                findings.append(Finding(
                    "ERROR", "FEEDBACK_UNREADABLE",
                    f"declared feedback path is not a file: {p}",
                    details="An explicitly named error channel that is not a "
                            "readable file was NOT read. Nothing about this "
                            "extraction is certified."))
            else:
                findings.append(Finding(
                    "ERROR", "FEEDBACK_ABSENT",
                    f"declared feedback path does not exist: {p}",
                    details="The extraction error channel was named on the "
                            "command line and is not on disk. This is 'could "
                            "not look', which is not 'looked and it was "
                            "fine'."))
        stats["run_count"] = len(runs)
        stats["checked"] = True
    else:
        scope = project if not under else (project / under)
        stats["scope_exists"] = scope.exists()
        if not scope.exists():
            runs, feedback = {}, []
        else:
            scope = scope if scope.is_dir() else scope.parent
            runs, feedback = discover(scope)
        stats["run_count"] = len(runs)

        if not runs:
            # ANTI-BLINDING. A gate can be silenced without touching a line of
            # its own code, by pointing `--under` somewhere an extraction never
            # lands. So when the SCOPED scan finds nothing at all, the whole
            # project is rescanned, and extraction runs living outside the
            # scope are a FAILURE of the wiring, reported by name. This fires
            # only in the blinding case — a scope that found runs is never
            # rescanned, so a correctly-scoped project pays nothing and sees
            # no noise.
            outside = {}
            if under:
                outside, _ = discover(project)
            if outside:
                named = ", ".join(
                    sorted(str(d.relative_to(project))
                           if d.is_relative_to(project) else str(d)
                           for d in outside))
                findings.append(Finding(
                    "ERROR", "SCOPE_MISSES_EXTRACTION",
                    f"--under {under} contains no extraction run, but the "
                    f"project holds {len(outside)}: {named}",
                    details="The scope this gate was given cannot see the "
                            "extraction the project actually performed, so a "
                            "rc-2 NOT CHECKED here would be a pass bought by "
                            "looking in the wrong place. Re-scope the gate or "
                            "move the extraction under the declared layout."))
                return findings, stats
            findings.append(Finding(
                "INFO", "NO_EXTRACTION_RUN",
                f"no Magic SPICE-extraction run found under {scope}",
                details="Looked for feedback.txt / *.feedback.txt / "
                        "cif_scale.txt / *.ext / a .spice|.sp|.cir carrying "
                        "Magic's ext2spice provenance header. None present "
                        "anywhere in the project, so there is no extraction "
                        "whose error channel could be read. NOT CHECKED — "
                        "this is not a clean extraction, it is the absence "
                        "of one."))
            return findings, stats

        stats["checked"] = True
        for d, fbs in runs.items():
            if not fbs:
                rel = str(d.relative_to(project)) if d.is_relative_to(project) \
                    else str(d)
                stats["runs_without_feedback"].append(rel)
                findings.append(Finding(
                    "ERROR", "FEEDBACK_ABSENT",
                    f"extraction run {rel} has no feedback file",
                    details="Magic wrote extraction products here but its "
                            "error channel (feedback.txt) is not on disk, so "
                            "the illegal-overlap count for this run is "
                            "UNKNOWN. An unknown count is not zero."))

    stats["feedback_file_count"] = len(feedback)

    totals_string = 0
    totals_parsed = 0
    any_number = False
    for fb in feedback:
        r = read_feedback(fb)
        rel = str(fb.relative_to(project)) if fb.is_relative_to(project) \
            else str(fb)
        r.path = rel
        stats["reads"].append(asdict(r))

        if r.read_error is not None:
            findings.append(Finding(
                "ERROR", "FEEDBACK_UNREADABLE",
                f"{rel}: cannot read the extraction error channel",
                details=f"{r.read_error}. The file exists and could not be "
                        f"read; its overlap count is UNKNOWN, not zero."))
            continue

        if r.parse_error is not None:
            findings.append(Finding(
                "ERROR", "FEEDBACK_UNPARSEABLE",
                f"{rel}: Magic feedback grammar could not be walked",
                details=f"{r.parse_error}. Upstream warns and silently keeps "
                        f"the string count here; a channel that could not be "
                        f"parsed has an UNKNOWN structured count, and this "
                        f"gate will not certify a number it could not "
                        f"re-derive. String count for this file was "
                        f"{r.string_count}."))

        if r.string_count is not None:
            totals_string += r.string_count
            any_number = True
        if r.parsed_count is not None:
            totals_parsed += r.parsed_count
            any_number = True

        if (r.string_count is not None and r.parsed_count is not None
                and r.string_count != r.parsed_count):
            findings.append(Finding(
                "ERROR", "COUNT_DISAGREEMENT",
                f"{rel}: string count {r.string_count} != parsed count "
                f"{r.parsed_count}",
                details="The same error channel read two ways gives two "
                        "answers, so one of the two readings is wrong and "
                        "which is not knowable from here. Upstream overwrites "
                        "the string count with the parsed one and says "
                        "nothing (steps/magic.py:666). The verdict below uses "
                        "max() — never the smaller of two irreconcilable "
                        "numbers."))

    if any_number:
        stats["string_count"] = totals_string
        stats["parsed_count"] = totals_parsed
        stats["illegal_overlap_count"] = max(totals_string, totals_parsed)

    total = stats["illegal_overlap_count"]
    if total is not None and total > THRESHOLD:
        findings.append(Finding(
            "ERROR", "ILLEGAL_OVERLAP",
            f"{total} illegal overlap(s) reported by the extraction tool "
            f"(threshold {THRESHOLD})",
            details="Magic reported geometry it cannot resolve electrically. "
                    "In many cases an illegal overlap IS an undetected short. "
                    "The extracted netlist was still emitted, so LVS can "
                    "match against it and report clean — this gate sits "
                    "between the two so that cannot happen."))

    return findings, stats


def build_report(findings: List[Finding], stats: Dict[str, Any],
                 project: str) -> Dict[str, Any]:
    errors = [f for f in findings if f.severity == "ERROR"]
    if errors:
        verdict, rc = "FAIL", RC_VIOLATION
    elif not stats["checked"]:
        verdict, rc = "NOT_CHECKED", RC_NOT_CHECKED
    else:
        verdict, rc = "PASS", RC_OK
    return {
        "program": PROGRAM,
        "version": VERSION,
        "flow_step": FLOW_STEP,
        "project_dir": project,
        "threshold": THRESHOLD,
        "verdict": verdict,
        "rc": rc,
        "summary": {
            "scope": stats["scope"],
            "scope_exists": stats["scope_exists"],
            "checked": stats["checked"],
            "extraction_run_count": stats["run_count"],
            "feedback_file_count": stats["feedback_file_count"],
            "illegal_overlap_count": stats["illegal_overlap_count"],
            "illegal_overlap_string_count": stats["string_count"],
            "illegal_overlap_parsed_count": stats["parsed_count"],
            "runs_without_feedback": stats["runs_without_feedback"],
            "findings_count": len(findings),
            "errors_count": len(errors),
            "pass": not errors and stats["checked"],
        },
        # Upstream's own key, verbatim, so the two flows' numbers diff directly.
        "metrics": {
            "magic__illegal_overlap__count": stats["illegal_overlap_count"],
        },
        "reads": stats["reads"],
        "findings": [asdict(f) for f in findings],
    }


def publish_metrics(project: Path, stats: Dict[str, Any]) -> Optional[Path]:
    """Emit through the declared per-step metrics schema. `None` — not 0 — is
    the value when nothing was read; see the module docstring."""
    try:
        return _sm.emit(project, FLOW_STEP, {
            "illegal_overlap_count": stats["illegal_overlap_count"],
            "illegal_overlap_string_count": stats["string_count"],
            "illegal_overlap_parsed_count": stats["parsed_count"],
            "feedback_file_count": stats["feedback_file_count"],
            "run_count": stats["run_count"],
        }, domain="extraction")
    except (OSError, ValueError):
        return None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Gate Magic's SPICE-extraction error channel "
                    "(illegal overlaps) at zero, between extraction and LVS.")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--under", default=None,
                    help="Scope discovery to this path under the project")
    ap.add_argument("--feedback", action="append", default=None,
                    help="Explicit feedback file (repeatable). Bypasses "
                         "discovery; a named path that is absent is a FAIL.")
    ap.add_argument("--json", default=None, help="JSON report output path")
    ap.add_argument("--no-metrics", action="store_true",
                    help="Do not write reports/metrics/31.json")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return RC_NOT_CHECKED

    findings, stats = audit(project, args.under, args.feedback)
    report = build_report(findings, stats, str(project))

    if not args.no_metrics:
        publish_metrics(project, stats)

    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        dest = Path(args.json)
        if not dest.is_absolute():
            dest = project / dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(dest, out)

    print(out)
    for f in findings:
        if f.severity == "ERROR":
            print(f"  [ERROR] {f.rule}: {f.message}", file=sys.stderr)
    return int(report["rc"])


if __name__ == "__main__":
    sys.exit(main())
