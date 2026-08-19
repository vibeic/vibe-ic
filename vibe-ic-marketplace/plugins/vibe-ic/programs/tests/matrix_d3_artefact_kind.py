#!/usr/bin/env python3
"""matrix_d3_artefact_kind.py — the CONTENT half of dimension 3's evidence bar.

    "This file is present, non-empty, a real file and carried by the commit.
     Are its BYTES the kind of artefact its declared path says it is?"

WHY THIS MODULE EXISTS
======================
Dimension 3 asks whether a step's ``required_outputs`` are genuinely PRODUCED,
and until this module its whole answer was a stat call:

    test_matrix_d3_outputs_produced.resolve()   is_file() and st_size > 0
                                                and not a symlink
                                                and tracked at HEAD

Every one of those four rules is about the file's EXISTENCE. Not one of them
opens it. A ``drc_signoff.json`` holding the four bytes ``TODO``, a
``netlist.v`` holding a tool's error message, a ``chip_top.gds`` holding the
README — each is present, non-empty, a real file, and committable, and each
reads to dimension 3 exactly as the artefact it is standing in for. That is an
existence check wearing the clothes of a correctness check, which is the one
disease this campaign was convened to find.

WHAT THIS MODULE IS, AND WHAT IT IS NOT
=======================================
It decides ONE question and says so in its verdict: **is the byte stream of the
KIND the declared filename names?** JSON that parses. A GDSII stream whose
first record is a HEADER. A DEF with a ``DESIGN``/``END DESIGN`` pair. Verilog
with a top-level construct or a compiler directive.

It is NOT a correctness check and must never be mistaken for one:

  * It cannot tell a right number from a wrong number. A ``drc.json`` that says
    0 violations when the tool found 17 is well-formed JSON and passes here.
    That question belongs to the step's own gate, and the instrument that
    measures whether the gate answers it is
    ``matrix_mutation_ledger.ARTEFACT_MUTATIONS``.
  * It cannot speak about a kind it does not decide. ``.rpt``, ``.log``,
    ``.md``, ``.flag`` and the rest have no format this module can adjudicate
    without inventing one, so they are UNDECIDABLE — reported by name and by
    count, never silently passed as if they had been looked at.

The ceiling is stated here rather than left to be discovered: this arm raises
dimension 3's evidence bar from "there are bytes" to "there are bytes OF THE
RIGHT KIND". It closes the placeholder / wrong-file / truncated-to-garbage
class. It does not close the wrong-value class.

MEASURED BLAST RADIUS
=====================
Every declared ``required_outputs`` alternative was resolved with the flow's
own ``flow_compliance_check._glob_first`` against all 115 published run roots
discoverable in a clone of ``vibeic/benchmark-data`` (the 107 ``ic/`` cells
plus the ``evaluation/`` run trees), 2026-08-19::

    2135 resolved artefacts of a decidable kind
       0 non-conforming

    JSON 2003   VERILOG 81   SPICE 20   XML 14   GDS 12   LEF 2   LIBERTY 2
                DEF 1

So this arm is a RATCHET, not a re-grading: on the corpus as published it
changes no cell's colour, and it can only ever subtract evidence that the four
existence rules had already accepted. It is applied LAST for exactly that
reason — a candidate that fails an older rule still reports the older reason.

The first draft of the VERILOG rule required an ``endmodule`` and reddened
three real artefacts (``defines.v``, ``user_defines.v``, ``uprj_netlists.v``
under one published cell). They are legitimate Verilog: a header of ```define``
lines and an include list carry no module. That is why the rule accepts a
compiler directive as a top-level construct, and why the number above is a
measurement and not an assumption.

THE SIZE BOUND
==============
A verdict needs the bytes, and an unbounded read is a way for one pathological
artefact to take a test session down. :data:`MAX_BYTES` is 64 MiB. The largest
artefact of a decidable kind in the corpus is a 2.58 MB GDS, so the bound sits
about 25x above anything measured. Above it the verdict is
:data:`TOO_LARGE` — DISCLOSED, counted, and never a silent pass.
"""
from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

#: A file bigger than this is not read. See "THE SIZE BOUND" above.
MAX_BYTES = 64 * 1024 * 1024

#: The verdict when the path names no kind this module decides.
UNDECIDABLE = "UNDECIDABLE"

#: The verdict when the kind is decidable and the file is above `MAX_BYTES`.
TOO_LARGE = "TOO_LARGE"

#: The verdict when the kind is decidable and the file cannot be read at all.
UNREADABLE = "UNREADABLE"

#: GDSII stream, first record: length 6, record type 0x0002 (HEADER), data
#: type 0x00. Every GDSII file begins with it; this is the format's own
#: definition and carries no process, vendor or design token.
_GDS_HEADER = bytes([0x00, 0x06, 0x00, 0x02])

#: suffix -> kind. Longest suffix wins, so a future `.gds.gz` can be added
#: without disturbing `.gz`. Lower-cased before matching.
SUFFIX_KIND: Dict[str, str] = {
    ".json": "JSON",
    ".def": "DEF",
    ".v": "VERILOG",
    ".sv": "VERILOG",
    ".gds": "GDS",
    ".lef": "LEF",
    ".lib": "LIBERTY",
    ".sp": "SPICE",
    ".spice": "SPICE",
    ".xml": "XML",
    ".lyrdb": "XML",
}

#: Suffixes that appear in the live flow's ``required_outputs`` and that this
#: module deliberately does NOT decide. PINNED, and asserted against the live
#: yaml by ``test_d3_the_kind_arm_names_every_suffix_it_cannot_decide``: a NEW
#: suffix arrives unpinned and reddens BY NAME, so the population can never
#: grow into a kind nobody decided whether to decide.
#:
#: Why each is here, so that "undecidable" is a decision and not a shrug:
#:   csv report rpt txt log   free-form tool text; no format to adjudicate
#:   done flag                sentinels whose whole content is their existence
#:   md                       prose
#:   sby sdc tcl yml          scripts/constraints; a syntax check needs the tool
#:   mag sof spef             binary/vendor containers with no stable magic
#:                            this module can assert without a tool
UNDECIDABLE_SUFFIXES = frozenset({
    ".csv", ".done", ".flag", ".log", ".mag", ".md", ".report", ".rpt",
    ".sby", ".sdc", ".sof", ".spef", ".tcl", ".txt", ".yml",
})


@dataclass(frozen=True)
class KindVerdict:
    """What this module decided about one file, and why.

    ``conforms`` is TRI-STATE on purpose. ``None`` means NOT DECIDED — an
    undecidable suffix, a file above the size bound, a file that would not
    read. A caller that collapses ``None`` into ``True`` turns "I did not look"
    into "I looked and it was fine", which is the failure mode this whole
    module exists to refuse.
    """
    kind: str
    conforms: Optional[bool]
    reason: str

    @property
    def decided(self) -> bool:
        return self.conforms is not None

    @property
    def rejects(self) -> bool:
        """True only for a file that was READ and found to be the wrong kind."""
        return self.conforms is False


def suffix_of(rel: str) -> str:
    """The lower-cased final suffix of *rel*'s basename, or ``''``."""
    base = posixpath.basename(str(rel)).lower()
    dot = base.rfind(".")
    return base[dot:] if dot > 0 else ""


def kind_for(rel: str) -> Optional[str]:
    """The kind *rel*'s declared filename names, or None if undecidable."""
    return SUFFIX_KIND.get(suffix_of(rel))


# ──────────────────────────────────────────────────────────────────────
# The per-kind deciders.
#
# Each returns (conforms, why-not). They are deliberately STRUCTURAL: a
# construct the format itself requires, never a keyword from any particular
# design, PDK, foundry or tool. `flow_change_acceptance`'s "no design/PDK/
# vendor literals" rule is what that sentence is quoting.
# ──────────────────────────────────────────────────────────────────────
_VERILOG_TOP = re.compile(
    r"(?m)^\s*(module|macromodule|primitive|package|interface|program|class"
    r"|`\w+)\b")
_LEF_TOP = re.compile(r"(?m)^\s*(MACRO|LAYER|VERSION|SITE|UNITS)\b")
_LIBERTY_TOP = re.compile(r"(?mi)^\s*library\s*\(")
_SPICE_TOP = re.compile(
    r"(?mi)^\s*\.(end|ends|title|subckt|tran|dc|ac|op|noise|include|inc|lib"
    r"|param|model|options?|global|temp|meas(?:ure)?|print|plot|save)\b")


def _decide(kind: str, raw: bytes) -> Tuple[bool, str]:
    if kind == "GDS":
        return (raw[:4] == _GDS_HEADER,
                f"does not begin with the GDSII HEADER record "
                f"{_GDS_HEADER.hex()}; first 4 bytes are {raw[:4].hex()!r}")
    if kind == "JSON":
        try:
            json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            return False, f"does not parse as JSON: {exc}"
        return True, ""
    text = raw.decode("utf-8", "replace")
    if kind == "DEF":
        ok = "DESIGN" in text and "END DESIGN" in text
        return ok, "carries no DESIGN / END DESIGN pair"
    if kind == "VERILOG":
        return (_VERILOG_TOP.search(text) is not None,
                "carries no Verilog top-level construct (module / primitive / "
                "package / interface / program / class) and no `<directive>")
    if kind == "LEF":
        return (_LEF_TOP.search(text) is not None,
                "carries no LEF top-level statement (MACRO / LAYER / VERSION / "
                "SITE / UNITS)")
    if kind == "LIBERTY":
        return (_LIBERTY_TOP.search(text) is not None,
                "carries no `library (...)` group header")
    if kind == "SPICE":
        return (_SPICE_TOP.search(text) is not None,
                "carries no SPICE dot-command")
    if kind == "XML":
        return (text.lstrip()[:1] == "<",
                "does not begin with an XML/markup element")
    raise AssertionError(f"no decider for kind {kind!r} — SUFFIX_KIND and "
                         f"_decide have drifted apart")


def check(rel: str, path: Path) -> KindVerdict:
    """Decide *path*'s bytes against the kind *rel*'s filename names."""
    kind = kind_for(rel)
    if kind is None:
        return KindVerdict(UNDECIDABLE, None,
                           f"{suffix_of(rel) or '(no suffix)'} names no kind "
                           f"this module decides")
    try:
        size = path.stat().st_size
    except OSError as exc:
        return KindVerdict(kind, None, f"{UNREADABLE}: {exc}")
    if size > MAX_BYTES:
        return KindVerdict(kind, None,
                           f"{TOO_LARGE}: {size} B is above the {MAX_BYTES} B "
                           f"read bound, so the bytes were NOT read")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return KindVerdict(kind, None, f"{UNREADABLE}: {exc}")
    ok, why = _decide(kind, raw)
    return KindVerdict(kind, ok, "" if ok else f"declared {kind}, but the file {why}")


def decidable_population(entries) -> Tuple[Dict[str, int], Dict[str, int]]:
    """``(decidable-by-kind, undecidable-by-suffix)`` over *entries*.

    The denominator this arm publishes on every run. The house rule
    (``gate_discloses_denominator_check``): an aggregate that does not say how
    much it looked at is not a measurement.
    """
    decidable: Dict[str, int] = {}
    undecidable: Dict[str, int] = {}
    for rel in entries:
        kind = kind_for(rel)
        if kind is None:
            key = suffix_of(rel) or "(no suffix)"
            undecidable[key] = undecidable.get(key, 0) + 1
        else:
            decidable[kind] = decidable.get(kind, 0) + 1
    return decidable, undecidable
