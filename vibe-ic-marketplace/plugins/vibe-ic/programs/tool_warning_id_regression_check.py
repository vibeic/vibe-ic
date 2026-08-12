#!/usr/bin/env python3
"""
tool_warning_id_regression_check.py — a tool diagnostic ID that was not there
last time is a change in tool behaviour nobody decided to accept. vibe-ic#1081.

ENFORCEMENT — TWO AXES, AND THEY CURRENTLY DISAGREE. Stated separately because
conflating them is how "62 of 72 gates cannot block" happened here.

  VERDICT SEVERITY: BLOCKING. A new message ID that no acceptance covers is
  rc 1; an expired or malformed acceptance is rc 1 whether or not it fired.
  rc 2 is NOT_CHECKED — "there is no predecessor to compare against" — which
  this gate refuses to score as clean. That severity is the point of #1081:
  the upstream practice this is adopted from (OpenROAD-flow-scripts,
  `flow/util/genRuleFile.py:70-75`, `level: warning`) only WARNs, so a
  brand-new tool warning never fails their build.

  FLOW WIRING: NOT WIRED — nothing invokes this gate yet, so today it stops
  nothing. Said plainly rather than left to the reader, because an unstated
  default of "advisory" is precisely how a gate ends up auditable-after-the-
  fact instead of preventive. Wiring it is deliberately NOT part of this
  change, for a measured reason: no published run carries a committed
  `tool_warning_ids.json`, so a `run` line in the hygiene sweep would return
  rc 2 for every cell and turn the sweep red on a tree that has no defect,
  while a `run_tolerating_uncheckable` line depends on the dated-exemption
  mechanism still in flight as vibe-ic#584/#1072. The honest sequence is:
  land the instrument, seed a baseline per published run
  (`--emit-baseline`), then wire it. Wiring it before it can measure anything
  would ship a gate whose every verdict is "I could not look".

WHY THIS IS DECIDABLE WITHOUT AN ORACLE
=======================================
This gate never asks "is this warning acceptable" — that question needs a human
and a design. It asks "did this message ID exist last time", which is a set
difference over two runs and owes no oracle. That property is exactly what §D9
requires, and it is why the verdict can be BLOCKING rather than advisory.

WHAT IS COMPARED, AND THE TRAP THAT SHAPED IT
=============================================
MEASURED over the published corpus at v1.10.32, which is what decided the
comparison axis rather than a guess:

    spm/v1.10.18_sky130A   ->  spm/v1.5.58_ihp-sg13g2   NEW = 3 IDs
    spm/v1.5.58_ihp-sg13g2 ->  spm/v1.8.37_sky130A      NEW = 12 IDs
    spm/v1.8.37_sky130A    ->  spm/v1.9.96_gf180mcuD    NEW = 3 IDs

Those runs differ by PDK. A different PDK legitimately produces different tool
diagnostics, so "the previous run of the same cell" — read naively as "the
directory next to it" — would fire on every one of those and be a bug in the
gate, not a finding (flow-change-acceptance §2). A gate people learn to ignore
is worse than no gate.

So the predecessor is never INFERRED from directory adjacency, ordering, or a
name parse. It is either:

  * NAMED explicitly (`--baseline-run DIR`) — the caller states which run is
    the predecessor, because only the caller knows which two runs are
    like-for-like; or
  * COMMITTED alongside the run (`tool_warning_ids.json`) — a reviewed record
    of the IDs this run is known to produce.

Absent both, the answer is NOT_CHECKED (rc 2), never PASS. "I could not find a
predecessor" and "there was no new warning" must not share an exit code — that
conflation is the shape this repo has paid for repeatedly.

MEASURED TRUE POSITIVE. With the two like-for-like runs the corpus does contain
(same cell, same four report files carrying diagnostics, 398 vs 387 lines):

    sha256/clean_run_v1422_20260715 -> sha256/clean_run_v1427_20260715
        NEW = ['DRT-0120']

`DRT-0120` ("Large net ... has N pins which may impact routing performance")
is present in v1427's `reports/phase3/drc_router.rpt` and absent from v1422's.
It is a real change in tool behaviour between two runs of the same cell, and
today nothing in the flow can see it. `test_the_real_corpus_pair_reports_the_new_id`
pins exactly that pair, so this gate is backed by a checked-in artefact and not
only by fixtures authored beside it (flow-change-acceptance §4).

WHY AN ACCEPTANCE MUST BE DATED AND REASONED
============================================
An acceptance with no expiry is a skip button. It silently starts covering a
real regression on some later run, and that run is the one nobody is looking
at. So an entry carries `until` (ISO-8601) and `why`, an expired entry fails
the gate whether or not it fired, and a malformed entry is refused rather than
ignored — a mis-typed acceptance that is silently skipped is an acceptance that
covers nothing while reading as though it covers something.

ISO-8601 only, so the expiry comparison is a plain string compare: on
YYYY-MM-DD, lexicographic order IS chronological order, in every locale, with
no date library and no parse that could itself fail open.

chip-AGNOSTIC: nothing here names an IC, a PDK, a vendor or a tool. The
diagnostic grammar `[SEVERITY ABCD-1234]` is a message-ID convention, not a
product name, and the tool prefixes it discovers are whatever the logs contain.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RC_CLEAN, RC_BLOCKING, RC_NOT_CHECKED = 0, 1, 2

#: `[WARNING DRT-0120]` / `[ERROR STA-0441]`. INFO is deliberately excluded:
#: informational chatter changes with verbosity and would drown the signal.
#: The tool prefix is captured, never enumerated — no tool is named here.
_DIAG = re.compile(r"\[(?:WARNING|ERROR)\s+([A-Z]{2,5}-\d{3,4})\]")

#: Text artefacts a published run carries its diagnostics in.
_TEXT_SUFFIXES = (".log", ".rpt", ".txt", ".out")

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")

BASELINE_NAME = "tool_warning_ids.json"
ACCEPTANCE_NAME = "tool_warning_id_acceptance.json"


def collect_ids(root: Path, exclude: list[Path] | None = None) -> dict[str, list[str]]:
    """{message_id: [relative paths it appeared in]} under `root`.

    `exclude` keeps a nested run root's diagnostics from being attributed to
    its parent. Without it a cell directory reads as the UNION of every run
    beneath it, which makes the parent look like it produced IDs no single run
    ever did — measured while scoping this gate, on a cell whose root reported
    19 distinct IDs that no individual run of it produced.
    """
    exclude = [e.resolve() for e in (exclude or [])]
    found: dict[str, list[str]] = {}
    if not root.is_dir():
        return found
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        rf = f.resolve()
        if any(str(rf).startswith(str(e) + "/") for e in exclude):
            continue
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for m in _DIAG.finditer(text):
            found.setdefault(m.group(1), [])
            rel = f.relative_to(root).as_posix()
            if rel not in found[m.group(1)]:
                found[m.group(1)].append(rel)
    return found


def _load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def load_acceptance(run: Path) -> tuple[dict[str, dict], list[str]]:
    """(accepted_by_id, malformed_reasons). A malformed entry is NEVER ignored."""
    path = run / ACCEPTANCE_NAME
    if not path.is_file():
        return {}, []
    data = _load_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("accepted"), list):
        return {}, [f"{ACCEPTANCE_NAME}: not an object with an 'accepted' list"]
    out: dict[str, dict] = {}
    bad: list[str] = []
    for i, e in enumerate(data["accepted"]):
        if not isinstance(e, dict):
            bad.append(f"{ACCEPTANCE_NAME}[{i}]: not an object")
            continue
        mid, until, why = e.get("id"), e.get("until"), e.get("why")
        if not mid or not isinstance(mid, str):
            bad.append(f"{ACCEPTANCE_NAME}[{i}]: no 'id'")
            continue
        if not isinstance(until, str) or not _ISO.match(until):
            bad.append(f"{ACCEPTANCE_NAME}[{i}] ({mid}): 'until' must be ISO-8601 YYYY-MM-DD")
            continue
        if not isinstance(why, str) or not why.strip():
            bad.append(f"{ACCEPTANCE_NAME}[{i}] ({mid}): an acceptance with no 'why' is a skip button")
            continue
        out[mid] = {"until": until, "why": why.strip()}
    return out, bad


def resolve_baseline(run: Path, baseline_run: Path | None) -> tuple[set[str] | None, str]:
    """(baseline_ids, provenance). None means: no predecessor — NOT_CHECKED.

    Never infers a predecessor from directory adjacency; see the module
    docstring for the measurement behind that.
    """
    if baseline_run is not None:
        if not baseline_run.is_dir():
            return None, f"named baseline run does not exist: {baseline_run}"
        ids = set(collect_ids(baseline_run))
        if not ids:
            return None, f"named baseline run carries no diagnostics: {baseline_run}"
        return ids, f"named baseline run {baseline_run}"
    committed = run / BASELINE_NAME
    if committed.is_file():
        data = _load_json(committed)
        if isinstance(data, dict) and isinstance(data.get("ids"), list):
            return set(str(x) for x in data["ids"]), f"committed {BASELINE_NAME}"
        return None, f"{BASELINE_NAME} present but unreadable / has no 'ids' list"
    return None, f"no --baseline-run given and no committed {BASELINE_NAME}"


def check(run: Path, baseline_run: Path | None, today: str) -> tuple[int, list[str]]:
    lines: list[str] = []
    current = collect_ids(run)
    accepted, malformed = load_acceptance(run)

    # A malformed acceptance is refused BEFORE anything else: it describes a
    # tolerance that does not exist, and a reader who saw it would believe it.
    for m in malformed:
        lines.append(f"  REFUSED  {m}")

    # An expired acceptance fails whether or not it fired. It is a promise to
    # revisit, and one kept past its reason is a blind spot the exact size of
    # the ID it covers.
    expired = sorted(m for m, e in accepted.items() if e["until"] < today)
    for m in expired:
        lines.append(f"  EXPIRED  acceptance for {m} lapsed {accepted[m]['until']} — revisit or re-date it")

    baseline, prov = resolve_baseline(run, baseline_run)
    if baseline is None:
        lines.append(f"  NOT_CHECKED  {run}: {prov}")
        lines.append("               a missing predecessor is NOT a pass — nothing was compared")
        # A refusal or an expiry is still a real defect even when the
        # comparison itself could not run; it must not be masked by rc 2.
        return (RC_BLOCKING if (malformed or expired) else RC_NOT_CHECKED), lines

    if not current:
        lines.append(f"  NOT_CHECKED  {run}: no tool diagnostics found to compare against {prov}")
        return (RC_BLOCKING if (malformed or expired) else RC_NOT_CHECKED), lines

    new = sorted(set(current) - baseline)
    unaccepted = [m for m in new if m not in accepted]
    covered = [m for m in new if m in accepted and m not in expired]

    for m in covered:
        lines.append(f"  ACCEPTED  {m} is new vs {prov}, covered until {accepted[m]['until']}: {accepted[m]['why'][:90]}")
    for m in unaccepted:
        where = ", ".join(current[m][:3])
        lines.append(f"  NEW       {m} appears in this run and not in {prov} — in {where}")

    if unaccepted or malformed or expired:
        lines.append(f"  FAIL  {len(unaccepted)} unaccepted new message ID(s); "
                     f"{len(expired)} expired, {len(malformed)} malformed acceptance(s)")
        return RC_BLOCKING, lines
    lines.append(f"  PASS  {len(current)} distinct ID(s) vs {prov}; "
                 f"{len(new)} new, all covered by a live acceptance")
    return RC_CLEAN, lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[1])
    ap.add_argument("run", help="the run root to judge")
    ap.add_argument("--baseline-run", default=None,
                    help="a predecessor run root to compare against. Required unless the run "
                         f"carries a committed {BASELINE_NAME}; never inferred from adjacency.")
    ap.add_argument("--today", default=None, help="override today's date (ISO-8601), for tests")
    ap.add_argument("--emit-baseline", action="store_true",
                    help=f"write {BASELINE_NAME} for this run instead of judging it")
    a = ap.parse_args(argv)

    run = Path(a.run)
    if not run.is_dir():
        print(f"tool_warning_id_regression_check: NOT_CHECKED — no such run root: {run}")
        return RC_NOT_CHECKED

    if a.emit_baseline:
        ids = sorted(collect_ids(run))
        (run / BASELINE_NAME).write_text(json.dumps({"ids": ids}, indent=2) + "\n")
        print(f"wrote {run / BASELINE_NAME} with {len(ids)} ID(s)")
        return RC_CLEAN

    if a.today is not None and not _ISO.match(a.today):
        print("tool_warning_id_regression_check: --today must be ISO-8601 YYYY-MM-DD")
        return RC_BLOCKING
    today = a.today
    if today is None:
        # Imported here so the module has no import-time clock dependency.
        from datetime import date
        today = date.today().isoformat()

    base = Path(a.baseline_run) if a.baseline_run else None
    rc, lines = check(run, base, today)
    print(f"tool_warning_id_regression_check: {run}")
    for ln in lines:
        print(ln)
    return rc


if __name__ == "__main__":
    sys.exit(main())
