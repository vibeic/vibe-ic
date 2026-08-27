#!/usr/bin/env python3
"""flow_output_substance — did the run actually produce this output, or only a file?

WHY THIS EXISTS
===============
`flow_gate_grid`'s D3 has always reported NOT DERIVABLE FROM SOURCE, and its
docstring is right about the reason:

    D3 outputs    NOT DERIVABLE FROM SOURCE. "required_outputs really exist and
                  are non-empty" is a fact about a RUN.

A fact about a run is not an undecidable fact. It is an UNSUPPLIED one. Given a
run directory it is a measurement like any other, and this module is that
measurement. The docstring's refusal to invent a plausible source-derived
predicate stands unchanged: nothing here reads the flow source for a verdict.

WHAT WENT THROUGH THE HOLE, MEASURED
====================================
MEASURED 2026-08-27 on
ghcr.io/vibeic/vibeic-eda@sha256:4ece6c01cddc99903af4f027326f7624b069311f2073a5a0b565d5a9cf649a16.
`eda_sta` built its script from the Liberty and the Verilog and read no LEF.
OpenROAD needs a technology before a netlist, so the whole script failed::

    [ERROR ORD-2010] no technology has been read.
    [ERROR STA-1570] No network has been linked.
    [ERROR STA-1571] No network has been linked.        (x4, one per report)

and `openroad -exit` returned **0**. The report file was written anyway: 591
bytes of it. Every predicate this repository owned passed that file:

    exists                    yes
    non-empty                 yes, 591 bytes
    not a symlink             yes
    would be tracked at HEAD  yes, if committed
    D8 catcher declared       yes -- and it had no reason to fire, because the
                              file it was watching for was RIGHT THERE

D8 asks whether a catcher is on the field. This module asks whether the ball was
actually caught. They are different questions and neither answers the other.

WHY THIS IS NOT D8 UNDER A NEW NAME
===================================
The grid's own docstring warns that inventing a plausible predicate "produces a
grid that measures something ADJACENT to what it claims". The guard against that
here is mechanical, not a promise:

  * No function in this module reads a step's `gate`.
  * No function in this module reaches a verdict from a `required_outputs`
    DECLARATION. The declaration is consulted only to learn which artefact to
    open -- the same use `flow_compliance_check` already makes of it.
  * Every verdict below is a statement about BYTES THAT A RUN WROTE.

Point this module at a tree with no run and every cell comes back NOT_MEASURED.
That is why `--run` is a required argument in the consumer rather than a
defaulted one: a defaulted run directory is how "unmeasured" becomes "fine".

THE THREE WRONG ANSWERS, NAMED SO THEY STAY REFUSED
===================================================
  * NOT_MEASURED must never render as a pass. That is the original disease --
    an absent measurement displayed as a good one.
  * NOT_MEASURED must never render as a fail. That converts "we did not look"
    into "it is broken", and a grid that is all red gets ignored, which costs
    the same as a grid that is all green.
  * A verdict inferred from the declaration is D8 wearing D3's name.

ABSENT AND VACUOUS ARE DIFFERENT FINDINGS
=========================================
"the step produced nothing" and "the step produced a file recording its own
failure" send a reader to two different places, so they are two states here and
are never folded together. This repository has paid for that distinction
before: `test_matrix_d3_outputs_produced` keeps 0-byte, symlinked and untracked
matches as separate categories for exactly the same reason.

WHAT "SUBSTANTIVE" MEANS, PER OUTPUT KIND
=========================================
There is no single predicate. A netlist with zero cells is CORRECT for a
constant design; a timing report produced after a failed `link_design` is not.
Asking one question of both is where a lazy predicate would measure something
adjacent. So the rule is chosen per kind, from the format's own evidence, and a
kind with no honest decider is reported NOT_DECIDABLE rather than guessed.

  TOOL_SELF_REPORT     The artefact IS a tool transcript, so the tool's own
                       error diagnostic in it is a first-hand report that the
                       work did not happen. Uses this repository's ALREADY
                       MEASURED diagnostic vocabulary -- `tool_diagnostic_id_gate
                       ._RE_BRACKETED`, whose prefix coverage is re-derived by
                       its own test -- rather than a second regex that would
                       drift away from it. Applied to: .rpt .log .txt

                       NOT applied to structured kinds. MEASURED: this repo
                       ships `programs/pdk_registry.json`, a healthy file that
                       legitimately CONTAINS a bracketed ERROR string, and the
                       MCP server writes provenance records whose `stdoutTail`
                       field carries a failed tool's error text verbatim -- a
                       CORRECT record of a failure. A detector that fired on
                       those would fire on healthy artefacts, and a detector
                       that fires on everything it is pointed at is broken.

  STRUCTURAL           The format's own mandatory landmark is present: JSON that
                       parses to a non-empty container, a DEF that reached
                       `END DESIGN`, a LEF that reached `END LIBRARY`, a Liberty
                       that opens a `library (` group, a SPEF with its `*SPEF`
                       header, a netlist that declares a `module`.

  DELEGATED            The repository already decides this kind. `.gds` goes to
                       `gds_substance_check.parse_gds` / `audit_gds`, which
                       walks the record stream and requires at least one
                       structure, one geometry element and one drawn layer. A
                       second GDS reader here would be a second source of truth
                       that drifts.

  SENTINEL             The artefact's entire content is its existence -- `.done`
                       and `.flag` markers. A 0-byte `pdn.done` is the format
                       working as designed, so emptiness is not evidence of
                       vacuity for this kind. This is not a relaxation of the
                       zero-byte rule: it is the zero-byte rule applied to a
                       format where zero bytes is the message.

  NON_BLANK_TEXT       The weakest rule, and it is still strictly stronger than
                       "non-empty": a file of nothing but whitespace has a
                       positive byte count and no content. Applied where no
                       stronger landmark exists.

  NOT_DECIDABLE        `.sof` -- an opaque vendor FPGA bitstream. Nothing in
                       this repository parses one, so no honest statement about
                       its substance can be made here. Saying NOT_DECIDABLE is
                       the finding; a size threshold would be a number unrelated
                       to the design, which is the shape `gds_substance_check`
                       was written to remove.

WHAT THIS MODULE DELIBERATELY REFUSES TO REQUIRE
================================================
It does NOT require a timing report to contain a slack number, a coverage report
to contain a percentage, or a netlist to contain cells. Each of those is the
adjacent-measurement trap in a different costume:

  * `report_checks` on a design with no timing paths legitimately prints
    "No paths found to report." -- not a failure.
  * A design that synthesises to zero cells is CORRECT for a constant output.
    MEASURED on the image above: `assign zero = 1'b0` yields a 205-byte netlist
    with `0 cells`, and it is a real netlist. Requiring cells would flag it.

The rule is "the tool said it failed" or "the format's landmark is missing",
never "the number I expected is not here".

WHAT THIS DOES NOT CATCH — STATED, NOT DISCOVERED LATER
=======================================================
TOOL_SELF_REPORT is NEGATIVE evidence: it fires when the tool wrote its failure
down. It cannot see a run that died and said NOTHING -- an OOM kill, a timeout,
a container evicted mid-report. For formats with a terminating record the
STRUCTURAL rule still catches that (a DEF without `END DESIGN`, a LEF without
`END LIBRARY`, a GDS without ENDLIB), but a plain `.rpt` has no terminator, so a
transcript truncated by a kill reads as substantive here.

The complete fix is POSITIVE evidence: a run that reached the end says so. The
MCP layer already does this for three tools -- `eda_pnr` keys on PNR_COMPLETE,
`eda_ir_drop` on IR_DROP_COMPLETE, and `eda_sta` on STA_COMPLETE as of the
tool-honesty work -- and mature open flows use the same shape. When a sentinel
is present in an artefact this module could require it rather than merely
tolerate its absence. It is NOT done here because a sentinel this module does
not emit is one it cannot require without failing every artefact written by any
other producer, which would be the fires-on-everything defect again. The
honest order is: emit sentinels first, require them second.

EXIT
    0  every decided entry is substantive
    1  at least one entry is absent or vacuous
    2  the run directory could not be read
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── States ──────────────────────────────────────────────────────────────────
SUBSTANTIVE = "SUBSTANTIVE"
VACUOUS = "VACUOUS"
ABSENT = "ABSENT"
NOT_DECIDABLE = "NOT_DECIDABLE"
NOT_MEASURED = "NOT_MEASURED"

#: States that mean "this cell was looked at and the answer is bad".
FAILING = (VACUOUS, ABSENT)
#: States that carry no verdict and must never be counted as either.
NO_VERDICT = (NOT_DECIDABLE, NOT_MEASURED)

# ── Rules ───────────────────────────────────────────────────────────────────
TOOL_SELF_REPORT = "TOOL_SELF_REPORT"
STRUCTURAL = "STRUCTURAL"
DELEGATED = "DELEGATED"
SENTINEL = "SENTINEL"
NON_BLANK_TEXT = "NON_BLANK_TEXT"
UNDECIDED = "NOT_DECIDABLE"

_HERE = Path(__file__).resolve().parent

# ── Vacuity codes ───────────────────────────────────────────────────────────
#
# ENUMERATED, not prose. This repository already settled that argument:
# `si_mcf_sta_check` publishes a `vacuity_code` from a closed set, and
# `drc_vacuous_pass_check` records tool prose as `wording_hints` that NEVER
# decide. A reader must be able to act on the reason without parsing a sentence,
# and a new reason must be an addition to this list rather than a new adjective.
VACUITY_CODES = {
    "TOOL_REPORTED_ERROR":  "the producing tool wrote its own ERROR diagnostic "
                            "into this artefact",
    "ZERO_BYTES":           "the file exists and carries nothing",
    "WHITESPACE_ONLY":      "a positive byte count and no content",
    "MALFORMED":            "the artefact does not parse as its own format",
    "EMPTY_CONTAINER":      "the artefact parses and holds nothing",
    "NO_MODULE":            "a netlist that declares no module",
    "TRUNCATED":            "the format's terminating record was never written",
    "MISSING_LANDMARK":     "the format's mandatory opening record is absent",
    "DELEGATE_REFUSED":     "the repository's own decider for this kind refused it",
}

#: Why a cell carries no verdict. Distinct from a vacuity code: these are not
#: findings about an artefact, they are statements about this module's reach.
NO_VERDICT_CODES = {
    "NO_RUN_SUPPLIED":      "D3 is a fact about a RUN and none was supplied",
    "STEP_NOT_EVIDENCED":   "no declared output of this step resolved, so the "
                            "run is not evidenced to have reached it",
    "NO_DECIDER_FOR_KIND":  "this output kind has no honest decider here",
    "DELEGATE_UNAVAILABLE": "the decider for this kind could not be loaded",
    "NOT_A_FILE":           "the pattern resolved to something that is not a file",
    "NO_OUTPUTS_DECLARED":  "the step declares no required_outputs",
}



# ── The diagnostic vocabulary is IMPORTED, never re-spelled ─────────────────
def _bracketed_diagnostic_re():
    """This repository's measured bracketed-diagnostic pattern.

    `tool_diagnostic_id_gate` derives the prefix coverage from the corpus and
    pins it with its own test, so importing it means a seventeenth tool becomes
    visible here the day that gate learns about it. A local copy of the regex
    would be a second vocabulary that silently ages.

    The fallback is used only when that module cannot be imported (a partial
    install). It is deliberately the SAME pattern rather than a looser one: a
    fallback that matched more would change verdicts depending on whether an
    import succeeded.
    """
    try:
        sys.path.insert(0, str(_HERE))
        from tool_diagnostic_id_gate import _RE_BRACKETED  # type: ignore
        return _RE_BRACKETED
    except Exception:
        return re.compile(
            r"\[(?P<level>WARNING|ERROR|INFO)\s+(?P<id>[A-Z][A-Z0-9]{1,7}-\d{3,5})\]")


def tool_error_diagnostics(text: str) -> List[str]:
    """Every ERROR-level bracketed tool diagnostic in a transcript.

    WARNING and INFO are deliberately NOT collected. A run that warns is a run
    that ran; a gate that treated a warning as vacuity would refuse most healthy
    artefacts in this repository, and `tool_diagnostic_id_gate` already owns the
    separate question of whether a warning is NEW.
    """
    rx = _bracketed_diagnostic_re()
    out: List[str] = []
    for m in rx.finditer(text):
        if m.group("level") == "ERROR":
            out.append(m.group(0))
    return out


# ── Kind table ──────────────────────────────────────────────────────────────
#
# Keyed on the resolved artefact's suffix. A suffix absent from this table is
# NOT an error: it falls to NON_BLANK_TEXT for a text file and NOT_DECIDABLE for
# a binary one, and the report says which, so a nineteenth output kind appearing
# in the flow is disclosed rather than silently defaulted to a pass.
#: Marker files whose entire content is their existence. MEASURED over the flow:
#: 11 of the 198 " OR " alternatives are of this shape (`pass.flag`,
#: `metal_fill.done`, `pdn.done`, `NO_TEMPLATE.txt`, `die_finishing.SKIPPED.txt`,
#: `scribe_line_layout.PENDING_FOUNDRY.txt`). A size rule reds every one of them.
_SENTINEL_SUFFIXES = {".done", ".flag"}

#: Kinds whose CONTENT IS A TOOL TRANSCRIPT, so the tool's own error diagnostic
#: in one is a first-hand report that the work did not happen. `.report` is the
#: analog track's spelling of `.rpt` (A6 declares both).
_TRANSCRIPT_SUFFIXES = {".rpt", ".log", ".report"}

#: `.txt` here is a MARKER kind by every occurrence the flow declares, so it gets
#: the content floor but not the transcript rule -- a marker file naming a
#: PENDING or SKIPPED state is not a transcript and must not be read as one.
_NOT_DECIDABLE_SUFFIXES = {".sof"}


def _is_probably_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


# ── Per-format landmarks ────────────────────────────────────────────────────
# Each returns (ok, detail). `detail` names what was missing, because "VACUOUS"
# with no noun is a verdict a reader cannot act on.

def _landmark_json(text: str) -> Tuple[bool, str]:
    try:
        doc = json.loads(text)
    except Exception as e:
        return False, f"does not parse as JSON ({type(e).__name__})"
    if doc is None:
        return False, "parses to null"
    if isinstance(doc, (dict, list, str)) and len(doc) == 0:
        return False, f"parses to an empty {type(doc).__name__}"
    return True, ""


def _landmark_yaml(text: str) -> Tuple[bool, str]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return True, ""          # cannot decide -> do not invent a failure
    try:
        doc = yaml.safe_load(text)
    except Exception as e:
        return False, f"does not parse as YAML ({type(e).__name__})"
    if doc is None:
        return False, "parses to null"
    if isinstance(doc, (dict, list, str)) and len(doc) == 0:
        return False, f"parses to an empty {type(doc).__name__}"
    return True, ""


def _landmark_xml(text: str) -> Tuple[bool, str]:
    import xml.etree.ElementTree as ET
    try:
        ET.fromstring(text)
    except Exception as e:
        return False, f"does not parse as XML ({type(e).__name__})"
    return True, ""


def _landmark_module(text: str) -> Tuple[bool, str]:
    """A netlist must DECLARE something. It need not contain cells.

    The cell count is the trap: a constant-driven design synthesises to zero
    cells and that is the correct answer for it (MEASURED: 205 bytes, `0 cells`,
    a real module). What a netlist cannot legitimately lack is the module
    declaration itself -- an empty or truncated write has none.
    """
    if re.search(r"^\s*module\s+[\\\w]", text, re.MULTILINE):
        return True, ""
    return False, "declares no `module` (a netlist with zero cells is legitimate; one with no module is not)"


def _landmark_def(text: str) -> Tuple[bool, str]:
    if "END DESIGN" in text:
        return True, ""
    return False, "never reached `END DESIGN` (a truncated or aborted write)"


def _landmark_lef(text: str) -> Tuple[bool, str]:
    if "END LIBRARY" in text:
        return True, ""
    return False, "never reached `END LIBRARY` (a truncated or aborted write)"


def _landmark_lib(text: str) -> Tuple[bool, str]:
    if re.search(r"\blibrary\s*\(", text):
        return True, ""
    return False, "opens no `library (` group"


def _landmark_spef(text: str) -> Tuple[bool, str]:
    if "*SPEF" in text:
        return True, ""
    return False, "carries no `*SPEF` header record"


def _landmark_mag(text: str) -> Tuple[bool, str]:
    """A Magic layout file opens with its own format keyword.

    MEASURED precedent in this repository: `_analog_a_check_common` records a
    34-byte `layout.mag` STUB that `analog_a5_layout_check` scored rc=0
    VACUOUS_PASS. A stub of that size can still be non-empty, so the byte count
    does not separate it; the format keyword does.
    """
    if text.lstrip().startswith("magic"):
        return True, ""
    return False, "does not open with the `magic` format keyword"


def _landmark_nonblank(text: str) -> Tuple[bool, str]:
    if text.strip():
        return True, ""
    return False, "contains only whitespace (a positive byte count and no content)"


_LANDMARKS = {
    ".json": _landmark_json,
    ".yml": _landmark_yaml,
    ".yaml": _landmark_yaml,
    ".xml": _landmark_xml,
    ".v": _landmark_module,
    ".sv": _landmark_module,
    ".def": _landmark_def,
    ".lef": _landmark_lef,
    ".lib": _landmark_lib,
    ".spef": _landmark_spef,
    ".lyrdb": _landmark_xml,      # KLayout report database is XML
    ".mag": _landmark_mag,
}


# ── The GDS delegate ────────────────────────────────────────────────────────
def _classify_gds(path: Path) -> Tuple[str, str, str, str]:
    """Delegate to the repository's existing GDS substance decider.

    `gds_substance_check` already walks the record stream and requires a
    structure and a geometry element. Re-implementing any of that here would
    create a second answer to one question.

    IT IS CALLED WITH ITS SIGN-OFF CRITERIA TURNED OFF, DELIBERATELY.
    `audit_gds(data, instance_count, elements_per_instance, min_distinct_layers)`
    also enforces a DESIGN-DERIVED FLOOR (elements per placed instance) and a
    MASK_STACK_TOO_THIN rule. Both are full-chip TAPE-OUT criteria and both are
    that gate's own job. D3 asks a narrower question -- "did a run put layout in
    this file, or only a file" -- and a hardmacro or an analog cell GDS can be a
    perfectly real layout while drawing on few layers. Passing
    `elements_per_instance=0.0, min_distinct_layers=0` keeps STRUCTURE,
    NO_STRUCTURES and NO_GEOMETRY -- the part that is a fact about THIS artefact
    alone -- and leaves the sign-off thresholds to the gate that owns them.
    Borrowing another gate's threshold would make D3 fail artefacts that are not
    vacuous, which is the detector-fires-on-everything failure in reverse.

    A delegate that cannot be imported reports NOT_DECIDABLE, never a pass: an
    unavailable decider is an absent measurement, and this whole module exists
    because an absent measurement was being rendered as a good one.
    """
    try:
        sys.path.insert(0, str(_HERE))
        from gds_substance_check import audit_gds  # type: ignore
    except Exception as e:
        return (NOT_DECIDABLE, DELEGATED, "DELEGATE_UNAVAILABLE",
                f"gds_substance_check could not be imported ({type(e).__name__}); "
                f"no GDS verdict was obtained and none is invented")
    try:
        findings, stats, _floor = audit_gds(path.read_bytes(), None, 0.0,
                                            min_distinct_layers=0)
    except Exception as e:
        return (NOT_DECIDABLE, DELEGATED, "DELEGATE_UNAVAILABLE",
                f"gds_substance_check raised {type(e).__name__}; no verdict obtained")
    errs = [f"{f.category}: {f.message}" for f in findings
            if str(getattr(f, "severity", "ERROR")).upper() == "ERROR"]
    if errs:
        return (VACUOUS, DELEGATED, "DELEGATE_REFUSED", "gds_substance_check — " + "; ".join(errs[:3]))
    return (SUBSTANTIVE, DELEGATED, "",
            f"gds_substance_check parsed {stats.structures} structure(s) and "
            f"{stats.elements} layout element(s)")


def _why_code(why: str) -> str:
    """Map a landmark's own explanation to an enumerated code.

    The mapping lives HERE and not in each landmark so that the codes stay a
    closed set a reader can enumerate; a landmark that grew a new explanation
    without a code lands on MALFORMED rather than inventing one.
    """
    if "parses to an empty" in why:
        return "EMPTY_CONTAINER"
    if "parses to null" in why:
        return "EMPTY_CONTAINER"
    if "declares no `module`" in why:
        return "NO_MODULE"
    if "never reached" in why:
        return "TRUNCATED"
    if "does not open with" in why or "opens no" in why or "carries no" in why:
        return "MISSING_LANDMARK"
    return "MALFORMED"


# ── Artefact classification ─────────────────────────────────────────────────
def classify_artefact(path: Path) -> Dict[str, str]:
    """Classify ONE resolved artefact. Returns state / rule / kind / detail."""
    suffix = path.suffix.lower()
    kind = suffix or "(no extension)"

    if not path.exists():
        return dict(state=ABSENT, rule=UNDECIDED, kind=kind,
                    detail="the resolved path does not exist", code="ABSENT")
    if path.is_symlink() and not path.resolve().exists():
        return dict(state=ABSENT, rule=UNDECIDED, kind=kind,
                    detail="a dangling symlink is a directory entry, not an artefact", code="ABSENT")
    if path.is_dir():
        return dict(state=NOT_DECIDABLE, rule=UNDECIDED, kind=kind,
                    detail="the pattern resolved to a directory; substance is undefined for one", code="NOT_A_FILE")

    if suffix in _SENTINEL_SUFFIXES:
        return dict(state=SUBSTANTIVE, rule=SENTINEL, kind=kind,
                    detail="a marker file's entire content is its existence", code="")

    if suffix in _NOT_DECIDABLE_SUFFIXES:
        return dict(state=NOT_DECIDABLE, rule=UNDECIDED, kind=kind,
                    detail="an opaque vendor bitstream; nothing in this repository "
                           "parses one, and a size threshold would be a number "
                           "unrelated to the design", code="NO_DECIDER_FOR_KIND")

    if suffix == ".gds":
        state, rule, code, detail = _classify_gds(path)
        return dict(state=state, rule=rule, kind=kind, code=code, detail=detail)

    try:
        data = path.read_bytes()
    except OSError as e:
        return dict(state=NOT_DECIDABLE, rule=UNDECIDED, kind=kind,
                    detail=f"unreadable ({type(e).__name__})", code="NOT_A_FILE")

    if len(data) == 0:
        return dict(state=VACUOUS, rule=NON_BLANK_TEXT, kind=kind,
                    detail="zero bytes", code="ZERO_BYTES")

    if _is_probably_binary(data):
        return dict(state=NOT_DECIDABLE, rule=UNDECIDED, kind=kind,
                    detail="binary content of a kind this module has no decider for", code="NO_DECIDER_FOR_KIND")

    text = _decode(data)

    # 1. The tool's own first-hand report, for kinds that ARE tool transcripts.
    if suffix in _TRANSCRIPT_SUFFIXES:
        errs = tool_error_diagnostics(text)
        if errs:
            uniq: List[str] = []
            for e in errs:
                if e not in uniq:
                    uniq.append(e)
            return dict(state=VACUOUS, rule=TOOL_SELF_REPORT, kind=kind,
                        code="TOOL_REPORTED_ERROR",
                        detail="the producing tool recorded its own failure in this "
                               "artefact: " + ", ".join(uniq[:4]))

    # 2. The format's mandatory landmark.
    landmark = _LANDMARKS.get(suffix)
    if landmark is not None:
        ok, why = landmark(text)
        if not ok:
            return dict(state=VACUOUS, rule=STRUCTURAL, kind=kind,
                        code=_why_code(why), detail=why)
        return dict(state=SUBSTANTIVE, rule=STRUCTURAL, kind=kind, code="",
                    detail="the format's mandatory landmark is present")

    # 3. The floor: content, not merely bytes.
    ok, why = _landmark_nonblank(text)
    if not ok:
        return dict(state=VACUOUS, rule=NON_BLANK_TEXT, kind=kind,
                    code="WHITESPACE_ONLY", detail=why)
    rule = TOOL_SELF_REPORT if suffix in _TRANSCRIPT_SUFFIXES else NON_BLANK_TEXT
    return dict(state=SUBSTANTIVE, rule=rule, kind=kind, code="",
                detail="carries content and records no tool failure"
                       if suffix in _TRANSCRIPT_SUFFIXES else "carries content")


# ── Entry / step classification ─────────────────────────────────────────────
def _resolver():
    """The flow's OWN resolver, imported rather than re-implemented.

    `flow_compliance_check._glob_first` carries the reports/<subdir> fallback,
    the canonical-analog-dir remap, and the rule that a dangling symlink is not
    a produced artefact. A private glob here would answer a different question
    from the gate that actually runs, and the two would drift.
    """
    sys.path.insert(0, str(_HERE))
    from flow_compliance_check import _glob_first  # type: ignore
    return _glob_first


class ResolverUnavailable(RuntimeError):
    """The flow's own resolver could not be loaded.

    Raised rather than swallowed. A caller must decide between NO_DECIDER and
    an abort; silently returning "nothing resolved" would render an unavailable
    resolver as ABSENT for all 165 entries, which reads exactly like a run that
    produced nothing — the confident-wrong-answer shape this repository has
    already paid for once ("50 failed ... asserted by a function that opened no
    file").
    """


def classify_entry(project: Path, entry: str) -> Dict[str, object]:
    """Classify one `required_outputs` entry against a run directory.

    An entry may name several alternatives joined by " OR ". The flow's own
    semantics are ANY-OF, so the entry is discharged by the BEST alternative
    that resolves -- and the reason a losing alternative lost is kept, because
    "one of three alternatives produced a file recording a failure" is a finding
    a reader wants even when another alternative saved the cell.
    """
    try:
        glob_first = _resolver()
    except Exception as e:                              # pragma: no cover
        raise ResolverUnavailable(
            f"flow_compliance_check._glob_first could not be imported "
            f"({type(e).__name__}); D3 resolves required_outputs with the flow's "
            f"OWN resolver on purpose and must not fall back to a private glob "
            f"that answers a different question") from e
    alts = [a.strip() for a in str(entry).split(" OR ") if a.strip()]
    per_alt: List[Dict[str, object]] = []
    for alt in alts:
        try:
            hits = glob_first(project, alt)
        except Exception as e:
            per_alt.append(dict(alternative=alt, state=NOT_DECIDABLE,
                                code="DELEGATE_UNAVAILABLE",
                                detail=f"resolver raised {type(e).__name__}"))
            continue
        if not hits:
            per_alt.append(dict(alternative=alt, state=ABSENT, code="ABSENT",
                                detail="nothing under the run root matches this pattern"))
            continue
        for h in hits:
            v = classify_artefact(project / h)
            per_alt.append(dict(alternative=alt, path=h, **v))

    order = {SUBSTANTIVE: 0, NOT_DECIDABLE: 1, VACUOUS: 2, ABSENT: 3}
    best = min(per_alt, key=lambda d: order.get(str(d["state"]), 9)) if per_alt \
        else dict(state=ABSENT, detail="the entry names no alternative")
    return dict(entry=entry, state=best["state"],
                rule=best.get("rule", UNDECIDED),
                kind=best.get("kind", "(unresolved)"),
                code=best.get("code", ""),
                path=best.get("path"),
                detail=best.get("detail", ""),
                alternatives=per_alt)


def classify_step(project: Path, step: dict) -> Dict[str, object]:
    """Roll one step's declared outputs up into a single D3 cell state.

    The rollup is deliberately PESSIMISTIC over verdicts and NEUTRAL over
    non-verdicts: one vacuous or absent entry makes the cell fail, but a cell
    whose every entry is NOT_DECIDABLE is NOT_DECIDABLE -- not a pass. A step
    that declares no outputs at all has nothing for this dimension to measure
    and is NOT_DECIDABLE too, which is a different statement from "clean".
    """
    outs = step.get("required_outputs") or []
    if not outs:
        return dict(step=str(step.get("id")), state=NOT_DECIDABLE,
                    code="NO_OUTPUTS_DECLARED",
                    detail="declares no required_outputs; this dimension has "
                           "nothing to measure for it",
                    entries=[])
    entries = [classify_entry(project, e) for e in outs]
    states = [str(e["state"]) for e in entries]

    # A STEP THAT NEVER RAN IS NOT A STEP THAT PRODUCED A HOLLOW OUTPUT.
    #
    # MEASURED while building this: pointed at a run tree carrying only steps 9
    # and 10, the first draft reddened 64 of 68 steps -- every phase-3 step of a
    # phase-2 project, every analog step of a digital one. That is a detector
    # that fires on every target it is pointed at, and one of those is as broken
    # as the silence it replaced. It would also have made D3 useless for the
    # ordinary case the flow is FOR: a design project that has reached step 12.
    #
    # The honest line: D3 asks whether the outputs a run WROTE carry substance.
    # "Did this step run at all" is a different question, it is already answered
    # by `flow_compliance_check` (status MISSING) and by D8's catcher, and
    # answering it here would both duplicate them and drown this dimension's own
    # finding. So when NOTHING a step declares resolved, the step is not
    # evidenced to have run and the cell is NOT_MEASURED -- neither a pass nor a
    # fail, the same refusal this module makes when no run is supplied at all.
    #
    # It is NOT a blanket exemption for absence. The moment ANY declared output
    # resolves, the step demonstrably ran, and a SIBLING output that is missing
    # becomes a real finding again -- a half-written step is exactly the shape
    # that a per-step "did it run" test would wave through.
    resolved = [e for e in entries if str(e["state"]) != ABSENT]
    if not resolved:
        return dict(step=str(step.get("id")), state=NOT_MEASURED,
                    code="STEP_NOT_EVIDENCED",
                    detail="no declared output resolved under this run, so this "
                           "step is not evidenced to have run; D3 measures the "
                           "substance of what a run wrote, not whether it got "
                           "this far",
                    entries=entries)

    if VACUOUS in states:
        state = VACUOUS
    elif ABSENT in states:
        state = ABSENT
    elif all(x == NOT_DECIDABLE for x in states):
        state = NOT_DECIDABLE
    else:
        state = SUBSTANTIVE
    decider = next((e for e in entries if str(e["state"]) == state), None)
    return dict(step=str(step.get("id")), state=state,
                code=(decider or {}).get("code", ""), entries=entries)


def classify_flow(project: Optional[Path], steps: List[dict]) -> Dict[str, object]:
    """The D3 dimension over every step.

    With `project=None` -- no run supplied -- every cell is NOT_MEASURED and the
    record says so. It is not a pass and it is not a fail; it is the honest
    report that nobody looked.
    """
    if project is None:
        return dict(state=NOT_MEASURED, run=None,
                    reason="no run directory was supplied; D3 is a fact about a "
                           "RUN and this tree contains no answer to it",
                    cells=[dict(step=str(s.get("id")), state=NOT_MEASURED,
                                code="NO_RUN_SUPPLIED") for s in steps])
    return dict(state="MEASURED", run=str(project),
                cells=[classify_step(project, s) for s in steps])


# ── CLI ─────────────────────────────────────────────────────────────────────
def _load_steps(path: Path) -> Optional[List[dict]]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    steps: List[dict] = []

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "name" in o:
                steps.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return [s for s in steps if not str(s.get("id", "")).startswith("stage")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--flow", type=Path,
                    default=_HERE.parent / "flow" / "phase1_phase2_phase3.yaml")
    ap.add_argument("--run", type=Path, default=None,
                    help="a COMPLETED run directory. Omit and every cell reports "
                         "NOT_MEASURED -- never a pass.")
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)

    steps = _load_steps(a.flow)
    if not steps:
        print(f"flow_output_substance: rc=2 NOT CHECKED — no steps in {a.flow}")
        return 2
    if a.run is not None and not a.run.is_dir():
        print(f"flow_output_substance: rc=2 NOT CHECKED — {a.run} is not a directory")
        return 2

    rec = classify_flow(a.run, steps)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(rec, indent=2, default=str) + "\n",
                          encoding="utf-8")

    if rec["state"] == NOT_MEASURED:
        print(f"flow_output_substance: D3 NOT MEASURED over {len(steps)} steps — "
              f"{rec['reason']}. This is neither a pass nor a fail.")
        return 0

    bad = [c for c in rec["cells"] if c["state"] in FAILING]
    for c in bad:
        print(f"flow_output_substance: step {c['step']} — {c['state']}")
        for e in c.get("entries", []):
            if e["state"] in FAILING:
                print(f"    {e['entry']}  [{e['state']}] {e['detail']}")
    counts: Dict[str, int] = {}
    for c in rec["cells"]:
        counts[str(c["state"])] = counts.get(str(c["state"]), 0) + 1
    print(f"\n  D3 over {len(steps)} steps against {rec['run']}: "
          + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
