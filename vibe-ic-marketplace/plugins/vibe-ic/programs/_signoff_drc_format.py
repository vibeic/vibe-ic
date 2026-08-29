#!/usr/bin/env python3
"""ONE answer to "what produced this DRC report, and what layout did it read?".

WHY THIS MODULE EXISTS
----------------------
The Step-31 sign-off DRC gate accepted the ROUTER as the producer of its own
sign-off certificate. MEASURED on a real Phase-3 run's router projection
(19,162 bytes, re-staged to ``reports/phase3/drc_signoff.rpt``, in a project
containing ZERO GDS files)::

    drc_report_check . --mode drc --under reports/phase3/drc_signoff.rpt
        -> rc=0  passed:true  tool_authentic:true  determined_files:1
                 real_violation_total:0

and, on the SAME artefact, the runner's provenance back-fill stamped
``tool: "klayout"`` with the command string ``klayout -b -r drc (sign-off DRC)``
— an invocation that never happened — so the Step-31 provenance allow-list
passed it under EVERY tool list tried (``klayout,magic,openroad`` /
``klayout,magic,svrfdrc`` / ``klayout,magic``: all rc=0). The allow-list was
never the hole; the ATTRIBUTION was.

Three programs already answered fragments of this question, divergently:

* ``signoff_audit._check_tapeout``  — an SVRF per-rule grammar, inline.
* ``signoff_ladder_run.check_tier_1_drc`` — a KLayout ``<item>`` count, no SVRF
  dialect, and NO producer test at all (it issues a RELEASE-GATING
  ``PASS`` named "Full DRC (KLayout/Magic)" from a router log — measured).
* ``eda_report_audit._drc_real_violation_count`` — KLayout ``<items>`` plus
  three text regexes, and NO SVRF dialect (a clean 4533-PASS foundry-deck
  sign-off measures ``determined_files:0`` → the gate FAILs the authoritative
  report).

A fourth private copy is how that divergence happened. This module is the
shared home the callers adopt.

WHAT IS AND IS NOT A SIGN-OFF PRODUCER
--------------------------------------
A sign-off DRC verdict is the output of a RULE DECK applied to a LAYOUT. The
router's detailed-route DRC is a routability measurement over its own database:
a legitimate and useful check (Step 21 gates on it), but it cannot certify
Step 31, because it never opened the streamed layout and never read the
foundry's rules. The distinction is a property of the REPORT, which is why it
is decided here from the report's own bytes and never from a caller's flag, a
filename, or a ``# Tool:`` header a producer wrote about itself.

chip-AGNOSTIC: every pattern below is report GRAMMAR. No design name, no PDK
SKU, no foundry, no part number appears in this file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --- producer kinds ---------------------------------------------------------
#: A rule deck was applied to a layout — a sign-off producer.
KLAYOUT = "klayout"
SVRFDRC = "svrfdrc"
MAGIC = "magic"
#: The router's own detailed-route DRC projection — NOT a sign-off producer.
OPENROAD = "openroad"

SIGNOFF_PRODUCERS: Tuple[str, ...] = (KLAYOUT, SVRFDRC, MAGIC)

#: How many bytes of a report are enough to classify it. A producer banner and
#: an XML/format header both live at the top; reading 64 KiB keeps an 11 MB
#: report cheap to classify.
_HEAD_BYTES = 65536


# --- the ORGANIC alias header ----------------------------------------------
# `phase3_one_shot_runner` re-stages the sign-off DRC report through
# `reports/phase3/drc_signoff.rpt` and prepends a 4-line `#` provenance banner.
# MEASURED consequence, on the published corpus: that banner makes
# `text.lstrip()` start with `#`, so `_drc_real_violation_count`'s
# `startswith("<?xml")` container test fails and the KLayout <items> branch —
# the STRONG dialect — is skipped on every headered report. All 7 headered
# published reports measure `None` (undeterminable) as published and a real
# count once the 4 lines are removed. Classification here must therefore look
# THROUGH the banner; it is metadata about the file, not the file's format.
_ALIAS_HEADER_LINE = re.compile(r"^\s*#")


def strip_alias_header(text: str) -> str:
    """`text` without its leading run of ``#`` comment lines."""
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines) and _ALIAS_HEADER_LINE.match(lines[i]):
        i += 1
    return "".join(lines[i:])


# --- the SVRF-native dialect ------------------------------------------------
# Lifted verbatim from `signoff_audit._check_tapeout`'s inline copy so the two
# cannot drift: the vibeic KLayout `svrfdrc` buddy running a foundry `.rule`
# deck emits per-rule result lines `FAIL|PASS|SKIP <rule> <op> ... -> <n>` and
# NEVER a "total violations:" line. Without this dialect a genuinely-clean
# sign-off reads as UNPARSED, which is why the highest-authority tier is the
# one the gate cannot currently credit.
SVRF_RESULT_RE = re.compile(r"(?m)^(FAIL|PASS|SKIP)\s+\S+\s+\S+.*->\s*\d+\s*$")
_SVRF_BANNER_RE = re.compile(r"(?i)svrf-native drc|\bsvrfdrc\b")
_SVRF_FAIL_RE = re.compile(r"(?m)^FAIL\s+\S+")
_SVRF_PASS_RE = re.compile(r"(?m)^PASS\s+\S+")


def looks_svrf(text: str) -> bool:
    """True iff `text` is an SVRF-native sign-off DRC report."""
    head = text[:4096]
    return bool(_SVRF_BANNER_RE.search(head) or SVRF_RESULT_RE.search(text))


def svrf_fail_count(text: str) -> Optional[int]:
    """Number of FAILing rules, or None when no per-rule tally is present.

    None (never 0) when the report carries no tally at all: an unreadable
    sign-off must not be credited as clean.
    """
    if not looks_svrf(text):
        return None
    fails = len(_SVRF_FAIL_RE.findall(text))
    passes = len(_SVRF_PASS_RE.findall(text))
    if fails or passes:
        return fails
    return None


# --- the router's iterative violation trajectory ---------------------------
# ORGANIC #585 grammar, lifted here so `signoff_audit`'s plain-text sign-off
# reader and `phase3_one_shot_runner._drt_final_violations` share ONE
# implementation and cannot return different numbers for one report.
#
# A detailed-route DRC report is ITERATIVE: the router emits one running count
# per repair iteration — `[INFO DRT-0199]  Number of violations = N` (older
# builds: `Completing 100% with N violations`) — and a single report may hold
# more than one route pass (a later incremental reroute restarts the sequence),
# so the trajectory is non-monotone in general. Only the LAST count describes
# the geometry that actually ships. `re.search` returns the FIRST match — the
# state BEFORE any repair — which can be LARGER than the final count (over-
# report → false FAIL on a clean design) or SMALLER (under-report → false PASS
# on a design that never converged). The reader must take the last, not the
# first. chip-AGNOSTIC: OpenROAD/TritonRoute log grammar only.
RE_DRT_0199 = re.compile(
    r"\[INFO DRT-0199\]\s*Number of violations\s*=\s*(\d+)")
RE_DRT_COMPLETING = re.compile(
    r"Completing\s+100%\s+with\s+(\d+)\s+violations?")

# DRT-0701 SUPERSEDES THE TRAJECTORY, AND THE ROUTER SAYS SO ITSELF.
# OpenROAD runs a POST-ROUTE VERIFICATION after the repair loop ends. When it
# disagrees with the loop it emits, in its own words:
#
#   [WARNING DRT-0701] Post-route verification found 1 violation(s) that the
#   routing loop did not report (0 in-loop). The published result is the verified one.
#
# "The published result is the verified one" — the tool is telling the reader
# which of its two numbers describes the geometry that ships. The DRT-0199
# trajectory is the loop's view and is SUPERSEDED whenever this line is present.
#
# MEASURED on a real gf180mcuD run of `spm` (2026-08-29): trajectory
# [251, 50, 50, 0] with DRT-0701 reporting 1. Reading the trajectory gave 0
# while `detailedroute__route__drc_errors` in the metrics JSON carried 1, and
# the disagreement failed pnr with ROUTE_DRC_METRIC_DISAGREEMENT — so NO GDS was
# ever streamed, which then failed steps 31/36/38 and left 37 MISSING. One
# unparsed line, four reds.
#
# Worse than the false number: `_route_feedback_loosen_ex` decides whether to
# grow the die from the trajectory, so a trailing 0 reads as "still converging"
# and the automatic rescue DECLINES to fire on a design that had not converged.
# chip-AGNOSTIC: OpenROAD/TritonRoute log grammar only.
RE_DRT_0701 = re.compile(
    r"\[WARNING DRT-0701\][^\n]*?found\s+(\d+)\s+violation")


def router_iter_counts(text: str) -> List[int]:
    """Every per-iteration router DRC count, in log order ([] when none).

    Prefers the explicit `[INFO DRT-0199]` end-of-iteration tally; only when a
    log has none does it fall back to the per-iteration `Completing 100% with N`
    line. Mixing the two would double-count, so the fallback is exclusive.
    """
    if not text:
        return []
    raw = RE_DRT_0199.findall(text) or RE_DRT_COMPLETING.findall(text)
    out: List[int] = []
    for c in raw:
        try:
            out.append(int(c))
        except (TypeError, ValueError):
            continue
    # The post-route verification's count is APPENDED, not substituted: the
    # trajectory is still the loop's real history and `_drt_violation_trajectory`
    # readers want it. Appending makes the LAST element the published number, so
    # `router_iter_last_count` — which every caller uses for "what ships" —
    # returns the verified count without any caller having to know about 0701.
    #
    # `out` MUST ALREADY BE NON-EMPTY. Appending to an empty list does not
    # supersede a trajectory, it MANUFACTURES one: DRT-0701 is not a
    # per-iteration count, and this function's contract one docstring up is
    # "every per-iteration router DRC count ([] when none)". v1.12.54 wrote the
    # condition as `(not out or out[-1] != verified)`, and that `not out`
    # disjunct made a log carrying ONLY a 0701 line read as a one-iteration
    # route. MEASURED on such a log at v1.12.68, before this line was fixed:
    #
    #   router_iter_counts        []  ->  [1]      a trajectory never printed
    #   _drt_violation_trajectory []  ->  [1]
    #   _drt_is_non_converging  False  ->  True    the loosen ladder judging
    #                                              convergence from one point
    #   _ppa route.drc.violation.count
    #        NOT_MEASURED(log)  ->  MEASURED 1 kind=log trajectory_len=1
    #
    # That last row is the damage that reached the PPA contract: the log then
    # AGREED with `openroad.metrics.json`, so the artefact-authority
    # declaration had no conflict left to settle and no silence left to record
    # — the log's honest "I never printed this" was replaced by a number it
    # never printed. A log the loop said nothing in is still UNDETERMINED here;
    # `router_post_route_verified_count` remains the way to ask 0701 directly.
    if out:
        verified = router_post_route_verified_count(text)
        if verified is not None and out[-1] != verified:
            out.append(verified)
    return out


def router_post_route_verified_count(text: str) -> Optional[int]:
    """OpenROAD's POST-ROUTE VERIFICATION count, or None when it did not speak.

    None, never 0, for the same reason `router_iter_last_count` returns None on
    a report with no trajectory: "the verifier said nothing" and "the verifier
    found nothing" are different facts, and collapsing them would turn a log this
    reader cannot read into a clean design.
    """
    if not text:
        return None
    m = RE_DRT_0701.findall(text)
    if not m:
        return None
    try:
        return int(m[-1])
    except (TypeError, ValueError):
        return None


def router_iter_last_count(text: str) -> Optional[int]:
    """The LAST per-iteration router DRC count — the shipped geometry's state —
    or None when the report carries no router-iteration grammar at all.

    None, never 0: a report with no DRT trajectory is UNDETERMINED here, not
    clean. Collapsing that to 0 would turn "could not read this report" into
    "this design is DRC-clean" — the exact false PASS this reader exists to
    avoid — so the caller keeps its own no-match handling for that case.
    Degrades correctly to "take the only match" for a single-count report.
    """
    counts = router_iter_counts(text)
    return counts[-1] if counts else None


# --- the router's own projection -------------------------------------------
# DISQUALIFYING markers, checked FIRST. Each is a literal the router (or the
# runner's projection of it) emits about ITSELF; none can appear in a rule
# deck's report database. `DRT-\d{4}` is OpenROAD's detailed-route message-code
# namespace, not a word that occurs in layout geometry.
#
# The `# Tool: openroad` banner is included even though every other decision
# here is content-first, because THIS self-report is against interest: no
# laundering attempt ever mis-attributes a report TOWARD the router. Reading it
# can only ever refuse something; it can never credit something.
_ROUTER_RE = re.compile(
    r"OpenROAD\s+detailed_route\s+DRC"
    r"|detailed_route\s+invoked"
    r"|\bdrt-pass\b"
    r"|\bDRT-\d{4}\b"
    r"|^[ \t]*#[ \t]*Tool:[ \t]*openroad\b",
    re.I | re.M)

# --- the KLayout report database -------------------------------------------
_RDB_RE = re.compile(r"<report-database\b")
#: The deck the run applied, as KLayout records it. A report database with NO
#: declared generator cannot say WHICH rules produced it — and "which rules"
#: is the whole content of a sign-off claim.
_RDB_DECK_RE = re.compile(r"<generator>\s*drc:\s*script\s*=\s*'([^']*)'", re.I)
_RDB_TOPCELL_RE = re.compile(r"<top-cell>([^<]*)</top-cell>")

# --- the Magic DRC transcript ----------------------------------------------
#: Magic's count, in the two dialects it is actually written in. The second is
#: what the LibreLane `Magic.DRC` step emits, and MEASURED on a real run it is
#: the ONLY verdict marker present:
#:
#:     $ grep -n 'COUNT:\|DRC errors' 67-magic-drc/reports/drc.magic.rpt
#:     [INFO] COUNT: 0
#:
#: `DRC errors found: N` never appears in that flow's output, so a classifier
#: that knows only the first dialect cannot recognise a Magic report this flow
#: produced -- see `_MAGIC_TAIL_BYTES` for the other half of the same miss.
_MAGIC_COUNT_RE = re.compile(
    r"(?i)(?:\bDRC\s+errors?\s+found\s*:\s*\d+"
    r"|^\s*(?:\[INFO\]\s*)?COUNT\s*:\s*\d+)", re.M | re.I)
_MAGIC_CMD_RE = re.compile(r"(?i)\bdrc\s+(?:count|why|check|catchup)\b")
_MAGIC_BANNER_RE = re.compile(r"(?i)\bmagic\b")

#: A TRANSCRIPT PUTS ITS VERDICT AT THE END. MEASURED on a real 11 471 075-byte
#: Magic DRC transcript from the gf180mcuD chip path:
#:
#:     'Magic 8.3'        first at byte           1     <- inside the 64 kB head
#:     'No errors found'  first at byte  11 470 745     <- 175x beyond it
#:     'COUNT:'           first at byte  11 470 769
#:     'drc count|why|check|catchup'  ABSENT ENTIRELY
#:
#: So the banner was visible and the verdict was not, and the file classified as
#: "no recognised producer signature" -- i.e. a clean Magic DRC read as an
#: unreadable report. The head window is right for a HEADER; a transcript needs
#: its tail read too. Bounded, so a huge file is still not held in full twice.
_MAGIC_TAIL_BYTES = 65536


class Producer:
    """What produced a DRC report, decided from the report's own bytes."""

    __slots__ = ("kind", "deck", "top_cell", "evidence", "header_tool")

    def __init__(self, kind: Optional[str], deck: Optional[str] = None,
                 top_cell: Optional[str] = None, evidence: str = "",
                 header_tool: Optional[str] = None):
        self.kind = kind
        self.deck = deck
        self.top_cell = top_cell
        self.evidence = evidence
        self.header_tool = header_tool

    @property
    def is_signoff_deck(self) -> bool:
        """A rule deck was applied to a layout AND the report says which deck.

        A KLayout report database with no ``<generator>`` deck is refused: it
        names no rule set, so it certifies nothing in particular. MEASURED on
        every published sign-off report in this repo — 13 of 13 carry one — so
        this costs no existing run. If a legitimate configuration can emit one
        without it, this rule is too narrow and must widen; that falsifier is
        stated in the PR rather than left implicit.
        """
        if self.kind == KLAYOUT:
            return bool(self.deck)
        return self.kind in (SVRFDRC, MAGIC)

    def as_dict(self) -> Dict[str, object]:
        return {"producer": self.kind, "deck": self.deck,
                "top_cell": self.top_cell, "evidence": self.evidence,
                "header_tool": self.header_tool,
                "is_signoff_deck": self.is_signoff_deck}

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"Producer({self.kind!r}, deck={self.deck!r}, {self.evidence!r})"


_HEADER_TOOL_RE = re.compile(r"(?im)^\s*#\s*Tool:\s*(\S+)")


def classify_text(text: str) -> Producer:
    """Classify a DRC report body. CONTENT decides; the header only corroborates.

    Order is deliberate and the router is tested FIRST: a router projection
    carrying a ``# Tool: klayout`` banner must classify as the router, because
    the banner is written by the same code path that mis-attributes it. A
    report database or an SVRF tally, by contrast, cannot be faked by a header.
    """
    hm = _HEADER_TOOL_RE.search(text[:4096])
    header_tool = hm.group(1).lower() if hm else None
    body = strip_alias_header(text)
    head = body[:_HEAD_BYTES]

    top = None
    tm = _RDB_TOPCELL_RE.search(head)
    if tm:
        top = tm.group(1).strip() or None

    rm = _ROUTER_RE.search(text[:_HEAD_BYTES])
    if rm:
        return Producer(OPENROAD, None, top,
                        f"router marker {rm.group(0)!r}", header_tool)
    if _RDB_RE.search(head):
        dm = _RDB_DECK_RE.search(head)
        return Producer(KLAYOUT, dm.group(1) if dm else None, top,
                        "klayout <report-database>", header_tool)
    if looks_svrf(body):
        return Producer(SVRFDRC, None, top,
                        "SVRF-native per-rule tally", header_tool)
    _tail = body[-_MAGIC_TAIL_BYTES:] if len(body) > _MAGIC_TAIL_BYTES else ""
    if (_MAGIC_COUNT_RE.search(head) or _MAGIC_COUNT_RE.search(_tail)
            or (_MAGIC_BANNER_RE.search(head)
                and (_MAGIC_CMD_RE.search(head) or _MAGIC_CMD_RE.search(_tail)))):
        return Producer(MAGIC, None, top, "magic DRC transcript", header_tool)
    return Producer(None, None, top, "no recognised producer signature",
                    header_tool)


def classify_file(path: Path) -> Producer:
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        return Producer(None, None, None, f"unreadable ({exc.__class__.__name__})")
    return classify_text(text)


def attribution_disagrees(p: Producer) -> bool:
    """Does the ``# Tool:`` banner contradict what the bytes say?

    MEASURED on the published corpus: 8 banners, all ``klayout``, all over
    report-database content, 0 disagreements. So this path is UNTESTED by the
    corpus and is the softest joint in the change; it is disclosed rather than
    assumed correct.
    """
    if not p.header_tool or not p.kind:
        return False
    return not p.header_tool.startswith(p.kind)


# --- the layout the deck read ----------------------------------------------
# A sign-off DRC certificate over a layout that was never streamed is the
# adjacent defect, and it REPRODUCES: the router-projection fixture above sits
# in a project holding zero GDS files and still measures rc=0.
#
# The design's streamout lives at exactly two canonical paths. Restricting the
# search to them is the anti-laundering rule: a PDK cell library GDS and a hard
# macro GDS are both "a .gds in the project" and neither is the design's
# layout. The report's own <top-cell> must match the file's stem on top of
# that, so a macro that happens to sit at a canonical path cannot stand in.
_STREAMOUT_RE = re.compile(r"^phase3/stage[34]/(?:pnr|gds)/(?P<stem>[^/]+)\.gds$")
#: The same two canonical locations, matched inside an ABSOLUTE path recorded
#: in a provenance command line (tier A works on the run's own strings, which
#: are absolute). Anchoring on the directory is what keeps a PDK cell-library
#: GDS and a hard-macro GDS — both "a .gds named in the command" — out.
_STREAMOUT_ABS_RE = re.compile(
    r"(?:^|/)phase3/stage[34]/(?:pnr|gds)/(?P<stem>[^/\s\"'=]+)\.gds\b")

#: Ordered strongest-first. `none` is the absence of all evidence.
TIER_INVOCATION = "invocation"
TIER_DECLARED = "declared"
TIER_ON_DISK = "on_disk"
TIER_NONE = "none"


def _prov_entries(project: Path) -> List[dict]:
    log = project / "provenance.jsonl"
    if not log.is_file():
        return []
    out: List[dict] = []
    try:
        raw = log.read_text(errors="replace")
    except OSError:
        return []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out


def _stem_ok(stem: str, top_cell: Optional[str]) -> bool:
    """A streamout stem is the design's iff it matches the report's top cell.

    When the report declares NO top cell (an SVRF or Magic transcript does
    not), the match cannot be required — the tier is still reported, and the
    companion ``layout_topcell_match`` field says ``null`` so a reader can see
    the weaker basis rather than being told a match happened.
    """
    return True if not top_cell else stem == top_cell


def layout_evidence(project: Path,
                    top_cell: Optional[str] = None) -> Dict[str, object]:
    """Evidence that a streamed design layout existed for the deck to read.

    Returns ``{"tier", "topcell_match", "witness"}``. Nothing here asserts the
    deck DID read it — only tier ``invocation`` comes close, and it is the tier
    that is rarest in practice. The tier is DISCLOSED for exactly that reason.
    """
    entries = _prov_entries(project)

    # A — a MEASURED invocation naming a streamout GDS.
    for e in entries:
        if e.get("record") != "invocation":
            continue
        blob = " ".join([str(e.get("command") or ""), str(e.get("marker") or "")])
        blob += " " + " ".join(str(k) for k in (e.get("outputs") or {}))
        blob += " " + " ".join(str(k) for k in (e.get("outputs_pruned_at_publish")
                                                or []))
        for m in _STREAMOUT_ABS_RE.finditer(blob):
            if _stem_ok(m.group("stem"), top_cell):
                return {"tier": TIER_INVOCATION,
                        "topcell_match": None if not top_cell else True,
                        "witness": f"{e.get('tool')} invocation -> "
                                   f"{m.group('stem')}.gds"}

    # B — a provenance DECLARATION of the streamout at a canonical path.
    for e in entries:
        for rel in (e.get("outputs") or {}):
            m = _STREAMOUT_RE.match(str(rel))
            if m and _stem_ok(m.group("stem"), top_cell):
                return {"tier": TIER_DECLARED,
                        "topcell_match": None if not top_cell else True,
                        "witness": str(rel)}

    # C — the streamout on disk.
    for sub in ("phase3/stage3/pnr", "phase3/stage4/gds"):
        d = project / sub
        if not d.is_dir():
            continue
        for gds in sorted(d.glob("*.gds")):
            if _stem_ok(gds.stem, top_cell):
                return {"tier": TIER_ON_DISK,
                        "topcell_match": None if not top_cell else True,
                        "witness": f"{sub}/{gds.name}"}

    return {"tier": TIER_NONE, "topcell_match": False if top_cell else None,
            "witness": ""}
