#!/usr/bin/env python3
"""A commit's protected manifest must describe the tree that commit ships.

WHY. A landing carries `tools/ci/protected_landing_transition.json`. Nothing
checks that the manifest it carries was rendered against the tree it carries,
so a branch can ship a manifest from an earlier main -- naming states that tree
has never been in -- and no gate says a word. `tools/gatekeeper-land.sh`
references the transition validator ZERO times, and the hygiene set's single
reference is a comment.

MEASURED 2026-08-22 on `land/two-assembled` (batch 72, 97 branches): it shipped
`current = reauthorised-at-81cd5321b`, rendered two mains earlier, while its own
tree matched neither of its own states -- 16 paths drifted from `current`, 12
from `next`. Four protected paths the batch moves were unauthorised by the
manifest it carried. The batch could not produce a receipt in any arrangement.

WHAT THIS REFUSES, and what it deliberately does NOT. It answers one question:
does `_match_state` recognise this commit's OWN protected tuple under this
commit's OWN manifest? That is the question a stale manifest fails and a correct
one passes, whether the commit is a PREPARE, an ACTIVATE or neither.

It does NOT decide whether a transition is REQUIRED -- a commit that moves no
protected path needs none, and this check passes it. It is not a replacement for
`protected_landing_transition.py`; it is the question nobody was asking.

rc 0 the manifest describes the tree
rc 1 it does not, and the drifted paths are named
rc 2 could not look (no manifest, unreadable, not a git tree) -- NAMING what it
     could not read, never a finding about the tree
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

MANIFEST_REL = "tools/ci/protected_landing_transition.json"


def _validator(repo: Path):
    src = repo / "tools" / "ci" / "protected_landing_transition.py"
    if not src.is_file():
        raise FileNotFoundError(src)
    spec = importlib.util.spec_from_file_location("_plt", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check(repo: Path, ref: str) -> tuple[int, str]:
    try:
        m = _validator(repo)
    except Exception as exc:
        return 2, (f"UNDETERMINED: cannot load the transition validator at "
                   f"{repo}/tools/ci/protected_landing_transition.py: {exc}")

    p = subprocess.run(["git", "-C", str(repo), "rev-parse", f"{ref}^{{commit}}"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return 2, f"UNDETERMINED: {ref!r} does not name a commit in {repo}"
    commit = p.stdout.strip()

    raw = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{MANIFEST_REL}"],
                         capture_output=True, text=True)
    if raw.returncode != 0:
        return 2, (f"UNDETERMINED: {commit[:12]} carries no {MANIFEST_REL}, so "
                   f"there is no manifest to compare against its tree")
    try:
        manifest = json.loads(raw.stdout)
        parsed = m.parse_manifest(manifest, 40)
    except Exception as exc:
        return 2, (f"UNDETERMINED: {commit[:12]}'s {MANIFEST_REL} could not be "
                   f"parsed, so nothing is claimed about the tree: {exc}")

    try:
        observed = m._observe_files(repo, commit, parsed["paths"], "sha1", 40)
    except Exception as exc:
        return 2, (f"UNDETERMINED: could not observe the protected paths at "
                   f"{commit[:12]}: {exc}")

    # `describes_tree` and NOT `_match_state`: the private name this was written
    # against was deleted at `3c9d6a2563` (v1.13.36) together with the LANDING
    # REFUSAL it powered, and the call sat inside the `except` that IS this
    # function's FAIL path -- so every input, compliant or not, reported "neither
    # of its own states". MEASURED 2026-08-31 on a manifest rendered by the
    # shipped author against its own tree: `0 drifted` against BOTH states, and
    # rc 1. The supported predicate answers the question without answering a
    # landing with it; `classify_move` still decides those.
    if not hasattr(m, "describes_tree"):
        # A CHECKOUT THAT CANNOT ANSWER IS NOT A FINDING ABOUT THE TREE. Between
        # `3c9d6a2563` and the commit that restored the predicate there is no
        # supported call for this question, and reporting FAIL there would be
        # reporting the checkout, not the commit.
        return 2, (f"UNDETERMINED: {repo}/tools/ci/protected_landing_transition.py "
                   f"exports no `describes_tree`, so this checkout cannot say "
                   f"which state {commit[:12]}'s tuple is")
    state = m.describes_tree(observed, manifest)
    if state is None:
        by = {r["path"]: r for r in observed}
        out = []
        for label in ("current", "next"):
            st = manifest[label]
            d = [f["path"] for f in st["files"]
                 if by.get(f["path"], {}).get("blob_oid") != f["blob_oid"]]
            out.append(f"    vs {label} ({st['id']}): {len(d)} drifted")
            for path in d[:6]:
                out.append(f"        {path}")
            if len(d) > 6:
                out.append(f"        … and {len(d) - 6} more")
            if not d:
                # `describes_tree` compares the WHOLE record. A count of zero
                # here with a verdict of "neither" means the drift is in a
                # field this summary does not print -- say so rather than print
                # a line that reads as its own contradiction.
                differ = sorted(f["path"] for f in st["files"]
                                if by.get(f["path"]) != f)
                out.append(f"        (0 blob_oid drifted; the record differs on "
                           f"mode/size/sha256 for: {differ})")
        return 1, (
            f"[FAIL] {commit[:12]} ships a manifest that describes neither of "
            f"its own states, so it was rendered against a different tree.\n"
            + "\n".join(out)
            + f"\n    A landing cannot produce a receipt in this state: "
              f"`build_receipt` establishes the BASE state first, so it refuses "
              f"for every candidate, this commit against ITSELF included.")
    return 0, (f"[PASS] {commit[:12]}'s protected tuple is the manifest's "
               f"{state!r} state, over {len(observed)} protected path(s).")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--ref", default="HEAD")
    a = ap.parse_args(argv)
    rc, msg = check(Path(a.repo).resolve(), a.ref)
    print(msg, file=sys.stderr if rc else sys.stdout)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
