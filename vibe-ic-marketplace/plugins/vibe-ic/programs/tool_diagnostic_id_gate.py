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

THE HONEST LIMIT
================
A cell with no earlier run has nothing to compare against. That exits **2**
(NO_BASELINE) with the disclosure "no previous run; nothing compared" — never
0. A first run is not a clean run, and a gate that returns success for a
comparison it could not perform is the exact defect this campaign removes.

AND THE LIMIT IS NOT HYPOTHETICAL: TODAY IT IS EVERY CELL
---------------------------------------------------------
Run over all five published cells this commit carries, the answer is **5 of 5
NO_BASELINE**::

    caravel_user_project/v1.9.43_sky130A  rc=2  (9 gated ids recorded)
    spm/v1.10.18_sky130A                  rc=2  (5)
    spm/v1.5.58_ihp-sg13g2                rc=2  (6)
    spm/v1.9.96_gf180mcuD                 rc=2  (7)
    u_hawaii_adc/v1.9.86_sky130A          rc=2  (0)

No design carries two cells of the SAME PDK, and `find_previous` requires same
PDK and a strictly lower version — correctly, because a different PDK legitimately
emits different ids. So on this commit the comparison path is UNREACHABLE from
the corpus. That is not a defect in the rule; it is the population, and it is
written here because a reader of "is BLOCKING" would otherwise assume the gate is
blocking something. `test_the_published_corpus_yields_no_comparable_pair` pins
it, and FAILS the day a second same-PDK cell is published — which is the day
this paragraph must be rewritten.

NOT WIRED YET — SAID PLAINLY
============================
Nothing invokes this program. It appears in no `flow/*.yaml` step, in no
`benchmark/CAPTURE_ROUTING.json` entry, in no runner, and in none of
`flow_compliance_check.py`'s registered gates: on this commit the only files in
the repository naming `tool_diagnostic_id_gate` are its own source, its test, its
acceptance list and its `programs/INDEX.md` row.

An unwired checker is the D9 defect class this campaign is actively removing, so
it is not left to a reader to discover: `test_the_unwired_state_is_disclosed_or_gone`
MEASURES the wiring and fails in BOTH directions — while unwired it requires this
paragraph to exist, and the moment somebody wires it the test fails and forces
the paragraph out. What it cannot do is decide WHICH step should own the clause;
that is a flow declaration and it needs the ruling, not a guess.

Exit codes: 0 = compared and clean, 1 = BLOCKING, 2 = could not compare (no
previous run, or this run yields zero gated ids so the comparison would be
vacuous — see VACUITY IS NOT CLEANLINESS in `compare`).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _prose_polarity as _polarity   # vibe-ic#1241

SCHEMA = "tool_diagnostic_id_census/v1"

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
    candidates = sorted(p for p in cell_root.rglob("*")
                        if p.suffix in _SCANNED_SUFFIXES)
    for log in candidates:
        if not log.is_file():
            continue
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        if _is_our_own_artifact(text):
            skipped_own += 1
            continue
        logs_scanned += 1
        found = scan_log(text)
        step = _step_of(log, cell_root)
        slot = steps.setdefault(
            step, {"logs": [], "ids": {}, "unkeyed_count": 0})
        slot["logs"].append(log.relative_to(cell_root).as_posix())
        slot["unkeyed_count"] += found["unkeyed_count"]
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


# ---------------------------------------------------------------------------
# the acceptance list, and the checking OF the acceptance list
# ---------------------------------------------------------------------------
_REQUIRED_FIELDS = ("id", "reason", "accepted_on", "expires_on",
                    "adjudicated_by")


def load_acceptance(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    doc = json.loads(path.read_text())
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
def find_previous(cell_dir: Path) -> Optional[Path]:
    """The published cell for the same (design, PDK) at the highest version
    strictly below this one. `None` when there is no earlier run."""
    parsed = _parse_cell_name(cell_dir.name)
    if parsed is None:
        return None
    ver, pdk = parsed
    best: Optional[Tuple[Tuple[int, ...], Path]] = None
    for sib in cell_dir.parent.iterdir():
        if not sib.is_dir() or sib.name == cell_dir.name:
            continue
        p = _parse_cell_name(sib.name)
        if p is None or p[1] != pdk:
            continue
        if p[0] < ver and (best is None or p[0] > best[0]):
            best = (p[0], sib)
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
    ap.add_argument("--today", help="ISO date for expiry evaluation (testing)")
    args = ap.parse_args(argv)

    cell = Path(args.cell_dir)
    if not cell.is_dir():
        print(f"[FAIL] tool_diagnostic_id_gate: no such cell: {cell}")
        return 2

    if args.census_only:
        cen = census(cell)
        _emit(cen, args.json)
        print(f"[INFO] tool_diagnostic_id_gate: censused {cen['logs_scanned']} "
              f"log(s), {len(gated_ids(cen))} gated id(s) in {cell.name}")
        return 0

    prev = Path(args.previous) if args.previous else find_previous(cell)
    if prev is None or not prev.is_dir():
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
    return rc


if __name__ == "__main__":
    sys.exit(main())
