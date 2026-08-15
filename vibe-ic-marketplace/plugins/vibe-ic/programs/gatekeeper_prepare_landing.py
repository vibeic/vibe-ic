#!/usr/bin/env python3
"""gatekeeper_prepare_landing.py — do the mechanical things the landing gate
refuses a batch for, and refuse ONLY what a program cannot fix (vibe-ic#1129).

WHY THIS EXISTS
===============
`tools/gatekeeper-land.sh` turns a batch away for reasons that are
deterministic, mechanical, and already owned by a tool in this repo:

    version_bump_monotonic_check      the version was not bumped
    landing_is_one_commit             no `[vX.Y.Z]`-tagged commit on the tip
    test_programs_index_freshness     programs/INDEX.md is stale
    63x8 census freshness             the derived figures are stale (#1382)

None of those is a judgement. Each has a program that already knows the answer:
`gatekeeper_assign_version.py --write` (the version, and it writes plugin.json,
every marketplace.json and the README prose in one place),
`marketplace_version_sync_check.py --fix` (residual manifest drift),
`tools/gen_programs_index.py` (the index), and
`tools/gen_matrix_63x8_census.py --fix` (the 63x8 derived figures).

WHERE THE 63x8 CENSUS IS DERIVED, AND WHY IT IS HERE (vibe-ic#1382)
====================================================================
`63x8 census freshness` was the single most frequent landing blocker measured —
eleven of thirteen finished batches on 2026-08-13 — and not one of those was a
defect in any PR it stopped. Every figure it named was off by exactly one: one
gate added by one PR in the batch, with the derived figures never re-derived.

#1382 put two readings and asked the repo to choose:

    (a) derive at LAND — the batch builder re-derives before gating, exactly
        as it already does for `programs/INDEX.md`;
    (b) derive at PUSH — move `--check` into `pre-push` so authors meet it in
        seconds, and accept a conflict on every gate-adding PR.

THIS FILE IS THE ADOPTION OF (a), and the reason (b) was refused is measured
rather than preferred. The anchored figures live in three shared files, each
carrying tree-wide COUNTERS, so two branches that each add a gate rewrite the
same lines with different totals and neither can be stacked after the other.
That pathology is not hypothetical — `programs/INDEX.md` is the same shape and
was measured at 26 of 30 conflicting open PRs on 2026-08-13 (vibe-ic#1431),
which is why `tools/resolve_generated_conflicts.sh` had to be written. Reading
(b) would have added three more files of that kind.

The repo had already ruled the same way on the same question for a different
gate: on 2026-08-14 `benchmark evidence structure` and `benchmark run manifest`
were REMOVED from `tools/git-hooks/pre-push` and left at the landing gate,
because "push means publish this branch; it does not mean this is fit to become
main", and at push the only remedy was to rebuild the entire batch.

Re-deriving here does NOT silence the gate. `repo_hygiene_gates.sh` still runs
`gen_matrix_63x8_census.py --check` afterwards, on the tree this step produced,
and still fails it on anything a generator run cannot reach.

BEST EFFORT, AND ONLY THIS STEP — stated because the asymmetry is deliberate
----------------------------------------------------------------------------
The index and version steps are UNRUNNABLE-on-failure: each is a pure function
of tracked files and completes in seconds, so one that cannot run means the
checkout is broken. The census step is not like that. It drives the eight
dimension modules through a 60 s inner bound (`180 // 3`), and on a contended
host that bound is smaller than the work — measured red five runs out of five,
including at load 33 on a 32-core box (vibe-ic#1277). Making it fatal would
convert EVERY landing into a refusal, which is strictly worse than the blocker
it is meant to remove.

So a census step that cannot complete leaves the landing exactly where it stood
before this step existed: the gate runs, and the gate decides. It is reported as
`NOT RE-DERIVED` with the generator's own reason, never skipped silently, and it
never turns a red tree green — the only thing it can do is fail to save an hour.

The defect is not a wrong verdict. It is that the gate costs about an hour of
wall-clock, so a refusal for a mechanical reason costs an hour and says nothing
about the code under test. The operator learns to run the steps from memory
beforehand, and memory is where this goes wrong — #1129 was filed after hitting
it three times in one afternoon while holding the gatekeeper role: three
candidate stacks refused on the version, two more on the index, and every one of
those looked like a real finding until it was traced back to the harness.

So: do the mechanical work, then let the gate refuse whatever is LEFT. A refusal
that survives preparation is a refusal about the change.

THE BOUNDARY, AND WHY IT IS DERIVED RATHER THAN TYPED
=====================================================
A preparation step inside the landing path is a path for the gate to EDIT ITS
OWN SUBJECT. That is #1029 (the tool dirties the tree it is judging) and #1089
(a mutant leaks into a tracked source file), and it is the one way this program
could be worse than the problem it solves.

So preparation is allowed to leave exactly one thing behind: paths that a
delegated writer DECLARED it wrote. The allow-list is not a literal in this
file — it is collected from the writers themselves at run time:

  * `gatekeeper_assign_version._write_version()` RETURNS the list of files it
    wrote (plugin.json, every marketplace.json, the READMEs carrying the version
    in prose — #152/#621). Whatever that helper grows to write next is inside
    the boundary automatically, and nothing else is.
  * `tools/gen_programs_index.py` writes exactly its `--out`, which this program
    passes explicitly rather than assuming.
  * `marketplace_version_sync_check.py --fix` writes only manifests already in
    the set above; it is run for residual drift and any path it touches must
    still fall inside that set or this program refuses.
  * `tools/gen_matrix_63x8_census.py --fix` is asked for `--written-json`, a
    JSON list of the repo-relative paths that run actually wrote. It is asked
    rather than assumed for the same reason as the index: the corpus is
    DISCOVERED by content ("a typed list is a promise that nobody will add a
    document"), so any allow-list typed here would rot the moment a corpus file
    appeared — silently, and in the forgiving direction. The generator emits
    that list even when it fails, because `--fix` writes the anchors first and
    only then drives the census, so a partial repair is the normal failure and
    exactly the case whose writes must still be attributable.

A hand-typed list would rot the moment a writer gained a file — silently, and in
the direction that matters (forgiving a write nobody authorised). Deriving it
means the boundary cannot drift away from the writers it is about.

ANY dirty path outside that set — whatever produced it — is a REFUSAL, printed
with the path. This program never cleans, never reverts and never commits a path
it did not itself cause a writer to produce.

EXIT
    0  prepared (or already prepared — nothing mechanical was left to do)
    1  REFUSED: something outside the declared boundary is dirty, or a
       mechanical step could not complete. Never a silent pass.
    2  could not run: a delegated writer is missing or unusable. A preparation
       that examined nothing has not prepared anything.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence, Set, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling import below resolves however this is invoked
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
REPO = PLUGIN.parent.parent.parent
INDEX = HERE / "INDEX.md"
GEN_INDEX = REPO / "tools" / "gen_programs_index.py"
GEN_CENSUS = REPO / "tools" / "gen_matrix_63x8_census.py"

#: Wall-clock bound on the census re-derivation, in seconds.
#:
#: NOT the `180 // 3` harness ceiling: this program is run by
#: `tools/gatekeeper-land.sh`, not under `pytest --timeout=180`, and the gate it
#: prepares for takes about ninety minutes. `ci_harness_timeout_ceiling_check`
#: scans `programs/tests/**/*.py` and `tools/test_*.py`, neither of which this
#: file is, and lowering the number to satisfy a harness that never bounds it
#: would guarantee the step can never succeed.
#:
#: Sized from the measurements on vibe-ic#1382: the generator's own runs on this
#: fleet took 102 s, ~250 s and 255 s before failing, and a successful run costs
#: the same census. Ten minutes is roughly 2x the slowest observed run, and it
#: MUST be able to fire — an unbounded subprocess inside the landing path would
#: hang the gate instead of reporting that it could not re-derive.
CENSUS_TIMEOUT_S = 600

RC_OK, RC_REFUSED, RC_UNRUNNABLE = 0, 1, 2

#: The tag `landing_is_one_commit_check` looks for, spelled the same way it
#: spells it (`_VERSION_RE` there). Imported rather than re-typed where the
#: import is possible; this literal is the documented fallback and the test
#: `test_the_tag_pattern_matches_the_consumers` pins the two together.
_VERSION_TAG = re.compile(r"\[v\d+\.\d+\.\d+\]")


def _git(repo: Path, *args: str) -> Tuple[int, str]:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def dirty_paths(repo: Path) -> Set[str]:
    """Tracked paths `git status --porcelain` reports as modified.

    Untracked (`??`) is deliberately EXCLUDED, matching
    `landing_worktree_is_clean_check`'s own scope — the gate this program has to
    leave satisfied. Widening it here would make preparation refuse on somebody's
    scratch notes, which `gitignore_scratch_guard` already reports separately.
    """
    rc, out = _git(repo, "status", "--porcelain")
    if rc != 0:
        return set()
    found: Set[str] = set()
    for line in out.splitlines():
        if not line.strip() or line.startswith("??"):
            continue
        found.add(line[3:].strip().split(" -> ")[-1])
    return found


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def tip_carries_version_tag(repo: Path) -> bool:
    rc, out = _git(repo, "log", "-1", "--format=%s")
    return bool(rc == 0 and _VERSION_TAG.search(out))


def current_version(plugin_json: Path) -> Optional[str]:
    try:
        return str(json.loads(plugin_json.read_text(encoding="utf-8"))["version"])
    except Exception:                                        # noqa: BLE001
        return None


def _default_index_writer(repo: Path) -> List[str]:
    """Regenerate `programs/INDEX.md`. Returns the repo-relative path it wrote.

    `--out` is passed EXPLICITLY rather than relying on the generator's default,
    so the path this program declares to the boundary is the same path the
    generator was told to write. Assuming they agree is how a boundary starts
    forgiving a file nobody named.
    """
    if not GEN_INDEX.is_file():
        raise FileNotFoundError(f"{GEN_INDEX} is missing")
    proc = subprocess.run([sys.executable, str(GEN_INDEX), "--out", str(INDEX)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"rc={proc.returncode}: "
                           f"{(proc.stdout + proc.stderr).strip()[:200]}")
    return [str(INDEX.relative_to(repo))]


def _default_census_writer(repo: Path) -> Tuple[List[str], Optional[str]]:
    """Re-derive the 63x8 census. Returns ``(paths written, reason it failed)``.

    A REASON, not an exception, because this step is best-effort by design —
    see the module docstring. Both halves of the pair are meaningful at once:
    `--fix` rewrites the anchored figures FIRST and only then drives the census
    block, so `(["…/flowref.py"], "rc=1: …")` is the normal partial repair and
    both facts have to reach the caller. Dropping either one loses a write that
    then cannot be attributed, or hides a failure behind files that did change.
    """
    if not GEN_CENSUS.is_file():
        return [], f"{GEN_CENSUS} is missing"
    # What was already dirty BEFORE the census, so a timeout can undo exactly what
    # the census wrote and nothing the earlier index step wrote.
    before = set(dirty_paths(repo))
    with tempfile.TemporaryDirectory() as td:
        written_json = Path(td) / "written.json"
        try:
            proc = subprocess.run(
                [sys.executable, str(GEN_CENSUS), str(repo), "--fix",
                 "--written-json", str(written_json)],
                capture_output=True, text=True, timeout=CENSUS_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            # THE BOUND FIRED, AND THE CHILD DOES NOT GET TO SAY WHAT IT WROTE.
            #
            # `subprocess.run` kills the child with SIGKILL on timeout, so the
            # generator's own `finally: write --written-json` NEVER RUNS. This
            # branch used to return `_read_written(written_json)` on the belief
            # that "anything written before it fired is still declared" — that
            # file does not exist, so the declaration came back EMPTY while the
            # census had already rewritten anchored figures. The boundary check
            # below then sees an undeclared dirty path and REFUSES, and
            # `gatekeeper-land.sh` exits 1 on a refusal — so a slow host turns a
            # best-effort convenience into a landing that cannot start.
            #
            # Measured: a child whose `finally` writes the declaration, timed out
            # by `subprocess.run`, leaves `written.json` ABSENT.
            #
            # The module docstring promises a census that cannot run "leaves the
            # landing exactly where it stood before this step existed". Honour
            # that literally: restore exactly the paths that became dirty during
            # the census, declare nothing, and report the timeout as a reason.
            # Restoring is safe precisely because `before` was captured above —
            # the earlier index write is untouched.
            undone, failed = [], []
            for rel in sorted(set(dirty_paths(repo)) - before):
                rc, _out = _git(repo, "checkout", "--", rel)
                (undone if rc == 0 else failed).append(rel)
            reason = f"the generator did not finish within {CENSUS_TIMEOUT_S}s"
            if undone:
                reason += f"; reverted {len(undone)} partial write(s)"
            if failed:
                # Could not restore: say so and DECLARE them, so the boundary
                # judges a real state instead of refusing on a path nobody owns.
                reason += (f"; COULD NOT revert {len(failed)}: "
                           + ", ".join(failed[:4]))
                return failed, reason
            return [], reason
        wrote = _read_written(written_json)
        if proc.returncode != 0:
            tail = (proc.stdout + proc.stderr).strip().splitlines()
            return wrote, (f"rc={proc.returncode}: "
                           + (tail[-1][:200] if tail else "no output"))
        return wrote, None


def _read_written(written_json: Path) -> List[str]:
    """The writer's own declaration, or [] if it made none.

    `[]` here means "declared nothing", and the caller must not read that as
    "wrote nothing" — the two are the same observation and only one of them is
    safe. It is safe HERE, and only here, because the boundary check downstream
    refuses any dirty path this list does not contain: an undeclared write turns
    into a REFUSAL rather than into silent forgiveness.
    """
    try:
        data = json.loads(written_json.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return []
    return [str(p) for p in data] if isinstance(data, list) else []


def _default_version_writer(repo: Path, plugin: Path,
                            old: Optional[str]) -> List[str]:
    """Assign + write the next version. Returns what the writer says it wrote."""
    av = _load(plugin / "programs" / "gatekeeper_assign_version.py",
               "_gpl_assign_version")
    nxt = av.next_version(old)
    if not nxt:
        raise RuntimeError(f"no next version derivable from {old!r}")
    written = av._write_version(plugin, nxt)
    return [str(Path(p).resolve().relative_to(repo)) for p in written]


def prepare(repo: Path, *, do_commit: bool,
            index_writer=None, version_writer=None, census_writer=None,
            plugin_root: Optional[Path] = None) -> Tuple[int, List[str], List[str]]:
    """Run every mechanical fixer. Returns (rc, notes, declared_paths).

    `declared_paths` is the boundary: repo-relative paths a writer said it wrote.

    `index_writer` / `version_writer` / `census_writer` exist so the
    ORCHESTRATION and the BOUNDARY — which are the new logic here — can be
    driven end-to-end over a real git repo in the tests without also re-testing
    writers that already have their own suites. All default to the real ones.

    `index_writer` and `version_writer` must RETURN the repo-relative paths they
    wrote: a writer that declares nothing is treated as unrunnable rather than
    as having written nothing, because those two are the same observation and
    only one of them is safe.

    `census_writer` returns `(paths, reason)` instead, because it is the one
    step allowed to fail without refusing the landing (see the module
    docstring), and "wrote these two files AND then failed" is a state the other
    two cannot be in.
    """
    notes: List[str] = []
    declared: Set[str] = set()
    plugin = plugin_root or PLUGIN
    plugin_json = plugin / ".claude-plugin" / "plugin.json"

    before = dirty_paths(repo)
    if before:
        # A tree that is ALREADY dirty cannot have its preparation attributed.
        # Refusing here is what keeps the boundary check below meaningful: it
        # can then say "this path was produced by preparation", instead of
        # inheriting somebody else's edit and calling it authorised.
        notes.append("REFUSE: the worktree is already dirty before preparation, "
                     "so nothing written now could be attributed to it — "
                     + ", ".join(sorted(before)[:6]))
        return RC_REFUSED, notes, sorted(declared)

    # ---- 1. the index -----------------------------------------------------
    try:
        wrote = (index_writer or _default_index_writer)(repo)
    except Exception as exc:                                 # noqa: BLE001
        notes.append(f"UNRUNNABLE: index regeneration failed: {exc}")
        return RC_UNRUNNABLE, notes, sorted(declared)
    if not wrote:
        notes.append("UNRUNNABLE: the index writer declared no files, so the "
                     "boundary cannot be established for it")
        return RC_UNRUNNABLE, notes, sorted(declared)
    declared |= set(wrote)
    notes.append(f"index regenerated -> {', '.join(sorted(wrote))}")

    # ---- 1b. the 63x8 census (vibe-ic#1382) -------------------------------
    # THE ADOPTION OF READING (a): derive at LAND, so the figures are true at
    # the only moment they are published, and no PR author is asked to re-derive
    # counters that live in three files every gate-adding branch touches.
    #
    # The ONLY step here that does not refuse on failure. Its generator drives
    # the eight dimension modules through a 60 s inner bound that is smaller
    # than the work on a contended host, so a fatal step would refuse every
    # landing (vibe-ic#1277). A census that could not be re-derived leaves the
    # tree exactly as it found it, and `repo_hygiene_gates.sh` still runs
    # `--check` on it afterwards and still decides.
    #
    # `except Exception` and NOT a bare call: an unexpected failure inside a
    # best-effort step must not be more fatal than the failure it is best-effort
    # about. Whatever it wrote before dying is still declared, so the boundary
    # below judges it exactly as it judges a clean run.
    try:
        wrote_c, census_why = (census_writer or _default_census_writer)(repo)
    except Exception as exc:                                 # noqa: BLE001
        wrote_c, census_why = [], f"{type(exc).__name__}: {exc}"
    declared |= set(wrote_c)
    if census_why:
        notes.append(
            f"63x8 census NOT RE-DERIVED ({len(wrote_c)} file(s) written "
            f"before it stopped) — the landing gate's `63x8 census freshness` "
            f"will decide on the tree as it stands, exactly as it did before "
            f"this step existed: {census_why}")
    else:
        notes.append(f"63x8 census re-derived -> {len(wrote_c)} file(s)"
                     + (": " + ", ".join(sorted(wrote_c)) if wrote_c
                        else " (already fresh)"))

    # ---- 2. the version, only when the tip does not already carry one -----
    if tip_carries_version_tag(repo):
        notes.append("version: the tip already carries a [vX.Y.Z] tag — not bumped")
    else:
        old = current_version(plugin_json)
        try:
            wrote_v = (version_writer or _default_version_writer)(repo, plugin, old)
        except Exception as exc:                             # noqa: BLE001
            notes.append(f"UNRUNNABLE: version assignment failed: {exc}")
            return RC_UNRUNNABLE, notes, sorted(declared)
        if not wrote_v:
            notes.append("UNRUNNABLE: the version writer declared no files, so "
                         "the boundary cannot be established for it")
            return RC_UNRUNNABLE, notes, sorted(declared)
        declared |= set(wrote_v)
        notes.append(f"version {old} -> {current_version(plugin_json)} across "
                     f"{len(wrote_v)} declared file(s)")

        # residual manifest drift, and ONLY where the version writer already
        # declared — a fixer allowed to reach further than the boundary would
        # be the boundary's first exception.
        sync = plugin / "programs" / "marketplace_version_sync_check.py"
        if sync.is_file():
            subprocess.run([sys.executable, str(sync), "--fix"],
                           capture_output=True, text=True)
            notes.append("marketplace sync --fix applied")

    # ---- THE BOUNDARY -----------------------------------------------------
    after = dirty_paths(repo)
    foreign = sorted(p for p in after if p not in declared)
    if foreign:
        notes.append("REFUSE: preparation touched path(s) OUTSIDE the set its "
                     "writers declared — this is the #1029/#1089 shape and it is "
                     "not forgiven: " + ", ".join(foreign[:8]))
        return RC_REFUSED, notes, sorted(declared)
    notes.append(f"boundary honoured: {len(after)} dirty path(s), all declared")

    # ---- 4. carry it into the tip ------------------------------------------
    if do_commit and after:
        for p in sorted(after):
            rc, out = _git(repo, "add", "--", p)
            if rc != 0:
                notes.append(f"REFUSE: could not stage {p}: {out.strip()[:120]}")
                return RC_REFUSED, notes, sorted(declared)
        ver = current_version(plugin_json) or "0.0.0"
        rc, subj = _git(repo, "log", "-1", "--format=%s")
        subject = subj.strip()
        if _VERSION_TAG.search(subject):
            rc, out = _git(repo, "commit", "--amend", "--no-edit", "--no-verify")
        else:
            rc, out = _git(repo, "commit", "--amend", "--no-verify",
                           "-m", f"{subject} [v{ver}]")
        if rc != 0:
            notes.append(f"REFUSE: amend failed: {out.strip()[:160]}")
            return RC_REFUSED, notes, sorted(declared)
        notes.append(f"tip amended, carries [v{ver}]")

    return RC_OK, notes, sorted(declared)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--commit", action="store_true",
                    help="stage ONLY the declared paths and amend the tip with "
                         "its [vX.Y.Z] tag. Off by default: writing files is "
                         "recoverable, rewriting a commit is the operator's call")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    rc, notes, declared = prepare(args.repo.resolve(), do_commit=args.commit)
    label = {RC_OK: "PREPARED", RC_REFUSED: "REFUSED",
             RC_UNRUNNABLE: "UNRUNNABLE"}[rc]
    print(f"gatekeeper_prepare_landing: {label}")
    for n in notes:
        print(f"    {n}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(args.json, json.dumps(
            {"verdict": label, "notes": notes, "declared_paths": declared},
            indent=1), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
