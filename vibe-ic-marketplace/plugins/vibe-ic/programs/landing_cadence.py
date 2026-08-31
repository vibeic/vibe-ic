#!/usr/bin/env python3
"""landing_cadence.py — wire the 2026-06-17 test-cadence policy into the LANDING.

THE POLICY IS NOT NEW AND IS NOT RE-IMPLEMENTED HERE
====================================================
It lives in ``gatekeeper_review.derive_cadence`` and this program IMPORTS it:

    x.y.0  milestone  ->  FULL       the whole ``programs/tests`` tree
    x.y.Z  patch      ->  TARGETED   the diff-derived subset suffices
    no parseable bump ->  NONE       the change ships nothing

Two copies of a rule are two rules. Nothing here decides the cadence; this
program only carries the existing decision to the caller that never had it.

WHAT WAS ACTUALLY MISSING, MEASURED AT v1.11.94
===============================================
``derive_cadence`` sat inside ``gatekeeper_review.py`` while the landing runs
``tools/gatekeeper-land.sh``, and those two were never wired together:

    $ grep -c -i cadence tools/gatekeeper-land.sh
    0

The landing's test lane called ``ci_targeted_test_select.py --base "$BASE"`` on
EVERY bump. That is NOT "FULL for everything" — it is the opposite, and it is
the unsafe direction. Measured on this tree at 40d0e14c:

    programs/tests holds                              2862 test files
    the selection for the real v1.11.94 landing        101 test files

So an ``x.y.0`` MILESTONE landed on 3.5% of the tree, and the one cadence the
policy refuses to let a subset satisfy was the one the landing could not run.
``ci_targeted_test_select.py``'s own header names the missing half in the
present tense — "The full both-tree suite still runs on the ``x.y.0`` milestone
job" — but that job was ``full-suite-milestone`` in
``.github/workflows-disabled/gatekeeper-ci.yml.disabled``, gated by
``if: needs.cadence.outputs.level == 'milestone'``. GitHub disabled Actions at
the ACCOUNT level, that workflow never ran once, and it was retired to
``workflows-disabled/`` on 2026-07-30 (0d66c96161, v1.8.40). The cadence
decision went with it and nothing inherited it.

THE CADENCE IS READ FROM THE TREE, NEVER FROM A FLAG
====================================================
There is deliberately NO ``--cadence`` option and there must never be one. A
caller-supplied cadence is a caller-supplied answer, and the single thing this
program exists to prevent is a milestone landing that declares itself a patch.
The inputs are two git refs; the version pair is read out of the committed
``plugin.json`` at each.

EVERY FAILURE RESOLVES TO ``FULL``
==================================
Unreadable ref, absent manifest, unparseable JSON, unparseable semver — all of
them print ``FULL``. "I could not read the version" must never reach the
landing as "the cheap tier is fine". The asymmetry is the whole point of the
policy, so it is also the direction of every default here: this program can
only ever make a landing run MORE than it needed, never less.

``--describe`` AND WHY THE COMMAND IS DERIVED, NOT ASSERTED
===========================================================
``gatekeeper_review.test_cadence_gate`` refuses a FULL cadence whose
``--pytest-cmd`` is a subset — but only if the landing tells it the truth about
what it ran. A landing that simply asserted the string
``python3 -m pytest -q programs/tests`` would satisfy the gate while running
101 files, which is the false green this whole wire exists to make impossible.

So ``--describe`` does not take the landing's word for it. It reads the
SELECTION FILE the run is about to execute, compares it against the test files
actually present in the tree, and emits the full-suite command ONLY when the
selection is the complete set. A short selection is described as the subset it
is, and at FULL cadence that description is what makes the review gate go red.
The claim is therefore EARNED from the selection rather than asserted beside it.

Usage
-----
    landing_cadence.py --repo R --base B --head H
        -> LANDING_CADENCE=FULL|TARGETED|NONE

    landing_cadence.py --plugin-root P --selection SEL --describe
        -> LANDING_TEST_SCOPE=full|subset
           LANDING_PYTEST_CMD=<the truthful pytest command for that selection>

Output is ``KEY=VALUE`` lines so the landing shell can read it without a JSON
parser. Exit 0 whenever an answer was produced (including the safe ``FULL``);
exit 2 only on a usage error.

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_PROGRAMS_DIR = Path(__file__).resolve().parent
_PLUGIN_ROOT_DEFAULT = _PROGRAMS_DIR.parent
_TEST_TREE = "programs/tests"

# The cadence rule's ONE home. Imported by file path rather than by package so
# this program runs from any cwd, exactly as the landing shell invokes it.
_gr = None


_fsr = None


def _full_suite_run_check():
    """Import full_suite_run_check lazily and by path, as above."""
    global _fsr
    if _fsr is None:
        spec = importlib.util.spec_from_file_location(
            "_lc_full_suite_run_check", _PROGRAMS_DIR / "full_suite_run_check.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_lc_full_suite_run_check"] = mod
        spec.loader.exec_module(mod)
        _fsr = mod
    return _fsr


def _gatekeeper_review():
    """Import gatekeeper_review lazily and by path (measured: 0.06 s)."""
    global _gr
    if _gr is None:
        spec = importlib.util.spec_from_file_location(
            "_lc_gatekeeper_review", _PROGRAMS_DIR / "gatekeeper_review.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_lc_gatekeeper_review"] = mod
        spec.loader.exec_module(mod)
        _gr = mod
    return _gr


def cadence_for(repo: Path, base: str, head: str) -> Tuple[str, str]:
    """Return (cadence, why). Any failure to determine yields FULL.

    Deliberately NOT a re-implementation: the version pair is read the way
    gatekeeper_review reads it, and the verdict is gatekeeper_review's own
    derive_cadence. If that function's rule ever changes, this changes with it.
    """
    try:
        gr = _gatekeeper_review()
    except Exception as e:                                   # pragma: no cover
        return "FULL", f"cadence source unavailable ({e.__class__.__name__}) — FULL"
    try:
        cur = gr._git_show_json_version(repo, head, gr._PLUGIN_JSON_REL)
        prev = gr._git_show_json_version(repo, base, gr._PLUGIN_JSON_REL)
    except Exception as e:
        return "FULL", f"version pair unreadable ({e.__class__.__name__}) — FULL"
    if cur is None:
        # NOT "NONE". A head with no readable plugin.json is a tree this program
        # cannot describe, and the safe reading of "cannot describe" is FULL.
        return "FULL", f"no readable version at {head} — FULL"
    try:
        cadence, label = gr.derive_cadence(cur, prev)
    except Exception as e:
        return "FULL", f"derive_cadence raised {e.__class__.__name__} — FULL"
    if cadence not in ("FULL", "TARGETED", "NONE"):
        return "FULL", f"unrecognised cadence {cadence!r} — FULL"
    return cadence, label


def milestone_check(repo: Path, base: str, head: str) -> str:
    """Answer the PUSH HOOK's question: "yes" | "no" | "unknown".

    THIS IS A NARROWER QUESTION THAN `cadence_for`, ON PURPOSE, AND THE
    DIFFERENCE IS THE DEFAULT.

    `cadence_for` chooses what the landing will RUN, so every ambiguity there
    resolves to FULL — running more than you owed costs time and nothing else.
    The hook is not choosing what to run. It is asking one thing: "is this
    commit an x.y.0 MILESTONE, so that a patch-grade stamp must not satisfy
    it?" A tree whose manifest cannot be read is not a milestone anyone
    identified; it is a tree the question does not apply to. Answering FULL
    there would refuse EVERY push from any checkout where this program cannot
    run — including the synthetic repos the hook's own tests drive — and a hook
    that refuses everything is a hook people bypass, which is the failure this
    repo has already paid for once.

    THE MILESTONE HOLE STAYS CLOSED ANYWAY, because the LANDING mints the
    stamp. For a real x.y.0 tree, `cadence_for` returns FULL whether it read
    the version or merely failed to, so gatekeeper-land.sh runs the whole tree
    and writes `cadence=FULL`. A TARGETED stamp for a milestone can therefore
    only exist if this program RAN on the landing host and said TARGETED for an
    x.y.0 bump, which is the case this function is here to catch. The residual
    gap is exactly: the program works when the stamp is minted and is broken
    when the same checkout is pushed. It is named here rather than papered over.
    """
    try:
        gr = _gatekeeper_review()
        cur = gr._git_show_json_version(repo, head, gr._PLUGIN_JSON_REL)
        prev = gr._git_show_json_version(repo, base, gr._PLUGIN_JSON_REL)
    except Exception:
        return "unknown"
    if cur is None:
        return "unknown"
    try:
        cadence, _ = gr.derive_cadence(cur, prev)
    except Exception:
        return "unknown"
    if cadence == "FULL":
        return "yes"
    if cadence == "TARGETED":
        return "no"
    # NONE means the version at HEAD did not parse as semver. That is not a
    # milestone and it is not a patch either -- it is unreadable, and it says so.
    return "unknown"


def tree_test_files(plugin_root: Path) -> List[str]:
    """Every test file the full suite would collect, plugin-root-relative.

    ``pytest.ini`` pins ``testpaths = programs/tests`` (one tree, guarded by
    single_testpath_guard.py), so that tree IS the full suite here.
    """
    tree = plugin_root / _TEST_TREE
    if not tree.is_dir():
        return []
    return sorted(
        str(p.relative_to(plugin_root))
        for p in tree.rglob("test_*.py")
    )


def read_selection(path: Path) -> List[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return sorted({ln.strip().rstrip("/") for ln in lines if ln.strip()})


#: The stages that, TOGETHER WITH `run_pytest`, make a landing reach every
#: tracked test file, and the literal that proves each is still wired into
#: `tools/gatekeeper-land.sh`. `run_pytest` alone reaches ONE of the five trees
#: (`ci_targeted_test_select.py:357 _TESTS_REL = "programs/tests"`), so the
#: full-suite claim below is only true while these are present. Deleting a
#: stage must move the landing's own description back to `subset`, not leave it
#: asserting a coverage nobody runs.
_SIBLING_STAGES = (
    ("run_repo_tools_pytest",
     "the repo-root tools/ tree (vibe-ic#1312)"),
    ("run_unselectable_pytest",
     "the git-derived COMPLEMENT — every tracked test file no other stage "
     "reaches: skills/*/tests, mcp-eda/test, tools/phase1_engine/tests, "
     "_shared (vibe-ic#1424)"),
)


def _landing_covers_the_rest(plugin_root: Path) -> Tuple[bool, str]:
    """Is every stage that covers the trees `run_pytest` cannot still wired?

    EARNED FROM `tools/gatekeeper-land.sh`, not assumed. This is the same
    `probe` idea `landing_unselectable_pytest_corpus._covered()` uses for the
    same reason: a stage that is deleted or renamed must not be able to quietly
    remove its tree from a completeness claim, because that removal is in the
    safe-looking direction.
    """
    land = None
    for anc in (plugin_root, *plugin_root.parents):
        cand = anc / "tools" / "gatekeeper-land.sh"
        if cand.is_file():
            land = cand
            break
    if land is None:
        return False, ("tools/gatekeeper-land.sh is not reachable from "
                       f"{plugin_root} — the sibling stages cannot be verified")
    try:
        text = land.read_text(encoding="utf-8", errors="replace")
    except OSError as e:                                    # pragma: no cover
        return False, f"tools/gatekeeper-land.sh unreadable ({e.__class__.__name__})"
    absent = [f"{name} ({why})" for name, why in _SIBLING_STAGES
              if name not in text]
    if absent:
        return False, ("landing stage(s) absent from gatekeeper-land.sh, so "
                       f"the trees they cover are unrun: {absent}")
    return True, f"all {len(_SIBLING_STAGES)} sibling stage(s) wired"


def describe(plugin_root: Path, selection: Path) -> Tuple[str, str, str]:
    """Return (scope, pytest_cmd, why) for the selection ACTUALLY about to run.

    ``full`` only when the selection covers every test file in the tree the
    selector can emit, AND the sibling stages that cover the other four trees
    are still wired. The comparison is by MEMBERSHIP, not by count: two sets of
    equal size that differ by one file are not the same run, and a count-only
    check would call a swap complete (the 'guard that compares counts'
    failure).

    THE FULL-SUITE COMMAND NAMES EVERY TIER, and that is not verbosity either.
    It used to be `python3 -m pytest -q programs/tests`, which was accepted as
    the full suite because `full_suite_run_check` judged the ARGUMENT SHAPE —
    a directory under the single testpath read as complete. Under the
    2026-08-31 ruling that string covers ONE of five trees and is refused, so
    the landing must describe what it really ran: `run_pytest`'s tree plus the
    trees `run_repo_tools_pytest` and `run_unselectable_pytest` reach, which
    together are the whole tracked corpus. The tier list is DERIVED from that
    corpus (`full_suite_run_check.covering_dirs`), so it cannot drift from the
    population the classifier will measure it against.

    THE SUBSET COMMAND LISTS THE REAL FILES, and that is not verbosity: only
    file-level paths make the classifier say subset for certain, and they
    happen to also be the literal truth.
    """
    tree = set(tree_test_files(plugin_root))
    sel = set(read_selection(selection))

    def _subset(paths):
        return "python3 -m pytest -q " + " ".join(sorted(paths))

    if not tree:
        # No tree to compare against: cannot certify completeness, so do not.
        return ("subset", _subset(sel) if sel else "python3 -m pytest -q --no-selection.py",
                "the test tree is empty or unreadable — not certifiable as full")
    missing = tree - sel
    if missing:
        return ("subset", _subset(sel),
                f"selection covers {len(sel & tree)} of {len(tree)} test file(s); "
                f"{len(missing)} not selected")

    wired, why_wired = _landing_covers_the_rest(plugin_root)
    if not wired:
        return ("subset", _subset(sel),
                f"selection covers all {len(tree)} file(s) of {_TEST_TREE}, but "
                f"{why_wired}")

    fsr = _full_suite_run_check()
    pop = fsr.population(plugin_root)
    if pop is None:
        return ("subset", _subset(sel),
                f"selection covers all {len(tree)} file(s) of {_TEST_TREE}, but "
                "the tracked corpus could not be derived from git, so the "
                "landing's total coverage cannot be certified")
    tiers = fsr.covering_dirs(pop)
    return ("full", "python3 -m pytest -q " + " ".join(tiers),
            f"selection covers all {len(tree)} file(s) of {_TEST_TREE} and "
            f"{why_wired}; together the stages run all {len(pop)} tracked test "
            f"file(s) across {len(tiers)} tier(s)")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Derive the landing's required test cadence from the "
                    "version bump in the tree (chip-AGNOSTIC). There is no "
                    "--cadence flag: the tree decides, not the caller.")
    ap.add_argument("--repo", default=None, help="repository root")
    ap.add_argument("--base", default=None, help="base git ref")
    ap.add_argument("--head", default=None, help="head git ref")
    ap.add_argument("--plugin-root", default=None,
                    help=f"plugin root holding {_TEST_TREE} (--describe)")
    ap.add_argument("--selection", default=None,
                    help="the selection file about to be executed (--describe)")
    ap.add_argument("--describe", action="store_true",
                    help="describe the SELECTION's true scope and pytest command")
    ap.add_argument("--milestone-check", action="store_true",
                    help="answer the push hook's narrower question: is this an "
                         "x.y.0 MILESTONE? yes|no|unknown. See milestone_check().")
    ap.add_argument("--emit-full-selection", action="store_true",
                    help="print every test file in the tree, one per line — the "
                         "FULL cadence's selection. Shares tree_test_files() "
                         "with --describe on purpose: the list that is RUN and "
                         "the list completeness is judged against must be the "
                         "same list, or the landing could run one and certify "
                         "the other.")
    args = ap.parse_args(argv)

    if args.milestone_check:
        if not (args.repo and args.base and args.head):
            print("ERROR: --milestone-check requires --repo, --base and --head",
                  file=sys.stderr)
            return 2
        print("LANDING_MILESTONE="
              + milestone_check(Path(args.repo).resolve(), args.base, args.head))
        return 0

    if args.emit_full_selection:
        root = Path(args.plugin_root).resolve() if args.plugin_root \
            else _PLUGIN_ROOT_DEFAULT
        files = tree_test_files(root)
        if not files:
            print(f"ERROR: no test files under {root / _TEST_TREE}", file=sys.stderr)
            return 2
        print("\n".join(files))
        return 0

    if args.describe:
        if not args.selection:
            print("ERROR: --describe requires --selection", file=sys.stderr)
            return 2
        root = Path(args.plugin_root).resolve() if args.plugin_root \
            else _PLUGIN_ROOT_DEFAULT
        scope, cmd, why = describe(root, Path(args.selection))
        print(f"LANDING_TEST_SCOPE={scope}")
        print(f"LANDING_PYTEST_CMD={cmd}")
        print(f"LANDING_TEST_SCOPE_WHY={why}")
        return 0

    if not (args.repo and args.base and args.head):
        print("ERROR: --repo, --base and --head are required", file=sys.stderr)
        return 2
    cadence, why = cadence_for(Path(args.repo).resolve(), args.base, args.head)
    print(f"LANDING_CADENCE={cadence}")
    print(f"LANDING_CADENCE_WHY={why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
