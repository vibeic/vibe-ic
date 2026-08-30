#!/usr/bin/env python3
"""Render ONE protected-landing transition manifest from an observed tree.

WHY THIS EXISTS
===============
Every manifest in this repository's history was hand-authored, and the last
three are malformed in a way the verifier's own parser refuses.  MEASURED over
`tools/ci/protected_landing_transition.json` at each commit that touched it::

    7c376e348  current legacy-landing-v1          next semantic-landing-v1
    46964e1fb  current live-at-v1-10-74           next select-guard-...-v1
    15e4c463a  current activated-at-v1-10-79      next xdist-...-v1-next
    521fd735d  current activated-at-v1-10-81      next 1704-...-v1-next
    533c71285  current activated-at-v1-10-87      next arm-exit-...-v1-next
    1fda956ba  current activated-at-v1-10-96      next landing-...-v1-next
    1f1749d2d  current activated-at-v1-11-1       next activated-at-v1-11-1
    b161ec6e5  current activated-at-v1-11-1       next activated-at-v1-11-1
    eda53573f  current activated-at-tier-preflight next activated-at-tier-preflight

From `1f1749d2d` on, `current.id == next.id`, and
`protected_landing_transition.parse_manifest` refuses exactly that::

    Refusal: manifest current and next state ids are equal

`build_receipt` parses the BASE manifest before it looks at any candidate, so
that refusal is reached by EVERY landing whose base carries such a manifest.
The predicate has existed since `7c376e348`, the commit that introduced the
manifest, so the malformation was never a rule change — it was three commits
transcribing 47 file records by hand and settling `current` onto `next` because
nothing rendered the file for them.

WHAT A LEGAL MANIFEST LOOKS LIKE, AND WHY THAT IS NOT OBVIOUS BY HAND
====================================================================
There is no "settled" manifest.  A manifest names the LAST transition and keeps
naming it: after an ACTIVATE the live tuple equals `next` on the paths that
transition moved, `classify_move` reports `next.id` as the base state, and
every subsequent landing is STEADY against the same unchanged bytes.
Collapsing `current` onto `next` to express "nothing pending" is therefore
never necessary and always fatal.

`current` covers all the protected paths because it is OBSERVED at one commit
and there is no reason to observe a subset -- but only the rows it disagrees
with `next` on are ever read as an authorisation.  A protected path that
legitimately changes on trunk under some LATER transition does not falsify
this manifest and does not have to be re-rendered into it; that is the
difference between a register that records a move and a photograph of a tree,
and it is why this file no longer has to be re-authored after every landing.

The two states are produced at DIFFERENT times, which is the part a hand edit
gets wrong:

  PREPARE   a manifest-only commit.  `current` is the tuple observed AT THAT
            COMMIT, `next` is the tuple the following commit will install.
  ACTIVATE  the following commit, which moves exactly the paths the two states
            disagree on and does not touch the manifest.

So `--next-file PATH=FILE` names the bytes that do not exist in the tree yet.
That is the whole reason this program takes them from the filesystem rather
than from a commit: at PREPARE time the future bytes are a working-tree edit.

NO SECOND DEFINITION
====================
Path/role policy and the runner profile are COPIED from the manifest already in
the tree — they are policy, not observation, and re-deriving them here would be
a second opinion about what is protected.  The tuples are observed through
`protected_landing_transition._observe_files`, the same function the verifier
uses, and the finished object is handed back to `parse_manifest` before it is
written.  A manifest this program emits and the verifier refuses is a bug in
this program, and it is refused here rather than committed.

chip-AGNOSTIC: repository landing machinery only; no design, PDK or vendor name.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


class Refusal(RuntimeError):
    pass


def _load_transition():
    """Import the verifier as a sibling, by exact path, never by name."""
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        "_vibeic_protected_landing_transition",
        here / "protected_landing_transition.py")
    if spec is None or spec.loader is None:
        raise Refusal("protected_landing_transition.py is not importable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, args: Sequence[str]) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, check=False)
    if proc.returncode != 0:
        raise Refusal(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _future_record(*, path: str, source: Path, mode: str, repo: Path,
                   oid_len: int) -> dict[str, Any]:
    """The record the tree WILL hold once `source` is installed at `path`.

    `git hash-object` is asked rather than computed so the oid is the one git
    will actually store, including whatever object format this repository uses.
    """
    raw = source.read_bytes()
    oid = _git(repo, ["hash-object", "-t", "blob", "--", str(source)]).strip()
    if len(oid) != oid_len:
        raise Refusal(
            f"{path}: git produced a {len(oid)}-character oid but this "
            f"repository's object format is {oid_len} characters")
    return {"path": path, "mode": mode, "blob_oid": oid,
            "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


#: Paths a previous register protected that the derivation deliberately no
#: longer covers, each with the reason. EMPTY, and it must stay a record of
#: decisions rather than a place to silence the guard below.
WITHDRAWN: dict[str, str] = {}


def refuse_a_shrink(previous_rows: Any, derived_rows: Any) -> None:
    """Refuse a derived set smaller than the register it replaces.

    A DERIVED SET THAT SILENTLY SHRINKS IS WORSE THAN A STALE ONE.  Staleness
    is visible -- the parity tests go red and somebody comes looking.  A quiet
    contraction is not: the register keeps validating, the landing keeps
    passing, and a file simply stops being protected with no line anywhere
    saying so.  So every path the previous register protected must still be
    derived, or be named in `WITHDRAWN` with its reason, in the same commit
    that removes it.  A reason nobody wrote is not a reason.

    Its own function so it can be exercised directly: `render` loads the
    verifier through `_load_transition`, so a test cannot reach the derivation
    by patching an imported module object.
    """
    previous = {row["path"] for row in previous_rows
                if isinstance(row, dict) and isinstance(row.get("path"), str)}
    derived = {row["path"] for row in derived_rows}
    dropped = sorted(previous - derived - set(WITHDRAWN))
    if dropped:
        raise Refusal(
            "the derived protected set is SMALLER than the register it "
            "replaces, and no reason is recorded for the difference: "
            + ", ".join(dropped)
            + ". Either the verifier stopped reading these files -- in which "
            "case say so in WITHDRAWN, in this commit -- or the derivation is "
            "wrong. A path that quietly stops being protected is the failure "
            "this check exists for.")


def render(*, repo: Path, commit: str, transition_id: str, current_id: str,
           next_id: str, moves: dict[str, Path]) -> dict[str, Any]:
    transition = _load_transition()
    repo = repo.resolve(strict=True)
    algorithm, oid_len = transition._object_format(repo)
    resolved, _tree_oid = transition._commit_and_tree(
        repo, commit, oid_len, "authoring commit")

    live_manifest_raw = transition._observe_manifest(
        repo, resolved, algorithm, oid_len)[1]
    live_manifest = transition.strict_loads(
        live_manifest_raw, what="the manifest already in the tree")

    # DERIVED FROM THE VERIFIER, NOT COPIED FROM THE LAST MANIFEST.
    #
    # Both of these used to be lifted verbatim out of whatever manifest was
    # already in the tree, which made the register a hand-fed list: it could
    # only ever be as current as the last person who remembered to edit it, and
    # at v1.13.3 that was v1.12.39.  A path is protected BECAUSE THE VERIFIER
    # READS IT, so the verifier is the source of truth and says so itself in
    # `RUNTIME_PATHS` / `REQUIRED_AUTHORITY_PATHS`; the runner is likewise the
    # profile `_runner_profile` validates against.  See `derived_paths`.
    paths = transition.derived_paths()
    runner = transition.derived_runner()

    # A DERIVED SET THAT SILENTLY SHRINKS IS WORSE THAN A STALE ONE.
    #
    # Staleness is visible -- the parity tests go red and somebody comes
    # looking.  A quiet contraction is not: the register keeps validating, the
    # landing keeps passing, and a file simply stops being protected with no
    # line anywhere saying so.  So every path the previous register protected
    # must still be derived, or be named here with its reason.  WITHDRAWN is
    # empty today and a future removal must add to it in the same commit that
    # removes the path; a reason nobody wrote is not a reason.
    refuse_a_shrink(live_manifest.get("paths", []), paths)

    current = transition._observe_files(
        repo, resolved, paths, algorithm, oid_len)
    known = {row["path"]: row for row in current}
    unknown = sorted(set(moves) - set(known))
    if unknown:
        raise Refusal("a move names a path the manifest does not protect: "
                      + ", ".join(unknown))
    if not moves:
        raise Refusal(
            "a manifest with no move is refused by parse_manifest ('manifest "
            "next tuple does not differ from current'). There is no settled "
            "manifest: leave the last transition in place, or name the move "
            "the next commit will install with --next-file.")

    nxt = []
    for row in current:
        source = moves.get(row["path"])
        if source is None:
            nxt.append(dict(row))
            continue
        future = _future_record(path=row["path"], source=source,
                                mode=row["mode"], repo=repo, oid_len=oid_len)
        if future == row:
            raise Refusal(
                f"{row['path']}: the named bytes are already the tree's bytes, "
                "so this move moves nothing")
        nxt.append(future)

    manifest = {
        "schema": transition.SCHEMA,
        "kind": transition.MANIFEST_KIND,
        "transition_id": transition_id,
        "manifest_path": transition.MANIFEST_PATH,
        "runner": runner,
        "paths": paths,
        "current": {"id": current_id, "files": current},
        "next": {"id": next_id, "files": nxt},
    }
    # The verifier's OWN parser, on the way out. A manifest this program emits
    # and `build_receipt` refuses would be a landing nobody could make, so it is
    # refused HERE, where the author can still see why.
    transition.parse_manifest(json.loads(json.dumps(manifest)), oid_len)
    return manifest


def serialise(manifest: dict[str, Any]) -> bytes:
    """The exact on-disk shape: sorted keys, no spaces, ONE trailing newline.

    THE NEWLINE IS THE POINT.  The docstring here used to say "no trailing
    newline" and to claim it round-tripped the manifest in the tree byte for
    byte.  It did not: the file on disk ends `0a` and this function emitted
    29 874 bytes against the file's 29 875, a difference of EXACTLY that one
    byte.  So `serialise(json.loads(raw)) != raw` for the tree's own manifest,
    every re-render diffed against itself, and the register could not be
    re-authored without a spurious whole-file change -- which is a large part
    of why it was last authored at v1.12.39 and left to go stale.

    The tree's bytes are the ones that win: a text file ends with a newline,
    every editor and `git diff` agrees, and the verifier hashes whatever the
    file contains, so this side is the one that was wrong.
    """
    return json.dumps(manifest, sort_keys=True,
                      separators=(",", ":")).encode("utf-8") + b"\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render one protected-landing transition manifest.")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--commit", default="HEAD",
                        help="the commit whose tree is the `current` tuple")
    parser.add_argument("--transition-id", required=True)
    parser.add_argument("--current-id", required=True)
    parser.add_argument("--next-id", required=True)
    parser.add_argument(
        "--next-file", action="append", default=[], metavar="PATH=FILE",
        help="a protected PATH whose future bytes are in FILE")
    parser.add_argument("--out", type=Path,
                        help="write here instead of stdout")
    args = parser.parse_args(argv)

    moves: dict[str, Path] = {}
    for item in args.next_file:
        path, sep, source = item.partition("=")
        if not sep or not path or not source:
            print(f"  REFUSE  --next-file must be PATH=FILE: {item}",
                  file=sys.stderr)
            return 2
        moves[path] = Path(source)

    try:
        manifest = render(repo=args.repo, commit=args.commit,
                          transition_id=args.transition_id,
                          current_id=args.current_id, next_id=args.next_id,
                          moves=moves)
    except Exception as exc:                       # noqa: BLE001 - reported
        print(f"  REFUSE  {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    raw = serialise(manifest)
    if args.out is None:
        sys.stdout.buffer.write(raw)
        sys.stdout.buffer.write(b"\n")
    else:
        args.out.write_bytes(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
