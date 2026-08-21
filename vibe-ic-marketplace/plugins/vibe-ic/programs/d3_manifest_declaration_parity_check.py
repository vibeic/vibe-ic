#!/usr/bin/env python3
"""Every declared `required_outputs` path must be covered by the d3 manifest.

BLOCKING. A violation exits 1 and the flow must not proceed.

WHY THIS GATE EXISTS, measured 2026-08-13 (vibe-ic batch R1)
===========================================================
`flow/phase1_phase2_phase3.yaml` declares what each step must produce.
`programs/tests/fixtures/matrix_d3_output_manifest.json` records, per declared
path, where a real run produced it. The manifest's own header states the
contract: *"For every required_outputs entry of every flow step"*.

Those two files must move TOGETHER. When a change adds a path to a step's
`required_outputs` and does not re-measure the manifest, dimension 3 reports the
new path as UNEVIDENCED and the step's cell goes RED — and that is not where the
damage stops:

    `matrix_mutation_ledger.py` declares `witness="D1"` for the
    `D3-UNDECLARED-ARTEFACT` mutation, and LOCK 2's first requirement is that the
    UNMUTATED run PASSES — "an already-red cell proves nothing". Reddening D1
    therefore does not merely add a red; it removes the proof that an entire
    class of undeclared-artefact defects is still caught. A gate stops being
    testable, quietly, from a two-line yaml edit.

MEASURED, four open PRs that all move the same artefact into step D1:

    main (24ff9530)   134 declared, 0 uncovered   d3/D1 GREEN
    #1235             134 declared, 0 uncovered   d3/D1 GREEN   (yaml AND manifest)
    #1175             134 declared, 0 uncovered   d3/D1 GREEN
    #1131             uncovered=2                 d3/D1 RED
    #1170             uncovered=2                 d3/D1 RED

The two this gate fires on are exactly the two that redden the witness, and it
names the offending paths rather than reporting a count.

WHY DECLARATION PARITY AND NOT PRODUCTION
=========================================
Dimension 3 asks whether the artefact was PRODUCED, which needs run roots and is
slow, host-dependent, and currently red for unrelated reasons (vibe-ic#1266 —
manifest entries citing run trees this repository does not carry). This gate asks
only whether the manifest has an ENTRY for each declared path. That question is
answerable from two files, needs no run tree, cannot be host-dependent, and
isolates the co-change defect from the evidence-availability defect they would
otherwise be confused with.

So a PASS here is NOT a claim that the artefacts exist. It is a claim that the
declaration and the pin describe the same set of paths — nothing more. The
distinction is the whole point: this gate and d3 fail for different reasons and
must not be read as substitutes.

WHY A TREE INVARIANT AND NOT A DIFF
===================================
A diff-based version would need a base ref and would pass whenever the base is
chosen badly — a rebase, a stacked branch, or a batch merge silently changes the
answer. The property is stated over the tree as it stands, so there is no base to
get wrong and a batch cannot merge its way past it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

RC_OK, RC_FAIL, RC_REFUSE = 0, 1, 2

_FLOW_REL = "flow/phase1_phase2_phase3.yaml"
_MANIFEST_REL = "programs/tests/fixtures/matrix_d3_output_manifest.json"


def _plugin_root(start: Path) -> Path | None:
    """Nearest ancestor (inclusive) that carries both files."""
    for cand in [start, *start.parents]:
        if (cand / _FLOW_REL).is_file() and (cand / _MANIFEST_REL).is_file():
            return cand
    return None


def _flow_steps(flow) -> list:
    steps = flow.get("steps") if isinstance(flow, dict) else flow
    return steps if isinstance(steps, list) else []


class DuplicateManifestKey(Exception):
    """A step id recorded twice in the manifest — the copies may disagree."""


def _load_manifest_no_duplicate_keys(path: Path):
    """Parse the manifest and REFUSE a duplicated key.

    MEASURED ON main, 2026-08-20
    ============================
    `json.loads` keeps the LAST of two same-named keys and says nothing. The
    manifest carried each of `15.5ic`, `26.5ic`, `37.5ip`, `37.5ic` TWICE, and
    the copies CONTRADICTED each other::

        copy 1   "verdict": "ENFORCED"
        copy 2   "verdict": "NA_DORMANT_CONDITION"

    Every program read the second. Every human reading top-down read the first.
    A reviewer and a gate looking at the same fixture would have reported
    different states of the same cell and neither would have been lying — which
    is worse than a wrong value, because there is no disagreement to notice.

    The cause is mechanical: a step was ADDED to a fixture that already carried
    it instead of the existing record being edited, and nothing in the toolchain
    can see the difference after `json.loads` has run. So the check has to
    happen DURING the parse, which is what `object_pairs_hook` is for.

    Repo-wide sweep at the time of the fix: 84 tracked JSON files, exactly this
    one affected, exactly those four keys.
    """
    dups: List[str] = []

    def hook(pairs):
        seen = set()
        for key, _ in pairs:
            if key in seen:
                dups.append(key)
            seen.add(key)
        return dict(pairs)

    doc = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=hook)
    if dups:
        raise DuplicateManifestKey(
            f"{path.name} records {len(set(dups))} key(s) more than once: "
            f"{', '.join(sorted(set(dups)))}. json.loads silently keeps the "
            f"LAST copy, so a reader and a reviewer can see different values "
            f"for the same step. Merge each pair into ONE record.")
    return doc


def audit(root: Path) -> Tuple[int, List[Tuple[str, str]], Dict[str, int]]:
    """Return (declared_count, uncovered, per_step_declared).

    `uncovered` is a list of (step_id, path) that the flow declares and the
    manifest does not carry an entry for.
    """
    import yaml  # deferred: keeps the import cost off callers that only --help

    manifest = _load_manifest_no_duplicate_keys(root / _MANIFEST_REL)
    flow = yaml.safe_load((root / _FLOW_REL).read_text(encoding="utf-8"))

    m_steps = manifest.get("steps") or {}
    declared = 0
    uncovered: List[Tuple[str, str]] = []
    per_step: Dict[str, int] = {}

    for step in _flow_steps(flow):
        if not isinstance(step, dict):
            continue
        sid = str(step.get("id"))
        paths = step.get("required_outputs") or []
        if not paths:
            continue
        per_step[sid] = len(paths)
        known = set(((m_steps.get(sid) or {}).get("entries") or {}).keys())
        for path in paths:
            declared += 1
            if path not in known:
                uncovered.append((sid, str(path)))

    return declared, uncovered, per_step


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="declared required_outputs vs the d3 evidence manifest (BLOCKING)")
    ap.add_argument("root", nargs="?", default=".",
                    help="plugin root, or any path inside it")
    a = ap.parse_args(argv)

    start = Path(a.root).resolve()
    root = _plugin_root(start)
    if root is None:
        print(f"REFUSE: no plugin root at or above {start} carries both "
              f"{_FLOW_REL} and {_MANIFEST_REL}. This gate cannot run, which is "
              f"NOT a pass.", file=sys.stderr)
        return RC_REFUSE

    try:
        declared, uncovered, per_step = audit(root)
    except Exception as exc:                       # noqa: BLE001 — report, never pass
        print(f"REFUSE: could not read the declaration/manifest pair: "
              f"{type(exc).__name__}: {exc}. NOT a pass.", file=sys.stderr)
        return RC_REFUSE

    # Zero-denominator refusal: a flow that declares nothing has not been
    # checked, and printing PASS over it is the vacuous shape this repo refuses.
    if declared == 0:
        print("REFUSE: the flow declares ZERO required_outputs across every "
              "step, so this gate examined nothing. That is not a clean tree, "
              "it is an unreadable one. NOT a pass.", file=sys.stderr)
        return RC_REFUSE

    print(f"d3 declaration parity: {declared} declared required_outputs "
          f"path(s) across {len(per_step)} step(s) with outputs; "
          f"{len(uncovered)} not covered by the manifest")

    if not uncovered:
        return RC_OK

    print("\nFAIL — the flow declares paths the d3 evidence manifest has never "
          "measured. Re-measure the manifest in the SAME change that moves the "
          "declaration:", file=sys.stderr)
    for sid, path in uncovered:
        print(f"  step {sid}: {path}", file=sys.stderr)
    print(f"\n{_FLOW_REL} and {_MANIFEST_REL} must move together. Leaving them "
          f"apart reddens the step's dimension-3 cell, and if that step is a "
          f"mutation witness (see matrix_mutation_ledger.py) it also disables "
          f"the proof that the mutation is still caught — LOCK 2 requires the "
          f"unmutated cell to PASS.", file=sys.stderr)
    return RC_FAIL


if __name__ == "__main__":
    sys.exit(main())
