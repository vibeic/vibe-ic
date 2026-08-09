#!/usr/bin/env python3
"""
foundry_signoff_plan_check.py — v0.113 (BACKLOG-v10 P1.2).

Enforces that any project with waivers also has a `foundry_signoff_plan.yaml`
documenting WHO will close each waiver, WHEN, with WHAT tool, and what
proof artefact closes it. Without this, "deferred to foundry tapeout review"
becomes a magic incantation with no accountability.

Schema (chip-AGNOSTIC, applies to any custom-PDK project):

```yaml
foundry_signoff_plan:
  foundry: <foundry>          # or TSMC, GF, IBM, etc.
  contact: signoff@example.com
  expected_review_date: 2026-12-01
  closures:
    - waiver_id: 20            # MUST match a waivers.json id
      tool: Cadence Quantus QRC
      input: gds/<top>.gds
      proof_artefact: extracted/parasitic.spef
      acceptance_criterion: "WNS @ post-route SS corner ≥ 0 ns with extracted SPEF"
    - waiver_id: 22
      ...
```

Gate logic:
  - If waivers.json has 0 entries → SKIP (no plan needed)
  - If waivers.json has N entries:
      - foundry_signoff_plan.yaml MUST exist
      - top-level fields foundry / contact / expected_review_date required
      - every waiver_id MUST appear as a closure entry
      - every closure entry MUST have tool / input / proof_artefact /
        acceptance_criterion non-empty
      - cascaded children (cascade_source != null) inherit parent's
        closure plan; explicit child entry NOT required
  - PASS only if every root waiver has a complete closure entry.

WHY THIS GATE COULD NOT SAY "FAIL" ON MOST PROJECTS
===================================================
A waivers.json carries its entry list under ONE OF TWO documented top-level
keys — `waived_steps` (written by `waivers_materialize`) and `waivers`
(written by `phase3_one_shot_runner._autogen_waivers_json`). See
`_waiver_entries` for the one reader and the reason it exists (#519).

This program read `waived_steps` ONLY, and then took an early return the
moment that list came back empty:

    [PASS] foundry_signoff_plan_check (skip — no waivers)

That line is a STATEMENT ABOUT THE PROJECT ("this project waives nothing"),
and on every runner-produced project it was false. Measured over the tracked
corpus at the time of this fix: 6 of 9 waiver files carry their entries under
`waivers`, and for all 6 this gate reported "no waivers in project — no
signoff plan required" with `pass: true`, no matter what — the PLAN_MISSING,
PLAN_FIELD_MISSING, CLOSURE_* and WAIVER_NOT_PLANNED verdicts were all
STRUCTURALLY UNREACHABLE for them, because the only branch that can construct
those findings sits behind a waiver list the reader could not see. Whether a
project had a closure plan made no difference to the verdict. The gate's own
purpose — "waivers without an accountable closure plan are refused" — was
decided by which producer wrote the file.

Two smaller instances of the same shape, fixed here as well:

  * An UNPARSEABLE waivers.json appended a `WAIVERS_PARSE` ERROR finding and
    then fell into the very same early return, which hard-codes
    `"findings": []` and `"pass": True`. That finding could never reach the
    verdict; a corrupt waiver ledger printed the skip-PASS line.
  * A top-level key PRESENT but holding a non-list (`"waivers": {...}`) reads
    as "no entries" in any fail-soft reader. A ledger this gate cannot read is
    not an empty ledger, and is now reported as such.

An empty ledger is still a legitimate SKIP-PASS — but the summary now
publishes `waiver_file_present`, `waiver_entry_count` and `waiver_keys_read`
so "0 problems found" is distinguishable from "0 entries examined".

WHICH WAIVER A CLOSURE ENTRY CLOSES — MATCHED AS WRITTEN
=========================================================
The two dialects name their step differently: `waived_steps` entries carry a
canonical `id` (e.g. 31); `waivers` entries carry a runner-local role name
(e.g. `step: "lvs"`). A `closures[].waiver_id` may use EITHER spelling of the
waiver's own identity, compared case-insensitively and across the int/str
divide (`20` and `"20"` are one waiver, not two — a hand-authored YAML plan
and a machine-written JSON ledger disagree on scalar type routinely, and that
is a spelling difference, not a missing plan).

Role names are NEVER resolved to canonical ids for this comparison, even
though `_waiver_entries.STEP_NAME_TO_ID` could. That map is MANY-TO-ONE
(`drc`, `lvs` and `erc` all resolve to 31), so resolving would let ONE closure
entry silently discharge THREE separately-waived steps — inventing coverage
the plan never wrote down, which is the failure mode this gate exists to stop.

Usage:
  python3 foundry_signoff_plan_check.py <project_dir> [--json [PATH]]

Exit codes: 0 PASS, 1 FAIL, 2 IO error.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _waiver_entries as _we  # noqa: E402


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


REQUIRED_TOP = ["foundry", "contact", "expected_review_date"]
REQUIRED_PER_CLOSURE = ["waiver_id", "tool", "input", "proof_artefact", "acceptance_criterion"]


def _load_yaml_or_json(path: Path) -> Dict[str, Any]:
    """Best-effort: try YAML first via PyYAML if available, else JSON."""
    text = path.read_text()
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        try:
            return json.loads(text)
        except Exception as exc:
            raise RuntimeError(f"PyYAML unavailable and {path} is not JSON: {exc}")


def _norm(value: Any) -> str:
    """The comparison form of a waiver identifier AS WRITTEN. Folds the
    int/str divide and case only — never resolves a role name to a canonical
    step id (see the module docstring: that map is many-to-one)."""
    return str(value).strip().lower()


def _identity(entry: Dict[str, Any]) -> List[Any]:
    """Every spelling of WHICH waiver this entry is, in the order a message
    should prefer them. `waived_steps` entries say `id`; `waivers` entries say
    `step`. An entry may legitimately carry both; an entry carrying neither has
    no identity at all, which is reported rather than skipped."""
    out: List[Any] = []
    wid = entry.get("id")
    if wid is not None:
        out.append(wid)
    step = entry.get("step")
    if isinstance(step, str) and step.strip():
        out.append(step.strip())
    return out


def _root_waiver_ids(
        waivers_doc: Any) -> List[Tuple[Any, List[Any]]]:
    """Root waivers only — cascade children inherit their parent's closure.

    Reads BOTH canonical top-level keys through the ONE shared reader, so a
    waivers.json written by either producer is visible here (#519). Returns
    `(label, [identifier, ...])` per root waiver: the label names it in a
    finding, the identifier list is what a `closures[].waiver_id` may match.
    """
    entries = _we.dict_entries(waivers_doc)
    cascade_targets: set = set()
    for entry in entries:
        for child in entry.get("cascades_to", []) or []:
            cascade_targets.add(_norm(child))
    out: List[Tuple[Any, List[Any]]] = []
    for index, entry in enumerate(entries):
        ids = _identity(entry)
        if any(_norm(i) in cascade_targets for i in ids):
            continue
        if entry.get("cascade_source") is not None:
            continue
        label = ids[0] if ids else f"<unidentified waiver #{index}>"
        out.append((label, ids))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(
        "Verify foundry_signoff_plan.yaml provides closure plan for every waiver."
    ))
    ap.add_argument("project_dir")
    ap.add_argument("--json", nargs="?", const="-", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    waivers_path = project / "waivers.json"
    plan_path_yaml = project / "foundry_signoff_plan.yaml"
    plan_path_yml = project / "foundry_signoff_plan.yml"
    plan_path_json = project / "foundry_signoff_plan.json"

    findings: List[Finding] = []
    waivers: List[Tuple[Any, List[Any]]] = []
    waivers_doc: Any = None
    entry_counts: Dict[str, int] = {}
    # "The ledger could not be read" is a DIFFERENT state from "the ledger is
    # empty", and only the second one is a skip. Conflating them is what made
    # a corrupt waivers.json print the skip-PASS line while its own ERROR
    # finding was dropped on the floor by the early return below.
    ledger_unreadable = False
    if waivers_path.exists():
        try:
            waivers_doc = json.loads(waivers_path.read_text())
        except Exception as exc:
            ledger_unreadable = True
            findings.append(Finding("ERROR", "WAIVERS_PARSE",
                f"cannot parse {waivers_path}: {exc}. A waiver ledger this "
                f"gate cannot read is not an empty ledger: the closure plan "
                f"it would demand cannot be verified either way."))
        else:
            for key in _we.malformed_keys(waivers_doc):
                ledger_unreadable = True
                findings.append(Finding("ERROR", "WAIVERS_SCHEMA",
                    f"{waivers_path}: top-level {key!r} is present but does "
                    f"not hold a list, so its entries cannot be read. A "
                    f"waiver ledger this gate cannot read is not an empty "
                    f"ledger."))
            entry_counts = {k: len(v) for k, v
                            in _we.entries_by_key(waivers_doc).items()}
            waivers = _root_waiver_ids(waivers_doc)

    if not waivers and not ledger_unreadable:
        # The ledger was READ and holds no root waiver → no plan needed.
        # The counts are published so a reader can tell "0 problems found"
        # from "0 entries examined" (#515 shape).
        result = {
            "program": "foundry_signoff_plan_check",
            "version": "1.0.0",
            "project": str(project),
            "summary": {
                "skip": True,
                "reason": "no waivers in project — no signoff plan required",
                "pass": True,
                "waiver_file_present": waivers_path.exists(),
                "waiver_entry_count": sum(entry_counts.values()),
                "waiver_entries_by_key": entry_counts,
                "waiver_keys_read": list(_we.WAIVER_LIST_KEYS),
            },
            "findings": [],
        }
        if args.json is None:
            print("[PASS] foundry_signoff_plan_check (skip — no waivers)")
        elif args.json == "-":
            print(json.dumps(result, indent=2))
        else:
            Path(args.json).write_text(json.dumps(result, indent=2))
            print(f"json: {args.json}")
        return 0

    # Find plan
    plan_path = None
    for cand in [plan_path_yaml, plan_path_yml, plan_path_json]:
        if cand.exists():
            plan_path = cand
            break

    if not waivers:
        # Reached only when the ledger was UNREADABLE. There is no root waiver
        # to demand a plan for, so PLAN_MISSING would be a false statement;
        # the ledger finding already carries the FAIL.
        pass
    elif plan_path is None:
        findings.append(Finding(
            severity="ERROR",
            category="PLAN_MISSING",
            message=(
                f"Project has {len(waivers)} root waiver(s) but no "
                f"foundry_signoff_plan.{{yaml,yml,json}} exists. Production "
                f"tapeout review needs a documented closure plan: who runs "
                f"each waiver on the foundry deck, with what tool, producing "
                f"what proof. Without this, 'deferred to foundry tapeout' is "
                f"untrackable."
            ),
            details=(
                "Schema: foundry_signoff_plan: { foundry, contact, "
                "expected_review_date, closures: [{waiver_id, tool, input, "
                "proof_artefact, acceptance_criterion}, ...] }. See "
                "vibe-ic/programs/foundry_signoff_plan_check.py docstring."
            ),
        ))
    else:
        try:
            doc = _load_yaml_or_json(plan_path)
        except Exception as exc:
            findings.append(Finding("ERROR", "PLAN_PARSE",
                f"cannot parse {plan_path}: {exc}"))
            doc = None

        if doc is not None:
            plan = doc.get("foundry_signoff_plan") or doc
            for k in REQUIRED_TOP:
                if not plan.get(k):
                    findings.append(Finding("ERROR", "PLAN_FIELD_MISSING",
                        f"foundry_signoff_plan.{k} is required"))
            closures = plan.get("closures", []) or []
            covered = set()
            for i, c in enumerate(closures):
                if not isinstance(c, dict):
                    findings.append(Finding("ERROR", "CLOSURE_TYPE",
                        f"closures[{i}] must be a mapping"))
                    continue
                wid = c.get("waiver_id")
                if wid is None:
                    findings.append(Finding("ERROR", "CLOSURE_NO_WID",
                        f"closures[{i}] missing waiver_id"))
                    continue
                covered.add(_norm(wid))
                for field in REQUIRED_PER_CLOSURE:
                    if not c.get(field):
                        findings.append(Finding("ERROR", "CLOSURE_FIELD_MISSING",
                            f"closures[{i}] (waiver_id={wid}) missing {field!r}"))

            for label, ids in waivers:
                if any(_norm(i) in covered for i in ids):
                    continue
                spellings = " / ".join(repr(i) for i in ids) or "<none>"
                findings.append(Finding(
                    severity="ERROR",
                    category="WAIVER_NOT_PLANNED",
                    message=(
                        f"Root waiver id={label!r} has no closure entry "
                        f"in foundry_signoff_plan. Add a closures: entry "
                        f"with tool / input / proof_artefact / "
                        f"acceptance_criterion."
                    ),
                    details=(
                        f"A closures[].waiver_id matching any of {spellings} "
                        f"closes this waiver."
                    ),
                ))

    pass_flag = not any(f.severity == "ERROR" for f in findings)
    result = {
        "program": "foundry_signoff_plan_check",
        "version": "1.0.0",
        "project": str(project),
        "summary": {
            "waiver_root_count": len(waivers),
            "waiver_root_ids": [label for label, _ids in waivers],
            "waiver_entry_count": sum(entry_counts.values()),
            "waiver_entries_by_key": entry_counts,
            "waiver_keys_read": list(_we.WAIVER_LIST_KEYS),
            "waiver_ledger_readable": not ledger_unreadable,
            "plan_path": str(plan_path) if plan_path else None,
            "pass": pass_flag,
        },
        "findings": [asdict(f) for f in findings],
    }

    if args.json is None:
        verdict = "PASS" if pass_flag else "FAIL"
        print(f"[{verdict}] foundry_signoff_plan_check")
        print(f"  waivers (root): {len(waivers)}")
        print(f"  plan: {plan_path}")
        for f in findings:
            print(f"  [{f.severity}] {f.category}: {f.message}")
    elif args.json == "-":
        print(json.dumps(result, indent=2))
    else:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"json: {args.json}")

    return 0 if pass_flag else 1


if __name__ == "__main__":
    sys.exit(main())
