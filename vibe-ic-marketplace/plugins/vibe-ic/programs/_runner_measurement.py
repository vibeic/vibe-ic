#!/usr/bin/env python3
"""Derive a tool-measurement record from the TOOL'S OWN OUTPUT ARTEFACT.

WHY THIS EXISTS
---------------
``_mcp_measurement`` is the READER half of a contract whose WRITER half is
``mcp-eda/src/index.js``'s ``measurementRecord()``. The phase-3 runner does not
go through that server: it drives openroad / magic / klayout / yosys by direct
``docker exec``. So the writer never runs, the third value is never stated, and
``provenance_check --require-measured`` reports UNDECLARED -> ``INCOMPLETE`` for
every physical artefact, on every design, forever.

MEASURED on spm x gf180mcuD, plugin v1.14.5, image sha256:fad41245fbff
(2026-08-31): `flow_compliance_check --phase all` returned FAIL through
`forced_fail`, from 34 step-execution ordering violations rooted in four steps —
16 of them naming step 22 (Parasitic Extraction) = INCOMPLETE, 7 naming step 31
(Physical Verification) = INCOMPLETE, 2 naming step 37 = INCOMPLETE. 25 of the 34
were this one gate with nothing to read.

WHAT THIS MODULE MAY AND MAY NOT CLAIM
--------------------------------------
It derives the record from the ARTEFACT the tool wrote, never from the fact that
a subprocess ran. That distinction is the whole safety argument, and there is a
live example of getting it wrong in this very tree: the runner's invocation
record already carries a flat ``"measured": True``, and it sits directly under

    "duration_ms": int(duration_ms),   # MEASURED, not a placeholder

i.e. it states that the DURATION was measured. Wiring THAT into the reader would
assert "openroad extracted parasitics" on the strength of "we timed the
subprocess" — exactly the fabrication ``_mcp_measurement`` was built to refuse
(its own example: openroad exiting 0 having linked nothing and analysed no path).

Reading the artefact is a real measurement and is strictly stronger than a
self-report: a tool that exited 0 having done nothing leaves an absent, empty or
header-only artefact, and every reader below turns that into ``measured: false``
with a hard class rather than into a pass.

WHAT IT REFUSES TO ANSWER
-------------------------
``None`` — no record at all — whenever this module has no rule for the artefact,
or the file does not parse as the format its extension claims. ``None`` is not
``measured: false``: it leaves the UNDECLARED state exactly as it was, which is
the state ``provenance_check`` already renders honestly. A reader with no rule
must add nothing.

EVERY RECORD IS LABELLED. ``operation`` names the artefact evidence the claim was
read from, and ``stated_by`` is ``"runner-derived"``, never a tool's self-report,
so a ledger reader can always tell the two apart.

chip-AGNOSTIC: file-format grammar only (SPEF / DEF / KLayout RDB). No design,
PDK or vendor literal.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

SCHEMA = "mcp-eda/measurement/1"
STATED_BY = "runner-derived"

#: Bounded, like every other reader that touches a sign-off artefact: a real
#: SPEF or DEF is multi-hundred-MB and a whole-file read has already killed a
#: step in this repo before it reached a verdict.
_CHUNK = 1 << 20
_OVERLAP = 64
_HEAD = 65536
_TAIL = 4096

_SPEF_HEADER_RE = re.compile(r"^\s*\*SPEF\b", re.M)
_SPEF_DNET_RE = re.compile(r"^\s*\*D_NET\b", re.M)
_DEF_COMPONENTS_RE = re.compile(r"^\s*COMPONENTS\s+(\d+)\s*;", re.M)
_RDB_OPEN_RE = re.compile(r"<report-database\b")
_RDB_CLOSE_RE = re.compile(r"</report-database>")
_RDB_DECK_RE = re.compile(r"<generator>\s*drc:\s*script\s*=\s*'([^']*)'", re.I)
_RDB_TOPCELL_RE = re.compile(r"<top-cell>([^<]*)</top-cell>")
_RDB_CATEGORY_RE = re.compile(r"<category>")
_RDB_ITEM_RE = re.compile(r"<item>")
_RDB_TOPCELL_REFUSED = ("", "unknown", "none", "null")


def _record(measured: bool, tool: str, operation: str, wrote: str,
            cls: Optional[str] = None, reason: str = "") -> Dict[str, Any]:
    rec: Dict[str, Any] = {
        "schema": SCHEMA,
        "measured": bool(measured),
        "operation": operation,
        "tool": tool,
        "read": [],
        "wrote": [wrote],
        "stated_by": STATED_BY,
    }
    if not measured:
        rec["not_measured_class"] = cls
        rec["not_measured_reason"] = reason
    return rec


def _count_streamed(path: Path, pattern: "re.Pattern") -> Optional[int]:
    """Occurrences of `pattern`, counted where each match STARTS.

    Counting a head slice and a carry as two separate strings splits any token
    that straddles the cut and counts it in NEITHER; accepting a match whose
    start is before the cut counts it exactly once, because the carry begins
    inside that token and the next round cannot see it again.
    """
    try:
        with path.open("rb") as fh:
            total = 0
            carry = ""
            while True:
                block = fh.read(_CHUNK)
                buf = carry + block.decode("utf-8", "ignore")
                last = not block
                cut = len(buf) if last else max(0, len(buf) - _OVERLAP)
                total += sum(1 for m in pattern.finditer(buf) if m.start() < cut)
                if last:
                    return total
                carry = buf[cut:]
    except OSError:
        return None


def _head(path: Path, n: int = _HEAD) -> Optional[str]:
    try:
        with path.open("rb") as fh:
            return fh.read(n).decode("utf-8", "ignore")
    except OSError:
        return None


def _spef(path: Path, rel: str, tool: str) -> Optional[Dict[str, Any]]:
    head = _head(path)
    if head is None or not _SPEF_HEADER_RE.search(head):
        return None                      # not a SPEF: no rule, say nothing
    n = _count_streamed(path, _SPEF_DNET_RE)
    if n is None:
        return None
    if n > 0:
        return _record(True, tool,
                       f"parasitic extraction — {n} *D_NET record(s) in the SPEF",
                       rel)
    return _record(
        False, tool, "parasitic extraction — 0 *D_NET records in the SPEF", rel,
        cls="TOOL_DID_NOT_RUN",
        reason=("the SPEF carries its header but not one extracted net, so no "
                "parasitic was produced for any net in this design"))


def _def(path: Path, rel: str, tool: str) -> Optional[Dict[str, Any]]:
    head = _head(path)
    if head is None:
        return None
    m = _DEF_COMPONENTS_RE.search(head)
    if m is None:
        body = _head(path, _HEAD * 8)    # COMPONENTS follows the header block
        m = _DEF_COMPONENTS_RE.search(body or "")
    if m is None:
        return None
    n = int(m.group(1))
    if n > 0:
        return _record(True, tool,
                       f"placement/route database — COMPONENTS {n} in the DEF",
                       rel)
    return _record(
        False, tool, "placement/route database — COMPONENTS 0 in the DEF", rel,
        cls="TOOL_DID_NOT_RUN",
        reason="the DEF declares no components, so nothing was placed")


def _rdb(path: Path, rel: str, tool: str) -> Optional[Dict[str, Any]]:
    """A COMPLETE KLayout report database measured; an incomplete one says
    nothing. The four guards are the same ones that separate a database which
    reported from a checker that died mid-write (0-byte report, top cell
    UNKNOWN)."""
    head = _head(path)
    if head is None or not _RDB_OPEN_RE.search(head):
        return None
    deck = _RDB_DECK_RE.search(head)
    if deck is None or not deck.group(1).strip():
        return None
    top = _RDB_TOPCELL_RE.search(head)
    if top is None or top.group(1).strip().lower() in _RDB_TOPCELL_REFUSED:
        return None
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - _TAIL))
            if not _RDB_CLOSE_RE.search(fh.read().decode("utf-8", "ignore")):
                return None              # truncated mid-write
    except OSError:
        return None
    # PRESENCE, not a count. `<category>` appears BOTH as a deck rule and as a
    # per-item reference inside `<items>`, so a raw tally is the deck size plus
    # the violation count and is not the number of rules — a test caught this
    # reporting 768 for a 763-rule deck with 5 items. The guard only needs "the
    # deck was enumerated at all"; the number that IS exact is the item count,
    # and that is the only one stated.
    if not _count_streamed(path, _RDB_CATEGORY_RE):
        return None                      # no deck enumerated
    items = _count_streamed(path, _RDB_ITEM_RE)
    if items is None:
        return None
    return _record(
        True, tool,
        f"rule-deck run — deck {deck.group(1).strip()} enumerated, "
        f"{items} violation item(s) recorded", rel)


#: Extension -> reader. Adding a format is adding one row and one function; a
#: format with no row yields None and the UNDECLARED state is left untouched.
_READERS = (
    (".spef", _spef),
    (".def", _def),
    (".rpt", _rdb),
    (".lyrdb", _rdb),
    (".xml", _rdb),
)


def derive(project: Path, rel: str, tool: str) -> Optional[Dict[str, Any]]:
    """A measurement record for `rel`, or None when nothing can be stated."""
    if not rel or not isinstance(rel, str):
        return None
    path = Path(project) / rel
    if not path.is_file() or path.stat().st_size == 0:
        return None
    low = rel.lower()
    for ext, fn in _READERS:
        if low.endswith(ext):
            try:
                return fn(path, rel, str(tool or ""))
            except (OSError, ValueError):
                return None
    return None


def derive_for_outputs(project: Path, outputs: Any,
                       tool: str) -> Optional[Dict[str, Any]]:
    """The record for the FIRST declared output this module can read.

    One entry may declare many outputs; the measurement answers "did this run
    do its work", so the first readable artefact answers it. A hard miss wins
    over a positive reading, for the same reason `_mcp_measurement.worst` ranks
    it that way: one artefact whose evidence says nothing was produced is not
    cured by a sibling that was.
    """
    if not isinstance(outputs, dict):
        return None
    best: Optional[Dict[str, Any]] = None
    for rel in outputs:
        rec = derive(project, rel, tool)
        if rec is None:
            continue
        if rec.get("measured") is False:
            return rec
        if best is None:
            best = rec
    return best
