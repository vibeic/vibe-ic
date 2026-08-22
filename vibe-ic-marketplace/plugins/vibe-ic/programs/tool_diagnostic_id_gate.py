#!/usr/bin/env python3
"""tool_diagnostic_id_gate.py — a tool diagnostic ID that was not there last
time is BLOCKING (vibe-ic#1081).

WHY THIS ONE OWES NO ORACLE
===========================
Every other "is this output acceptable" question needs someone who knows the
right answer. This one does not. It never asks whether `RSZ-0062` is a warning
we should tolerate — that would need an expert or a golden. It asks whether
`RSZ-0062` was emitted by the PREVIOUS run of the same cell. That is decidable
from two runs and nothing else, which is the §D9 property: the owner refused
oracles for D9 with 「當然我們自己在訓練、收斂的時候可以用 oracle。可是真的在跑
的時候，oracle 哪裡來？」 — this check never needs one, at training time or at
run time.

WHAT ORFS DOES, AND WHERE IT STOPS
==================================
OpenROAD-flow-scripts (studied at `f9ec54a6`) counts warnings by message ID and
publishes them as metrics::

    "cts__flow__warnings__count:ORD-0012": 1

and `flow/util/checkMetadata.py:91-95` reports an ID absent from the baseline.
But `flow/util/genRuleFile.py:70-75` assigns `level: warning`, so a brand-new
tool warning NEVER fails their build. We block instead.

THE ID SHAPES ARE MEASURED, NOT ASSUMED — AND RE-MEASURED, ON THIS COMMIT
=========================================================================
Read out of the real files this repository carries rather than taken from the
tools' documentation. The figures below are RE-DERIVED on ``4b22e36ea``
(v1.10.32) by ``test_the_corpus_figures_in_this_docstring_are_re_derived``, so
a prune or a publish moves them REDLY instead of leaving prose that was true
about some other tree on some other day. The first draft of this section quoted
figures none of which reproduced here — 1068 ``*.log``, 86,449 ``Warning 1650``,
4,504 ``Warning 1648``, thirteen prefixes, 1,183 ``DRT-0036`` — and the two
biggest were the load-bearing argument for family B. They are replaced by what
the tree says, and pinned so the next drift is an event.

Population, as measured AT COMMIT ``4b22e36ea``: 57 ``*.log`` and 2719 files of
the scanned suffixes (``.log`` ``.rpt`` ``.json``) under ``benchmark-data/ic/``.
Those two are DATED OBSERVATIONS and are written as such — every publish or
prune moves them, so pinning them would make this file's tests measure the
publication schedule, which is the defect #527 removed from this repo. ``.rpt``
carries the majority — see WHICH FILES CARRY DIAGNOSTICS below; a ``*.log``-only
scan, this program's own first draft, would have examined a small fraction.

What IS pinned is the coverage claim, because that one is not about how much data
we happen to ship:

  A. ``[WARNING RSZ-0104]`` — the OpenROAD suite. The prefixes occurring in our
     own logs are ANT CTS DPL DRT EST GPL GRT IFP ODB ORD PDN PPL PSM RCX RSZ
     STA. This is the family ORFS handles. The regex does NOT pin this list
     (``[A-Z][A-Z0-9]*``) precisely so a seventeenth tool is CAPTURED rather
     than dropped — but the list is re-derived by
     ``test_the_prefix_coverage_claim_is_re_derived``, so a new tool appearing is
     an event that updates this sentence instead of aging it out of true.

  B. ``Warning 441: <file> line N, ...`` — STANDALONE OpenSTA, which numbers its
     messages but does not bracket them. ORFS's regex does not match this shape.
     Honest size: 41 lines across 20 ``.rpt`` files (``aging_sta.rpt``,
     ``power.rpt``) at the commit above, carrying five distinct numbers — 441,
     305, 503, 168, 198. That is SMALL; the first draft of this section claimed
     86,449 ``Warning 1650`` and 4,504 ``Warning 1648``, and neither number
     appears anywhere in this repository. It is handled anyway, and the reason is
     specific rather than volumetric: ``STA-0168`` and ``STA-0198`` are
     ``Warning 168:`` and ``Warning 198:``, two of the ids the gate's own worked
     example turns on, so dropping family B would silently drop them from the
     comparison while the gate still reported a clean one.

And one family carries NO id:

  C. ``Warning: Replacing memory \\W with list of registers. See /abs/path.v:281``
     — Yosys/ABC, and the same bare shape from magic / netgen / KLayout.

C IS DISCLOSED, NEVER SYNTHESISED. Hashing the message text would manufacture
an ID that changes whenever an absolute path or a line number in the message
changes, so every rerun would invent "new" IDs and the gate would either scream
constantly or be tuned until it screamed never. Instead the census records
`unkeyed_count` per step, and the comparison REPORTS it: "N unkeyed diagnostics
were not compared". A reader must never be able to mistake "no new IDs" for
"no new warnings".

WHAT IS GATED
=============
WARNING and ERROR. INFO ids are censused (they fold into #1080 like the rest)
but do NOT gate: `DRT-0036` alone occurs **692** times as ordinary progress
chatter, and the issue's subject is a warning that was not there last time.
The choice is stated here so it is a decision on the record, not an omission.

THE PER-STEP METRIC — #1081's THIRD ITEM, NOW THAT #1080 HAS LANDED
===================================================================
#1081 asks for three things, and the first — "count tool diagnostics by message
id per step, AS A METRIC" — carried the issue's own caveat "(depends on the
per-step metrics schema)". That dependency is `programs/step_metrics.py`,
landed on `main` as `4a8c4bf6b` (#1080). Until then this program COUNTED per
step and emitted nothing, so the count existed only inside a report nobody
collects: `step_metrics collect` over a run this gate had just censused
answered `0 metric(s) from 0 step(s)`, rc 2.

`--emit-metrics <project>` folds the census into that schema — same scan, same
definition of what an id is, no second parser (#1080's rule 1: emitted by the
program that computed the number, never re-derived from a log).

WHY NOT ORFS'S EXACT SPELLING. ORFS writes
`cts__flow__warnings__count:ORD-0012`. That key is NOT conformant with the
schema #1080 landed: `step_metrics.key_defect` requires every `__`-separated
component to be lowercase alphanumeric/underscore, and `count:ORD-0012` is one
component containing a colon and capitals. Emitting it would fail
`step_metrics check`. So the id becomes its own component, lowercased with the
hyphen collapsed, and the level moves to the TAIL where `step_metrics`'s
`DIRECTIONS` table can read it::

    reports_phase3__tool__id__rsz_0104__warning_count = 12
    reports_phase3__tool__id__odb_0227__info_count    = 3
    reports_phase3__tool__unkeyed__diagnostic_count   = 4
    reports_phase3__tool__denied__diagnostic_count    = 0
    reports_phase3__tool__gated__id_count             = 2
    reports_phase3__tool__logs__scanned_count         = 370

`warning_count` and `error_count` are the two tails `DIRECTIONS` declares
`lower`, so a run-to-run `step_metrics diff` says *worse* rather than
*undeclared* when a count grows — and an id that was NOT THERE LAST TIME shows
up in the diff's `added` list, which is the same fact this gate blocks on,
reported by the metric layer instead of asserted by it. `info_count` and the
three disclosure counts are deliberately left with no declared direction: this
gate does not decide whether fewer INFO lines is an improvement.

The id -> component mapping is checked for collisions rather than assumed
injective (`metrics_for_step` raises); two distinct ids silently merging into
one metric would understate a count with no visible symptom.

DENIALS ARE DISCLOSED — THEY USED TO BE COUNTED AND THEN DROPPED
================================================================
`scan_log` returns `denied_count` (ids read out of a sentence that denies them,
vibe-ic#1241) and the comment below promises they are "counted, never silently
dropped". `census` did not aggregate it, so no report and no metric ever
carried the number: it was computed once per log and discarded. It is now
aggregated per step, surfaced in the comparison report beside
`unkeyed_not_compared`, and emitted as a metric — because "this run emitted
nothing" and "this extractor discarded what it read" must not read alike.

THE HONEST LIMIT
================
A cell with no earlier run has nothing to compare against. That exits **2**
(NO_BASELINE) with the disclosure "no previous run; nothing compared" — never
0. A first run is not a clean run, and a gate that returns success for a
comparison it could not perform is the exact defect this campaign removes.

THE LIMIT WAS NOT THE POPULATION. IT WAS THE NAME PARSE
-------------------------------------------------------
An earlier version of this section reported **5 of 5 NO_BASELINE** over five
published cells and concluded "the comparison path is UNREACHABLE from the
corpus… that is not a defect in the rule; it is the population". **The second
half of that sentence was wrong**, and it is corrected here rather than quietly
edited, because it was the reasoning that made an unusable gate look acceptable.

The resolver read the PDK out of the DIRECTORY NAME. That works for
``v1.9.96_gf180mcuD`` and cannot work for ``clean_run_v1422_20260715``, so
``_parse_cell_name`` returned None for every directory in the repository's OTHER
naming family and ``find_previous`` skipped them all — including the one pair
that is genuinely like-for-like and genuinely carries a regression::

    sha256/clean_run_v1427_20260715   vs   sha256/clean_run_v1422_20260715
        NEW = DRT-0120   in reports/phase3/drc_router.rpt
        (0 occurrences in v1422, 26 in v1427 — checked with grep, not inferred)

Measured on ``94754771`` (v1.10.33), the resolver keys on :func:`pdk_key` — the
run's OWN recorded PDK where it has one, the name where it does not — and admits
both naming families (:func:`_cell_ordinal`):

    run dir                                  pdk key     source    previous
    caravel_user_project/v1.9.43_sky130A     sky130      measured  —
    sha256/clean_run_v1422_20260715          sky130      measured  —
    sha256/clean_run_v1427_20260715          sky130      measured  clean_run_v1422_20260715
    spm/v1.10.18_sky130A                     sky130A     measured  —
    spm/v1.5.58_ihp-sg13g2                   ihp-sg13g2  measured  —
    spm/v1.9.96_gf180mcuD                    gf180mcuD   measured  —
    u_hawaii_adc/v1.9.86_sky130A             sky130A     name      —
    u_hawaii_adc/clean_run_v1422_20260715    (none)      —         —

**1 comparable pair of 8, and it BLOCKS (rc 1).** The other seven are honest
NO_BASELINEs: six have no same-key sibling at all, and one yields no key from
either source, where refusing is the only safe answer — "I could not tell" must
never resolve to "same". ``test_the_corpus_pair_resolves_and_the_gate_fires``
pins the pair and the finding, so this is backed by a committed artefact and not
only by fixtures authored beside it.

TWO SPELLINGS OF ONE PDK, AND WHY IT IS STILL SAFE. The recorded values are not
normalised: caravel and sha256 record ``sky130`` while spm records ``sky130A``.
Comparison is exact, so a cell pair that disagreed in spelling would resolve to
NO_BASELINE rather than compare. That is the safe direction — a missed
comparison, never a wrong one — and it is stated because the failure it produces
looks like "no predecessor" and could otherwise be mistaken for absence of data.

ROUTED RECEIPT OWNER
====================
`tools/ci/routed_def_corpus.py` invokes this program for every published cell
that carries a routed DEF and records the independent result in the trusted
landing manifest.  The routed-corpus parent, rather than a filename trigger in
one flow step, owns the population because the comparison spans whole-cell tool
output and its predecessor.

Exit codes: 0 = compared and clean, 1 = BLOCKING, 2 = could not compare (no
previous run, or this run yields zero gated ids so the comparison would be
vacuous — see VACUITY IS NOT CLEANLINESS in `compare`).
"""
from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from functools import lru_cache
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

import _prose_polarity as _polarity   # vibe-ic#1241
import _routed_checker_progress as _routed_progress
import _semantic_child_progress as _semantic_progress
import step_metrics as _metrics       # vibe-ic#1080 — the per-step schema

SCHEMA = "tool_diagnostic_id_census/v1"
PROGRESS_SCOPE = "routed-def:tool-diagnostic-id"
_ACTIVE_INPUT_PLAN: Optional[_routed_progress.FiniteInputPlan] = None
_ACTIVE_OWNER_PATHS: Optional[Tuple[Path, ...]] = None
_ACTIVE_CELL_ROOT: Optional[Path] = None


def _read_input_text(path: Path, *, encoding: str | None = None,
                     errors: str = "strict") -> str:
    if _ACTIVE_INPUT_PLAN is not None:
        return _ACTIVE_INPUT_PLAN.text_for(
            path, encoding=encoding, errors=errors)
    return Path(path).read_text(encoding=encoding, errors=errors)

#: The `<domain>` this program owns inside #1080's `<step>__<domain>__<name>`.
METRIC_DOMAIN = "tool"

#: Family A — the OpenROAD suite's bracketed form. The level word is captured
#: so INFO can be censused without gating. Prefix is left open (`[A-Z][A-Z0-9]*`)
#: rather than pinned to the thirteen we happen to have seen: a fourteenth tool
#: appearing must be CAPTURED, not silently dropped, or the gate's own coverage
#: shrinks whenever the flow grows.
_RE_BRACKETED = re.compile(
    r"\[(?P<level>WARNING|ERROR|INFO)\s+(?P<id>[A-Z][A-Z0-9]{1,7}-\d{3,5})\]")

#: Family B — standalone OpenSTA. Anchored at line start so the digits are the
#: message number and not a coincidence inside prose.
_RE_STA_NUMBERED = re.compile(
    r"^(?P<level>Warning|Error)\s+(?P<num>\d{2,5}):", re.MULTILINE)

#: Family C — a diagnostic with no id at all. Counted, never keyed.
_RE_UNKEYED = re.compile(
    r"^(?P<level>Warning|WARNING|Error|ERROR)\s*:", re.MULTILINE)

#: Only these gate. INFO is censused and ignored by the comparison.
GATED_LEVELS = ("WARNING", "ERROR")

#: `v1.9.94_sky130A` -> ((1,9,94), 'sky130A'). Parsed, never string-sorted:
#: lexicographically `v1.9.10` precedes `v1.9.9`, which would silently compare
#: a run against a LATER one and call a removed warning a new one.
_RE_CELL = re.compile(r"^v(?P<ver>\d+(?:\.\d+)*)_(?P<pdk>.+)$")


def _parse_cell_name(name: str) -> Optional[Tuple[Tuple[int, ...], str]]:
    m = _RE_CELL.match(name)
    if not m:
        return None
    return tuple(int(p) for p in m.group("ver").split(".")), m.group("pdk")


def _norm_sta(num: str) -> str:
    """`441` -> `STA-0441`, so family B lands in the same namespace as family A.

    Zero-padded to four so `STA-0441` and `STA-1650` sort and read like every
    other id. Prefixed `STA-` because that is the tool; it does NOT collide with
    OpenROAD's in-process `STA-xxxx` ids in practice, and if it ever did the
    collision would be two ids from the same tool meaning the same thing.
    """
    return f"STA-{int(num):04d}"


#: vibe-ic#1241 — a diagnostic id read out of a sentence that DENIES it.
#:
#: This extractor's whole job is "which ids did this run emit", and a regex
#: cannot tell an emission from a statement about the absence of one. Both of
#: these appear in real tool output:
#:
#:     [WARN ORDER-1234] pin access blocked        <- emitted
#:     no [WARN ORDER-1234] warnings were emitted  <- explicitly NOT emitted
#:
#: Counting the second is not a near miss: this gate BLOCKS on an id that was
#: not in the predecessor run, so a denial read as an emission invents a
#: regression and stops a landing. That is the direction that costs most.
#:
#: `extra_breaks=("\n",)` because this input is NOT prose — consecutive lines of
#: a tool log are unrelated RECORDS, and `_prose_polarity.sentence_scope`
#: documents that a caller with record-structured input declares that itself
#: rather than every prose reader paying for it. Without it a denial on one line
#: would retract an id emitted on the next.
#:
#: DENIALS ARE COUNTED, NEVER SILENTLY DROPPED. A reader has to be able to tell
#: "this run emitted nothing" from "this extractor discarded what it read" —
#: which is the same requirement this repository puts on every other gate.
def scan_log(text: str) -> Dict[str, Any]:
    """Extract every diagnostic id from ONE log's text.

    An id whose sentence denies it is NOT an emission and is excluded, with the
    count reported as `denied_count`.
    """
    by_level: Dict[str, Dict[str, int]] = {}
    denied = 0

    def _emitted(start: int, end: int) -> bool:
        """False only when the sentence denies THE OCCURRENCE of this id.

        THE SPAN IS WHAT PRECEDES THE MATCH, and that is the whole correctness
        of this check. A diagnostic line IS the emission, and its message text
        is ordinary English that very often negates something about the design:

            [WARNING RSZ-0104] no clock found       <- EMITTED. "no" is about
                                                       the clock, not the id.
            no [WARNING RSZ-0104] were emitted      <- NOT emitted.

        Scanning the whole sentence conflates the two — measured, not reasoned:
        doing so dropped every id in this file's own fixtures, the run then
        yielded zero gated ids, and the gate correctly answered rc 2 VACUOUS on
        eight tests. A denial governs what FOLLOWS it, so only the text from the
        sentence start up to the match can retract it.
        """
        lo, _hi = _polarity.sentence_scope(text, start, end,
                                           extra_breaks=("\n",))
        return _polarity.is_denied(text[lo:start]) is None

    for m in _RE_BRACKETED.finditer(text):
        if not _emitted(m.start(), m.end()):
            denied += 1
            continue
        by_level.setdefault(m.group("level"), {})
        d = by_level[m.group("level")]
        d[m.group("id")] = d.get(m.group("id"), 0) + 1
    for m in _RE_STA_NUMBERED.finditer(text):
        if not _emitted(m.start(), m.end()):
            denied += 1
            continue
        lvl = m.group("level").upper()
        by_level.setdefault(lvl, {})
        d = by_level[lvl]
        key = _norm_sta(m.group("num"))
        d[key] = d.get(key, 0) + 1
    unkeyed = len(_RE_UNKEYED.findall(text))
    return {"ids": by_level, "unkeyed_count": unkeyed,
            "denied_count": denied}


#: WHICH FILES CARRY DIAGNOSTICS — measured over the published cells, not
#: assumed from the extension's name. Counting ID-bearing files under
#: `benchmark-data/ic/*/v*_*/`:
#:
#:     bracketed ids : 16 .rpt, 10 .log, 5 .json
#:     OpenSTA `Warning NNNN:` : 6 .rpt, 0 .log
#:
#: `.rpt` carries MORE than `.log` and every OpenSTA-numbered file is a `.rpt`,
#: so a scan of `*.log` alone — the obvious first guess, and this program's own
#: first draft — would have missed the majority of the population while
#: reporting a confident count. The `.json` hits are the runner storing a
#: tool's console output inside a JSON field (e.g. `dynamic_ir.json` carries
#: `[WARNING ODB-0220]` verbatim), which is real tool output and not a report
#: about tool output.
_SCANNED_SUFFIXES = (".log", ".rpt", ".json")


def _input_plan(
        cell: Path,
) -> Tuple[_routed_progress.FiniteInputPlan, Tuple[Path, ...], Path]:
    cell = Path(cell)
    design = cell.parent
    index = _routed_progress.IndexSnapshot(design)

    # find_previous() consults every sibling in the same naming family before
    # it decides which lower ordinal owns the comparison.  Git does not track
    # directories, so bind those directory names to at least one indexed path;
    # an untracked or sparse sibling must not silently change the predecessor.
    mine = _cell_ordinal(cell.name)

    def relevant_owner(name: str) -> bool:
        if name == cell.name:
            return True
        theirs = _cell_ordinal(name)
        return bool(mine is not None and theirs is not None
                    and theirs[0] == mine[0])

    indexed_owners = {
        PurePosixPath(relative).parts[0]
        for relative in index.relative_paths
        if PurePosixPath(relative).parts
        and relevant_owner(PurePosixPath(relative).parts[0])
    }
    disk_owners = set()
    for sibling in design.iterdir():
        if not relevant_owner(sibling.name):
            continue
        try:
            sibling_stat = sibling.lstat()
        except OSError as exc:
            raise _semantic_progress.ProgressProtocolError(
                f"tool diagnostic predecessor cannot be inspected: {exc}") from exc
        if stat.S_ISLNK(sibling_stat.st_mode):
            raise _semantic_progress.ProgressProtocolError(
                f"tool diagnostic predecessor traverses a symlink: {sibling}")
        if not stat.S_ISDIR(sibling_stat.st_mode):
            continue
        disk_owners.add(sibling.name)
    if indexed_owners != disk_owners:
        raise _semantic_progress.ProgressProtocolError(
            "tool diagnostic predecessor directory population differs "
            f"between Git and disk; missing={sorted(indexed_owners-disk_owners)}, "
            f"untracked={sorted(disk_owners-indexed_owners)}")

    scanned = index.select(
        lambda relative: Path(relative).suffix in _SCANNED_SUFFIXES,
        _routed_progress.disk_files(
            design, lambda path: path.suffix in _SCANNED_SUFFIXES),
        population="tool diagnostic design log population")

    acceptance = Path(__file__).with_name(
        "tool_diagnostic_id_acceptance.json")
    acceptance_index = _routed_progress.IndexSnapshot(acceptance.parent)
    acceptance_inputs = acceptance_index.select(
        lambda relative: relative == acceptance.name,
        [acceptance] if acceptance.exists() else [],
        population="tool diagnostic acceptance input")
    reads = [
        *_routed_progress.planned_reads("design-scan", scanned),
        *_routed_progress.planned_reads("acceptance", acceptance_inputs),
    ]
    plan = _routed_progress.FiniteInputPlan(
        [index.population_unit("tool-diagnostic:design-index"),
         acceptance_index.population_unit(
             "tool-diagnostic:acceptance-index")], reads)
    owners = tuple(index.root / name for name in sorted(disk_owners))
    return plan, owners, index.root / cell.name


def semantic_progress_units(cell: Path) -> List[str]:
    """Trusted parent's exact finite manifest for the default cell argv."""
    return _input_plan(Path(cell))[0].units


def _is_our_own_artifact(text: str) -> bool:
    """Skip this program's own output.

    THE FEEDBACK LOOP THIS CLOSES. The report below lists every new id it
    found. Written into the cell it describes — which is where run artefacts
    go — the NEXT run would scan it, read those ids as tool output, and the
    gate would start reporting ids whose only source is its own previous
    complaint. A check whose output becomes its input cannot be trusted about
    either. Keyed on the schema string rather than on a filename so renaming
    the report does not silently reopen the loop.
    """
    return f'"schema": "{SCHEMA}"' in text or f'"schema":"{SCHEMA}"' in text


def _step_of(log_path: Path, cell_root: Path) -> str:
    """The step a log belongs to.

    Derived from the log's own location under the cell, because that is what
    the tree actually records. `phase3/stage3/extracted/si_timing.log` ->
    `phase3/stage3/extracted`. Folding into #1080's per-step schema is then a
    rename of this key, not a re-derivation.
    """
    rel = log_path.relative_to(cell_root)
    parent = rel.parent.as_posix()
    return parent if parent != "." else "<cell-root>"


def census(cell_root: Path) -> Dict[str, Any]:
    """Walk a published cell and census every diagnostic id, per step.

    THE SHAPE #1080 CAN ABSORB. Each entry here maps 1:1 onto a per-step metric
    name in the ORFS style this project already reads:

        steps["<step>"]["ids"]["WARNING"]["RSZ-0104"] = 12
              -> "<step>__tool__warnings__count:RSZ-0104" = 12

    so #1080 can fold this file in by flattening two levels and renaming, with
    no second scan of the logs and no second definition of what an id is.
    """
    steps: Dict[str, Any] = {}
    logs_scanned = 0
    skipped_own = 0
    if _ACTIVE_INPUT_PLAN is not None:
        candidates = sorted(
            p for p in _ACTIVE_INPUT_PLAN.paths("design-scan")
            if p.is_relative_to(cell_root)
            and p.suffix in _SCANNED_SUFFIXES)
    else:
        candidates = sorted(p for p in cell_root.rglob("*")
                            if p.suffix in _SCANNED_SUFFIXES)
    for log in candidates:
        if _ACTIVE_INPUT_PLAN is None and not log.is_file():
            continue
        try:
            text = _read_input_text(log, errors="replace")
        except OSError:
            continue
        if _is_our_own_artifact(text):
            skipped_own += 1
            continue
        logs_scanned += 1
        found = scan_log(text)
        step = _step_of(log, cell_root)
        slot = steps.setdefault(
            step, {"logs": [], "ids": {}, "unkeyed_count": 0,
                   "denied_count": 0})
        slot["logs"].append(log.relative_to(cell_root).as_posix())
        slot["unkeyed_count"] += found["unkeyed_count"]
        # vibe-ic#1081 — `scan_log` computed this and `census` threw it away,
        # so the promise two comments up ("counted, never silently dropped")
        # was true of the extractor and false of everything downstream.
        slot["denied_count"] += found["denied_count"]
        for lvl, ids in found["ids"].items():
            dst = slot["ids"].setdefault(lvl, {})
            for k, v in ids.items():
                dst[k] = dst.get(k, 0) + v
    return {"schema": SCHEMA, "cell": cell_root.name,
            "logs_scanned": logs_scanned,
            "own_artifacts_skipped": skipped_own, "steps": steps}


def gated_ids(cen: Dict[str, Any]) -> Dict[str, List[str]]:
    """{id: [steps it appeared in]} over the GATED levels only."""
    out: Dict[str, List[str]] = {}
    for step, slot in sorted(cen.get("steps", {}).items()):
        for lvl in GATED_LEVELS:
            for i in sorted(slot.get("ids", {}).get(lvl, {})):
                out.setdefault(i, [])
                if step not in out[i]:
                    out[i].append(step)
    return out


def total_unkeyed(cen: Dict[str, Any]) -> int:
    return sum(s.get("unkeyed_count", 0) for s in cen.get("steps", {}).values())


def total_denied(cen: Dict[str, Any]) -> int:
    return sum(s.get("denied_count", 0) for s in cen.get("steps", {}).values())


# ---------------------------------------------------------------------------
# the per-step METRIC — #1081 item 1, through #1080's schema
# ---------------------------------------------------------------------------
#: `RSZ-0104` -> `rsz_0104`. One component of the metric key, not a suffix
#: glued onto `count` with a colon: see WHY NOT ORFS'S EXACT SPELLING above.
_RE_NOT_KEY_SAFE = re.compile(r"[^a-z0-9]+")

#: level -> the metric TAIL. `warning_count`/`error_count` are exactly the two
#: tails `step_metrics.DIRECTIONS` declares `lower`, so the differ can say
#: better/worse instead of `undeclared`. INFO gets a tail with no declared
#: direction ON PURPOSE — this program does not rule on whether fewer progress
#: lines is an improvement.
_LEVEL_TAIL = {"WARNING": "warning_count", "ERROR": "error_count",
               "INFO": "info_count"}


def _metric_id(diagnostic_id: str) -> str:
    return _RE_NOT_KEY_SAFE.sub("_", diagnostic_id.lower()).strip("_")


def metrics_for_step(step: str, slot: Dict[str, Any]) -> Dict[str, Any]:
    """The #1080-conformant metrics for ONE step of a census.

    Raises on an id-component collision. Two distinct ids folding onto one key
    would silently ADD their counts, and the resulting metric would be wrong in
    the direction that hides a diagnostic — no exception, no log line, just a
    number that disagrees with the census beside it.
    """
    step_n = _metrics.normalize_step(step)
    out: Dict[str, Any] = {}
    origin: Dict[str, str] = {}
    for level, tail in _LEVEL_TAIL.items():
        for did, count in sorted(slot.get("ids", {}).get(level, {}).items()):
            key = _metrics.key_for(step_n, METRIC_DOMAIN, tail,
                                   "id", _metric_id(did))
            if key in origin and origin[key] != did:
                raise ValueError(
                    f"tool_diagnostic_id_gate: ids {origin[key]!r} and {did!r} "
                    f"both normalise to metric key {key!r}; refusing to merge "
                    f"two diagnostics into one count")
            origin[key] = did
            out[key] = count
    gated = sum(len(slot.get("ids", {}).get(lvl, {})) for lvl in GATED_LEVELS)
    out[_metrics.key_for(step_n, METRIC_DOMAIN, "id_count", "gated")] = gated
    out[_metrics.key_for(step_n, METRIC_DOMAIN, "scanned_count", "logs")] = \
        len(slot.get("logs", []))
    # The two disclosures, carried as metrics rather than only as report prose,
    # so a reader of the METRICS cannot mistake "no new id" for "no new
    # warning" either. See the family-C note and the denial note above.
    out[_metrics.key_for(step_n, METRIC_DOMAIN, "diagnostic_count",
                         "unkeyed")] = int(slot.get("unkeyed_count", 0))
    out[_metrics.key_for(step_n, METRIC_DOMAIN, "diagnostic_count",
                         "denied")] = int(slot.get("denied_count", 0))
    return out


def metrics_for_census(cen: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{normalised step: {metric key: value}} for a whole census."""
    return {_metrics.normalize_step(step): metrics_for_step(step, slot)
            for step, slot in sorted(cen.get("steps", {}).items())}


def emit_metrics(cen: Dict[str, Any], project: Path) -> List[Path]:
    """Write this census into `<project>/reports/metrics/<step>.json`.

    THIS PROGRAM'S OWN KEYS ARE REPLACED, NOT MERGED INTO. `step_metrics.emit`
    merges by design, which is right when several programs contribute to one
    step — but wrong for a re-emit of the SAME census over the same project: an
    id that disappeared between two runs would keep its old count from the
    earlier emit and the metric would report a diagnostic nothing emitted. So
    every `<step>__tool__` key is dropped first, and only ours; another
    program's contribution to the same step file is untouched.
    """
    written: List[Path] = []
    for step_n, metrics in metrics_for_census(cen).items():
        f = Path(project) / _metrics.METRICS_REL / f"{step_n}.json"
        if f.is_file():
            try:
                prior = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                prior = {}
            if isinstance(prior, dict):
                mine = f"{step_n}__{METRIC_DOMAIN}__"
                kept = {k: v for k, v in prior.items()
                        if not k.startswith(mine)}
                if len(kept) != len(prior):
                    f.write_text(
                        json.dumps(kept, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
        written.append(_metrics.emit(Path(project), step_n, metrics,
                                     domain=METRIC_DOMAIN))
    return written


# ---------------------------------------------------------------------------
# the acceptance list, and the checking OF the acceptance list
# ---------------------------------------------------------------------------
_REQUIRED_FIELDS = ("id", "reason", "accepted_on", "expires_on",
                    "adjudicated_by")


def load_acceptance(path: Path) -> List[Dict[str, Any]]:
    if (_ACTIVE_INPUT_PLAN is not None
            and not _ACTIVE_INPUT_PLAN.contains(path)):
        return []
    if _ACTIVE_INPUT_PLAN is None and not path.exists():
        return []
    doc = json.loads(_read_input_text(path))
    return list(doc.get("accepted") or [])


def audit_acceptance(entries: List[Dict[str, Any]],
                     present_ids: Dict[str, List[str]],
                     today: date) -> List[str]:
    """The list is itself a check subject. Returns BLOCKING problems.

    An allowlist nobody re-examines becomes a check that lies — it silently
    grows until it accepts everything, and the gate above it reads green for a
    population it no longer inspects. So three ways an entry dies LOUDLY:

      1. malformed — a field missing means nobody recorded who decided, when,
         or why, and an unattributable exemption is not an adjudication;
      2. EXPIRED — past `expires_on`. Not auto-renewed and not silently
         dropped: expiry is a BLOCK, which forces a human to look again or to
         write a new date with a new reason;
      3. STALE — the id it excuses is not emitted anywhere in the current run.
         An exemption outliving the thing it exempts is the shape
         `retention.json` already blocks on for cells, applied to ids.
    """
    problems: List[str] = []
    seen: set = set()
    for idx, e in enumerate(entries):
        where = f"acceptance[{idx}]"
        if not isinstance(e, dict):
            problems.append(f"{where}: not an object")
            continue
        missing = [f for f in _REQUIRED_FIELDS if not e.get(f)]
        if missing:
            problems.append(
                f"{where} (id={e.get('id')!r}): missing required field(s) "
                f"{missing} — an exemption nobody signed or dated is not an "
                f"adjudication")
            continue
        eid = str(e["id"])
        if eid in seen:
            problems.append(f"{where}: duplicate entry for id {eid}")
        seen.add(eid)
        try:
            exp = date.fromisoformat(str(e["expires_on"]))
        except ValueError:
            problems.append(
                f"{where} (id={eid}): expires_on={e['expires_on']!r} is not an "
                f"ISO date")
            continue
        if exp < today:
            problems.append(
                f"{where} (id={eid}): EXPIRED on {exp.isoformat()} "
                f"(reason was: {e['reason']!r}) — re-adjudicate it or remove "
                f"it; an expired exemption is not renewed by being ignored")
        elif eid not in present_ids:
            problems.append(
                f"{where} (id={eid}): STALE — this run emits it nowhere, so "
                f"the exemption outlived the diagnostic it excused; remove it")
    return problems


# ---------------------------------------------------------------------------
# previous run of the SAME cell
# ---------------------------------------------------------------------------
#: `clean_run_v1422_20260715` -> ordinal (1422, 20260715). THE REPOSITORY USES
#: TWO cell-naming conventions and this gate recognised one. `_parse_cell_name`
#: returns None for every `clean_run_*` directory, so `find_previous` skipped
#: them and `sha256/clean_run_v1427_20260715` reported NO_BASELINE with its own
#: predecessor sitting beside it — the pair that carries the corpus' only real
#: diagnostic regression (`DRT-0120`: absent from v1422's
#: `reports/phase3/drc_router.rpt`, 26 occurrences in v1427's).
_RE_RUN_SEQ = re.compile(r"^clean_run_v(?P<seq>\d+)_(?P<date>\d{8})$")

#: The structured field every published cell records its PDK in. READ, never
#: parsed out of the directory name.
#:
#: WHY MEASURED AND NOT PARSED. The PDK guard is the load-bearing half of this
#: resolver: comparing two runs that differ by PDK produces "new" ids that are
#: only a change of process, and on this corpus that mistake yields 18 false
#: positives across three consecutive `spm` pairs. The old resolver got the
#: guard right and paid for it by reading the PDK out of the NAME, which works
#: for `v1.9.96_gf180mcuD` and is impossible for `clean_run_v1422_20260715` —
#: so the whole naming family was dropped rather than compared. The run records
#: its own PDK; reading it keeps the guard exact AND admits both families.
_RE_PDK_FIELD = re.compile(r'"pdk"\s*:\s*"(?P<pdk>[^"]+)"')


def _cell_ordinal(name: str) -> Optional[Tuple[str, Tuple[int, ...]]]:
    """``(family, ordinal)`` for a run directory name, or None.

    The FAMILY is returned with the ordinal and compared, because an ordinal is
    only meaningful inside its own convention: `v1.9.96_gf180mcuD` and
    `clean_run_v1422_20260715` both yield integers and those integers mean
    different things. Ordering across families would be an invented fact, so it
    is refused rather than guessed.
    """
    m = _RE_CELL.match(name)
    if m:
        return "version", tuple(int(p) for p in m.group("ver").split("."))
    m = _RE_RUN_SEQ.match(name)
    if m:
        return "run_seq", (int(m.group("seq")), int(m.group("date")))
    return None


@lru_cache(maxsize=256)
def measured_pdk(cell_dir: Path) -> Optional[str]:
    """The PDK this run RECORDS, read from its own reports. None if unstated.

    Structured field only. A bare token scan would be wrong and was measured to
    be: grepping `sky130|gf180` over `sha256/clean_run_v1422_20260715` returns
    BOTH, because tcl and rpt files mention other processes in passing. The
    `"pdk": "..."` field is the run's own statement about itself.
    """
    seen: Dict[str, int] = {}
    paths = (sorted(
        p for p in _ACTIVE_INPUT_PLAN.paths("design-scan")
        if p.is_relative_to(cell_dir) and p.suffix == ".json")
        if _ACTIVE_INPUT_PLAN is not None else
        sorted(cell_dir.rglob("*.json")))
    for p in paths:
        if _ACTIVE_INPUT_PLAN is None and not p.is_file():
            continue
        try:
            text = _read_input_text(p, errors="replace")
        except OSError:
            continue
        for m in _RE_PDK_FIELD.finditer(text):
            # ASK WHETHER THE SENTENCE DENIES IT. The scan is over raw text, so
            # `"pdk": "sky130A"` quoted inside a note saying it was NOT used
            # reads identically to a real declaration, and the modal rule below
            # means enough denials outvote the truth.
            #
            # `ignore_bracketed=False` is load-bearing and was measured: the
            # default blanks bracketed spans, and a JSON document is entirely
            # inside `{...}`, so the prose default blanks the whole file and
            # `is_denied` can never fire. With the default this consult would be
            # a no-op that looks like a check.
            #
            # `extra_breaks=("\n",)` because these are machine-generated
            # records, not prose: `_prose_polarity` leaves bare newlines out of
            # SENTENCE_BREAKS on purpose and has the caller declare them, so a
            # denial on one record cannot retract a value on another.
            lo, hi = _polarity.sentence_scope(
                text, m.start(), m.end(), extra_breaks=("\n",))
            if _polarity.is_denied(text[lo:hi], ignore_bracketed=False):
                continue
            v = m.group("pdk")
            seen[v] = seen.get(v, 0) + 1
    if not seen:
        return None
    # The most frequently recorded value. A cell that records two PDKs is a
    # different defect and not this gate's to adjudicate; taking the modal value
    # keeps the comparison from turning on which file happened to sort first.
    return max(sorted(seen), key=lambda k: seen[k])


def pdk_key(cell_dir: Path) -> Optional[str]:
    """The PDK to compare on: MEASURED if the run records one, else the NAME.

    A FALLBACK, not a replacement, and the difference is a behaviour rule rather
    than a convenience. Requiring the measured value outright was written first
    and was wrong: a run that records no `"pdk"` field would silently lose its
    predecessor, so a gate that used to compare would quietly stop — the same
    "degrade to nothing without saying so" this whole file argues against. It
    was caught by the existing fixtures, which record no PDK and are named
    `v1.0.0_pdkX`, all of which went NO_BASELINE.

    So: prefer the run's own record; fall back to the name where the name
    carries it. Both sides must yield a key and the keys must be EQUAL — a cell
    that yields nothing is refused rather than matched, because "I could not
    tell" must not resolve to "same". Mixing sources is safe in the only
    direction that matters: if one side measured `sky130` and the other can only
    offer the name's `sky130A`, they differ and the pair is refused. A missed
    comparison, never a wrong one.
    """
    m = measured_pdk(cell_dir)
    if m:
        return m
    named = _RE_CELL.match(cell_dir.name)
    return named.group("pdk") if named else None


def find_previous(cell_dir: Path) -> Optional[Path]:
    """The sibling run of the same design and the same PDK, at the
    highest ordinal strictly below this one. `None` when there is no earlier run.

    Three rules, and the second is the one that was silently excluding runs:

    1. same design — siblings of the same parent directory only;
    2. same PDK via :func:`pdk_key` — the run's own record where it has one,
       the name where it does not. Both sides must yield a key and the keys must
       match; a side that yields neither is refused, because "I could not tell"
       must not resolve to "same";
    3. same naming FAMILY and a lower ordinal (:func:`_cell_ordinal`), so the
       comparison is never ordered across two conventions whose numbers mean
       different things.

    A caller who knows better can always override all three with `--previous`.
    """
    mine = _cell_ordinal(cell_dir.name)
    if mine is None:
        return None
    family, ordinal = mine
    my_pdk = pdk_key(cell_dir)
    if my_pdk is None:
        return None
    best: Optional[Tuple[Tuple[int, ...], Path]] = None
    siblings = (_ACTIVE_OWNER_PATHS if _ACTIVE_OWNER_PATHS is not None else
                tuple(sorted(cell_dir.parent.iterdir())))
    for sib in siblings:
        if ((_ACTIVE_OWNER_PATHS is None and not sib.is_dir())
                or sib.name == cell_dir.name):
            continue
        theirs = _cell_ordinal(sib.name)
        if theirs is None or theirs[0] != family:
            continue
        if pdk_key(sib) != my_pdk:
            continue
        if theirs[1] < ordinal and (best is None or theirs[1] > best[0]):
            best = (theirs[1], sib)
    return best[1] if best else None


def compare(cell_dir: Path, prev_dir: Path, acceptance: Path,
            today: date) -> Tuple[int, Dict[str, Any]]:
    cur = census(cell_dir)
    old = census(prev_dir)
    cur_ids, old_ids = gated_ids(cur), gated_ids(old)
    new_ids = {i: s for i, s in cur_ids.items() if i not in old_ids}

    entries = load_acceptance(acceptance)
    problems = audit_acceptance(entries, cur_ids, today)
    accepted = {str(e["id"]) for e in entries
                if isinstance(e, dict) and e.get("id")
                and not [p for p in problems if f"id={e['id']!r}" in p]}
    blocking_new = {i: s for i, s in new_ids.items() if i not in accepted}

    report = {
        "schema": SCHEMA,
        "cell": cell_dir.name,
        "previous_cell": prev_dir.name,
        "compared_ids_current": len(cur_ids),
        "compared_ids_previous": len(old_ids),
        "new_ids": {i: sorted(s) for i, s in sorted(new_ids.items())},
        "new_ids_accepted": sorted(set(new_ids) & accepted),
        "new_ids_blocking": {i: sorted(s)
                             for i, s in sorted(blocking_new.items())},
        "acceptance_problems": problems,
        # NOT a footnote. Without this a reader takes "0 new ids" for "0 new
        # warnings", and families C exists precisely where ids do not.
        "unkeyed_not_compared": {
            "current": total_unkeyed(cur), "previous": total_unkeyed(old),
            "note": ("diagnostics with no message id (Yosys/ABC/magic/netgen/"
                     "KLayout emit these); counted, NOT compared — a change "
                     "here is invisible to this gate"),
        },
        # vibe-ic#1081 — the third thing a reader must be able to tell apart:
        # ids this extractor READ and then EXCLUDED because the sentence around
        # them denied the emission (#1241). Counted since #1241, reported since
        # now; before this it was computed per log and dropped by `census`.
        "denied_not_counted": {
            "current": total_denied(cur), "previous": total_denied(old),
            "note": ("id-shaped tokens whose sentence denies the emission "
                     "(e.g. 'no [WARNING X-0001] were emitted'); excluded from "
                     "the comparison ON PURPOSE, disclosed so 'emitted "
                     "nothing' cannot be confused with 'discarded what it "
                     "read'"),
        },
        "census_current": cur,
    }
    # VACUITY IS NOT CLEANLINESS — caught by this program's own two-arm demo,
    # which reported `[PASS] ... no new diagnostic id (0 compared)` over a cell
    # pair that yields zero gated ids. "No new warning" computed over no
    # warnings at all is `len(new) == 0` being vacuously true, and it is far
    # more likely to mean the scan found no diagnostics than that the tools
    # emitted none. It reads identically to a real clean comparison, which is
    # the exact defect this gate exists to remove, in the gate itself.
    #
    # So it takes the same tri-state as the missing baseline: 2, not 0. The
    # PREVIOUS run being empty is fine on its own — every id is then new and
    # the gate says so — but an empty CURRENT run means nothing was examined.
    if not cur_ids:
        report["verdict"] = "VACUOUS"
        report["disclosure"] = (
            "this run yields zero gated diagnostic ids, so 'no new id' is "
            "vacuously true and nothing was compared; a scan that finds no "
            "diagnostics is not a run that emitted none")
        return 2, report

    rc = 1 if (blocking_new or problems) else 0
    return rc, report


def _emit(report: Dict[str, Any], out: Optional[str]) -> None:
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def _emit_metrics_cli(cen: Dict[str, Any], project: Optional[str]) -> int:
    """`--emit-metrics`, and a failure to emit is NOT a quiet no-op.

    Returns 0 when nothing was asked for or the emit succeeded, 1 when it was
    asked for and did not happen. A run that was told to publish a metric,
    could not, and still exited 0 would leave the next comparison reading a
    file that silently does not exist.
    """
    if not project:
        return 0
    try:
        paths = emit_metrics(cen, Path(project))
    except (ValueError, OSError) as exc:
        print(f"[FAIL] tool_diagnostic_id_gate: could not emit per-step "
              f"metrics into {project}: {exc}")
        return 1
    total = sum(len(m) for m in metrics_for_census(cen).values())
    print(f"[INFO] emitted {total} per-step metric(s) across {len(paths)} "
          f"step file(s) under {Path(project) / _metrics.METRICS_REL}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cell_dir", help="published cell, e.g. "
                                     "benchmark-data/ic/spm/v1.9.96_gf180mcuD")
    ap.add_argument("--acceptance", default=str(
        Path(__file__).with_name("tool_diagnostic_id_acceptance.json")))
    ap.add_argument("--json", help="write the report here")
    ap.add_argument("--census-only", action="store_true",
                    help="emit this cell's census and exit 0; no comparison")
    ap.add_argument("--previous", help="compare against this cell instead of "
                                       "the auto-discovered previous run")
    ap.add_argument("--emit-metrics", metavar="PROJECT",
                    help="fold this run's census into PROJECT's per-step "
                         "metrics (#1080 schema, reports/metrics/<step>.json)")
    ap.add_argument("--today", help="ISO date for expiry evaluation (testing)")
    args = ap.parse_args(argv)

    global _ACTIVE_INPUT_PLAN, _ACTIVE_OWNER_PATHS, _ACTIVE_CELL_ROOT
    with _semantic_progress.child_progress(PROGRESS_SCOPE) as progress:
        try:
            if progress.enabled:
                cell = Path(args.cell_dir)
                expected_acceptance = Path(__file__).with_name(
                    "tool_diagnostic_id_acceptance.json")
                try:
                    supplied_acceptance = Path(args.acceptance).resolve(strict=True)
                    expected_acceptance = expected_acceptance.resolve(strict=True)
                except OSError as exc:
                    raise _semantic_progress.ProgressProtocolError(
                        f"tool diagnostic acceptance input is unavailable: {exc}") from exc
                if (not cell.is_dir() or args.json is not None
                        or args.census_only
                        or args.previous is not None
                        or args.emit_metrics is not None
                        or args.today is not None
                        or supplied_acceptance != expected_acceptance):
                    raise _semantic_progress.ProgressProtocolError(
                        "routed parent progress covers the default cell "
                        "comparison only")
                (_ACTIVE_INPUT_PLAN, _ACTIVE_OWNER_PATHS,
                 _ACTIVE_CELL_ROOT) = _input_plan(cell)
                _ACTIVE_INPUT_PLAN.materialize(progress)
            rc = _main_parsed(args)
            if _ACTIVE_INPUT_PLAN is not None:
                fresh_plan, _, _ = _input_plan(Path(args.cell_dir))
                _ACTIVE_INPUT_PLAN.checkpoint_decision(fresh_plan=fresh_plan)
            return rc
        finally:
            _ACTIVE_INPUT_PLAN = None
            _ACTIVE_OWNER_PATHS = None
            _ACTIVE_CELL_ROOT = None


def _main_parsed(args) -> int:

    cell = (_ACTIVE_CELL_ROOT if _ACTIVE_CELL_ROOT is not None
            else Path(args.cell_dir))
    if _ACTIVE_INPUT_PLAN is None and not cell.is_dir():
        print(f"[FAIL] tool_diagnostic_id_gate: no such cell: {cell}")
        return 2

    if args.census_only:
        cen = census(cell)
        _emit(cen, args.json)
        print(f"[INFO] tool_diagnostic_id_gate: censused {cen['logs_scanned']} "
              f"log(s), {len(gated_ids(cen))} gated id(s) in {cell.name}")
        return _emit_metrics_cli(cen, args.emit_metrics)

    prev = Path(args.previous) if args.previous else find_previous(cell)
    if (prev is None
            or (_ACTIVE_INPUT_PLAN is None and not prev.is_dir())):
        cen = census(cell)
        report = {"schema": SCHEMA, "cell": cell.name, "previous_cell": None,
                  "verdict": "NO_BASELINE",
                  "disclosure": "no previous run; nothing compared",
                  "census_current": cen}
        _emit(report, args.json)
        print(f"[NO_BASELINE] tool_diagnostic_id_gate: no previous run of "
              f"{cell.name} — nothing compared. A first run is not a clean "
              f"run; {len(gated_ids(cen))} gated id(s) recorded as the future "
              f"baseline.")
        # THE METRIC IS EMITTED EVEN HERE, and that is the point of the
        # metric. NO_BASELINE means the COMPARISON could not run; it does not
        # mean nothing was measured. Publishing this run's per-step counts is
        # what gives the NEXT run something to be compared against — and the
        # rc stays 2, because a recorded baseline is still not a clean run.
        if _emit_metrics_cli(cen, args.emit_metrics):
            return 1
        return 2

    today = date.fromisoformat(args.today) if args.today else date.today()
    rc, report = compare(cell, prev, Path(args.acceptance), today)
    _emit(report, args.json)

    u = report["unkeyed_not_compared"]
    if rc == 2:
        print(f"[VACUOUS] tool_diagnostic_id_gate: {cell.name} vs "
              f"{prev.name} — {report['disclosure']}")
    elif rc == 0:
        print(f"[PASS] tool_diagnostic_id_gate: {cell.name} vs "
              f"{prev.name} — no new diagnostic id "
              f"({report['compared_ids_current']} compared).")
    else:
        for i, steps in report["new_ids_blocking"].items():
            print(f"[FAIL] NEW diagnostic id {i} — not emitted by "
                  f"{prev.name}; steps: {', '.join(steps)}")
        for p in report["acceptance_problems"]:
            print(f"[FAIL] acceptance list: {p}")
    if report.get("new_ids_accepted"):
        print(f"[INFO] new but accepted: "
              f"{', '.join(report['new_ids_accepted'])}")
    print(f"[INFO] {u['current']} unkeyed diagnostic(s) in this run were NOT "
          f"compared (no message id to key on)")
    d = report["denied_not_counted"]
    print(f"[INFO] {d['current']} id-shaped token(s) were read as DENIALS and "
          f"excluded from the comparison (not emissions)")
    if _emit_metrics_cli(report["census_current"], args.emit_metrics):
        return 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
