#!/usr/bin/env python3
r"""run_entry_manifest.py — record WHICH STEP a run entered the flow at.

WHY A RUN NEEDS TO SAY THIS OUT LOUD
====================================
Not every task starts at the beginning. A debug task arrives with RTL that is
already written and already wrong; pushing it through spec-extraction to
re-derive documents it was never given is not a flow, it is ceremony. The
owner's directive is exactly that: *"我走任何的 benchmark 應該都是要走正常路徑嘛,
只是說你要知道我正常路徑是從哪一個接口進來。比如說我是 debug, 我 debug 就不是從
phase 1 進來嘛。"*

But a run that skips the front of the flow and says nothing produces a report
that is **indistinguishable from a Phase 1 that ran and failed** — the upstream
steps come back MISSING either way. Measured on a tree holding only
`phase2/stage1/sim/`: `D1 -> MISSING`, `1 -> MISSING`, overall exit 1, with no
way for a reader to tell "never attempted, by design" from "attempted, broke".

This manifest is that missing sentence. It is written BEFORE the run dispatches
anything, so it is a declaration of intent, not a post-hoc excuse.

THE LAUNDERING RISK, AND THE TWO CONDITIONS THAT CONTAIN IT
===========================================================
The manifest is written by the run that will be judged against it. Left
unconstrained, `--entry-step` becomes a switch that turns MISSING into PASS —
the run grading its own scope. So a step is only ever `OUT-OF-SCOPE-BY-ENTRY`
when BOTH hold:

  1. it is strictly UPSTREAM of the declared entry, and
  2. every one of its `required_outputs` that an in-scope downstream step
     declares as a `required_input` is **present on disk**.

Condition 2 is the anti-laundering rule, and it is the load-bearing one: you may
call D1 out-of-scope only if the L10/L12 that step 4 actually reads exist. The
artefacts still have to BE there — the claim is only that this run did not
produce them. A hard sign-off output (DRC/LVS/ERC/STA) can never be excused this
way, whatever the manifest says.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
=========================================
It does not decide whether the entry is REACHABLE — that is
`step_preflight.entry_admission`, which reads the declared inputs. This module
records what was declared and validates the record's own shape. Two jobs, two
programs, so a bug in one cannot silently excuse the other.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

SCHEMA = 1
MANIFEST_REL = "reports/run_entry.json"

# Outputs that no entry declaration may ever excuse. A sign-off artefact is the
# evidence the chip is manufacturable; "we started late" is not a reason to have
# none. Mirrors flow_compliance_check._is_hard_signoff_output.
# Bounded on BOTH sides, because the short tokens here are substrings of
# ordinary words. Unbounded, `sta` matched `L8_RTL_CONSTANTS.json`
# (CON-STA-NTS) and the guard refused to excuse a Phase-1 constants document as
# though it were timing sign-off — a false positive that made the whole
# mechanism silently never fire. `erc`, `drc` and `lvs` are equally exposed.
_HARD_SIGNOFF = re.compile(
    r"(?<![A-Za-z])(drc|lvs|erc|antenna|density|ir_drop|em_check|sta|signoff)"
    r"(?![A-Za-z])", re.I)


def manifest_path(project: Path) -> Path:
    return Path(project) / MANIFEST_REL


def _flow_yaml(plugin_root: Optional[Path] = None) -> Path:
    root = Path(plugin_root) if plugin_root else Path(__file__).resolve().parents[1]
    return root / "flow" / "phase1_phase2_phase3.yaml"


def flow_step_ids(path: Optional[Path] = None) -> List[str]:
    """Declared STEP ids, in flow order — from the `steps:` block only.

    The YAML declares two id-bearing blocks: `stages:` (8 entities: stage1,
    stage_analog, ...) and `steps:`. A bare `- id:` regex over the file returns
    all 76 and puts the eight STAGES at the head of every "upstream" list, so
    `upstream_of("D1")` came back naming stage_phase1 through
    stage5_manufacturing — none of which is a step, let alone one upstream of
    D1. Scope the scan to the `steps:` block so a stage can never be excused as
    an un-run step.
    """
    try:
        text = (Path(path) if path else _flow_yaml()).read_text(errors="replace")
    except OSError:
        return []
    m = re.search(r"^steps:\s*$", text, re.M)
    if not m:
        return []
    return re.findall(r"^\s*-\s*id:\s*([\w.\-]+)\s*$", text[m.end():], re.M)


def upstream_of(entry_step: str, path: Optional[Path] = None) -> List[str]:
    """Steps declared BEFORE `entry_step`, in flow order.

    Declaration order, not the blocks_on closure: the closure is incomplete —
    several steps declare no blocks_on at all (2, 4, 9 among them) — so using it
    would silently call an unordered step "not upstream" and excuse it. Order is
    the weaker claim and the honest one.
    """
    ids = flow_step_ids(path)
    if entry_step not in ids:
        return []
    return ids[:ids.index(entry_step)]


def build(project: Path, entry_step: str, runner: str, site: Optional[str],
          argv: Sequence[str], timestamp: str,
          flow_path: Optional[Path] = None) -> Dict[str, Any]:
    """The manifest object. `timestamp` is passed IN — this module never reads
    the clock, so the same inputs always produce the same record."""
    return {
        "schema": SCHEMA,
        "entry_step": str(entry_step),
        "runner": runner,
        "site": site,
        "argv": list(argv),
        "timestamp": timestamp,
        "upstream_steps": [
            {"id": s, "disposition": "not-run-in-this-run-root"}
            for s in upstream_of(entry_step, flow_path)
        ],
    }


def write(project: Path, manifest: Dict[str, Any]) -> Path:
    p = manifest_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, indent=2) + "\n")
    return p


def read(project: Path) -> Optional[Dict[str, Any]]:
    p = manifest_path(project)
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return d if isinstance(d, dict) else None


def validate(manifest: Optional[Dict[str, Any]],
             flow_path: Optional[Path] = None) -> List[str]:
    """Problems with the record's own shape. Empty list = sound."""
    if manifest is None:
        return ["no manifest"]
    bad: List[str] = []
    if manifest.get("schema") != SCHEMA:
        bad.append(f"schema is {manifest.get('schema')!r}, expected {SCHEMA}")
    entry = manifest.get("entry_step")
    ids = flow_step_ids(flow_path)
    if not ids:
        bad.append("flow YAML unreadable — the manifest cannot be checked")
    elif str(entry) not in ids:
        bad.append(f"entry_step {entry!r} is not a step in the flow")
    if not manifest.get("runner"):
        bad.append("runner is unset — a manifest must say who wrote it")
    ups = manifest.get("upstream_steps")
    if not isinstance(ups, list):
        bad.append("upstream_steps is not a list")
    else:
        declared = {str(u.get("id")) for u in ups if isinstance(u, dict)}
        expected = set(upstream_of(str(entry), flow_path)) if ids else set()
        extra = declared - expected
        if extra:
            bad.append(
                "upstream_steps names step(s) that are NOT upstream of "
                f"{entry!r}: {sorted(extra)} — a manifest may not widen its "
                "own scope")
    return bad


def excusable(manifest: Optional[Dict[str, Any]], step_id: str,
              required_outputs: Sequence[str],
              consumed_by_in_scope: Sequence[str],
              project: Path) -> Dict[str, Any]:
    """May `step_id` be OUT-OF-SCOPE-BY-ENTRY? Returns the verdict AND why.

    `consumed_by_in_scope` are this step's outputs that some in-scope
    downstream step declares it reads. Every one must be present on disk —
    that is condition 2, the anti-laundering rule.
    """
    if manifest is None:
        return {"excusable": False, "reason": "no run-entry manifest"}
    if validate(manifest):
        return {"excusable": False, "reason": "manifest fails validation"}
    ups = {str(u.get("id")) for u in (manifest.get("upstream_steps") or [])
           if isinstance(u, dict)}
    if str(step_id) not in ups:
        return {"excusable": False,
                "reason": f"{step_id} is not declared upstream of "
                          f"{manifest.get('entry_step')!r}"}
    hard = [o for o in required_outputs if _HARD_SIGNOFF.search(str(o))]
    if hard:
        return {"excusable": False,
                "reason": "declares hard sign-off output(s) which no entry "
                          f"declaration may excuse: {hard}"}
    missing = [o for o in consumed_by_in_scope
               if not _any_match(Path(project), str(o))]
    if missing:
        return {"excusable": False,
                "reason": "an in-scope step reads these, and they are ABSENT: "
                          f"{missing}"}
    return {"excusable": True,
            "reason": f"upstream of declared entry "
                      f"{manifest.get('entry_step')!r}; every output an "
                      f"in-scope step reads is present"}


def _any_match(project: Path, spec: str) -> bool:
    """Does any file satisfy this required_output spec? Handles the flow's
    ``A OR B`` alternation and glob patterns."""
    for alt in re.split(r"\s+OR\s+", spec):
        alt = alt.strip()
        if not alt:
            continue
        if any(ch in alt for ch in "*?["):
            if any(project.glob(alt)):
                return True
        elif (project / alt).exists():
            return True
    return False


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Write or validate a run's entry-step manifest.")
    ap.add_argument("project")
    ap.add_argument("--entry-step", default=None)
    ap.add_argument("--runner", default=None)
    ap.add_argument("--site", default=None)
    ap.add_argument("--timestamp", default=None,
                    help="passed in, never read from the clock")
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args(argv)
    proj = Path(a.project)

    if a.validate:
        problems = validate(read(proj))
        for p in problems:
            print(f"FAIL: {p}", file=sys.stderr)
        if not problems:
            m = read(proj)
            print(f"PASS: entry_step={m.get('entry_step')!r} "
                  f"upstream={len(m.get('upstream_steps') or [])} step(s)")
        return 1 if problems else 0

    if not (a.entry_step and a.runner and a.timestamp):
        print("ERROR: --entry-step, --runner and --timestamp are required",
              file=sys.stderr)
        return 2
    m = build(proj, a.entry_step, a.runner, a.site, argv or [], a.timestamp)
    problems = validate(m)
    if problems:
        for p in problems:
            print(f"FAIL: {p}", file=sys.stderr)
        return 1
    print(f"wrote {write(proj, m)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
