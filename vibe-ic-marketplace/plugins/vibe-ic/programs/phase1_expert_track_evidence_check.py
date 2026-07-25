#!/usr/bin/env python3
"""
phase1_expert_track_evidence_check.py — did the Phase-1 EXPERT track actually
run, or is its zero the zero of never having been asked? (#312)

The defect
----------
The doctrine is program-first + AI-backup DUAL-TRACK convergence: two tracks
solve the same problem independently, then every disagreement is converged.
Phase 1 has ONE track.

Verified, not assumed:
  * `ai_deep_review_patches.json` has THREE readers
    (phase1_doc_input_completeness_check, l_doc_structured_field_count_check,
    phase1_input_vs_generated_completeness_check) and ZERO writers. Nothing in
    programs/, skills/ or agents/ produces it.
  * `phase1_doc_one_shot_runner` contains no expert-track call site at all.
  * `ic_expert_backup_pack` — the module that assembles exactly this hand-off,
    and that carries a MEASURED A/B result (folding the DB into the skills
    digest dropped single-shot recovery 38->31; the two as INDEPENDENT authors
    reached 51) — is referenced by nothing but INDEX.md and its own test. It is
    ORPHANED in the sense flow_gate_enforcement_audit (#306) defines.

So `ai_captured_tokens_count: 0` cannot mean anything else. A real report read
`tokens_missing_everywhere: 52, ai_captured_tokens_count: 0` — which looks like
"the AI track performed badly" and actually means "the AI track never ran".

WHY THAT FRAMING IS THE BUG
---------------------------
This is the same failure this campaign keeps finding, in a new place: an EMPTY
result and a CLEAN result are indistinguishable at the verdict.
  #300  CTS built 0 clock nets; setup reported 0 violations; verdict MET
  #306  gates FAILed honestly; nothing blocked; the run completed
  here  the expert track never ran; its capture count is 0; the report reads
        like a track that ran and found nothing

A zero that means "not measured" must never be presented as a zero that means
"measured, nothing there".

What this program does
----------------------
Reports the expert track's EXECUTION STATE, so downstream numbers can be read
correctly:

  NEVER_RAN     no sidecar exists AND no runner call site does either — the
                zero is an artefact of the track not existing
  RAN_EMPTY     a sidecar exists and is well-formed but carries no patches —
                the track ran and genuinely found nothing (a real zero)
  RAN           a sidecar exists with patches
  MALFORMED     a sidecar exists but does not parse / has the wrong shape —
                treated as NOT ran, because unreadable evidence is not evidence

DISCLOSURE-ONLY by default (rc 0). `--require-expert-track` makes NEVER_RAN a
hard FAIL for callers that want the dual-track doctrine enforced rather than
described — deliberately opt-in, because turning it on today would fail every
Phase-1 run in the fleet, and that is an owner's decision (see #306).

chip-AGNOSTIC: sidecar shape and repo structure only.

ENFORCEMENT: advisory — this reports an execution state; making the missing
track fatal is the opt-in flag, not the default.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_SIDECAR_RELS = (
    "phase1/ai_deep_review_patches.json",
    "ai_deep_review_patches.json",
)

# The module that assembles the expert hand-off. Its presence in a runner is
# what would make the second track real.
_HANDOFF_MODULE = "ic_expert_backup_pack"
_PHASE1_RUNNERS = ("phase1_doc_one_shot_runner.py", "phase1_one_shot_runner.py")


def find_sidecar(project: Path) -> Optional[Path]:
    for rel in _SIDECAR_RELS:
        p = project / rel
        if p.is_file():
            return p
    return None


def expert_track_wired(programs_dir: Path) -> bool:
    """Does ANY Phase-1 runner actually invoke the expert hand-off?

    This is the difference between "the track is missing today" and "the track
    exists but produced nothing for this design" — without it, NEVER_RAN could
    not be told apart from a design whose sidecar was simply deleted.
    """
    # Match an IMPORT or CALL, never a bare mention. #306 established this the
    # hard way: `cts_quality_check` appears in a runner COMMENT, and counting
    # that as enforcement would have hidden the entire defect. A comment saying
    # "we should call ic_expert_backup_pack" is precisely the state #312
    # describes — it must read as NOT wired.
    pat = re.compile(
        r"^[ \t]*(?:from[ \t]+" + re.escape(_HANDOFF_MODULE) + r"[ \t]+import"
        r"|import[ \t]+" + re.escape(_HANDOFF_MODULE) + r"\b)"
        r"|\b" + re.escape(_HANDOFF_MODULE) + r"\s*\.\s*\w+\s*\(",
        re.M)
    for r in _PHASE1_RUNNERS:
        p = programs_dir / r
        if not p.is_file():
            continue
        if pat.search(p.read_text(errors="replace")):
            return True
    return False


def assess(project: Path, programs_dir: Path) -> Dict[str, Any]:
    sidecar = find_sidecar(project)
    wired = expert_track_wired(programs_dir)
    if sidecar is None:
        state = "NEVER_RAN"
        detail = ("no expert-track sidecar, and no Phase-1 runner invokes "
                  f"{_HANDOFF_MODULE} — any ai_captured count is 0 because the "
                  "track does not run, NOT because it ran and found nothing"
                  ) if not wired else (
                  "no expert-track sidecar for this project (the track is "
                  "wired, so this design simply has no patches recorded)")
        return {"state": state, "wired": wired, "sidecar": None,
                "patch_count": 0, "layers": [], "detail": detail}
    try:
        blob = json.loads(sidecar.read_text(errors="replace"))
    except (OSError, ValueError) as e:
        return {"state": "MALFORMED", "wired": wired, "sidecar": str(sidecar),
                "patch_count": 0, "layers": [],
                "detail": f"sidecar does not parse ({e.__class__.__name__}); "
                          f"unreadable evidence is not evidence"}
    patches = (blob or {}).get("patches")
    if not isinstance(patches, dict):
        return {"state": "MALFORMED", "wired": wired, "sidecar": str(sidecar),
                "patch_count": 0, "layers": [],
                "detail": "sidecar has no `patches` mapping"}
    layers = sorted(k for k, v in patches.items() if isinstance(v, list) and v)
    n = sum(len(v) for v in patches.values() if isinstance(v, list))
    return {
        "state": "RAN" if n else "RAN_EMPTY",
        "wired": wired, "sidecar": str(sidecar),
        "patch_count": n, "layers": layers,
        "detail": (f"expert track produced {n} patch(es) across {len(layers)} "
                   f"layer(s)") if n else
                  ("expert track ran and recorded NO patches — this is a real "
                   "zero, distinct from NEVER_RAN"),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Report whether the Phase-1 expert track actually ran.")
    ap.add_argument("project_dir")
    ap.add_argument("--programs", help="programs dir (default: this one)")
    ap.add_argument("--require-expert-track", action="store_true",
                    help="make NEVER_RAN / MALFORMED a hard FAIL (opt-in: "
                         "enabling it today fails every Phase-1 run, which is "
                         "an owner decision — see #306)")
    ap.add_argument("--json", help="write the report here")
    a = ap.parse_args(argv)
    project = Path(a.project_dir)
    if not project.is_dir():
        print(f"IO_ERROR: no such project dir: {project}", file=sys.stderr)
        return 2
    programs = Path(a.programs) if a.programs else Path(__file__).resolve().parent
    rep = assess(project, programs)
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    print("=== Phase-1 expert-track evidence ===")
    print(f"state : {rep['state']}")
    print(f"wired : {rep['wired']}")
    print(rep["detail"])
    if rep["state"] == "NEVER_RAN" and not rep["wired"]:
        print("READ ANY ai_captured / expert-derived COUNT AS 'NOT MEASURED', "
              "NOT AS ZERO FINDINGS.")
    if a.require_expert_track and rep["state"] in ("NEVER_RAN", "MALFORMED"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
