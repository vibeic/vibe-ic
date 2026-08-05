"""programs/tests/_control_corpus_replay.py — replay this repo's OWN standard
control over its own history, and classify what each one proved.

NOT a test module (no `test_` prefix, so pytest does not collect it). It is the
harness that produced the corpus measurement quoted by
`programs/control_substance_check.py`, kept in the tree so the number can be
re-derived instead of trusted.

THE CONTROL, AS THIS REPO DEFINES IT
------------------------------------
"Copy the change's new test file onto clean `main`, run it, show it FAILS."

For a commit C with parent P, that is mechanical:

    1. check P out into a throwaway worktree
    2. write in the test files C ADDED (and only those)
    3. run pytest on exactly those paths, with --junitxml
    4. classify the report with control_substance_check

Every run is a real pytest invocation over real repository history. Nothing is
hand-typed, so the corpus cannot be tuned to the classifier.

WHAT IT IS FOR
--------------
A distribution, not a verdict on any one commit. A commit whose control did not
collect is not thereby a bad commit — a new module cannot exist on its parent.
The point is how often "the tests fail pre-fix" is reported for a run that
executed no assertion, which is invisible unless somebody counts.

WHAT THIS HARNESS DOES NOT REPRODUCE — read before quoting a number
-------------------------------------------------------------------
* It copies in only files matching `programs/tests/test_*.py` that the commit
  ADDED. A commit that also added a non-`test_` helper into the test tree
  gets a slightly harsher control here than its author ran. (Checked on the
  45-commit sweep: all 5 zero-collected cases were a genuinely new PROGRAM
  module, not a missing helper.)
* It replays commits, which are post-review and post-squash. It is not the
  branch state the author measured against at the time.
* A per-CASE ratio over this corpus is dominated by whichever commit
  parametrised most heavily — one commit contributed 497 of 759 presence-only
  cases. Per-COMMIT figures are the ones that survive re-weighting.
* `pytest` is run per commit with a 300 s cap; a slower control is recorded as
  `timeout`, not as a verdict.

USAGE
-----
    python3 programs/tests/_control_corpus_replay.py \\
        --repo /path/to/clone --limit 45 --out /tmp/sweep.json

Requires a git clone with history; skipped automatically when absent.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import control_substance_check as CSC  # noqa: E402

PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"
TESTS_REL = f"{PLUGIN_REL}/programs/tests"


def _git(repo: Path, *args, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def candidates(repo: Path, limit: int, scan: int = 500) -> List[Dict]:
    """Non-merge commits on main that ADD at least one test file."""
    shas = _git(repo, "log", "--format=%H", f"-{scan}", "main", "--",
                f"{TESTS_REL}/").split()
    out: List[Dict] = []
    for sha in shas:
        parents = _git(repo, "rev-list", "--parents", "-n1", sha).split()
        if len(parents) != 2:            # merge commit: no single control
            continue
        added = [ln.split("\t", 1)[1]
                 for ln in _git(repo, "diff-tree", "--no-commit-id",
                                "--name-status", "-r", "--diff-filter=A",
                                sha, "--", f"{TESTS_REL}/").splitlines()
                 if ln.startswith("A\t") and ln.endswith(".py")
                 and "/test_" in ln]
        if not added:
            continue
        out.append({"sha": sha, "parent": parents[1], "added": added,
                    "subject": _git(repo, "log", "-1", "--format=%s",
                                    sha).strip()})
        if len(out) >= limit:
            break
    return out


def replay_one(repo: Path, wt: Path, item: Dict, basetemp: Path,
               timeout: int) -> Dict:
    """Check out the parent, drop in the added tests, run, classify."""
    rec = {"sha": item["sha"][:9], "subject": item["subject"][:90],
           "added": [Path(a).name for a in item["added"]]}
    try:
        _git(wt, "checkout", "--quiet", "--force", "--detach", item["parent"])
        _git(wt, "clean", "-qfd", "--", TESTS_REL)
    except RuntimeError as exc:
        return {**rec, "status": "checkout-failed", "detail": str(exc)[:200]}

    rel_paths: List[str] = []
    for path in item["added"]:
        blob = subprocess.run(
            ["git", "-C", str(repo), "show", f"{item['sha']}:{path}"],
            capture_output=True)
        if blob.returncode != 0:
            continue
        dest = wt / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob.stdout)
        rel_paths.append(str(Path(path).relative_to(PLUGIN_REL)))
    if not rel_paths:
        return {**rec, "status": "no-blob"}

    xml = basetemp / f"{item['sha'][:9]}.xml"
    # pytest creates --basetemp itself but NOT its parents. Without this the
    # `tmp_path` fixture dies in SETUP for every test in the file, which reads
    # as "collected, body never ran" and is a defect of THIS harness, not of
    # the commit under replay. Measured: it fabricated 79 such records over the
    # first 8 commits swept.
    bt = basetemp / "bt" / item["sha"][:9]
    bt.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *rel_paths, "-q",
             "-p", "no:cacheprovider", f"--junitxml={xml}",
             f"--basetemp={bt}"],
            cwd=str(wt / PLUGIN_REL), env=env, capture_output=True,
            text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {**rec, "status": "timeout"}
    if not xml.exists():
        return {**rec, "status": "no-report",
                "detail": (proc.stdout or proc.stderr)[-200:]}

    cases = CSC.read_junit(xml)
    rep = CSC.audit(cases)
    return {**rec, "status": "ok", "counts": rep["counts"],
            "substantive": rep["substantive"],
            "failures": rep["failures_reported"],
            "tautological": rep["tautological"],
            "pytest_rc": proc.returncode}


def sweep(repo: Path, limit: int, timeout: int,
          basetemp: Optional[Path] = None) -> Dict:
    basetemp = basetemp or Path(tempfile.mkdtemp(prefix="control_corpus_"))
    basetemp.mkdir(parents=True, exist_ok=True)
    wt = basetemp / "wt"
    _git(repo, "worktree", "add", "--quiet", "--detach", str(wt), "main")
    results: List[Dict] = []
    try:
        for item in candidates(repo, limit):
            results.append(replay_one(repo, wt, item, basetemp, timeout))
            print(f"  {results[-1]['status']:14s} {results[-1]['sha']} "
                  f"{results[-1].get('substantive', '-')}/"
                  f"{results[-1].get('failures', '-')} "
                  f"{results[-1]['subject'][:56]}", flush=True)
    finally:
        subprocess.run(["git", "-C", str(repo), "worktree", "remove",
                        "--force", str(wt)], capture_output=True)
        shutil.rmtree(wt, ignore_errors=True)

    ok = [r for r in results if r["status"] == "ok"]
    ran = [r for r in ok if r["failures"]]
    return {
        "replayed": len(results),
        "usable": len(ok),
        "controls_with_a_failure": len(ran),
        "tautological": sum(1 for r in ran if r["tautological"]),
        "with_substantive": sum(1 for r in ran if r["substantive"]),
        "zero_collected": sum(1 for r in ran
                              if r["counts"][CSC.NOT_COLLECTED]),
        "total_substantive": sum(r["substantive"] for r in ran),
        "total_presence_only": sum(r["counts"][CSC.PRESENCE_ONLY]
                                   for r in ran),
        "total_not_collected": sum(r["counts"][CSC.NOT_COLLECTED]
                                   for r in ran),
        "total_undecided": sum(r["counts"][CSC.UNDECIDED] for r in ran),
        "results": results,
        "basetemp": str(basetemp),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--limit", type=int, default=45)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--basetemp")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rep = sweep(Path(a.repo).resolve(), a.limit, a.timeout,
                Path(a.basetemp) if a.basetemp else None)
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=2) + "\n")
    for k in ("replayed", "usable", "controls_with_a_failure", "tautological",
              "with_substantive", "zero_collected", "total_substantive",
              "total_presence_only", "total_not_collected",
              "total_undecided"):
        print(f"{k:26s} {rep[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
