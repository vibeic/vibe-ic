#!/usr/bin/env python3
"""The tool-measurement record: read the third value a tool now states.

WHAT THIS IS FOR
----------------
A flow gate that consumes an MCP EDA tool has had exactly two things to read,
and neither of them answers the question a sign-off actually asks:

  * THE EXIT CODE.  MEASURED 2026-08-27 on
    ``vibeic-eda@sha256:4ece6c01``: ``openroad`` running the STA script exactly
    as ``eda_sta`` emitted it read no technology, aborted ``read_verilog`` with
    ``[ERROR ORD-2010]``, failed ``link_design`` with ``[ERROR STA-1570]``,
    failed every report with ``STA-1571`` -- and **exited 0**.  The tool
    therefore returned ``success:true`` and wrote a manifest ``status:"PASS"``
    for a run in which nothing was linked and no path was analysed.
  * THE SHAPE OF THE BYTES.  A report parser asks whether the text *looks* like
    tool output.  MEASURED the same night: a design with no ``clk`` port yields
    ``[WARNING STA-0366] port 'clk' not found``, a source-less clock, and
    ``wns max 0.00`` -- byte-indistinguishable from a genuinely clean clocked
    design.  ``eda_report_audit``'s STA gate set
    ``any_verdict_determined=True, real_violation_found=False`` on it: the
    fabricated 0.00 was accepted as a met verdict.

So the tool states a third value beside PASS/FAIL -- *did I measure anything* --
and this module is how a gate reads it.  It is the READER half of the contract
whose WRITER half is ``mcp-eda/src/index.js``'s ``measurementRecord()``.  A
field nothing consults relocates a defect instead of fixing it, so every
consumer of this module is a decision point, named in its own docstring.

THE THREE STATES, AND WHY THERE ARE THREE
-----------------------------------------
``measured: true``
    The substantive operation completed and produced a reading.  Whether that
    reading is GOOD is a separate question with a separate field -- a DRC run
    that found twelve violations measured perfectly.

``measured: false`` with a **hard** class
    (``TOOL_DID_NOT_RUN`` / ``UNCONSTRAINED`` / ``NO_PATHS`` / ``UNPARSEABLE``)
    The operation could not run, or ran on a precondition that makes its
    numbers meaningless.  A verdict read off this run would be fabricated.
    This is the state a gate must REFUSE, naming what was missing.

``measured: false`` with the **benign** class ``NOTHING_TO_MEASURE``
    The operation ran and there was legitimately nothing to judge -- a purely
    combinational block has no timing paths to constrain, and never did.  This
    is NOT a defect.  A gate that refuses it refuses every such design, and a
    gate that refuses everything gets bypassed, which is a deleted gate.

**UNDECLARED** -- no record at all -- is a fourth state and it is none of the
above.  It must not be read as ``measured:false``: that converts an unmeasured
thing into a bad result, which is a different lie in the opposite direction.
It is renderable as itself; see ``Measurement.undeclared`` and the
``INCOMPLETE`` tier ``provenance_check --require-measured`` prints for it.

WHERE THE RECORD LIVES
----------------------
Two places, on purpose, because a report does not always travel with its run:

  1. ``provenance.jsonl`` -- the ``measurement`` object on the run record.
     Bound to the artefact by digest, so it answers "did the run that produced
     THIS file measure anything".
  2. A ``# MCP_MEASUREMENT: {...}`` comment on the FIRST line of the artefact
     itself.  MEASURED on the published corpus: three cells record a GDS in
     provenance under one path and ship it under another, and reports are
     routinely copied and symlinked away from the project that made them.  A
     stamp travels with the bytes.  It is a ``#`` comment so every existing
     report reader still reads the report unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

#: The writer stamps this exact prefix as the artefact's first line.
STAMP_PREFIX = "# MCP_MEASUREMENT: "

#: Schema token the writer emits. Kept as a prefix match so a later
#: ``mcp-eda/measurement/2`` is still recognisably a measurement record rather
#: than being silently read as "undeclared" -- a reader that stops recognising
#: records is exactly the falsely-clean shape this module exists to prevent.
SCHEMA_FAMILY = "mcp-eda/measurement/"

#: A reading taken from a run in one of these classes would be fabricated.
HARD_CLASSES = frozenset({
    "TOOL_DID_NOT_RUN",
    "UNCONSTRAINED",
    "NO_PATHS",
    "UNPARSEABLE",
})

#: The one honest non-failure: the operation ran, and there was nothing to judge.
BENIGN_CLASS = "NOTHING_TO_MEASURE"

#: How many bytes of an artefact to read when looking for the stamp. The stamp
#: is the FIRST line by construction; a bounded read keeps this cheap on the
#: multi-megabyte reports a sign-off corpus is full of.
_STAMP_SCAN_BYTES = 8192


@dataclass(frozen=True)
class Measurement:
    """One tool's answer to "did I do my work", plus where it was found."""

    declared: bool
    measured: Optional[bool]
    reason_class: Optional[str]
    reason: str
    operation: str
    tool: str
    read: List[str]
    wrote: List[str]
    source: str          # "stamp:<path>" | "provenance" | "undeclared"

    # -- the three questions a decision point asks --------------------------
    @property
    def undeclared(self) -> bool:
        """No record. NOT the same as ``measured:false``; see module docstring."""
        return not self.declared

    @property
    def hard_miss(self) -> bool:
        """The tool says a reading from this run would be fabricated."""
        return (self.declared and self.measured is False
                and (self.reason_class or "") in HARD_CLASSES)

    @property
    def nothing_to_measure(self) -> bool:
        """The tool ran and there was legitimately nothing to judge."""
        return (self.declared and self.measured is False
                and (self.reason_class or "") == BENIGN_CLASS)

    @property
    def positive(self) -> bool:
        """Positive evidence the tool performed its work."""
        return self.declared and self.measured is True

    def describe(self) -> str:
        if self.undeclared:
            return ("no tool measurement record: this artefact carries no "
                    "`# MCP_MEASUREMENT:` stamp and no run record declares "
                    "whether the tool measured anything")
        if self.measured:
            return f"{self.tool or self.operation}: measured"
        return (f"{self.tool or self.operation}: NOT MEASURED "
                f"[{self.reason_class}] {self.reason}")


UNDECLARED = Measurement(
    declared=False, measured=None, reason_class=None, reason="",
    operation="", tool="", read=[], wrote=[], source="undeclared",
)


def _from_obj(obj: Any, source: str) -> Measurement:
    """Build a Measurement from a parsed record, or UNDECLARED if it isn't one.

    A malformed or foreign object is UNDECLARED, never a miss: guessing that
    something we could not parse means "the tool failed" is the opposite lie.
    """
    if not isinstance(obj, dict):
        return UNDECLARED
    schema = str(obj.get("schema", ""))
    if not schema.startswith(SCHEMA_FAMILY):
        return UNDECLARED
    measured = obj.get("measured")
    if measured not in (True, False):
        # A record that cannot say is not a record. Treated as undeclared so it
        # renders as "nobody stated this" rather than as a failure.
        return UNDECLARED
    return Measurement(
        declared=True,
        measured=bool(measured),
        reason_class=obj.get("not_measured_class") or None,
        reason=str(obj.get("not_measured_reason") or ""),
        operation=str(obj.get("operation") or ""),
        tool=str(obj.get("tool") or ""),
        read=[str(x) for x in (obj.get("read") or [])],
        wrote=[str(x) for x in (obj.get("wrote") or [])],
        source=source,
    )


def from_text(text: str, source: str = "stamp") -> Measurement:
    """Read the stamp out of an artefact's text. UNDECLARED when absent."""
    for line in (text or "")[:_STAMP_SCAN_BYTES].splitlines():
        stripped = line.strip()
        if not stripped.startswith(STAMP_PREFIX.strip()):
            continue
        payload = stripped.split(STAMP_PREFIX.strip(), 1)[1].strip()
        try:
            return _from_obj(json.loads(payload), source)
        except json.JSONDecodeError:
            return UNDECLARED
    return UNDECLARED


def from_file(path: Path) -> Measurement:
    """Read the stamp from a file on disk. Unreadable file -> UNDECLARED.

    An unreadable file is a finding for whoever declared it, not evidence that
    a tool failed -- the caller already reports unreadability itself.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(_STAMP_SCAN_BYTES)
    except OSError:
        return UNDECLARED
    return from_text(head.decode("utf-8", errors="replace"), f"stamp:{path}")


def from_provenance_entry(entry: Dict[str, Any]) -> Measurement:
    """Read the ``measurement`` object off one provenance.jsonl record."""
    if not isinstance(entry, dict):
        return UNDECLARED
    return _from_obj(entry.get("measurement"), "provenance")


def worst(measurements: Iterable[Measurement]) -> Measurement:
    """The one a gate must answer to, when several artefacts were examined.

    Precedence is by SEVERITY OF THE CLAIM, not by order: one artefact whose
    tool says it measured nothing is not cured by a sibling that did.  A hard
    miss outranks a benign one; a benign one outranks undeclared; undeclared
    outranks a positive measurement, because "somebody must come back" is
    louder news than "this one is fine".
    """
    ms = list(measurements)
    if not ms:
        return UNDECLARED
    for pred in (lambda m: m.hard_miss,
                 lambda m: m.nothing_to_measure,
                 lambda m: m.undeclared):
        for m in ms:
            if pred(m):
                return m
    return ms[0]


def strip_stamp(text: str) -> tuple:
    """Return ``(text_without_stamp, stamp_bytes)``.

    THE STAMP MUST NOT PAY FOR ITSELF. MEASURED while adding it: a 873-byte
    link-failure report grew past the 1024-byte ``*_REPORT_TOO_SMALL`` floor and
    acquired a ``*_NO_TOOL_SIGNATURE`` match purely because the stamp names the
    tool -- so two authenticity checks that had correctly refused that report
    started passing it. A stamp is metadata ABOUT the tool output; counting it
    AS tool output lets any report buy its way past a size or signature screen
    by being stamped. Both screens are measured on what the tool actually wrote.
    """
    lines = (text or "").splitlines(keepends=True)
    kept, dropped = [], 0
    for line in lines:
        if line.lstrip().startswith(STAMP_PREFIX.strip()):
            dropped += len(line.encode("utf-8"))
            continue
        kept.append(line)
    return "".join(kept), dropped
