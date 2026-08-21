#!/usr/bin/env python3
"""waivers_materialize.py — materialize the MACHINERY-SANCTIONED in-memory
ENV_UNAVAILABLE-tier auto-waivers into <project>/waivers.json (#146 blocker-1).

The flow ALREADY auto-synthesizes sanctioned ENV_UNAVAILABLE-tier waivers
in-memory during the strict audit (`_synthesise_pdk_substitution_waivers` /
`_synthesise_fpga_skip_waivers` in flow_compliance_check) — each already carries
a SANCTIONED tier approver (`field-agent-attest (…tier)`, never a self-approver)
+ review_required:true + a ticket + evidence. But the strict completion audit
lists `waivers.json` as a MISSING required artifact because no FILE ever
materializes: the runner emits neither the file nor its template automatically.

This program writes EXACTLY those machinery-sanctioned in-memory waivers to
`<project>/waivers.json` so the required-artifact slot is populated by a real,
schema-valid, review-required file — WITHOUT ever self-approving or promoting a
human-judgment waiver.

ANTI-FABRICATION invariants (Step-2.7 surfaces — this is guard-adjacent):
  * ONE source of truth: reuses flow_compliance_check's synthesis, so a
    materialized entry is FIELD-IDENTICAL to the in-memory waiver the audit
    would apply (behavioral equivalence — materializing changes nothing except
    that the deferral is now an auditable FILE).
  * NEVER a human-judgment waiver: only the two sanctioned ENV_UNAVAILABLE tiers
    are materialized. Human-judgment deferrals stay in waivers.json.template for
    a person to fill; this program never reads/promotes a template entry.
  * NEVER clobbers a HUMAN waivers.json: an existing file is touched ONLY when it
    is itself auto-generated (every entry carries `_autogen`/`auto_synthesized`);
    a human-authored file wins untouched.
  * NO sanctioned auto-waivers → writes NOTHING. Absence stays an HONEST MISSING
    (an undisclosed gap still hard-FAILs; never a fabricated empty pass).
  * Every materialized entry keeps its sanctioned approver (rejected by
    waivers_schema_check if ever 'agent'/'self'/'ai'/'claude') +
    review_required:true + an `auto_synthesized:true` marker so a reviewer sees
    it was machine-materialized and still owes a foundry sign-off close.

Usage:
    python3 waivers_materialize.py <project_dir> [--json <out>]

Exit: 0 always (materialization is best-effort; absence is honest, not an error).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import waiver_staleness as _ws  # noqa: E402  (after sys.path bootstrap)
import _waiver_entries as _we  # noqa: E402

_PROGRAM = "waivers_materialize"


def sanctioned_auto_waivers(project: Path) -> Dict[Any, Dict[str, Any]]:
    """The machinery-sanctioned in-memory ENV_UNAVAILABLE-tier auto-waivers for
    this project (pdk-substitution + fpga-board cap-gap), reusing
    flow_compliance_check's synthesis as the SINGLE source of truth. Empty when
    no sanctioned tier is disclosed for the project. NEVER includes a
    human-judgment waiver."""
    try:
        import flow_compliance_check as _fcc  # type: ignore
    except Exception:  # pragma: no cover - defensive
        return {}
    out: Dict[Any, Dict[str, Any]] = {}
    for fn in ("_synthesise_pdk_substitution_waivers",
               "_synthesise_fpga_skip_waivers"):
        f = getattr(_fcc, fn, None)
        if f is not None:
            try:
                f(project, out)
            except Exception:  # pragma: no cover - a synth predicate must never
                pass           # crash the materializer; a failing tier just no-ops
    return out


def _is_auto_generated(data: Any) -> bool:
    """True iff an existing waivers.json is itself auto-generated (safe to merge
    into). A file with ANY human-authored entry (no auto marker) is treated as
    human — never touched."""
    if not isinstance(data, dict):
        return False
    if data.get("_generator") == "waivers_materialize.py":
        return True
    # #519 — via the ONE shared reader (this site already unioned by hand).
    entries = _we.entries(data)
    if not entries:
        return False
    return all(
        isinstance(e, dict)
        and (e.get("_autogen") is True or e.get("auto_synthesized") is True)
        for e in entries)


def _to_entry(w: Dict[str, Any], project: Path) -> Dict[str, Any]:
    """A materialized `waived_steps` entry — FIELD-IDENTICAL to the in-memory
    synth waiver (preserves `_env_unavailable`, evidence, ticket, tier so
    check_step behaves identically), plus the review/auto markers.

    STALENESS STAMP (false-clean guard): an ENV_UNAVAILABLE entry is stamped
    with the CONDITION it is issued under (`step_did_not_execute` + the run
    identity). A later run that actually EXECUTES the step breaks the condition
    and the consumer REFUSES the waiver — so a waiver written when a step could
    not run can never excuse a failure that really happened."""
    entry = dict(w)
    entry["review_required"] = True
    entry["auto_synthesized"] = True
    return _ws.stamp(entry, project)


_COMMENT = (
    "Auto-materialized by waivers_materialize.py from the flow's "
    "MACHINERY-SANCTIONED ENV_UNAVAILABLE auto-waivers (pdk-substitution / "
    "fpga-board cap-gap). Each entry carries a sanctioned tier approver + "
    "review_required:true; NONE is self-approved and NONE is a human-judgment "
    "waiver (those stay in waivers.json.template). review_required is OPEN WORK "
    "— a human closes it at foundry sign-off; this is not a green PASS.")


def prune_stale(project: Path) -> List[Dict[str, Any]]:
    """Drop every AUTO-GENERATED waiver in <project>/waivers.json whose
    reason-condition no longer holds — i.e. the ENV_UNAVAILABLE-excused step
    actually EXECUTED in this run. Returns the refused entries (each carrying
    `_refused_reason`) so the rejection is auditable, never silent.

    A HUMAN-authored waivers.json is never touched (same invariant as
    `materialize`); only machine-materialized entries are pruned."""
    wpath = project / "waivers.json"
    if not wpath.is_file():
        return []
    try:
        data = json.loads(wpath.read_text())
    except (OSError, ValueError):
        return []                          # unreadable/foreign — never clobber
    if not _is_auto_generated(data):
        return []                          # HUMAN file wins — never touched
    entries = list(data.get("waived_steps") or [])
    keep, refused = _ws.filter_honorable(
        [e for e in entries if isinstance(e, dict)], project)
    if not refused:
        return []
    data["waived_steps"] = keep
    data["_refused_stale_waivers"] = refused
    wpath.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return refused


def materialize(project: Path, force: bool = False
                ) -> Tuple[int, List[Any]]:
    """Write the sanctioned auto-waivers into <project>/waivers.json.
    Returns (count_written, [step ids]). See module docstring for invariants."""
    wpath = project / "waivers.json"
    # FALSE-CLEAN GUARD: before anything else, evict any carried-over waiver
    # whose excused step actually ran this time. A stale waiver must never
    # survive into a run that executed the step it excuses.
    prune_stale(project)
    sanctioned = sanctioned_auto_waivers(project)
    if not sanctioned:
        return 0, []                       # honest MISSING — nothing to write

    def _key(sid: Any):
        return (str(type(sid)), str(sid))
    new_entries = [_to_entry(sanctioned[sid], project)
                   for sid in sorted(sanctioned, key=_key)]

    if wpath.exists() and not force:
        try:
            existing = json.loads(wpath.read_text())
        except (OSError, ValueError):
            return 0, []                   # unreadable/foreign — never clobber
        if not _is_auto_generated(existing):
            return 0, []                   # HUMAN file wins — never touched
        merged = list(existing.get("waived_steps") or [])
        have = {str(e.get("id")) for e in merged if isinstance(e, dict)}
        added = [e for e in new_entries if str(e["id"]) not in have]
        if not added:
            return 0, []
        existing["waived_steps"] = merged + added
        wpath.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n")
        return len(added), [e["id"] for e in added]

    payload = {
        "_schema_version": "1",
        "_comment": _COMMENT,
        "_generator": "waivers_materialize.py",
        "waived_steps": new_entries,
    }
    wpath.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return len(new_entries), [e["id"] for e in new_entries]


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir")
    p.add_argument("--json", default=None, help="write a machine-readable result")
    p.add_argument("--force", action="store_true",
                   help="overwrite/merge even if waivers.json exists (still "
                        "never promotes a human entry)")
    args = p.parse_args(argv)
    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"{_PROGRAM}: not a directory: {project}", file=sys.stderr)
        return 2
    n, ids = materialize(project, force=args.force)
    res = {"program": _PROGRAM, "materialized": n, "step_ids": ids,
           "waivers_json": str(project / "waivers.json") if n else None}
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=2) + "\n")
    if n:
        print(f"{_PROGRAM}: materialized {n} sanctioned auto-waiver(s) "
              f"→ waivers.json (steps {ids})")
    else:
        print(f"{_PROGRAM}: no sanctioned auto-waivers to materialize "
              f"(honest MISSING — nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
