#!/usr/bin/env python3
"""waiver_staleness.py — REFUSE to honor a waiver whose reason-condition no
longer holds (the FALSE-CLEAN guard).

THE DEFECT THIS CLOSES
----------------------
An `ENV_UNAVAILABLE`-tier waiver is issued for exactly ONE reason: the step
COULD NOT RUN on this host (tool absent / PDK substituted / board absent). It
is written to `<project>/waivers.json` as a FILE, and the file SURVIVES into
the next run. When a later run actually HAS the tool, the step EXECUTES — and
may FAIL. The stale waiver then excuses a real, observed failure. That is a
FALSE-CLEAN: the most dangerous verdict a sign-off gate can produce, because
the failure genuinely happened and the audit reports it as waived.

THE RULE (chip-AGNOSTIC, deterministic)
---------------------------------------
A waiver carries the CONDITION it was issued under. An ENV_UNAVAILABLE waiver's
condition is `step_did_not_execute`. The consumer re-evaluates that condition
against the CURRENT run's own evidence before honoring it:

  * step has POSITIVE evidence it EXECUTED  -> condition BROKEN -> REFUSE.
    The step's real verdict stands; a failure is NOT excused.
  * step still reports a did-not-run status  -> condition HOLDS  -> HONOR.
    A genuine ENV_UNAVAILABLE deferral keeps working exactly as before.
  * NO evidence either way (no report yet)   -> condition HOLDS  -> HONOR.
    Absence of evidence never manufactures a rejection; the guard only fires
    on POSITIVE proof that the excused step ran.

Waivers are additionally STAMPED with the run identity they were issued for
(`_waiver_condition.run_id`), so a reviewer can see a waiver was carried over
from a different run even when the step-status evidence is missing.

The evidence is the flow's own phase-report `steps[] {name, status}` — a
STRUCTURAL property of the run, never a chip-class literal. No design name, no
chip id, no problem id appears anywhere in this module.

WHICH STEP A WAIVER NAMES. Both spellings are read, never one. The ``waivers``
dialect writes a role NAME (``{"step": "lvs"}``); the ``waived_steps`` dialect —
the one BOTH auto-synthesisers in ``flow_compliance_check`` emit — writes only
the canonical flow step ID (``{"id": 6}``). Asking for a name alone made every
auto-generated waiver answer "condition unevaluable" and be honoured
unconditionally, i.e. the guard was disarmed for exactly the class it exists
for. ``_waiver_entries.step_names_for_id`` resolves the id through the one
shared vocabulary; that map is many-to-one, so an id contributes EVERY role
name and the positive-evidence rule above applies across all of them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _waiver_entries as _we  # noqa: E402  (after sys.path bootstrap)

_PROGRAM = "waiver_staleness"

#: The waiver-condition kind an ENV_UNAVAILABLE-tier waiver is issued under.
CONDITION_STEP_DID_NOT_EXECUTE = "step_did_not_execute"

#: Statuses that mean the step DID NOT actually execute. Anything else in a
#: phase report (PASS / FAIL / OK / ERROR / BLOCK / …) is POSITIVE evidence the
#: step RAN — and therefore breaks an ENV_UNAVAILABLE waiver's condition.
DID_NOT_RUN_STATUSES = frozenset({
    "", "ENV_UNAVAILABLE", "SKIP", "SKIPPED", "NOT_RUN", "NOTRUN",
    "NOT_APPLICABLE", "N/A", "NA", "PENDING", "DEFERRED", "WAIVED",
    "UNAVAILABLE", "TOOL_ABSENT",
})

#: Every plausible phase-report location. The runners have rotated the
#: canonical layout across releases; all are read so the guard cannot be
#: defeated by a layout change.
_REPORT_CANDIDATES = (
    "reports/phase3_one_shot.json",
    "reports/orchestrator/phase3_one_shot.json",
    "phase3/reports/phase3_one_shot.json",
    "reports/phase2_one_shot.json",
    "reports/orchestrator/phase2_one_shot.json",
    "phase2/reports/phase2_one_shot.json",
    "reports/phase23_one_shot.json",
    "reports/orchestrator/phase23_one_shot.json",
    "reports/vibe_ic_one_shot.json",
)


# ---------------------------------------------------------------------------
# Evidence: did the step actually execute in THIS run?
# ---------------------------------------------------------------------------
def _norm(name: Any) -> str:
    return str(name or "").strip().lower().replace("-", "_")


def _names_match(waiver_step: str, report_step: str) -> bool:
    """True when a waiver's step name denotes the same step as a phase-report
    step name. Exact normalized match, or one is the leading `_`-token of the
    other (`drc` <-> `drc_klayout`). Deliberately NOT substring matching, so
    `lvs` never claims `lvs_setup_emit`-unrelated steps by accident."""
    a, b = _norm(waiver_step), _norm(report_step)
    if not a or not b:
        return False
    if a == b:
        return True
    return a.split("_")[0] == b.split("_")[0] and (
        a.startswith(b + "_") or b.startswith(a + "_"))


def _iter_report_steps(project: Path):
    """Yield (report_path, step_name, status) for every step in every readable
    phase report under `project`."""
    for cand in _REPORT_CANDIDATES:
        p = project / cand
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        steps = data.get("steps") if isinstance(data, dict) else None
        if not isinstance(steps, list):
            continue
        for s in steps:
            if isinstance(s, dict):
                yield p, s.get("name"), str(s.get("status", "")).strip()


def step_execution_status(project: Path, step_name: str) -> Optional[str]:
    """The recorded status of `step_name` in this project's phase reports, or
    None when no report mentions the step (no evidence).

    When several reports mention the step, POSITIVE execution evidence wins: a
    step that ran anywhere in this run DID run. This is the conservative
    direction for a guard — it can only ever REFUSE a waiver, never mint one.
    """
    seen: Optional[str] = None
    for _p, name, status in _iter_report_steps(project):
        if not _names_match(step_name, name):
            continue
        if status.upper() not in DID_NOT_RUN_STATUSES:
            return status          # positive execution evidence — decisive
        seen = status
    return seen


def step_executed(project: Path, step_name: str) -> Optional[bool]:
    """True  = POSITIVE evidence the step executed in this run.
    False = evidence it did NOT execute (ENV_UNAVAILABLE / SKIP / …).
    None  = no evidence at all."""
    status = step_execution_status(project, step_name)
    if status is None:
        return None
    return status.upper() not in DID_NOT_RUN_STATUSES


# ---------------------------------------------------------------------------
# Run identity
# ---------------------------------------------------------------------------
def current_run_id(project: Path) -> Optional[str]:
    """A deterministic identity for THIS run, derived from the phase report the
    run wrote (an explicit `run_id`/`started_at` when present, else the report's
    mtime). None when no report exists yet. chip-AGNOSTIC."""
    for cand in _REPORT_CANDIDATES:
        p = project / cand
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(errors="replace"))
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict):
            for key in ("run_id", "started_at", "start_time", "timestamp"):
                v = data.get(key)
                if isinstance(v, (str, int, float)) and str(v).strip():
                    return f"{cand}:{v}"
        try:
            return f"{cand}:mtime={p.stat().st_mtime_ns}"
        except OSError:
            continue
    return None


# ---------------------------------------------------------------------------
# Stamping (producer side)
# ---------------------------------------------------------------------------
def waiver_step_name(entry: Dict[str, Any]) -> str:
    """The step name an entry excuses — `step`, else `step_name`, else the
    stamped condition's step. Empty string when the entry names no step.

    NAME ONLY. An entry that identifies its step by `id` answers "" here and is
    resolved by `waiver_step_names`; this function stays the literal reader so
    an explicit spelling always wins over a resolved one."""
    for key in ("step", "step_name"):
        v = entry.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    cond = entry.get("_waiver_condition")
    if isinstance(cond, dict):
        v = cond.get("step")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def waiver_step_names(entry: Dict[str, Any]) -> List[str]:
    """EVERY step this entry excuses, as report-step role names.

    The written name first when there is one, then every role name the entry's
    canonical flow step `id` resolves to. Both spellings are read, never one:
    the flow's two waiver synthesisers emit `{"id": 6, ...}` with no name at
    all, and asking only for a name made the guard below answer "condition
    unevaluable" for the entire auto-generated waiver class — the class most
    likely to be carried into a later run, which is the only situation this
    module exists for.

    The id map is MANY-TO-ONE (31 is drc/lvs/erc/physical_verification), so an
    id contributes ALL of its role names and the caller's existing rule —
    POSITIVE execution evidence anywhere is decisive — applies across them. An
    id no role name maps to contributes nothing, so an unidentifiable entry
    stays honestly unevaluable rather than being matched by a guess."""
    if not isinstance(entry, dict):
        return []
    names: List[str] = []
    written = waiver_step_name(entry)
    if written:
        names.append(written)
    for candidate in _we.step_names_for_id(entry.get("id")):
        if candidate not in names:
            names.append(candidate)
    return names


def is_env_unavailable(entry: Dict[str, Any]) -> bool:
    """True for an ENV_UNAVAILABLE-tier waiver, in either shape the flow emits
    (`_env_unavailable: true` or `verdict_tier: "ENV_UNAVAILABLE"`)."""
    if entry.get("_env_unavailable") is True:
        return True
    return str(entry.get("verdict_tier") or "").strip().upper() == "ENV_UNAVAILABLE"


def stamp(entry: Dict[str, Any], project: Path,
          step_name: Optional[str] = None) -> Dict[str, Any]:
    """Return `entry` stamped with the CONDITION it is issued under.

    Only ENV_UNAVAILABLE-tier entries are stamped — a human-judgment waiver is
    not conditioned on a step failing to run and is returned untouched."""
    if not is_env_unavailable(entry):
        return entry
    out = dict(entry)
    # The RESOLVED name, not just the written one: an id-only entry used to be
    # stamped `"step": ""`, which is the shape a reviewer reads as "this waiver
    # names nothing" and the shape the consumer below could not evaluate.
    resolved = waiver_step_names(out)
    step = step_name or (resolved[0] if resolved else "")
    out["_waiver_condition"] = {
        "kind": CONDITION_STEP_DID_NOT_EXECUTE,
        "step": step,
        "run_id": current_run_id(project),
        "note": ("This waiver is valid ONLY while the step could not run. If a "
                 "later run EXECUTES the step, the waiver is REFUSED and the "
                 "step's real verdict stands."),
    }
    return out


# ---------------------------------------------------------------------------
# Refusal (consumer side)
# ---------------------------------------------------------------------------
def condition_holds(entry: Dict[str, Any], project: Path
                    ) -> Tuple[bool, str]:
    """(honorable, reason) for one waiver entry.

    An ENV_UNAVAILABLE waiver is REFUSED iff there is POSITIVE evidence its
    step EXECUTED in this run. A legacy UNSTAMPED ENV_UNAVAILABLE entry carries
    the SAME implicit condition and is checked identically — the guard must not
    be defeatable by simply omitting the stamp."""
    if not isinstance(entry, dict):
        return True, "not a waiver entry"
    if not is_env_unavailable(entry):
        return True, "not an ENV_UNAVAILABLE waiver — no run-condition attached"
    steps = waiver_step_names(entry)
    if not steps:
        return True, ("ENV_UNAVAILABLE waiver names no step and carries no "
                      "resolvable step id — condition unevaluable")
    did_not_run: Optional[str] = None
    for step in steps:
        ran = step_executed(project, step)
        if ran is True:
            status = step_execution_status(project, step)
            cond = entry.get("_waiver_condition")
            issued = ((cond or {}).get("run_id")
                      if isinstance(cond, dict) else None)
            return False, (
                f"STALE WAIVER REFUSED: step '{step}' actually EXECUTED in this "
                f"run (status={status!r}), so the ENV_UNAVAILABLE condition "
                f"'{CONDITION_STEP_DID_NOT_EXECUTE}' no longer holds"
                + (f" (waiver issued under run {issued!r})" if issued else "")
                + ". The step's real verdict stands — a failure is NOT excused.")
        if ran is False and did_not_run is None:
            did_not_run = step
    if did_not_run is not None:
        return True, (f"step '{did_not_run}' still reports a did-not-run "
                      f"status — condition holds")
    return True, (f"no execution evidence for step(s) "
                  f"{', '.join(repr(s) for s in steps)} — condition assumed "
                  f"to hold")


def filter_honorable(entries: List[Dict[str, Any]], project: Path
                     ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split entries into (honorable, refused). Refused entries carry a
    `_refused_reason` so the rejection is AUDITABLE, never silent."""
    keep: List[Dict[str, Any]] = []
    drop: List[Dict[str, Any]] = []
    for e in entries:
        ok, why = condition_holds(e, project)
        if ok:
            keep.append(e)
        else:
            r = dict(e)
            r["_refused_reason"] = why
            drop.append(r)
    return keep, drop


def prune_stale_mapping(waivers: Dict[Any, Dict[str, Any]], project: Path
                        ) -> Dict[Any, str]:
    """In-place: drop every step-id whose waiver's condition no longer holds.
    Returns {step_id: refusal_reason} for the entries removed (auditable)."""
    refused: Dict[Any, str] = {}
    for sid in list(waivers):
        entry = waivers.get(sid)
        if not isinstance(entry, dict):
            continue
        ok, why = condition_holds(entry, project)
        if not ok:
            refused[sid] = why
            waivers.pop(sid, None)
    return refused
