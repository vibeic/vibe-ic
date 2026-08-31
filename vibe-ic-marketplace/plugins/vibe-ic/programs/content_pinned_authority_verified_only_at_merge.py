#!/usr/bin/env python3
"""An authority pin whose only reader runs after the point of repair.

VERDICT CLASS: **ADVISORY** (rc 0 with findings) unless ``--strict``.
And it must stay advisory. A mismatch on a branch that legitimately edits a
pinned path is the EXPECTED state; blocking it would refuse the very change the
manifest exists to record. What is missing is not a refusal, it is a REPORT
that reaches the author instead of the merge.

WHAT IT ASKS THE REPOSITORY
===========================
A tracked manifest records the content hash of a set of protected authority
paths. Editing one of those paths is legitimate and expected — but between the
edit and the re-render the manifest describes no tree that exists, and nothing
on the editing side says so.

Measured: the manifest pins 47 protected paths with a hash in both transition
states. Its readers are the merge-time verification script, the manifest
author, the trusted-selection helper, the census tool and two tests. The
repository-wide hygiene script mentions it exactly ONCE and that occurrence is
a COMMENT, so no pre-merge check compares any pin against the tree.

The verdict is correct and arrives at the wrong time, which is a different
defect from a verdict that is wrong. This program is the missing early reader.

MEASURED A/B AT THE MERGE WITH main a4caccefe (v1.11.69). This is why the
program is advisory rather than blocking, and the numbers are the argument:

    pristine main a4caccefe          11 pinned paths hash to NEITHER state
    this branch merged onto it       12 -- the same 11, plus `_prose_polarity.py`

ELEVEN OF THE TWELVE ARE MAIN'S OWN. `tools/ci/_gate_dispatch.sh`,
`repo_hygiene_gates.sh`, `landing_completion_record.py`, `routed_def_corpus.py`,
`tools/gatekeeper-land.sh`, `_corpus_location.py`,
`ci_harness_timeout_ceiling_check.py`, `hygiene_finding_delta.py`,
`landing_merge_verdict.py`, `repo_hygiene_parallel.py` and
`tests/test_flow_matrix_coverage.py` were all edited on main without the
manifest being re-rendered. Only the twelfth is this branch's.

That is the defect this program exists to report, and it is reporting it about
the trunk rather than about a feature branch: the merge-time verification will
refuse eleven changes that nothing on the producing side ever flagged. A gate
that blocked here would block main, so it warns and names them, and `--strict`
is available to whoever wants the refusal.

WHAT COUNTS AS A MISMATCH
=========================
A transition manifest names two states, `current` and `next`. A working tree
sitting in EITHER is consistent — that is what a transition means. A path is
reported only when its content hashes to NEITHER of the two states it is
pinned in, and the report names the manifest identifier that must be
re-rendered and the tool that renders it.

A pinned path that is ABSENT from the tree is reported separately: a deleted
authority file and an edited one are different obligations.

EXIT
====
  0  advisory run (any findings printed), or strict run with no mismatch
  1  --strict with at least one mismatch
  2  cannot determine — no manifest, unreadable manifest, unreadable path
  3  bad invocation
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082

_MANIFEST_REL = "tools/ci/protected_landing_transition.json"

#: Named, not inferred: the report has to say what to re-run, and a reader who
#: has to go and find that out is a reader who does not.
_RENDERER = "tools/ci/protected_landing_transition.py"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _states(doc: dict) -> Dict[str, Dict[str, str]]:
    """state id -> {path: sha256}."""
    out: Dict[str, Dict[str, str]] = {}
    for key in ("current", "next"):
        block = doc.get(key) or {}
        sid = str(block.get("id") or key)
        out[f"{key} ({sid})"] = {
            f["path"]: f["sha256"] for f in (block.get("files") or [])
            if f.get("path") and f.get("sha256")}
    return out


def scan(root: Path, manifest: Path) -> Tuple[List[dict], Dict[str, int]]:
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    states = _states(doc)
    pinned = sorted({p for s in states.values() for p in s})
    findings: List[dict] = []
    absent = 0
    for rel in pinned:
        f = root / rel
        if not f.is_file():
            absent += 1
            findings.append({"path": rel, "kind": "ABSENT",
                             "matches": [], "actual": None})
            continue
        actual = _sha256(f)
        matched = [name for name, s in states.items() if s.get(rel) == actual]
        if not matched:
            findings.append({"path": rel, "kind": "MISMATCH",
                             "matches": [], "actual": actual})
    return findings, {"pinned_paths": len(pinned),
                      "states": len(states),
                      "absent": absent,
                      "mismatched": sum(1 for f in findings
                                        if f["kind"] == "MISMATCH")}


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="make a mismatch rc 1 (default: report only)")
    ap.add_argument("--json", dest="json_out", default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    try:
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] content_pinned_authority_verified_only_at_"
                  "merge: no repository root. NOT a pass.", file=sys.stderr)
            return 2
        manifest = Path(a.manifest) if a.manifest else root / _MANIFEST_REL
        if not manifest.is_file():
            print(f"[CANNOT DETERMINE] content_pinned_authority_verified_only_"
                  f"at_merge: no manifest at {manifest}. NOT a pass.",
                  file=sys.stderr)
            return 2
        findings, denom = scan(root, manifest)
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] content_pinned_authority_verified_only_at_"
              f"merge: the comparison did not complete ({type(exc).__name__}: "
              f"{exc}). NOT a pass.", file=sys.stderr)
        return 2

    print(f"  manifest:            {manifest.relative_to(root) if manifest.is_relative_to(root) else manifest}")
    print(f"  pinned paths:        {denom['pinned_paths']}")
    print(f"  transition states:   {denom['states']}")
    print(f"  hashing to neither:  {denom['mismatched']}")
    print(f"  absent from tree:    {denom['absent']}")

    if findings:
        print(f"\n[WARN] {len(findings)} pinned authority path(s) do not match "
              f"the manifest:")
        for f in findings:
            if f["kind"] == "ABSENT":
                print(f"   {f['path']}  ABSENT from the tree")
            else:
                print(f"   {f['path']}  hashes to {f['actual'][:12]}, which is "
                      f"neither pinned state")
        print(f"\n  This is the EXPECTED state on a branch that edits an "
              f"authority path.\n  Re-render the manifest with {_RENDERER} "
              f"before landing, or the merge-time\n  verification will refuse "
              f"a change nothing on this side reported.")
        if a.strict:
            return 1
        return 0

    print("[PASS] content_pinned_authority_verified_only_at_merge: every "
          "pinned authority path matches a state the manifest names.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
