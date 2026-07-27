#!/usr/bin/env python3
"""Was the input actually READ? (#499)

WHY THIS MODULE EXISTS — several Phase-1 gates have an honest and
necessary escape for designs whose input genuinely lacks the thing they
audit.  ``l3_opcode_name_coverage_check`` prints

    VACUOUS_PASS: L3.opcodes empty — no command protocol in input
                  (structurally correct for non-protocol IPs).

and that sentence is true of, say, a hash core.  It was also printed —
twice, by two independent gates — for a RISC-V CPU, because the document
carrying its eleven-entry opcode table had been silently dropped by the
ingester and the layer therefore came out empty (#499).

The verdict is a claim about the INPUT, and the gate had no way to know
whether the input had been read.  A dropped document manufactures a
clean-looking zero, and a vacuous pass built on one is indistinguishable
downstream from a real one.

WHAT THIS MODULE PROVIDES — the ingester already records every file it
visited and could not render, in ``extraction_skipped.json``.  This
module reads that record and separates two very different things:

  * ``deliberate`` — a binary or archive the ingester decided is not a
    document (``.zip``, ``.gds``, ``.lib``).  Nothing was lost that
    Phase 1 was ever going to read, so an absence claim stands.
  * ``unread``     — a document Phase 1 INTENDED to read and could not:
    a converter that returned empty, a legacy office format with no
    decoder available, a raster whose OCR was unavailable, a write that
    failed.  An absence claim does not stand over these, and a gate that
    makes one must say so instead.

The distinction is drawn from the reason strings the ingester itself
writes, so a new skip reason gets classified where it is emitted rather
than guessed at here — anything unrecognised is treated as UNREAD,
because the safe default for "I don't know whether I read this" is not
"I did".

Chip-AGNOSTIC: pure report-file structure and the ingester's own reason
vocabulary.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Where the ingester writes its skip record. Both locations are read:
# `_path_layout` routes phase-1 reports under `reports/phase1/`, and the
# runner additionally writes a copy beside the extracted docs.
SKIP_LOG_RELPATHS: Tuple[str, ...] = (
    "reports/phase1/extraction_skipped.json",
    "phase1/extraction_skipped.json",
    "reports/extraction_skipped.json",
)

CLASS_DELIBERATE = "deliberate_non_document"
CLASS_UNREAD = "unread_document"

# Reason-string fragments the ingester writes when it decided a file is
# not a document at all. Everything else counts as unread — see the
# module docstring for why the default points that way.
_DELIBERATE_FRAGMENTS = (
    "binary/archive extension",
)

# Within UNREAD, the cause matters for whose defect it is:
#
#   converter gap — the ingester has NO branch for this format. That is
#                   a plugin defect: it will drop the same document on
#                   every machine, forever, until a branch is written.
#   tooling gap   — the ingester has a branch but the external decoder
#                   it needs (antiword, xlrd, tesseract) is absent from
#                   THIS machine. Loud, but not a plugin defect, and not
#                   something a user can fix by re-running.
#
# Both make an absence claim unavailable; only the first is the
# plugin's own bug.
_CONVERTER_GAP_FRAGMENTS = (
    "returned empty",
    "did not look like plain text",
)


def classify_skip_reason(reason: str) -> str:
    """``CLASS_DELIBERATE`` or ``CLASS_UNREAD`` for one skip reason."""
    text = (reason or "").lower()
    for frag in _DELIBERATE_FRAGMENTS:
        if frag in text:
            return CLASS_DELIBERATE
    return CLASS_UNREAD


def is_converter_gap(reason: str) -> bool:
    """True when the ingester had no working branch for the format."""
    if classify_skip_reason(reason) != CLASS_UNREAD:
        return False
    text = (reason or "").lower()
    return any(frag in text for frag in _CONVERTER_GAP_FRAGMENTS)


def read_skip_log(project: Path) -> Optional[Dict[str, Any]]:
    """The ingester's skip record, or ``None`` when it wrote none.

    ``None`` is NOT the same as an empty record: it means Phase 1's
    document ingester did not run (or predates the record), so nothing
    can be concluded about completeness either way.
    """
    for rel in SKIP_LOG_RELPATHS:
        p = Path(project) / rel
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8",
                                          errors="replace"))
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return None


def unread_input_documents(project: Path) -> List[Dict[str, str]]:
    """Documents Phase 1 visited and failed to read.

    Empty list means either "everything rendered" or "no record" — call
    ``read_skip_log`` when the difference matters.
    """
    data = read_skip_log(Path(project))
    if not data:
        return []
    out: List[Dict[str, str]] = []
    for entry in (data.get("skipped") or []):
        if not isinstance(entry, dict):
            continue
        reason = str(entry.get("reason") or "")
        if classify_skip_reason(reason) != CLASS_UNREAD:
            continue
        out.append({
            "path": str(entry.get("path") or ""),
            "reason": reason,
        })
    return out


def converter_gap_documents(project: Path) -> List[Dict[str, str]]:
    """Unread documents whose cause is a MISSING CONVERTER BRANCH.

    The subset of ``unread_input_documents`` that is the plugin's own
    defect rather than a property of the machine it ran on.
    """
    return [e for e in unread_input_documents(Path(project))
            if is_converter_gap(e.get("reason", ""))]


def absence_claim_disclosure(project: Path) -> str:
    """The sentence a gate must append when it reports "not in input".

    Empty string when the input was read completely, so a gate can
    concatenate it unconditionally.
    """
    unread = unread_input_documents(Path(project))
    if not unread:
        return ""
    shown = ", ".join(e["path"] for e in unread[:3])
    more = f" (+{len(unread) - 3} more)" if len(unread) > 3 else ""
    return (
        f" NOT AN ABSENCE — THE INPUT WAS NOT FULLY READ: the Phase-1 "
        f"ingester visited {len(unread)} document(s) it could not "
        f"render ({shown}{more}); see reports/phase1/"
        f"extraction_skipped.json. This layer's emptiness cannot be "
        f"attributed to the design until every staged document has been "
        f"ingested."
    )


def input_fully_read(project: Path) -> bool:
    """True when no staged document was left unread."""
    return not unread_input_documents(Path(project))
