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

chip-AGNOSTIC: file-format grammar only (SPEF / DEF / KLayout RDB / Verilog
gate netlist / LVS comparison report / GDSII stream). No design, PDK or
vendor literal.
"""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# The cell counter is REUSED, never re-written. `synth_netlist_check` already
# owns the one in this tree, and it already handles the two shapes a naive
# regex gets wrong on real yosys output: escaped identifiers (`\$_NAND_`,
# `\u.q_reg[0]`) and the `/* _NNN_ */` block comments `write_verilog -noexpr`
# puts between the cell type and the instance name. A second copy of the same
# fact answers differently the first time either side is touched.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:                                    # pragma: no cover - import guard
    from synth_netlist_check import count_cell_instances as _count_cells
except Exception:                       # pragma: no cover - import guard
    #: None means this module has NO rule for a netlist, which leaves the
    #: UNDECLARED state exactly as it was. A test asserts this is not None, so
    #: a broken import cannot silently make the netlist rule vacuous.
    _count_cells = None

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

# -- Verilog gate-level netlist ------------------------------------------
#: A prefix is enough to answer "did the tool map any gate at all", and this
#: module refuses whole-file reads by charter (its own docstring: a whole-file
#: read has already killed a step in this repo before it reached a verdict). A
#: gate netlist for a large SoC is hundreds of MB.
_NETLIST_SCAN_BYTES = 32 << 20
_V_MODULE_RE = re.compile(r"^\s*module\s+[\\A-Za-z_]", re.M)

# -- LVS comparison report (netgen / magic / KLayout text) ----------------
#: The STRUCTURAL tell that this text is a netlist COMPARISON at all. Without
#: it the file is somebody else's format and this module says nothing.
_LVS_TELL_RE = re.compile(
    r"^\s*(?:Subcircuit summary:|Contents of circuit\s|Circuit 1:)", re.M)
#: The comparator's CONCLUSION, spelled POLARITY-NEUTRALLY on purpose. "do not
#: match" is measured just as fully as "match" is: the module's own rule is
#: that a DRC run which found twelve violations measured perfectly, and an LVS
#: run that proved a mismatch measured perfectly too. A reader that only
#: recognised the passing spelling would report the failing run as unmeasured,
#: which is the "absence reads like a pass" defect pointing the other way.
_LVS_RESULT_RE = re.compile(
    r"^\s*(?:Final result\s*:|Result\s*:"
    r"|(?:Netlists|Circuits|Subcircuits)\s+(?:match|do not match|differ))",
    re.M | re.I)
#: One `Circuit 1:` header per compared circuit pair — a count of what was
#: compared, carrying no verdict.
_LVS_PAIR_RE = re.compile(r"^\s*Circuit 1:", re.M)

# -- GDSII stream --------------------------------------------------------
_GDS_HEADER = 0x0002
_GDS_BGNSTR = 0x0502
_GDS_ENDLIB = 0x0400
#: The records that ARE layout. NODE (0x1500) is deliberately absent: it is an
#: electrical annotation, not geometry, and a library holding only NODEs
#: streamed no layout.
_GDS_ELEMENTS = frozenset((0x0800,   # BOUNDARY
                           0x0900,   # PATH
                           0x0A00,   # SREF
                           0x0B00,   # AREF
                           0x0C00,   # TEXT
                           0x2D00))  # BOX
#: Walk buffer. Payloads are SKIPPED, never decoded, so this bounds memory at
#: one block no matter how large the stream is.
_GDS_BLOCK = 1 << 20


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


def _verilog_netlist(path: Path, rel: str, tool: str) -> Optional[Dict[str, Any]]:
    """A gate-level Verilog netlist measured by its CELL INSTANCE COUNT.

    The question is the same one every reader here asks — did the run do its
    work — and for logic synthesis the artefact answers it directly: a yosys
    invocation that read no RTL, or mapped nothing, writes a file with a module
    header and not one instantiation. That is the shape `synth_netlist_check`
    already names ZERO_CELLS, and its counter is the one used here rather than
    a second one written beside it.

    BOUNDED, and the bound is disclosed in the record. A prefix cut at a line
    boundary is enough to prove `n > 0` (the counter is line-oriented, so the
    cut is well-defined). It is NOT enough to prove `n == 0`: a netlist whose
    first 32 MiB happen to be declarations is not a netlist with no cells, so a
    zero count over a TRUNCATED read returns None — no rule, say nothing —
    instead of a hard miss this module cannot actually justify.
    """
    if _count_cells is None:
        return None
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            raw = fh.read(_NETLIST_SCAN_BYTES)
    except OSError:
        return None
    truncated = size > len(raw)
    text = raw.decode("utf-8", "replace")
    if truncated:
        cut = text.rfind("\n")
        if cut <= 0:
            return None                  # no complete line: nothing to count
        text = text[:cut]
    if not _V_MODULE_RE.search(text):
        return None                      # not a Verilog module: no rule
    try:
        total, _ = _count_cells(text)
    except Exception:                    # a counter that raises states nothing
        return None
    if total > 0:
        where = (f" (first {len(text)} character(s) of {size} bytes)"
                 if truncated else "")
        return _record(True, tool,
                       f"logic synthesis — {total} cell instance(s) "
                       f"in the netlist{where}", rel)
    if truncated:
        return None
    return _record(
        False, tool, "logic synthesis — 0 cell instances in the netlist", rel,
        cls="TOOL_DID_NOT_RUN",
        reason=("the netlist declares a module and not one cell instance, so "
                "no gate was mapped for this design"))


def _lvs_report(path: Path, rel: str, tool: str) -> Optional[Dict[str, Any]]:
    """A netlist COMPARISON report measured by whether the comparator concluded.

    Two guards, in the same discipline as `_rdb`: a structural tell that this
    text is a comparison at all, and the comparator's own conclusion. A report
    that enumerates circuits and never states a result is a comparator that
    died mid-run, and that is a hard miss. A file with no tell is somebody
    else's format and this module says nothing about it.

    WHAT THIS DELIBERATELY DOES NOT READ: the POLARITY of the conclusion. An
    LVS run that proved a mismatch measured its design completely; reporting it
    as unmeasured would hide a real defect behind "nobody looked", and reading
    the polarity here would also duplicate `lvs_report_check`, which owns the
    verdict. This states only that the comparison happened.
    """
    head = _head(path)
    if head is None:
        return None
    tell = _LVS_TELL_RE.search(head)
    if tell is None:
        # The tell is a per-circuit header and a long report may carry its
        # first one past the head window, so look once more at the whole
        # bounded scan before refusing.
        head = _head(path, _HEAD * 8)
        if head is None or _LVS_TELL_RE.search(head) is None:
            return None
    pairs = _count_streamed(path, _LVS_PAIR_RE)
    results = _count_streamed(path, _LVS_RESULT_RE)
    if results is None or pairs is None:
        return None
    if results > 0:
        return _record(True, tool,
                       f"layout-vs-schematic — {pairs} circuit pair(s) "
                       f"compared, comparator stated its result", rel)
    return _record(
        False, tool,
        f"layout-vs-schematic — {pairs} circuit pair(s) enumerated, no result "
        f"stated", rel,
        cls="TOOL_DID_NOT_RUN",
        reason=("the report enumerates circuits but the comparator never "
                "stated a result, so no netlist comparison was concluded"))


def _gds_walk(path: Path) -> Optional[Dict[str, int]]:
    """Walk a GDSII record stream. None when the bytes are not one.

    Payloads are SKIPPED, never decoded: the walk reads a 4-byte record header,
    advances by the declared length, and refills a one-block buffer. Memory is
    one block regardless of stream size, which is the same bound every other
    reader in this module keeps.
    """
    try:
        with path.open("rb") as fh:
            first = fh.read(4)
            if len(first) < 4:
                return None
            rec_len, rec_type = struct.unpack(">HH", first)
            if rec_type != _GDS_HEADER or rec_len < 4:
                return None              # not a GDSII stream: no rule
            fh.seek(0)
            structures = elements = 0
            saw_endlib = False
            buf = b""
            pos = 0
            while True:
                if len(buf) - pos < 4:
                    buf = buf[pos:] + fh.read(_GDS_BLOCK)
                    pos = 0
                    if len(buf) < 4:
                        break
                rec_len, rec_type = struct.unpack_from(">HH", buf, pos)
                # GDSII record lengths are ALWAYS even (the format pads every
                # payload to a word). An odd length is a malformed stream, and
                # a reader that walks past it silently produces a count for
                # bytes it did not understand. Found by the cross-check against
                # `gds_substance_check.parse_gds`, which reported
                # MALFORMED_RECORD on a fixture this walk happily counted.
                if rec_len < 4 or rec_len % 2:
                    return None          # malformed: say nothing
                if rec_type == _GDS_BGNSTR:
                    structures += 1
                elif rec_type in _GDS_ELEMENTS:
                    elements += 1
                elif rec_type == _GDS_ENDLIB:
                    saw_endlib = True
                pos += rec_len
                if pos > len(buf):       # record runs past what we have
                    skip = pos - len(buf)
                    buf, pos = b"", 0
                    fh.seek(skip, 1)
            if not saw_endlib:
                return None              # truncated mid-write: say nothing
            return {"structures": structures, "elements": elements}
    except (OSError, struct.error):
        return None


def _gdsii(path: Path, rel: str, tool: str) -> Optional[Dict[str, Any]]:
    """A GDSII stream measured by the LAYOUT IT CARRIES.

    A streamer that exited 0 having read nothing writes a well-formed but empty
    library — HEADER, BGNLIB, LIBNAME, UNITS, ENDLIB and no structure. That is
    a real, measured failure and it is reported as one. An incomplete stream
    (no ENDLIB) is a writer that died, and this module has no standing to say
    what such a run did: it says nothing.

    This counts records; it does not judge them. Whether the geometry is
    SUFFICIENT for the design is `gds_substance_check`'s question, and it
    answers it against the DEF's own placed-instance count.
    """
    stats = _gds_walk(path)
    if stats is None:
        return None
    if stats["elements"] > 0:
        return _record(True, tool,
                       f"GDSII stream-out — {stats['structures']} structure(s), "
                       f"{stats['elements']} layout element(s) in the library",
                       rel)
    return _record(
        False, tool,
        f"GDSII stream-out — {stats['structures']} structure(s), 0 layout "
        f"elements in the library", rel,
        cls="TOOL_DID_NOT_RUN",
        reason=("the library closes with ENDLIB and holds no boundary, path, "
                "reference, text or box, so no geometry was streamed"))


def _rpt(path: Path, rel: str, tool: str) -> Optional[Dict[str, Any]]:
    """`.rpt` is not one grammar, so the row is a CHAIN, not a reader.

    MEASURED on one run tree: `reports/phase3/drc_signoff.rpt` is a KLayout
    report database (XML) and `reports/phase3/lvs.rpt` is netgen text. They
    share an extension and nothing else, and while `.rpt` meant only the RDB,
    the LVS artefact fell through to "no rule" and Step 31 was INCOMPLETE
    forever on a run whose LVS had in fact completed.

    Order matters and is not arbitrary: `_rdb` requires an XML open tag before
    it will say anything, so a text report can never reach it, while an RDB
    could conceivably contain an LVS-looking word in a rule description. The
    stricter reader goes first.
    """
    return _rdb(path, rel, tool) or _lvs_report(path, rel, tool)


#: Extension -> reader. Adding a format is adding one row and one function; a
#: format with no row yields None and the UNDECLARED state is left untouched.
#:
#: THE TABLE IS THE CONTRACT'S COVERAGE, and a row missing here is a step
#: INCOMPLETE forever, not a step that merely reads a little less. MEASURED on
#: spm x gf180mcuD (run spm_firstpass_f63410d, plugin v1.14.30): the flow
#: declares SIX `provenance_check --require-measured` clauses; the two whose
#: artefact had a row (.def for step 21, .spef for step 22) PASSED and the
#: three whose artefact had none — the Verilog netlist (step 9), the netgen LVS
#: report (step 31) and the GDSII (step 37) — were UNMEASURED, which is exactly
#: the three steps the completion audit listed as INCOMPLETE.
_READERS = (
    (".spef", _spef),
    (".def", _def),
    (".v", _verilog_netlist),
    (".sv", _verilog_netlist),
    (".gds", _gdsii),
    (".gds2", _gdsii),
    (".gdsii", _gdsii),
    (".rpt", _rpt),
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


def attach(project: Path, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Attach the derived measurement to ONE provenance entry, in place.

    WHY EVERY WRITER AND NOT JUST THE INVOCATION LOGGER
    ---------------------------------------------------
    The runner appends to `provenance.jsonl` from several places: the
    `docker exec` invocation logger, and a family of BACK-FILL writers that
    declare artefacts the runner finds on disk. Only the first ever stated the
    measurement, and `provenance_check._find_entry` binds an artefact to its
    MOST RECENT matching entry — so a back-fill written seconds later
    SUPERSEDES the invocation record that carried the reading, and the gate
    reports UNMEASURED over a run that was measured.

    MEASURED on spm x gf180mcuD (spm_firstpass_f63410d): `reports/phase3/lvs.rpt`
    had four declaring entries; the one carrying the tool invocation was
    written at 08:07:43 and the one the check actually bound to was a back-fill
    at 08:07:58. `phase3/stage3/pnr/routed.def` escaped only because its later
    back-fill was written under the tool name `phase3_one_shot_runner`, which
    that clause's `--tool openroad` allow-list happens to reject — a
    coincidence of a tool NAME, not a property of the design.

    THE SAFETY ARGUMENT IS UNCHANGED, and it is the reason this is sound on a
    back-fill at all: the record is derived from the ARTEFACT ON DISK, never
    from the fact that a subprocess ran. A back-fill that finds an empty GDS or
    a cell-less netlist states `measured: false` with a hard class, exactly as
    the invocation logger would. `stated_by: "runner-derived"` labels it either
    way, so a ledger reader can always tell a derived record from a tool's own.

    Never overwrites a record that is already there, and never raises: a
    provenance entry that cannot carry this is still a correct provenance
    entry, and bookkeeping must not break a run.
    """
    try:
        if not isinstance(entry, dict) or "measurement" in entry:
            return entry
        rec = derive_for_outputs(Path(project), entry.get("outputs"),
                                 str(entry.get("tool") or ""))
        if rec is not None:
            entry["measurement"] = rec
    except Exception:      # nosec - provenance must never break a run
        pass
    return entry
