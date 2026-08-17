#!/usr/bin/env python3
"""suite_write_guard.py — a test run must not write into the tree it tests.

THIS GATE BLOCKS (rc=1) on a tracked or untracked write. Ignored-class writes
are ADVISORY (named, rc unchanged); see WHAT BLOCKS below for why the line is
drawn exactly there. rc=2 means NOT CHECKED — it never means clean.

WHY THIS EXISTS (vibe-ic#1029)
==============================
Three separate writers into the shipped tree were found during one campaign.
Every one of them was found BY ACCIDENT:

  * `skills/fork-gatekeeper-loop/SKILL.md`, appended to by
    `_shared/add_compliance_gate.py` under `test_tools_and_integration.py` —
    noticed by an agent working on a different issue;
  * `benchmark-data/**/opentitan_aes/reports/ic_class.json`, re-armed whenever
    the published cache file is deleted — caught mid `git add -A`;
  * three published `benchmark-data/**/reports/phase1/l20_*.json`, whose
    `project` and `evidence` provenance was rewritten to name a throwaway
    worktree — caught by a maintainer watching a status line at 80 %.

None was found by looking, because nothing looked. The rule "a full suite run
on a clean worktree leaves `git status --porcelain` empty" was a fact somebody
had to REMEMBER to check, and a rule that has to be remembered is not a check.
This module is that rule, executing.

The cost of missing one is not the dirty file. It is that an agent which does
not notice runs `git add -A` and SHIPS the mutation — and in the `l20` case
what ships is a published artefact's claim about its own provenance, rewritten
to point at a scratch directory that will not exist tomorrow.

WHAT BLOCKS, AND WHY THE LINE IS THERE
======================================
    TRACKED   (M/A/D/R/C, staged or not)   BLOCKING
    UNTRACKED (`??`)                       BLOCKING
    IGNORED   (`!!`)                       ADVISORY, named, never blocking

Blocking is exactly what plain `git status --porcelain` reports, because that
is exactly what `git add -A` would sweep into a commit. That is the assertion
#1029 asks for, and it is drawn at the same place as the consequence.

The ignored class is reported but does not block, for a measured reason in each
direction. It matters: one controlled run left 22 IGNORED artefacts that
`git status` does not show, so they were invisible while still being READ by
the next gate (`test_corpus_write_guard.py`'s own header). It cannot block:
`__pycache__` churn is universal, unavoidable, and harmless, and a gate that
fires on every run in every checkout is a gate people learn to route around.
So it is named and it is not fatal — and because it is named, the next reader
of a 22-artefact leak sees it on the first run instead of losing hours to it.

WHAT IT COMPARES, AND WHY NOT AGAINST "EMPTY"
=============================================
Against the BASELINE taken when the session started, never against an empty
tree. A developer running the suite on a branch with three edits in flight must
not be told the suite wrote them. Only paths that APPEAR, or whose content
signature CHANGES, between the two snapshots are attributed to the run.

The signature is `(status, size, mtime_ns)` rather than the status alone, so a
test that rewrites an ALREADY-dirty file is still caught: its porcelain status
stays ` M` and only the bytes move.

WHAT IT DOES NOT COVER, stated because a bound nobody states gets read as a
guarantee:

  * a write made AND reverted inside a single test is invisible to a snapshot
    taken after it. Such a write would not be swept by `git add -A` either, so
    it is outside this gate's stated subject — but it is not outside
    "the instrument perturbs its subject";
  * session mode attributes to the RUN, not to a test. `--per-test` attributes
    to the test, and costs one `git status` per test (measured 0.10 s on this
    repo, so ~53 min over a 32 k-test suite) — which is why it is opt-in and
    session mode is the default;
  * it sees what git sees. A write outside the repo is not its subject.
  * a DETACHED COPY of this tree (a `cp -al` mirror, an unpacked tarball, a
    scratch dir under a `$TMPDIR` that happens to sit inside some unrelated
    checkout) has no `git status` that describes it. The guard declines it as
    NOT CHECKED rather than measuring whatever repository happens to enclose
    it — see `_repo_root` for the measurement that made that necessary
    (vibe-ic#1412).

DEGRADING LOUDLY (flow-change-acceptance §6)
============================================
Every path that declines to measure emits a named `WRITE_GUARD_NOT_CHECKED:`
record and exits 2. There is no branch that returns 0 without having compared
two snapshots. "I could not look" must never reach a reader as "I looked and it
was clean" — that is the `_vacuous_exit` convention this repo already runs on.

chip-AGNOSTIC: reads `git status`. No design, PDK, vendor or IC input anywhere.

USAGE
-----
    suite_write_guard.py --repo R --snapshot BASE.json
    suite_write_guard.py --repo R --compare  BASE.json [--json REPORT]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

#: Exit codes. 2 is NOT CHECKED and is never folded into 0.
RC_CLEAN = 0
RC_WROTE = 1
RC_NOT_CHECKED = 2

TRACKED = "tracked"
UNTRACKED = "untracked"
IGNORED = "ignored"

#: The two classes `git add -A` would sweep into a commit.
BLOCKING_CLASSES = (TRACKED, UNTRACKED)

#: Machine-regenerable interpreter/test caches. COUNTED and disclosed, never
#: listed path-by-path. Python rewrites these on import and pytest on startup,
#: so every run in every checkout produces dozens; listing them would bury the
#: leftovers that matter (the 22-artefact leak in `test_corpus_write_guard`'s
#: header was reports and scratch dirs, not bytecode) under noise nobody reads.
#: They are cache CONTENT only — never a path a gate reads for evidence.
_CACHE_NOISE = ("__pycache__/", ".pytest_cache/", ".mypy_cache/",
                ".ruff_cache/", ".hypothesis/")


def _is_cache_noise(path: str) -> bool:
    if path.endswith((".pyc", ".pyo")):
        return True
    return any(seg in path for seg in _CACHE_NOISE)


class NotChecked(Exception):
    """The guard could not look. Never silently degraded into a pass."""


#: Bound for the two REPO-DISCOVERY calls (`rev-parse`, `ls-files`). Both read
#: the index and neither walks the worktree, so they are milliseconds; the bound
#: exists only so a wedged git cannot hang the session. It is deliberately under
#: the 60 s ceiling `ci_harness_timeout_ceiling_check` derives from
#: `gatekeeper-land.sh` (`--timeout=180` // 3): above that, pytest kills the
#: whole SESSION first and every other file in the subset loses its verdict.
#: The two SNAPSHOT calls keep the 120 s bound they landed with — those DO walk
#: the worktree, and lowering them would turn a slow checkout into a
#: NOT_CHECKED, which is a different change from this one.
_DISCOVERY_TIMEOUT_S = 30


def _git(repo: Path, *args: str, timeout: int = 120) -> str:
    """Run git read-only, and turn every failure into a LOUD NotChecked.

    `--no-optional-locks` so the guard can run concurrently with whatever it is
    measuring without ever taking `.git/index.lock` — a guard that perturbs its
    subject is the defect this file exists to catch.
    """
    argv = ["git", "--no-optional-locks", "-C", str(repo), *args]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise NotChecked("git executable not found on PATH")
    except subprocess.TimeoutExpired:
        raise NotChecked(f"git timed out after {timeout}s: {' '.join(args)}")
    if p.returncode != 0:
        raise NotChecked(
            f"git {' '.join(args)} exited {p.returncode}: "
            f"{(p.stderr or '').strip()[:200]}")
    return p.stdout


def _parse_porcelain_z(raw: str) -> List[Tuple[str, str]]:
    """Parse `--porcelain=v1 -z` into [(status, path)].

    `-z` rather than the newline form because a path containing a quote,
    backslash or newline is C-quoted in the default output and would be
    silently mis-attributed. Rename/copy entries carry a SECOND NUL-terminated
    field (the origin path) which is consumed and discarded: the destination is
    the path that changed.
    """
    fields = raw.split("\0")
    out: List[Tuple[str, str]] = []
    i = 0
    while i < len(fields):
        f = fields[i]
        i += 1
        if not f:
            continue
        # "XY <path>" — status is the first two columns, then one space.
        status, path = f[:2], f[3:]
        out.append((status, path))
        if status and status[0] in ("R", "C"):
            i += 1  # discard the origin path field
    return out


def _classify(status: str) -> str:
    if status == "??":
        return UNTRACKED
    if status == "!!":
        return IGNORED
    return TRACKED


def snapshot(repo: Path) -> Dict[str, list]:
    """Signature of every path git currently reports as not-pristine.

    Includes the ignored class so the advisory half has something to compare;
    measured at 0.10 s with or without `--ignored` on this repo, so carrying it
    costs nothing.
    """
    repo = Path(repo)
    if not repo.is_dir():
        raise NotChecked(f"not a directory: {repo}")
    raw = _git(repo, "status", "--porcelain=v1", "-uall", "--ignored", "-z")
    sig: Dict[str, list] = {}
    for status, rel in _parse_porcelain_z(raw):
        try:
            st = (repo / rel).stat()
            size, mtime = st.st_size, st.st_mtime_ns
        except OSError:
            # Deleted, or a directory entry git collapsed. The status alone
            # still distinguishes it; -1 is not a real size so it cannot
            # collide with one.
            size, mtime = -1, -1
        sig[rel] = [status, size, mtime]
    return sig


def compare(before: Dict[str, list], after: Dict[str, list]) -> dict:
    """Paths the run APPEARED at or CHANGED, split into blocking and advisory.

    Disappearances are recorded but never blocking: a run that CLEANS up
    something it did not create is not the defect this gate is about, and
    `git add -A` cannot ship an absence it did not cause.
    """
    findings: List[dict] = []
    for path, sig in sorted(after.items()):
        prev = before.get(path)
        if prev is None:
            what = "appeared"
        elif prev != sig:
            what = "rewritten" if prev[0] == sig[0] else "status-changed"
        else:
            continue
        findings.append({
            "path": path,
            "status": sig[0],
            "class": _classify(sig[0]),
            "what": what,
            "was": prev,
            "now": sig,
        })
    for path, sig in sorted(before.items()):
        if path not in after:
            findings.append({
                "path": path, "status": sig[0], "class": _classify(sig[0]),
                "what": "disappeared", "was": sig, "now": None,
            })

    def _blocks(f: dict) -> bool:
        return f["class"] in BLOCKING_CLASSES and f["what"] != "disappeared"

    blocking = [f for f in findings if _blocks(f)]
    advisory = [f for f in findings if not _blocks(f)]
    return {"findings": findings, "blocking": blocking, "advisory": advisory}


def format_report(result: dict, *, where: str = "this run",
                  can_attribute: bool = True) -> str:
    """Name EVERY offending path. #1029: 'It must name every offending path,
    not just fail.' A count is what made three writers cost three discoveries.

    `can_attribute` says whether the CALLER can vouch for what its snapshot
    bracketed. The pytest plugin can: its window is one session and the report
    names it. The `--compare` CLI cannot: it compares two snapshots of the whole
    tree across whatever the caller wrapped, which in `gatekeeper-land.sh` is
    `run_pytest` + ~74 hygiene gates + `plugin_full_audit`. #1087 measured what
    that costs — a tier write was reported against `63x8 census freshness`,
    which does not write — so when the window is unattributable the report now
    SAYS SO instead of leaving a reader to take a gate name off the surrounding
    log. This changes no verdict and adds no failure; it removes a false
    accusation the output was inviting.
    """
    lines: List[str] = []
    blocking, advisory = result["blocking"], result["advisory"]
    if blocking:
        lines.append(
            f"[FAIL] suite_write_guard: {where} WROTE INTO THE TREE — "
            f"{len(blocking)} path(s) that `git add -A` would ship:")
        for f in blocking:
            lines.append(f"    {f['status']:>2}  {f['path']}   ({f['what']})")
        lines.append(
            "  Nothing that READS this tree may write to it — not a test, and "
            "not a gate. Direct the write into a tmp dir, or copy the subject "
            "before mutating it.")
        if not can_attribute:
            lines.append(
                "  THIS FINDING NAMES PATHS, NOT A WRITER. The snapshot pair "
                "spans everything the caller bracketed, so nothing here "
                "identifies which step or gate inside that window wrote these "
                "paths — do not read one off the surrounding log. The guard "
                "that CAN attribute (`_gate_dispatch.sh`, per gate) watches "
                "only $GATE_DISPATCH_CORPUS_REL, so a write outside it is "
                "visible here and attributable nowhere (vibe-ic#1087). Bisect "
                "by re-running the bracketed steps individually.")
    named = [f for f in advisory if not _is_cache_noise(f["path"])]
    noise = len(advisory) - len(named)
    if named:
        # Two things land here and the header must not claim only one: the
        # IGNORED class (invisible to `git status`, still read by the next
        # gate), and a path the run made CLEAN again (a developer's in-flight
        # edit reverted under them). Neither blocks; both are named.
        lines.append(
            f"[INFO] suite_write_guard: {len(named)} further path(s) changed "
            f"(ADVISORY, not blocking — ignored-class artefacts `git status` "
            f"does not show, and paths the run reverted):")
        for f in named:
            lines.append(f"    {f['status']:>2}  {f['path']}   ({f['what']})")
    if noise:
        # Disclosed as a count, never hidden: a suppression nobody states reads
        # downstream as "there was nothing there".
        lines.append(
            f"[INFO] suite_write_guard: +{noise} regenerable cache artefact(s) "
            f"(__pycache__/.pytest_cache/*.pyc) not listed.")
    if not blocking:
        # Always emitted when nothing blocks, so a reader can tell "the guard
        # ran and found nothing" from "the guard did not run" without inferring
        # it from an absence of output.
        lines.append(
            f"[PASS] suite_write_guard: {where} wrote nothing "
            f"`git status --porcelain` would show.")
    return "\n".join(lines)


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="repository root")
    ap.add_argument("--snapshot", metavar="OUT",
                    help="write a baseline snapshot and exit")
    ap.add_argument("--compare", metavar="BASE",
                    help="compare the tree against a baseline snapshot")
    ap.add_argument("--json", metavar="OUT", help="write the report as JSON")
    a = ap.parse_args(argv)

    repo = Path(a.repo).resolve()
    try:
        if bool(a.snapshot) == bool(a.compare):
            raise NotChecked("exactly one of --snapshot / --compare is required")
        if a.snapshot:
            Path(a.snapshot).write_text(
                json.dumps(snapshot(repo), indent=1) + "\n")
            print(f"[PASS] suite_write_guard: baseline written to {a.snapshot}")
            return RC_CLEAN
        base_p = Path(a.compare)
        if not base_p.is_file():
            raise NotChecked(f"baseline not found: {base_p}")
        try:
            before = json.loads(base_p.read_text())
        except (OSError, ValueError) as exc:
            raise NotChecked(f"baseline unreadable: {exc}")
        result = compare(before, snapshot(repo))
    except NotChecked as exc:
        # The one thing this gate must never do is answer 0 without looking.
        print(f"WRITE_GUARD_NOT_CHECKED: {exc}", file=sys.stderr)
        print("[NOT CHECKED] suite_write_guard: could not measure — this is "
              "NOT a pass (rc=2)")
        return RC_NOT_CHECKED

    # can_attribute=False: this entry point brackets whatever its CALLER
    # wrapped and has no way to learn what that was. It is the whole-tier arm
    # in `gatekeeper-land.sh` (#1087), and claiming attribution it cannot
    # perform is what put a tier write on a named gate that does not write.
    print(format_report(result, where=f"the run against {repo}",
                        can_attribute=False))
    if a.json:
        Path(a.json).write_text(json.dumps(result, indent=1) + "\n")
    return RC_WROTE if result["blocking"] else RC_CLEAN


# ---------------------------------------------------------------------------
# pytest plugin — the same comparison, driven by the session it measures.
#
# Loaded by the plugin-root conftest.py, so it rides EVERY pytest invocation
# rooted at the plugin: the targeted subset `gatekeeper-land.sh` runs on every
# landing, and any full-suite run. It is deliberately not a workflow step:
# GitHub Actions is disabled for this account (see
# .github/workflows-disabled/README.md), so a gate wired there would never
# execute — which is the exact defect #1029 is about.
#
# Session mode costs two `git status` calls (0.20 s measured). `--per-test`
# costs one per test and is opt-in for that reason.
# ---------------------------------------------------------------------------

_STATE: dict = {}


def pytest_addoption(parser):
    g = parser.getgroup("suite_write_guard")
    g.addoption("--write-guard", action="store", default="session",
                choices=("session", "per-test", "off"),
                help="tree-write guard mode (default: session)")
    g.addoption("--write-guard-repo", action="store", default=None,
                help="repository root to measure (default: discovered)")


def _repo_root(config) -> Path:
    """The repository whose `git status` describes THE TREE UNDER TEST.

    THE AMBIENT-REPOSITORY TRAP (vibe-ic#1412)
    ------------------------------------------
    `rev-parse --show-toplevel` answers "is there a repo above me", which is
    NOT the question. A DETACHED COPY of this tree — the `cp -al` hardlink
    mirror `matrix_mutation_ledger`'s LOCK 2 replay runs its cells in, an
    unpacked tarball, any scratch dir under a `$TMPDIR` that happens to sit
    inside some unrelated checkout — answers it with the AMBIENT repository.
    The guard then measures a tree it is not testing, under a `.gitignore` that
    never carried this tree's rules, so the session's own `__pycache__` lands in
    the UNTRACKED class instead of the IGNORED one and BLOCKS a session that
    wrote nothing anybody would ship.

    Measured on #1412: the same commit, the same cell, the only difference
    being `$TMPDIR` — `1 passed` and rc=1, 19 blocking paths, every one of them
    `<mirror>/**/__pycache__/*.pyc`. The ledger read that rc and recorded
    `ALREADY_RED`, i.e. "this gate can no longer be shown to have teeth", for
    two mutations whose replays were in fact working perfectly.

    So the discovered repo must actually TRACK this file. Anything else is a
    tree with no `git status` to describe it, and NOT CHECKED is the honest
    answer — the same one this guard already gives when there is no ambient
    repo at all. It is never a pass: `pytest_configure` records the reason and
    `pytest_sessionfinish` prints `WRITE_GUARD_NOT_CHECKED:` by name.

    An EXPLICIT `--write-guard-repo` is obeyed unchecked. That is an operator
    naming the subject on purpose, and every test in `test_suite_write_guard`
    that plants a writer drives this door.
    """
    explicit = config.getoption("--write-guard-repo")
    if explicit:
        return Path(explicit).resolve()
    here = Path(__file__).resolve()
    root = Path(_git(here.parent, "rev-parse", "--show-toplevel",
                     timeout=_DISCOVERY_TIMEOUT_S).strip()).resolve()
    try:
        _git(root, "ls-files", "--error-unmatch", "--", str(here),
             timeout=_DISCOVERY_TIMEOUT_S)
    except NotChecked as exc:
        raise NotChecked(
            f"the repository above this file ({root}) does not track it "
            f"({here}) — this is a DETACHED COPY of the tree, not a checkout, "
            f"so a `git status` there reports the AMBIENT repository and not "
            f"the tree under test [{exc}]")
    return root


def pytest_configure(config):
    # Under xdist every worker would snapshot and compare the SAME tree, so the
    # report would be printed N times and a write attributed to whichever
    # worker happened to observe it. The controller alone measures; workers
    # carry `workerinput` and stay out of it.
    if hasattr(config, "workerinput"):
        return
    mode = config.getoption("--write-guard")
    if mode == "off":
        # A disabled guard announces itself. Silence here would read as "the
        # guard ran and found nothing" to anyone reading the log later.
        print("WRITE_GUARD_NOT_CHECKED: --write-guard=off — the tree is NOT "
              "being measured this run", file=sys.stderr)
        return
    try:
        repo = _repo_root(config)
        _STATE["repo"] = repo
        _STATE["baseline"] = snapshot(repo)
        _STATE["mode"] = mode
    except NotChecked as exc:
        _STATE["not_checked"] = str(exc)


def pytest_runtest_teardown(item):
    if _STATE.get("mode") != "per-test" or "repo" not in _STATE:
        return
    try:
        now = snapshot(_STATE["repo"])
    except NotChecked:
        return
    result = compare(_STATE.get("last", _STATE["baseline"]), now)
    if result["blocking"]:
        _STATE.setdefault("per_test", []).append(
            (item.nodeid, [f["path"] for f in result["blocking"]]))
    _STATE["last"] = now


def pytest_sessionfinish(session, exitstatus):
    reason = _STATE.get("not_checked")
    if reason:
        print(f"\nWRITE_GUARD_NOT_CHECKED: {reason}", file=sys.stderr)
        return
    if "baseline" not in _STATE:
        return
    try:
        result = compare(_STATE["baseline"], snapshot(_STATE["repo"]))
    except NotChecked as exc:
        print(f"\nWRITE_GUARD_NOT_CHECKED: {exc}", file=sys.stderr)
        return
    _STATE["result"] = result
    report = format_report(result, where="this pytest session")
    print("\n" + report)
    for nodeid, paths in _STATE.get("per_test", []):
        print(f"    ^ written by {nodeid}: {', '.join(paths)}")
    if result["blocking"]:
        session.exitstatus = 1


if __name__ == "__main__":
    raise SystemExit(_main())

# selector-probe: no-op line added by the xdist equivalence experiment
