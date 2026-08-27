#!/usr/bin/env python3
"""ci_harness_timeout_ceiling_check.py — a test's own subprocess timeout must
be able to FIRE under the pytest harness that bounds it.

THIS GATE BLOCKS (rc=1).

WHY THIS GATE EXISTS
--------------------
CI runs the targeted subset as::

    xargs -a /tmp/sel.txt pytest -q --maxfail=10 --timeout=180 \\
        --timeout-method=thread

``--timeout-method=thread`` does not fail the TEST when the bound is reached.
It dumps every thread's stack and takes the whole PROCESS down. So a test that
permits its own subprocess 900 s can never reach that bound: pytest kills the
SESSION at 180 s first, and the consequences are all worse than one red test:

  * ``--maxfail`` stops applying — there is no session left to count in;
  * no per-test diagnostic is printed, so the culprit is identified only by a
    stack dump;
  * every OTHER file in that subset loses its verdict, including files that had
    already passed.

That is how v1.7.92 went red: the session died at file 18 of 53 and the twelve
files after it were never run, so nobody knew whether they passed. And the exit
code cannot be used to tell the two apart — ``xargs`` maps any inner exit in
1..125 onto 123, so an ordinary assertion failure and a session kill are the
same number to the caller.

WHY IT READS THE BOUND INSTEAD OF STATING IT
--------------------------------------------
A number derived from the workflow and written into a source file is a second
copy of a value that file cannot see — the drift shape vibe-ic#527, #530 and
#534 each spent a version removing from waiver registries. Two hand-copies of
``= 180`` were already on main when this gate was written, in two different
test files, neither of which could notice if the workflow changed.

So the bound is RESOLVED from ``.github/workflows/*.yml`` on every run. Doing
that immediately found something no hand-copy knew: there is not ONE harness
bound, there are FOUR pytest invocations across two workflows, and they do not
agree --- the targeted subsets bound a test at 180 s and the milestone
full-suite jobs bound it at 300 s. Every file under the scanned tree is
reachable by BOTH, so the binding bound is the MINIMUM, and a check that had
copied any single number would have been describing one lane of four.

THE CEILING IS A FRACTION OF THE BOUND, NOT A HAIR UNDER IT
------------------------------------------------------------
"below the harness bound" is not enough. A call bounded at 179 s under a 180 s
harness still consumes the entire budget, so the harness has no room left to
report and everything scheduled after it is starved exactly as before.

MEASURED on this tree (``--table`` prints the same census): of the 253 test
functions that carry any bounded call, 230 carry exactly one — but 19 carry
two, two carry three, one carries four and one carries five. A ceiling of
``bound / 2`` clears the prior art's stated reason ("the harness must have room
to REPORT") and still lets a two-call test reach 2 x 89 = 178 s, which dies. A
ceiling of ``bound / 3`` lets a test spend TWO full-length bounded calls and
keeps a third of the budget for fixture setup and for the harness to report.

That is why the divisor is 3 and not 2. It is a NECESSARY condition and this
gate says so rather than implying more: bounding one call cannot by itself
bound a test's total wall time, because a loop can make the same call N times.
What it does guarantee is that no single call can outlive the harness, which is
the whole of the defect it was written for.

WHAT IS FLAGGED, AND WHY THE CALLEE SET IS AN ALLOWLIST
--------------------------------------------------------
The reproduce command in the report was a grep, and a grep cannot tell a bound
from a mention: it matches ``def runner(cmd, timeout=3600)`` — a test double's
signature, which never blocks anything. Parsing with ``ast`` removes that class
for free, because a function-definition default is not a ``Call`` node.

But a CALL to a double still looks like a call, so the callee is resolved and
only the ones that can really block are judged:

  * the process-launching ``subprocess`` API — ``run`` / ``check_output`` /
    ``check_call`` / ``call`` / ``Popen`` — reached through whatever alias the
    file imported it under (``import subprocess as sp`` -> ``sp.run``,
    ``from subprocess import run`` -> a bare ``run``), NEVER by assuming the
    module is spelled ``subprocess``;
  * the two blocking ``Popen`` methods that accept a timeout, ``communicate``
    and ``wait``;
  * container invocations, recognised by a ``docker`` element in the callee
    name: a container run is a process launch by construction;
  * a helper DEFINED IN THE SAME FILE that forwards a timeout into one of the
    above -- either through a named parameter or by splatting its own
    ``**kwargs`` into the call, which is how the most common wrapper in this
    corpus is written and how the first draft of this gate missed one. DERIVED
    by parsing, not listed, and iterated to a fixed point so a helper calling a
    helper is still resolved.

Deliberately NOT flagged, because they record a bound rather than impose one:
``subprocess.TimeoutExpired(cmd, timeout=300)`` and its sibling exception
constructors, which a naive walk reads as a 300 s bound; and any callee whose
body this file cannot see.

The excluded set is not silent. Every unresolved callee at or above the ceiling
is COUNTED and PRINTED as advisory with its file and line, so a reader can see
what the allowlist did not judge instead of inferring it from a clean verdict.

A BOUND IS A BOUND WHATEVER ITS SPELLING (vibe-ic#1277)
--------------------------------------------------------
The bound is read from the call site, from a module constant, AND from the
enclosing function's PARAMETER DEFAULT. The third was missing and it was the
worst of the three to miss, because the shape is ordinary::

    def _run(args, timeout=180):
        return subprocess.run([...] + args, timeout=timeout)

A default is not a ``Constant`` at the call site and not a module constant, so
until #1277 that call fell through the resolver entirely — and "entirely" is
the point. It was not moved to the advisory list where a reader could see it;
it was DROPPED, out of the findings, out of the advisories, and out of the
``readable bound(s) at call sites`` denominator. Two spellings of the same
1800 s bound produced ``1 readable bound / 1 FAIL`` and ``0 readable bounds /
0 not judged / PASS``. The second report tells a reader nothing was skipped.

The function-definition default is still NOT a bound on its own — a test
double's ``def runner(cmd, timeout=3600)`` whose body launches nothing is
flagged by nobody, exactly as before. What is judged is the CALL the parameter
reaches, and only when the callee allowlist above says that call can block.
A default is refused when the function's own body rebinds the name, for the
same reason ``module_constants`` refuses a function-local assignment.

…AND JUDGED AGAINST THE BOUND THAT WILL REALLY APPLY TO IT
------------------------------------------------------------
``harness // 3`` is right only while ``--timeout=180`` is the bound the harness
puts on the item. For a test carrying ``@pytest.mark.timeout(N)`` it is not:
pytest-timeout applies N to that item, which is what the marker is for and what
this repo already relies on. Such a call is judged against ``N // 3``. That is
the gate's own second remedy — "move the test out of the targeted subset if it
genuinely needs longer" — finally having a spelling the gate can read, and it
cuts both ways: a marker BELOW the harness bound tightens the ceiling. Every
marked item is counted and printed with its value, because raising a ceiling
must be a visible act.

A module-level ``pytestmark`` is read the same way and for a reason a per-test
decorator cannot cover: a finding lands at the LAUNCHER call, and in this
corpus that call usually lives in a module-level ``_run`` helper every test in
the file shares. No decorator on one test governs a helper the other nine also
call; ``pytestmark`` bounds every item in the module, so every call in it does
run inside an item bounded at N. Verified rather than assumed —
``pytestmark = pytest.mark.timeout(30)`` under ``--timeout=2
--timeout-method=thread`` yields ``2 passed``, not a killed session.

THE POPULATION IS EVERY TREE A PYTEST LANE RUNS, WHICH IS TWO
--------------------------------------------------------------
The report named one tree. The workflows run two: the plugin's
``programs/tests`` and the repo's ``tools``. They are scanned with different
globs, and the difference is stated rather than being a silent inconsistency —
see ``TOOLS_DIR_REL`` for the measurement behind it. Each root's file count is
printed on every run, so a root that stops resolving shrinks a number a reader
can see rather than quietly leaving the denominator.

…AND THE ROOT IS THE CHECKOUT THIS FILE IS IN, WHICH IS NOT A DETAIL
---------------------------------------------------------------------
``find_repo_root`` used to climb until it found ``.github/workflows``. Since
#550 that directory is not in the repository at all, so in a worktree nested
under another checkout — which is where every agent in this project works — the
walk left its own tree and answered about the ENCLOSING one, and in a fresh
clone it answered ``None`` and every dependent test skipped. Neither symptom
is visible in the verdict, and they point in opposite directions: one reports
confidently about files the caller never touched, the other reports nothing at
all. The walk now stops at a checkout boundary.

chip-AGNOSTIC: pure Python/YAML structure. No design, PDK, vendor or process
literal appears here.

USAGE
-----
    python3 ci_harness_timeout_ceiling_check.py [ROOT] [--tests-root PATH]
                                                [--table] [--json OUT]

EXIT CODES
----------
    0 = PASS   1 = FAIL (a bound above the ceiling)
    2 = CANNOT DETERMINE (no workflow bound, or nothing to scan) -- not a pass

When the local landing gate uses ``pytest_per_file_junit.py`` for every pytest
lane, this program instead validates that semantic-progress contract: no fixed
pytest timeout, output/CPU activity cannot renew the lease, and the watchdog's
whole-run ceiling is infinite.  Inner diagnostic subprocess bounds can then
fire without ever being eclipsed by an outer elapsed-time verdict.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# --- the harness bound, resolved ------------------------------------------

#: Where the pytest harness bounds are declared. Relative to the REPO root.
WORKFLOW_DIR_REL = ".github/workflows"

#: …and where they are declared now that GitHub Actions is retired (#550:
#: `Actions has been disabled for this user.`, appeal rejected). `ci.yml` and
#: `gatekeeper-ci.yml` moved to `.github/workflows-disabled/`, and the harness
#: that actually runs pytest is the local landing script. Resolving from BOTH
#: keeps this check honest either way: it does not assume CI is dead, and it
#: does not assume CI is alive. Losing its only source is what surfaced the gap
#: — it reported CANNOT DETERMINE (rc 2) rather than passing, which is the
#: behaviour that made the omission visible instead of silent.
#:
#: `gatekeeper-verify-merge.sh` was missing from this tuple until vibe-ic#1417.
#: It runs a REAL pytest harness — arm A1, the base side of the landing
#: differential — at its own `--timeout=`, and being unlisted meant this gate
#: could not see it. Both bounds read 180 today, so listing it changes no
#: ceiling; what it removes is the second undeclared copy of the number, which
#: is the drift shape #527/#530/#534 each spent a version removing. An arm
#: whose bound nothing resolves is an arm whose reds nobody can attribute to an
#: envelope — #1417's own conclusion about why two honest sweeps disagree.
EXTRA_HARNESS_RELS = (
    "tools/gatekeeper-land.sh",
    "tools/gatekeeper-verify-merge.sh",
    ".github/workflows-disabled",
)

#: `pytest ... --timeout=N` / `--timeout N`, anywhere in one logical shell
#: command. Continuation lines are joined before matching so a bound written
#: on the line after `pytest` is still found.
_PYTEST_RE = re.compile(r"(?<![\w.-])pytest(?![\w.-])")
_TIMEOUT_RE = re.compile(r"--timeout[= ](\d+)")
_ELAPSED_WRAPPER_RE = re.compile(r"(?<![\w.-])timeout(?![\w.-])")
_DRIVER_COMMAND_RE = {
    # `PYTHONDONTWRITEBYTECODE=1` IS REQUIRED OF ALL THREE, NOT TWO.
    # `run_unselectable_pytest` has always required it here. The other two
    # gained it when the tier's independent stages started running at the same
    # time: `python3 -I` does not imply `-B`, so a lane that writes bytecode
    # into $ROOT changes `gate_host_independence_check`'s untracked+ignored
    # stimulus set — and under concurrency it changes it WHILE another lane is
    # measuring it. Requiring the token rather than merely tolerating it means
    # deleting it again is a policy change with a red test, not a silent
    # reintroduction of an ordering hazard.
    "run_pytest": re.compile(
        r'^\s*if\s+out="\$\(\s*cd\s+"\$PLUGIN"\s+&&\s+'
        r'PYTHONDONTWRITEBYTECODE=1\s+'
        r'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1\s+python3\s+'
        r'programs/pytest_per_file_junit\.py(?=\s)'),
    "run_repo_tools_pytest": re.compile(
        r'^\s*out="\$\(\s*cd\s+"\$ROOT"\s+&&\s+'
        r'PYTHONDONTWRITEBYTECODE=1\s+'
        r'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1\s+python3\s+'
        r'"\$PROGRAMS/pytest_per_file_junit\.py"(?=\s)'),
    "run_unselectable_pytest": re.compile(
        r'^\s*out="\$\(\s*cd\s+"\$ROOT"\s+&&\s+'
        r'PYTHONDONTWRITEBYTECODE=1\s+'
        r'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1\s+python3\s+'
        r'"\$PROGRAMS/pytest_per_file_junit\.py"(?=\s)'),
}
# Exact shipped function bodies are the control-flow contract.  A regex can
# recognize a reassuring command that lives under ``if false``, inside a
# never-called nested function, or even in heredoc data.  Hashing the complete
# reviewed bodies turns every such control-flow rewrite into an explicit policy
# change that the parent-side landing differential can review; there is no
# permissive "looks command-like" fallback.
_LANDING_LANE_SHA256 = {
    "run_pytest":
        "e0b1e4f3337466370e4a8d992ab48aa59bd08db4183e5149ee5d921c284114ed",
    "run_repo_tools_pytest":
        "fafa41bc22777096f5a60601f755830b5744ef57e67f92fd1391fa730834c8fd",
    "run_unselectable_pytest":
        "70d7764ca0c83843f0b66a4e768c0ca5b874589894f1c688cb2d831b17863e78",
}
# Entry-to-last-lane control flow is reviewed as one indivisible contract.
# Hashing only the three function definitions is insufficient: their exact
# bodies can remain present while a top-level ``exit``, ``false && call``, or a
# later function redefinition makes every call a no-op.  This prefix ends at
# the point by which every required invocation has been reached, so any
# executable rewrite that can affect reachability must be reviewed together
# with a new digest.
#: WHERE THAT PREFIX ENDS, now that the three lanes are not column-zero calls.
#:
#: It used to end at the bare `run_unselectable_pytest` line — the last of the
#: three populations, invoked at top level, so "everything up to here" was
#: exactly the control flow that decides whether all three run. The full tier's
#: independent stages now run AT THE SAME TIME: `lane_run_window` launches the
#: lanes and `lane_emit_window` joins every one of them and prints its verdict,
#: so the populations are reached through the lane bodies and no population is
#: a top-level call any more. Anchoring on the old shape did not weaken the
#: rule, it ABOLISHED it: no line matched, the prefix was never computed, and
#: the only thing printed was "must invoke … at its reviewed top-level call
#: site".
#:
#: `lane_emit_window` is the replacement and it is not a weaker anchor. It is
#: the single top-level line by which every lane has been both dispatched AND
#: joined, so a prefix ending there still contains every byte that decides
#: whether the three populations run: their bodies, the lane bodies that call
#: them, the launcher, the window, and everything before them.
_LANDING_WINDOW_ANCHOR = "lane_emit_window"
_LANDING_EXECUTION_PREFIX_SHA256 = (
    "f9f176413f7d1e278c02d205bc02744799838137cab9f3e7c5901c3eee2425de"
)
# RE-PINNED when the landing gained its runtime PREFLIGHT. Both digests below
# moved for one reason and it is stated here rather than left to `git log`: the
# three lanes' bodies are byte-identical (their digests above did not move), and
# what changed is the control flow ahead of them — a fatal `rc 2` refusal that
# runs `landing_pytest_runtime_preflight.py` before the first arm, so a host on
# which the isolated trusted entry cannot import the runner refuses ONCE with a
# named cause instead of reporting NORECORD for every file in all three arms.
# Both new digests are DERIVED from the reviewed script by this file's own
# `landing_semantic_progress_contract` rule, never hand-transcribed.
#
# A prefix proves the required calls are reached; the complete script proves a
# later rewrite cannot erase their verdict (for example ``FAILED=0`` or an
# early successful exit after the third call).  Gate control-flow changes are
# intentionally an explicit policy migration, never a heuristic match.
#
# RE-PINNED AGAIN at v1.11.5, and this migration is a RATCHET THAT WAS LEFT
# UNTURNED rather than a new policy. The three pins here had been stale since
# 0060d835 and kept SIX tests in `test_ci_harness_timeout_ceiling_check.py` red
# on `main`, plus the hygiene gate "inner timeouts fit the harness" — across six
# landings, none of which the drift was about. A permanently-red contract check
# is a contract check nobody reads.
#
# WHAT MOVED, reviewed rather than absorbed:
#   * `tools/gatekeeper-land.sh` (both digests above and below): ONE commit,
#     eda53573 (v1.11.2), which inserts `landing_tier_checkout_preflight.py`
#     and a fatal `exit 2` AHEAD of the arms so a full tier refuses to start in
#     a checkout a third party can unregister mid-run. It adds a refusal in
#     front of the lanes; it removes, reorders and rewrites none of them — and
#     the three `_LANDING_LANE_SHA256` bodies did NOT move, which is this
#     file's own independent witness that the lane bodies are byte-identical.
#   * the semantic driver: five landed fixes to `pytest_per_file_junit.py`
#     (3e6c1bfc, f96494b8, 732e0ee3, fe132795, 2b93d872) plus the progress-scan
#     rewind that ships with this commit. Each was reviewed at its own landing;
#     what nobody did afterwards was turn this ratchet.
#
#
# RE-PINNED AGAIN on 2026-08-21, for the landing review. Both digests moved and
# the three `_LANDING_LANE_SHA256` bodies did NOT, which is this file's own
# independent witness that no lane body was touched.
#
# WHAT MOVED, reviewed rather than absorbed:
#   * INSIDE the prefix (so it is control flow, and reviewed as such): the
#     hygiene `--summary-json` record became UNCONDITIONAL — it used to be
#     written only when `GATEKEEPER_HYGIENE_REPORT` named a path — and
#     `lane_emit_window` gained one assignment, `GK_HYG_RC="$EMIT_RC"`, kept
#     because the record says WHICH gates were red and only the rc says the set
#     finished. Neither removes, reorders nor rewrites a lane; neither adds an
#     exit; the window still launches and joins exactly the same lanes.
#   * AFTER the anchor (so it is in the whole-file digest only): a new
#     `full:gatekeeper-review` unit between `full:plugin-audit` and
#     `full:write-guard-final`. It runs `gatekeeper_review.py` under a 240 s
#     budget and maps a timeout — and every unexpected exit status — to rc 2
#     UNDETERMINED, blocking. It is deliberately outside the prefix: it cannot
#     affect whether the three populations run, and the prefix exists to pin
#     exactly that.
#
#
# RE-PINNED AGAIN, same day, because the two paragraphs above describe a wiring
# that did not survive its own gates. `--hygiene-record-in` was a command-line
# way to hand `gatekeeper_review`'s hygiene gate a substitute for running it,
# and two gates that exist for exactly that were red about it. Both digests
# moved again; the three `_LANDING_LANE_SHA256` bodies did NOT, which is again
# this file's own independent witness that no lane body was touched.
#
# WHAT MOVED, reviewed rather than absorbed:
#   * INSIDE the prefix: the caller's `GATEKEEPER_HYGIENE_REPORT` is passed to
#     `--summary-json` at the call site again instead of through a `:-`
#     default, and the record stays unconditional in the other branch — the
#     two are different contracts and only the first has a reader outside this
#     process. `lane_emit_window` LOST the `GK_HYG_RC="$EMIT_RC"` assignment
#     the paragraph above added, because the only thing that read it was the
#     flag that is gone. Neither removes, reorders nor rewrites a lane;
#     neither adds an exit; the window still launches and joins exactly the
#     same lanes.
#   * AFTER the anchor: `full:gatekeeper-review` no longer passes a record to
#     the review, so the review runs the hygiene set, and the budget it is
#     given moved from 240 s to 1800 s — `repo_hygiene_gate`'s own
#     `_HYGIENE_STALL_GRACE_S`, below which this `timeout` would kill runs the
#     gate itself still considers alive. A timeout is still rc 2 UNDETERMINED
#     and still blocking; that half did not move and is what
#     `tools/test_gatekeeper_land_review_budget.py` drives.
#
# RE-PINNED a third time, and ONLY the whole-file digest: the edit is a comment
# BELOW the `lane_emit_window` anchor, correcting what 1800 s bounds (the
# review's supervisor, not the hygiene set's 300 s shard watchdog). The
# execution-prefix digest did NOT move, which is this file's own witness that
# the change is downstream of the anchor and touches no control flow.
#
#
# RE-PINNED a fourth time. WHAT MOVED, and the witness that nothing else did:
# the whole-file digest and the execution prefix moved, and of the three lane
# bodies ONLY `run_repo_tools_pytest` did — `run_pytest` and
# `run_unselectable_pytest` are byte-identical, which is this file's own
# independent evidence that no other lane was touched.
#
# THE EDIT, reviewed rather than absorbed: `run_repo_tools_pytest`'s discovery
# gains one `-path 'tools/harvest' -prune -o` clause. `tools/harvest/` holds
# RESCUE SNAPSHOTS of another workspace's untracked tree; the three test files
# under it import fixtures that live beside them there, so `find` selected them
# and all 30 of the stage's ERRORs were theirs. Nothing else in the function
# moved: same guard, same snapshot/compare, same runner, same flags, same
# vacuous-corpus refusal, same write-guard. The prefix digest moved only
# because the function is defined above the anchor.
#
# IT IS A PRUNE OF ONE DIRECTORY, NEVER A FILE LIST, and it is checked in both
# directions by `tools/test_repo_tools_discovery_prunes_harvest.py` — including
# a control that goes red if `tools/harvest/` ever stops holding a test file,
# because a prune whose subject has vanished is a no-op that still reads as a
# guard.
#
# RE-PINNED a fifth time, for the TEST-CADENCE WIRE. Three digests moved: the
# whole file, the entry-to-final-pytest execution prefix, and `run_pytest`.
#
# THE WITNESS THAT NOTHING ELSE DID, and it is this file's own: of the three
# lane bodies, `run_repo_tools_pytest` and `run_unselectable_pytest` are
# BYTE-IDENTICAL. Only `run_pytest` moved, which is exactly the one lane the
# edit touches. The prefix moved because `run_pytest` is defined above the
# `lane_emit_window` anchor and because the cadence is derived near the top of
# the script, before any lane starts.
#
# THE EDIT, reviewed rather than absorbed: the landing now DERIVES its required
# test cadence from the version bump in the tree (x.y.0 MILESTONE -> FULL,
# x.y.Z PATCH -> TARGETED) via `landing_cadence.py`, which imports
# `gatekeeper_review.derive_cadence` rather than restating it. `run_pytest`
# gains one branch: at FULL the selection is the whole `programs/tests` tree,
# otherwise it is the same `ci_targeted_test_select.py` subset it has always
# been. Nothing about SUPERVISION moved — same driver, same `--stall-after`,
# same `--aggregate-check`, same no-ceiling contract, same write guard, same
# junit. The stage still declares SEMANTIC PROGRESS and still carries no
# elapsed-time bound, which is the property this file exists to hold.
#
# RE-PINNED a sixth time, for the BATCH FLAG THE REVIEW WAS NEVER TOLD. ONE
# digest moved: the whole file. Not the prefix, not any lane body, not the
# semantic driver.
#
# THE WITNESS THAT NOTHING ELSE DID, enumerated from this file rather than from
# a diff, because three of four re-pinned is the same as none — this is a
# conjunction. The edit is inside `run_gatekeeper_review`, which is defined at
# line 1685, and the `lane_emit_window` anchor is line 1577: the execution
# prefix ends BEFORE the edit, so it is byte-identical, and so are all three
# lane bodies (defined at 891 / 1175 / 1278) and `pytest_per_file_junit.py`.
# Each of the four inputs was recomputed by slicing exactly as
# `landing_semantic_progress_contract` slices them; three came back equal.
#
# THE EDIT, reviewed rather than absorbed: `cheap:landing-shape` counts the
# range and, above one commit, already runs `landing_is_one_commit_check.py
# --batch` and passes. The review then ran the SAME checker again through
# `gatekeeper_review.one_commit_gate` and was handed no flag, so one caller
# called a tree a valid batch and the other called it an illegal landing inside
# one gate run. A ceremony landing is structurally at least three commits, so
# the un-forwarded form had no passing case at all. `run_gatekeeper_review` now
# forwards the condition the script had already computed, as an array expanded
# with the file's existing `"${arr[@]+...}"` guard.
#
# IT IS NOT A RELAXATION AND IT IS NOT A `--hygiene-record-in`. Batch mode asks
# a STRICTER question — no manifest-only commit in the range, exactly one
# version bump, and that bump on the TIP — and it stays opt-in, so a single
# landing is judged exactly as before. Nothing about SUPERVISION moved: same
# driver, same `--stall-after`, same `--aggregate-check`, same no-ceiling
# contract, same write guard, same junit, same lanes.
#
# Every digest here is DERIVED — this file run over the reviewed tree, and the
# sha256 it reports read back — never hand-transcribed.
_LANDING_SCRIPT_SHA256 = (
    "6118f25ccad0388d8c95c821c2fadc539b1d8209db8f2d2c93eeab0a5f3a9f65"
)
# The helper AST is not enough: a counterfeit CLI can define the expected
# helper and never call it.  Bind the policy to the complete reviewed driver
# whose functional tests prove selection -> aggregate JUnit coverage.
# RE-PINNED 2026-08-24, and it is the FOURTH digest in this file to move for one
# edit. The other three (whole file / execution prefix / run_repo_tools_pytest)
# were re-pinned when `gatekeeper-land.sh` changed; THIS one pins the SEMANTIC
# DRIVER, `pytest_per_file_junit.py`, and it was missed in that same round.
#
# WHAT MOVED: the driver's domain-progress scope guard, which was a flat cap of
# 64 distinct `(nodeid, scope)` keys per session and is now split into a
# per-node rule plus a ceiling derived from what the session actually collected.
# The guard still refuses a runaway single test; it no longer refuses a large
# honest selection. Nothing about supervision, timeouts or the JUnit contract
# this file checks moved with it.
#
# THE COST OF MISSING IT, RECORDED: the edit landed as v1.11.74 with only the
# ten directly-related tests run, so `inner timeouts fit the harness` went red
# on main and stayed red until someone read a hygiene report. A digest pin is
# exactly the check that catches this, and it did — one landing later than it
# should have.
_SEMANTIC_DRIVER_SHA256 = (
    "da77e90942aff5ff9f61aff7683a17eb477a5fbdf4dfcffac17f954e58c8125f"
)
#: `pip install pytest-timeout` names the plugin, not a bound; it carries no
#: `--timeout=N` and so cannot match, but the negative is stated because a
#: future looser pattern would pick it up.

#: The harness bound is divided by this to get the per-call ceiling. See the
#: module docstring: 2 clears the prior art's "room to REPORT" reason and still
#: dies on the two-call shape that 19 test functions in this corpus have; 3
#: survives two full-length calls and keeps a third of the budget in reserve.
CEILING_DIVISOR = 3

#: Scanned population, relative to the plugin root.
TESTS_DIR_REL = "programs/tests"

#: The SECOND tree a pytest lane runs (`pytest -q tools` in the milestone job),
#: and the reason it is scanned with a narrower glob than the first.
#:
#: Everything under `programs/tests/` exists to be run by pytest, helpers
#: included — which is why that root is scanned as `*.py`, and it earned its
#: keep: `matrix_d4_probe.py` is not a `test_` file and carried a 90 s bound
#: that five test files spend. `tools/` is not like that. It mixes production
#: entry points with their tests in one directory, and a production tool's
#: timeout is its RUNTIME behaviour, not a bound the harness ever imposes.
#: Measured: 66 `.py` under `tools/`, 15 readable bounds, 4 above the ceiling —
#: all four in `flow_runner.py` / `phase1_menu.py` / `pipeline_run.py`, none of
#: which pytest ever executes. Lowering those would change what the tools do.
#: So this root is scanned as `test_*.py`, and the exclusion is stated here
#: rather than being a silent difference between two globs.
TOOLS_DIR_REL = "tools"
TOOLS_GLOB = "test_*.py"


class HarnessBound:
    """One `pytest --timeout=N` declared by a workflow."""

    def __init__(self, workflow: str, line: int, seconds: int, command: str):
        self.workflow = workflow
        self.line = line
        self.seconds = seconds
        self.command = command

    def as_dict(self) -> Dict:
        return {"workflow": self.workflow, "line": self.line,
                "seconds": self.seconds, "command": self.command}


def _strip_shell_comment(raw: str) -> str:
    """Remove an executable Bash comment without touching quoted ``#``.

    The semantic-lane contract is about what Bash executes, not reassuring
    words after a comment marker.  ``shlex`` is not a Bash parser (notably for
    command substitutions), so keep this deliberately small and exact: Bash
    starts a comment at an unquoted ``#`` that begins a shell word.
    """
    quote: Optional[str] = None
    # A command substitution inside double quotes is a fresh shell parse.  Its
    # comments are executable comments even though the surrounding ``$(...)``
    # sits inside a quoted assignment (the exact false-green this guards).
    substitutions: List[Tuple[Optional[str], int]] = []
    escaped = False
    index = 0
    while index < len(raw):
        char = raw[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and quote != "single":
            escaped = True
            index += 1
            continue
        if quote == "single":
            if char == "'":
                quote = None
            index += 1
            continue
        if char == "'" and quote is None:
            quote = "single"
            index += 1
            continue
        if char == '"':
            quote = None if quote == "double" else "double"
            index += 1
            continue
        if (char == "$" and index + 1 < len(raw)
                and raw[index + 1] == "("):
            substitutions.append((quote, 1))
            quote = None
            index += 2
            continue
        if substitutions and quote is None and char == "(":
            outer, depth = substitutions[-1]
            substitutions[-1] = (outer, depth + 1)
            index += 1
            continue
        if substitutions and quote is None and char == ")":
            outer, depth = substitutions[-1]
            depth -= 1
            if depth == 0:
                substitutions.pop()
                quote = outer
            else:
                substitutions[-1] = (outer, depth)
            index += 1
            continue
        if (char == "#" and quote is None
                and (index == 0 or raw[index - 1].isspace()
                     or raw[index - 1] in ";|&()")):
            return raw[:index]
        index += 1
    return raw


def _logical_lines(text: str) -> Iterable[Tuple[int, str]]:
    """Yield (first_line_number, joined_command) with backslash continuations
    folded, so a flag on a continuation line belongs to its own command."""
    buf: List[str] = []
    start = 0
    for i, raw in enumerate(text.splitlines(), start=1):
        stripped = _strip_shell_comment(raw).rstrip()
        if not buf:
            start = i
        if stripped.endswith("\\"):
            buf.append(stripped[:-1])
            continue
        buf.append(stripped)
        yield start, " ".join(buf)
        buf = []
    if buf:
        yield start, " ".join(buf)


def _semantic_driver_contract_errors(driver: Path) -> List[str]:
    """Validate the executed supervisor call structurally, not by comments."""
    try:
        raw = driver.read_bytes()
        source = raw.decode("utf-8", errors="strict")
        tree = ast.parse(source, filename=str(driver))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return [f"semantic pytest driver cannot be parsed: {exc}"]
    errors: List[str] = []
    observed_digest = hashlib.sha256(raw).hexdigest()
    if observed_digest != _SEMANTIC_DRIVER_SHA256:
        errors.append(
            "semantic pytest driver is not the exact reviewed executable "
            f"(sha256={observed_digest}, expected="
            f"{_SEMANTIC_DRIVER_SHA256})")
    functions = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == "_run_progress_supervised"]
    if len(functions) != 1:
        errors.append("semantic pytest driver must define "
                      "_run_progress_supervised exactly once")
        return errors
    calls = [node for node in ast.walk(functions[0])
             if isinstance(node, ast.Call)
             and ((isinstance(node.func, ast.Attribute)
                   and node.func.attr == "run_supervised")
                  or (isinstance(node.func, ast.Name)
                      and node.func.id == "run_supervised"))]
    if len(calls) != 1:
        errors.append(
            "_run_progress_supervised must call run_supervised exactly once")
        return errors
    keywords = {kw.arg: kw.value for kw in calls[0].keywords
                if kw.arg is not None}
    output = keywords.get("output_progress")
    if not (isinstance(output, ast.Constant) and output.value is False):
        errors.append("semantic pytest driver no longer proves: output bytes "
                      "are not progress")
    domain = keywords.get("domain_progress_probe")
    if not (isinstance(domain, ast.Name)
            and domain.id == "_progress_sample"):
        errors.append("semantic pytest driver no longer proves: validated "
                      "lifecycle is the progress source")
    ceiling = keywords.get("hard_ceiling_s")
    if not (isinstance(ceiling, ast.Call)
            and isinstance(ceiling.func, ast.Name)
            and ceiling.func.id == "float"
            and len(ceiling.args) == 1
            and isinstance(ceiling.args[0], ast.Constant)
            and ceiling.args[0].value == "inf"
            and not ceiling.keywords):
        errors.append("semantic pytest driver no longer proves: there is no "
                      "whole-run elapsed ceiling")
    return errors


def _shell_control_depths(lines: Sequence[str], start: int,
                          end: int) -> Dict[int, int]:
    """A deliberately narrow structural model for the three shipped functions.

    Bash has no stdlib AST.  The landing functions use only ordinary
    ``if/fi``, loops and ``case/esac`` control blocks, so track exactly those
    block boundaries.  A semantic-driver command is accepted only at function
    depth zero; putting the reassuring command under ``if false`` therefore
    cannot satisfy the contract.  ``bash -n`` remains the syntax authority.
    """
    depths: Dict[int, int] = {}
    depth = 0
    for lineno in range(start + 1, end):
        stripped = lines[lineno - 1].strip()
        if not stripped or stripped.startswith("#"):
            depths[lineno] = depth
            continue
        if re.match(r"^(fi|done|esac)\b", stripped):
            depth = max(0, depth - 1)
        depths[lineno] = depth
        if re.match(r"^(if|for|while|until|case)\b", stripped):
            # One-line controls close themselves and do not contain an
            # independently accepted canonical driver command.
            closes = ((stripped.startswith("if ") and re.search(
                r";\s*fi(?:\s*;|\s*$)", stripped))
                or (re.match(r"^(for|while|until)\b", stripped)
                    and re.search(r";\s*done(?:\s*;|\s*$)", stripped))
                or (stripped.startswith("case ")
                    and re.search(r";\s*esac(?:\s*;|\s*$)", stripped)))
            if not closes:
                depth += 1
    return depths


def landing_semantic_progress_contract(repo_root: Path) -> Dict:
    """Validate the local landing pytest lanes' no-fixed-timeout contract.

    This deliberately owns only ``gatekeeper-land.sh``.  The A/B verifier has
    its own two-wave/process-census contract and tests; treating historical
    disabled workflows or a separate orchestrator as this harness's elapsed
    bound is how a dead lane used to constrain the live one.
    """
    root = Path(repo_root)
    land = root / "tools" / "gatekeeper-land.sh"
    driver = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" /
              "programs" / "pytest_per_file_junit.py")
    errors: List[str] = []
    lanes: List[Dict] = []
    try:
        land_raw = land.read_bytes()
        land_text = land_raw.decode("utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        return {"declared": False, "errors": [
            f"landing script is unreadable: {exc}"], "lanes": []}

    script_digest = hashlib.sha256(land_raw).hexdigest()
    if script_digest != _LANDING_SCRIPT_SHA256:
        errors.append(
            "gatekeeper-land.sh is not the complete reviewed executable "
            f"(sha256={script_digest}, expected={_LANDING_SCRIPT_SHA256})")

    source_lines = land_text.splitlines()
    populations = ("run_pytest", "run_repo_tools_pytest",
                   "run_unselectable_pytest")
    final_calls = [i for i, line in enumerate(source_lines, 1)
                   if line in {_LANDING_WINDOW_ANCHOR,
                               f"if {_LANDING_WINDOW_ANCHOR}; then"}]
    if len(final_calls) != 1:
        errors.append(
            f"gatekeeper-land.sh must invoke {_LANDING_WINDOW_ANCHOR} exactly "
            "once at its reviewed top-level call site")
    else:
        prefix_bytes = ("\n".join(source_lines[:final_calls[0]]) +
                        "\n").encode("utf-8")
        prefix_digest = hashlib.sha256(prefix_bytes).hexdigest()
        if prefix_digest != _LANDING_EXECUTION_PREFIX_SHA256:
            errors.append(
                "gatekeeper-land.sh entry-to-final-pytest execution prefix "
                "is not the exact reviewed control flow "
                f"(sha256={prefix_digest}, expected="
                f"{_LANDING_EXECUTION_PREFIX_SHA256})")
    ranges: Dict[str, Tuple[int, int]] = {}
    depths: Dict[str, Dict[int, int]] = {}
    for population in populations:
        starts = [i for i, line in enumerate(source_lines, 1)
                  if line.startswith(f"{population}() {{")]
        if len(starts) != 1:
            errors.append(
                f"gatekeeper-land.sh must define {population} exactly once")
            continue
        start = starts[0]
        ends = [i for i in range(start + 1, len(source_lines) + 1)
                if source_lines[i - 1] == "}"]
        if not ends:
            errors.append(
                f"gatekeeper-land.sh has no structural end for {population}")
            continue
        function_bytes = ("\n".join(
            source_lines[start - 1:ends[0]]) + "\n").encode("utf-8")
        observed_digest = hashlib.sha256(function_bytes).hexdigest()
        if observed_digest != _LANDING_LANE_SHA256[population]:
            errors.append(
                f"gatekeeper-land.sh function {population} is not the exact "
                "reviewed executable body "
                f"(sha256={observed_digest}, expected="
                f"{_LANDING_LANE_SHA256[population]})")
        # A HERE-STRING IS NOT A HEREDOC, and the difference is the whole
        # reason this rule exists. The concern is a literal block of
        # command-SHAPED DATA sitting in the file where a reader — and the
        # canonical-command regex above — might take it for an executed
        # command. `<<<"$out"` carries the value of a variable, so there is no
        # literal in the file to mistake for anything; it is also the form the
        # lane shells were deliberately moved TO, because `printf … | grep -q`
        # asks its question in a subshell whose exit status is the pipeline's,
        # not the probe's. Matching `<<` naively forbade the safer form.
        if any(re.search(r"(?<!<)<<(?!<)", source_lines[i - 1])
               for i in range(start + 1, ends[0])):
            errors.append(
                f"gatekeeper-land.sh function {population} contains a "
                "heredoc; command-shaped data cannot prove lane execution")
        nested = [i for i in range(start + 1, ends[0])
                  if (re.match(
                      r"^\s*(?:function\s+)?[A-Za-z_][A-Za-z0-9_]*"
                      r"\s*(?:\(\s*\))?\s*\{\s*$",
                      source_lines[i - 1]) is not None)]
        if nested:
            errors.append(
                f"gatekeeper-land.sh:{nested[0]} nests a function inside "
                f"{population}; a never-called body cannot prove execution")
        ranges[population] = (start, ends[0])
        depths[population] = _shell_control_depths(
            source_lines, start, ends[0])

    # EACH POPULATION IS INVOKED EXACTLY ONCE, WHEREVER IT IS INVOKED FROM.
    #
    # The old top-level-call-site rule carried two properties at once: an
    # anchor for the execution prefix, and "this population is actually
    # called". Splitting them is what lets the anchor move to the lane window
    # without losing the second: a population that is defined, digest-matched
    # and never called still proves nothing, and a population called twice is
    # two lanes where the record expects one. Shape-independent on purpose —
    # `fn_capture "full:targeted-tests" run_pytest` inside a lane body is a
    # call, and so is a bare top-level line; pinning the SHAPE is what made
    # three separate tests in this repo stop discriminating at once.
    for population in populations:
        span = ranges.get(population)
        if span is None:
            continue
        start, end = span
        callers = [
            lineno for lineno, command in _logical_lines(land_text)
            if command.strip()
            and not command.lstrip().startswith("#")
            and not (start <= lineno <= end)
            and re.search(rf"(?<![\w./-]){re.escape(population)}(?![\w(])",
                          command)]
        if len(callers) != 1:
            errors.append(
                f"gatekeeper-land.sh must invoke {population} exactly once "
                f"outside its own definition (found {len(callers)})")

    for lineno, command in _logical_lines(land_text):
        stripped = command.lstrip()
        if stripped.startswith("#"):
            continue
        owners = [name for name, (start, end) in ranges.items()
                  if start < lineno < end]
        owner = owners[0] if len(owners) == 1 else None
        driver_invocation = bool(
            owner and _DRIVER_COMMAND_RE[owner].search(command))
        # A standalone `pytest` token in executable shell is forbidden unless
        # this exact logical command invokes the semantic driver.  This catches
        # env/absolute-path/function/array aliases without pretending to be a
        # complete shell parser.  The one diagnostic grep is data, not a lane.
        diagnostic = "grep -qa '^=== pytest junit summary'" in command
        if ("pytest_per_file_junit.py" in command
                and not driver_invocation and not stripped.startswith("#")):
            errors.append(
                f"gatekeeper-land.sh:{lineno} names the semantic driver "
                "outside its canonical executable lane")
        if (_PYTEST_RE.search(command) and not driver_invocation
                and not diagnostic):
            errors.append(f"gatekeeper-land.sh:{lineno} mentions executable "
                          "pytest outside the semantic aggregate driver")
        if not driver_invocation:
            lane_already_ran = any(
                lane["population"] == owner and lane["line"] < lineno
                for lane in lanes)
            if (owner and not lane_already_ran
                    and depths.get(owner, {}).get(lineno) == 0
                    and re.match(r"^\s*(return|exit)(?:\s|$)", command)):
                errors.append(
                    f"gatekeeper-land.sh:{lineno} can leave {owner} before "
                    "its semantic pytest lane")
            continue
        if depths.get(owner, {}).get(lineno) != 0:
            errors.append(
                f"gatekeeper-land.sh:{lineno} semantic pytest lane is nested "
                "under conditional control")
        lanes.append({"population": owner, "line": lineno,
                      "command": " ".join(command.split())})
        if "--aggregate-check" not in command:
            errors.append(
                f"gatekeeper-land.sh:{lineno} does not require the aggregate "
                "semantic pytest record")
        trusted_entry = re.search(
            r"--\s+python3\s+-I\s+"
            r"\"\$PROGRAMS/trusted_pytest_entry\.py\"(?=\s)",
            command,
        )
        if trusted_entry is None:
            errors.append(
                f"gatekeeper-land.sh:{lineno} does not execute pytest through "
                "the isolated trusted entry at the semantic driver's "
                "subject-command boundary")
        if re.search(r"(?:^|\s)-p\s+no:cacheprovider(?:\s|$)", command) is None:
            errors.append(
                f"gatekeeper-land.sh:{lineno} does not disable pytest's cache "
                "plugin at the trusted entry boundary")
        if _TIMEOUT_RE.search(command) or "pytest_timeout" in command:
            errors.append(
                f"gatekeeper-land.sh:{lineno} reintroduces a fixed pytest "
                "elapsed-time verdict")
        if _ELAPSED_WRAPPER_RE.search(command):
            errors.append(
                f"gatekeeper-land.sh:{lineno} wraps semantic pytest in a "
                "fixed elapsed-time command")
        if "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" not in command:
            errors.append(
                f"gatekeeper-land.sh:{lineno} inherits ambient pytest plugins")
    repository_marker = (root / "vibe-ic-marketplace" / "plugins" /
                         "vibe-ic" / ".claude-plugin" /
                         "plugin.json").is_file()
    required = (driver.is_file() or repository_marker
                or bool(ranges) or bool(lanes))
    if required:
        for population in populations:
            count = sum(lane["population"] == population for lane in lanes)
            if count != 1:
                errors.append(
                    f"gatekeeper-land.sh must route {population} through "
                    f"exactly one semantic aggregate lane (found {count})")
    if not required:
        return {"declared": False, "errors": [], "lanes": []}
    errors.extend(_semantic_driver_contract_errors(driver))
    return {"declared": True, "errors": errors, "lanes": lanes}


def harness_bounds(repo_root: Path) -> List[HarnessBound]:
    """Every pytest harness bound declared under `.github/workflows`.

    Reading them ALL, rather than the first, is the point: this repo has four
    and they disagree. A resolver that returned the first match would answer
    with whichever file the glob happened to yield first.
    """
    found: List[HarnessBound] = []
    sources: List[Path] = []
    wf_dir = Path(repo_root) / WORKFLOW_DIR_REL
    if wf_dir.is_dir():
        sources += sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml")))
    for rel in EXTRA_HARNESS_RELS:
        q = Path(repo_root) / rel
        if q.is_file():
            sources.append(q)
        elif q.is_dir():
            sources += sorted(q.glob("*.disabled")) + sorted(q.glob("*.yml"))
    if not sources:
        return found
    for wf in sources:
        try:
            text = wf.read_text(errors="replace")
        except OSError:
            continue
        for lineno, cmd in _logical_lines(text):
            if not _PYTEST_RE.search(cmd):
                continue
            m = _TIMEOUT_RE.search(cmd)
            if not m:
                continue
            found.append(HarnessBound(wf.name, lineno, int(m.group(1)),
                                      " ".join(cmd.split())))
    return found


def ci_harness_timeout_seconds(repo_root: Path) -> Optional[int]:
    """The BINDING harness bound: the minimum of every declared one.

    A file under the scanned tree is reachable by every pytest lane in the
    repo, so the smallest bound is the one that decides whether an inner
    timeout can fire. Returns None when no bound can be read at all -- which
    this program reports as CANNOT DETERMINE, never as a pass.
    """
    bounds = harness_bounds(repo_root)
    return min((b.seconds for b in bounds), default=None)


def inner_timeout_ceiling(repo_root: Path) -> Optional[int]:
    """The largest inner bound a single blocking call may declare."""
    harness = ci_harness_timeout_seconds(repo_root)
    return None if harness is None else harness // CEILING_DIVISOR


#: Where the driver's stall window is DECLARED. Resolved, never hand-copied, for
#: the same reason the harness bound is: a number copied into this file is a
#: second copy that cannot notice when the original moves.
_STALL_SOURCE = ("vibe-ic-marketplace/plugins/vibe-ic/programs/"
                 "pytest_per_file_junit.py", "DEFAULT_STALL_AFTER")


def driver_stall_window(repo_root: Path) -> Optional[int]:
    """Seconds an inner call may block before the DRIVER kills the session.

    WHY THIS BOUND EXISTS ALONGSIDE THE HARNESS BOUND (vibe-ic#1734).

    ``harness // 3`` assumes pytest's per-item clock is what ends a runaway call.
    For an item carrying ``@pytest.mark.timeout(N)`` that is false, and the gate
    already reads the marker. But the marker is supplied by the same contributor
    whose bound is being judged, so it is not a constraint -- it is a dial. A
    marker of 2700 buys a 900 s ceiling and silently retires a real 900 s bound.

    The driver's stall window is the bound a contributor CANNOT supply. It is not
    a runtime limit: it is how long the per-file driver tolerates NO validated
    pytest lifecycle event before classifying the session hung. A blocking call
    emits no such events, so it is exactly the window an inner call can hang in
    before the SESSION -- not the test -- is killed. That is this gate's subject.

    So the applicable item bound is ``min(marker or harness, stall)``, and
    ``timeout(0)`` resolves to the stall window rather than to zero: zero means
    "no per-item clock", and the stall clock is then the only thing left that can
    end the call. Reading 0 as a BOUND of zero made every inner timeout in such a
    file a violation -- which is how ``test_matrix_63x8_coverage.py:305
    subprocess.run(timeout=60)`` was reported as a session risk in a file whose
    items cannot be killed by the item clock at all, and blocked landing on main.

    Returns None when the declaration cannot be read; the caller then falls back
    to the harness bound, which is smaller and therefore the safe direction.
    """
    rel, const = _STALL_SOURCE
    try:
        tree = ast.parse((repo_root / rel).read_text(errors="replace"))
    except (OSError, SyntaxError):
        return None
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not (isinstance(tgt, ast.Name) and tgt.id == const):
            continue
        v = node.value
        if isinstance(v, ast.Constant) and isinstance(v.value, (int, float)):
            return int(v.value)
    return None


#: A checkout root, recognised WITHOUT reference to the harness sources.
#:
#: `.git` is tested with `exists()` and not `is_dir()` ON PURPOSE: in a
#: `git worktree` it is a FILE holding a `gitdir:` pointer, and a worktree is
#: exactly the case this stop rule exists for.
_ROOT_MARKERS = (".git", "vibe-ic-marketplace/plugins/vibe-ic")


def _is_checkout_root(base: Path) -> bool:
    return all((base / m).exists() for m in _ROOT_MARKERS)


def find_repo_root(start: Optional[Path] = None) -> Optional[Path]:
    """The root of the checkout `start` (or this file) belongs to.

    IT MUST NOT CLIMB PAST ITS OWN ROOT, and until v1.9.78 it did. The rule was
    "nearest ancestor holding `.github/workflows`", and since #550 retired
    Actions that directory does not exist in the repository at all. Every agent
    in this project works in `.claude/worktrees/agent-*` UNDER the main
    checkout, so the walk left the worktree, found a stale empty
    `.github/workflows` still sitting in the outer checkout, and answered about
    a tree it had never been pointed at: it read the OUTER `tools/` and the
    OUTER `programs/tests`, and reported PASS or FAIL about files the caller
    was not changing. In a FRESH CLONE — no stale directory anywhere above — it
    returned None instead, and every test that depends on it SKIPPED. One
    defect, two opposite symptoms, neither of them visible in the verdict.
    Fixing this is what makes the residual below measurable at all.
    """
    here = (Path(start) if start else Path(__file__)).resolve()
    for base in [here] + list(here.parents):
        # The harness sources first: a directory that carries them IS the root
        # whether or not it looks like a checkout (`--tests-root` fixtures in
        # the tests are exactly that shape).
        if (base / WORKFLOW_DIR_REL).is_dir():
            return base
        if any((base / rel).exists() for rel in EXTRA_HARNESS_RELS):
            return base
        # …and STOP at the checkout boundary regardless. A root with no harness
        # source at all is reported as CANNOT DETERMINE, which is the honest
        # answer; climbing on to borrow another checkout's is not.
        if _is_checkout_root(base):
            return base
    return None


# --- which callees can actually block --------------------------------------

#: The `subprocess` entry points that LAUNCH a process and accept a timeout.
SUBPROCESS_LAUNCHERS = frozenset({"run", "check_output", "check_call", "call",
                                  "Popen"})
#: Same module, explicitly NOT bounds: these RECORD a timeout in an exception
#: rather than imposing one. `subprocess.TimeoutExpired(cmd, timeout=300)` is
#: read as a 300 s bound by any check that matches on the keyword alone.
SUBPROCESS_NON_BLOCKING = frozenset({"TimeoutExpired", "SubprocessError",
                                     "CalledProcessError", "CompletedProcess"})
#: The two `Popen` methods that block until the child is done. Matched on the
#: attribute alone, because the receiver is a local handle whose type this file
#: cannot resolve.
BLOCKING_METHODS = frozenset({"communicate", "wait"})
#: A container invocation is a process launch by construction.
CONTAINER_TOKEN = "docker"

#: Keyword names that carry a timeout. `sat_timeout` and friends are included
#: because a solver budget forwarded into a launcher blocks exactly as long.
_TIMEOUT_KW = "timeout"


#: How a bound that is not a literal at the call site was resolved. Printed,
#: and carried into the JSON record, because the REMEDY differs: a module
#: constant is one edit at its declaration, a parameter default is one edit in
#: the signature that every caller inherits.
VIA_MODULE_CONSTANT = "module constant"
VIA_PARAMETER_DEFAULT = "parameter default"


class Finding:
    def __init__(self, path: str, line: int, callee: str, keyword: str,
                 seconds: float, resolved_via: str,
                 constant: Optional[str] = None,
                 constant_line: Optional[int] = None,
                 constant_kind: str = VIA_MODULE_CONSTANT,
                 owner: Optional[str] = None):
        self.path = path
        self.line = line
        self.callee = callee
        self.keyword = keyword
        self.seconds = seconds
        self.resolved_via = resolved_via
        #: Set when the bound is spelled as a module-level constant rather
        #: than at the call site — the remedy is then ONE edit, not N.
        self.constant = constant
        self.constant_line = constant_line
        #: …or as the enclosing function's PARAMETER DEFAULT (vibe-ic#1277),
        #: which is the same "one declaration, N call sites" shape reached by a
        #: different spelling.
        self.constant_kind = constant_kind
        #: The function whose signature carries that default.
        self.owner = owner

    def as_dict(self) -> Dict:
        return {"path": self.path, "line": self.line, "callee": self.callee,
                "keyword": self.keyword, "seconds": self.seconds,
                "resolved_via": self.resolved_via,
                "constant": self.constant,
                "constant_line": self.constant_line,
                "constant_kind": self.constant_kind if self.constant else None,
                "owner": self.owner}

    def __str__(self) -> str:
        via = ""
        if self.constant and self.constant_kind == VIA_PARAMETER_DEFAULT:
            via = (f" [via {VIA_PARAMETER_DEFAULT} {self.constant}="
                   f"{self.seconds} of {self.owner}(), declared at line "
                   f"{self.constant_line}]")
        elif self.constant:
            via = (f" [via {self.constant} = {self.seconds}, declared at line "
                   f"{self.constant_line}]")
        return (f"{self.path}:{self.line}  "
                f"{self.callee}({self.keyword}={self.seconds}){via}")


def _dotted(func: ast.expr) -> str:
    """Source-level spelling of a call target, e.g. `sp.run`, `proc.wait`."""
    parts: List[str] = []
    cur = func
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    elif isinstance(cur, ast.Call):
        parts.append("<call>")
    else:
        parts.append("<expr>")
    return ".".join(reversed(parts))


def _subprocess_aliases(tree: ast.AST) -> Tuple[Set[str], Set[str]]:
    """(module aliases, names imported FROM subprocess).

    Derived from the file's own imports rather than assuming the module is
    spelled `subprocess`: this corpus really does `import subprocess as sp`.
    """
    mods: Set[str] = set()
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "subprocess":
                    mods.add(a.asname or a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "subprocess":
                for a in node.names:
                    names.add(a.asname or a.name)
    return mods, names


#: Third state, and it is not a detail. `None` means "this file cannot tell",
#: which the caller reports as an ADVISORY so the exclusion has a denominator.
#: NOT_A_BOUND means "resolved, and it does not block" — an exception
#: constructor recording a timeout in its message. Folding the second into the
#: first would put a permanent, un-actionable entry in the advisory list, and an
#: advisory list nobody can ever empty is one nobody reads.
NOT_A_BOUND = "resolved: records a timeout, does not impose one"


def _classify_callee(func: ast.expr, mods: Set[str], names: Set[str],
                     forwarders: Set[str]) -> Optional[str]:
    """Why this callee blocks, NOT_A_BOUND when it provably does not, or None
    when this file cannot tell."""
    dotted = _dotted(func)
    last = dotted.rsplit(".", 1)[-1]

    if isinstance(func, ast.Attribute):
        base = func.value
        if isinstance(base, ast.Name) and base.id in mods:
            if last in SUBPROCESS_NON_BLOCKING:
                return NOT_A_BOUND
            if last in SUBPROCESS_LAUNCHERS:
                return "subprocess launcher"
            return None
    if isinstance(func, ast.Name):
        if func.id in SUBPROCESS_NON_BLOCKING and func.id in names:
            return NOT_A_BOUND
        if func.id in names and func.id in SUBPROCESS_LAUNCHERS:
            return "subprocess launcher (imported by name)"

    if last in BLOCKING_METHODS and isinstance(func, ast.Attribute):
        return "blocking child-process method"
    if CONTAINER_TOKEN in last.lower():
        return "container invocation"
    if last in forwarders or dotted in forwarders:
        return "same-file helper forwarding its timeout into a launcher"
    return None


def _timeout_kwargs(call: ast.Call) -> List[Tuple[str, ast.expr]]:
    return [(kw.arg, kw.value) for kw in call.keywords
            if kw.arg and _TIMEOUT_KW in kw.arg.lower()]


def module_constants(tree: ast.AST) -> Dict[str, Tuple[float, int]]:
    """Module-level `NAME = <number>` bindings, as name -> (value, line).

    WHY THIS EXISTS, and it is not a refinement. A bound written as a named
    module constant is the shape this repo PREFERS — one declaration instead
    of a number copied to every call site — and it is invisible to a check
    that only judges literals at the call site. Measured when this resolution
    was added: `test_matrix_d6_skip_discipline.py` declares
    `_SUBPROCESS_TIMEOUT_S = 900` and spends it at five real launcher calls.
    Neither the grep in the report nor the literal-only first draft of this
    gate could see any of them, so the single worst offender in the tree was
    hiding behind the good shape.

    Deliberately module level only: a name assigned inside a function can be
    reassigned on a branch, and a check that picked one of several bindings
    would be reporting a number the call may never receive.
    """
    consts: Dict[str, Tuple[float, int]] = {}
    body = getattr(tree, "body", [])
    for node in body:
        target = value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        if not (isinstance(target, ast.Name) and isinstance(value, ast.Constant)
                and isinstance(value.value, (int, float))
                and not isinstance(value.value, bool)):
            continue
        # LAST binding wins, matching what the interpreter would hold by the
        # time any test runs.
        consts[target.id] = (value.value, node.lineno)
    return consts


def _numeric(node: ast.expr,
             consts: Dict[str, Tuple[float, int]]
             ) -> Optional[Tuple[float, int]]:
    """`(value, declaration line)` for an expression this file can read as a
    number: a literal, or a module constant already resolved by
    `module_constants`. `None` for anything else."""
    if (isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)):
        return float(node.value) if isinstance(node.value, float) \
            else node.value, node.lineno
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    return None


def parameter_defaults(fn: ast.AST, consts: Dict[str, Tuple[float, int]]
                       ) -> Dict[str, Tuple[float, int]]:
    """`name -> (value, line)` for this function's readable numeric defaults.

    WHY THIS EXISTS (vibe-ic#1277). The gate resolved a literal at the call
    site and a module constant; a bound that arrives as a FUNCTION PARAMETER
    was neither, so it fell into the "callee not resolvable" branch and was
    dropped — not merely unjudged, UNCOUNTED, which is the worse of the two
    because the report then tells a reader nothing was skipped.

    The shape that surfaced it is ordinary and it is in this repo::

        def audit_ci(repo_root: Path, timeout: int = 120) -> CiAudit:
            for decl in gates:                                  # a LOOP
                subprocess.run(argv, ..., timeout=timeout)      # a PARAMETER

    120 s is double the 60 s ceiling and it killed real pytest sessions on
    main. It is the same "one declaration, N call sites" shape that
    `module_constants` already resolves — only the spelling differs.

    A default is judged as the bound because it is the value the call receives
    when the caller says nothing, and because it is a bound the FILE declares:
    if every caller happens to override it, the declaration is still a promise
    the 180 s harness will not keep, and lowering it is one edit.
    """
    out: Dict[str, Tuple[float, int]] = {}
    args = getattr(fn, "args", None)
    if args is None:
        return out
    positional = list(args.posonlyargs) + list(args.args)
    # `defaults` covers the LAST N positional parameters.
    for arg, default in zip(positional[len(positional) - len(args.defaults):],
                            args.defaults):
        got = _numeric(default, consts)
        if got is not None:
            out[arg.arg] = got
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if default is None:
            continue
        got = _numeric(default, consts)
        if got is not None:
            out[arg.arg] = got
    return out


def _rebound_in_scope(fn: ast.AST) -> Set[str]:
    """Names this function's own body rebinds, so a parameter default can no
    longer be claimed as the value the call receives.

    The same rule `module_constants` states for function-local assignment: a
    name that can be reassigned on a branch would have this gate reporting a
    number the call may never see. NESTED function and class bodies are their
    own scopes and are excluded here — the scope walk in `_call_scopes` visits
    them separately, innermost first, so a nested rebinding still wins where it
    actually applies.
    """
    out: Set[str] = set()

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.Lambda, ast.ClassDef)):
                continue
            if isinstance(child, ast.Name) and isinstance(
                    child.ctx, (ast.Store, ast.Del)):
                out.add(child.id)
            elif isinstance(child, (ast.Global, ast.Nonlocal)):
                out.update(child.names)
            visit(child)

    for stmt in getattr(fn, "body", []):
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            continue
        if isinstance(stmt, ast.Name) and isinstance(stmt.ctx,
                                                     (ast.Store, ast.Del)):
            out.add(stmt.id)
        visit(stmt)
    return out


def _call_scopes(tree: ast.AST) -> Dict[int, Tuple[ast.AST, ...]]:
    """`id(Call) -> enclosing functions, outermost first`.

    A decorator, an annotation and a default are evaluated in the ENCLOSING
    scope, not in the function they decorate, so they are descended with the
    outer chain.
    """
    chains: Dict[int, Tuple[ast.AST, ...]] = {}

    def walk(node: ast.AST, chain: Tuple[ast.AST, ...]) -> None:
        if isinstance(node, ast.Call):
            chains[id(node)] = chain
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            outer: List[ast.expr] = list(node.decorator_list)
            outer += list(node.args.defaults)
            outer += [k for k in node.args.kw_defaults if k is not None]
            if node.returns is not None:
                outer.append(node.returns)
            for o in outer:
                walk(o, chain)
            inner = chain + (node,)
            for stmt in node.body:
                walk(stmt, inner)
            return
        for child in ast.iter_child_nodes(node):
            walk(child, chain)

    walk(tree, ())
    return chains


def _forwards_a_timeout(fn: ast.AST, mods: Set[str], names: Set[str],
                        resolved: Set[str]) -> bool:
    """True when this function hands a caller-supplied timeout to a blocking
    call, by either of the two shapes this corpus actually uses."""
    args = fn.args
    named = {a.arg for a in list(args.posonlyargs) + list(args.args)
             + list(args.kwonlyargs) if _TIMEOUT_KW in a.arg.lower()}
    # `def _run(args, **kw): return subprocess.run(cmd, **kw)` — the timeout
    # never appears by name in the wrapper, and the FIRST version of this gate
    # missed it for exactly that reason. The splat is the forwarding.
    splat = args.kwarg.arg if args.kwarg else None
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if _classify_callee(node.func, mods, names, resolved) is None:
            continue
        for _kw, val in _timeout_kwargs(node):
            if isinstance(val, ast.Name) and val.id in named:
                return True
        if splat and any(k.arg is None and isinstance(k.value, ast.Name)
                         and k.value.id == splat for k in node.keywords):
            return True
    return False


def _forwarding_helpers(tree: ast.AST, mods: Set[str], names: Set[str],
                        funcs: Optional[List[ast.AST]] = None) -> Set[str]:
    """Names of same-file functions that pass a caller's timeout into a
    blocking call, iterated to a fixed point so a chain resolves.

    Derived rather than listed: a hand-written list of helper names would be a
    second registry beside the code, free to drift from it.
    """
    if funcs is None:
        funcs = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    resolved: Set[str] = set()
    for _ in range(len(funcs) + 1):
        grew = False
        for fn in funcs:
            if fn.name in resolved:
                continue
            if _forwards_a_timeout(fn, mods, names, resolved):
                resolved.add(fn.name)
                grew = True
        if not grew:
            break
    return resolved


class MarkedItem:
    """A test whose `@pytest.mark.timeout(N)` replaces the session bound.

    Recorded and printed rather than applied silently: raising a ceiling is an
    EXCLUSION from the default rule, and this file's standing position is that
    an exclusion a reader cannot see is indistinguishable from a clean result.
    """

    def __init__(self, path: str, line: int, test: str, seconds: float,
                 ceiling: int):
        self.path = path
        self.line = line
        self.test = test
        self.seconds = seconds
        self.ceiling = ceiling

    def as_dict(self) -> Dict:
        return {"path": self.path, "line": self.line, "test": self.test,
                "item_seconds": self.seconds, "ceiling_seconds": self.ceiling}

    def __str__(self) -> str:
        return (f"{self.path}:{self.line}  {self.test}  "
                f"@pytest.mark.timeout({self.seconds}) -> its calls are judged "
                f"against {self.ceiling}s")


def item_timeout_marker(fn: ast.AST, consts: Dict[str, Tuple[float, int]]
                        ) -> Optional[float]:
    """Seconds from a `@pytest.mark.timeout(N)` on `fn`, or None.

    WHY THE GATE MUST READ THIS. The ceiling is `harness // 3` because the
    harness bounds every ITEM at `--timeout=180`. That is not true of an item
    carrying this marker: pytest-timeout applies the MARKER to that test
    instead, which is the whole reason the marker exists, and this repository
    already relies on it — `test_matrix_63x8_census_freshness.py` carries
    `@pytest.mark.timeout(600)` with its measurement, and
    `test_issue1181_probe_budget_and_summary.py` PINS the mechanism (a marked
    test under `--timeout=2 --timeout-method=thread` yields `2 passed` rather
    than a killed session).

    So `harness // 3` is a PROXY for "the bound that will apply to this call",
    and for a marked item the proxy and the property disagree. Judging a marked
    item against 60 s reports a session risk that provably cannot occur, and
    the gate's own second remedy — "move the test out of the targeted subset if
    it genuinely needs longer" — has no other spelling in this tree.

    The divisor still applies: a marked item gets `N // 3`, for the same reason
    the unmarked one does. A marker SMALLER than the harness bound therefore
    tightens the ceiling rather than loosening it.
    """
    for dec in getattr(fn, "decorator_list", []):
        if not isinstance(dec, ast.Call):
            continue
        dotted = _dotted(dec.func)
        parts = dotted.split(".")
        if len(parts) < 2 or parts[-1] != "timeout" or "mark" not in parts:
            continue
        val = None
        if dec.args:
            val = dec.args[0]
        else:
            for kw in dec.keywords:
                if kw.arg in ("timeout", "seconds"):
                    val = kw.value
        if val is None:
            continue
        got = _numeric(val, consts)
        if got is not None:
            return got[0]
    return None


def _is_fixture_function(fn: ast.AST) -> bool:
    """Whether ``fn`` is declared as a pytest fixture, hence not an item."""
    for dec in getattr(fn, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        dotted = _dotted(target)
        if dotted == "fixture" or dotted.endswith(".fixture"):
            return True
    return False


def pytest_item_functions(tree: ast.Module) -> Set[int]:
    """Function nodes pytest can collect under this repository's defaults.

    A timeout marker changes pytest-timeout's bound only when it belongs to a
    collected item.  A helper (including a nested helper) and a fixture still
    execute under the caller item's bound, even if somebody decorates the
    function itself.  Pytest's default ``python_functions`` pattern is
    ``test*`` and its default class pattern is ``Test*``; those are the
    collection rules used by this repository.
    """
    items: Set[int] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test") and not _is_fixture_function(node):
                items.add(id(node))
            continue
        if not isinstance(node, ast.ClassDef) or not node.name.startswith("Test"):
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if child.name.startswith("test") and not _is_fixture_function(child):
                    items.add(id(child))
    return items


def module_item_marker(tree: ast.AST, consts: Dict[str, Tuple[float, int]]
                       ) -> Optional[Tuple[float, int]]:
    """`(seconds, line)` from a module-level `pytestmark`, or None.

    pytest applies `pytestmark` to EVERY item in the module, which this file
    verified rather than assumed: `pytestmark = pytest.mark.timeout(30)` under
    `--timeout=2 --timeout-method=thread` yields `2 passed`, not a killed
    session.

    It is read for a reason a per-test marker cannot cover. A finding lands at
    the launcher call, and in this corpus that call usually lives in a
    module-level `_run` helper shared by every test in the file — a decorator
    on one test cannot govern a helper the other nine also call. When the whole
    module is bounded at N, every call in it does run inside an item bounded at
    N, so N is the honest ceiling for the file.

    Several timeout marks resolve to the SMALLEST, not the last: a ceiling
    argued from the widest of several declarations would be the one number in
    this file a reader could not check by eye.
    """
    best: Optional[Tuple[float, int]] = None
    for node in getattr(tree, "body", []):
        target = value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        if not (isinstance(target, ast.Name) and target.id == "pytestmark"):
            continue
        items = (list(value.elts)
                 if isinstance(value, (ast.List, ast.Tuple)) else [value])
        for item in items:
            if not isinstance(item, ast.Call):
                continue
            parts = _dotted(item.func).split(".")
            if len(parts) < 2 or parts[-1] != "timeout" or "mark" not in parts:
                continue
            val = item.args[0] if item.args else None
            if val is None:
                for kw in item.keywords:
                    if kw.arg in ("timeout", "seconds"):
                        val = kw.value
            got = _numeric(val, consts) if val is not None else None
            if got is not None and (best is None or got[0] < best[0]):
                best = (got[0], node.lineno)
    return best



def marker_ceiling(marker_seconds: float, base_ceiling: int,
                   stall: Optional[int]) -> int:
    """The per-call ceiling that applies inside an item carrying a timeout marker.

    THREE CASES, AND THE CAP IS THE POINT (vibe-ic#1734):

      marker N > 0   the item clock is N, so calls are judged against N // 3 --
                     BUT never above the stall window, because a marker is
                     supplied by the same contributor whose bound is judged and
                     is therefore a dial, not a constraint. `timeout(2700)` used
                     to buy a 900 s ceiling and retire a real 900 s bound.
      marker 0       pytest-timeout DISABLES the item clock. Zero is not a bound
                     of zero seconds; it means there is no per-item clock, and
                     the driver's stall window is then the only thing that can
                     end a blocking call. Judging against `0 // 3 == 0` made
                     every inner timeout in such a file a violation.
      no stall read  fall back to the harness bound, which is smaller. When the
                     cap cannot be read the tighter answer is the safe one.
    """
    harness = base_ceiling * CEILING_DIVISOR
    if stall:
        effective = int(marker_seconds) if marker_seconds else stall
        return min(effective, stall) // CEILING_DIVISOR
    # NO STALL RESOLVED -> NO CAP, and `main` REFUSES in this state rather than
    # publishing a verdict it cannot justify. Capping at the harness bound instead
    # was tried and is wrong in a way worth recording: the marker exists precisely
    # to REPLACE the harness item bound, so capping at it makes every marker inert
    # and silently converts "this test genuinely needs longer" into a finding.
    effective = int(marker_seconds) if marker_seconds else harness
    return effective // CEILING_DIVISOR


def scan_source(text: str, rel_path: str, ceiling: int,
                stall: Optional[int] = None
                ) -> Tuple[List[Finding], List[Finding], int]:
    """(findings, unresolved_above_ceiling, bounded_call_sites) for one file.

    Kept as the three-value shape every caller and test already uses; the
    marked-item census is the fourth thing `scan_source_report` returns.
    """
    rep = scan_source_report(text, rel_path, ceiling, stall)
    return rep["findings"], rep["unresolved_above_ceiling"], rep["sites"]


def scan_source_report(text: str, rel_path: str, ceiling: int,
                       stall: Optional[int] = None) -> Dict:
    """findings / unresolved / site count / marked items, for one file.

    Raises nothing: an unparseable file yields empty lists and is counted by
    the caller, because a syntax error is a different defect.
    """
    tree = ast.parse(text)
    consts = module_constants(tree)
    # ONE walk for both populations. The rest of this function is arranged so a
    # file that declares no bound at all pays for nothing beyond it: this gate
    # scans ~2600 files on every hygiene run, and #1277's resolution would have
    # doubled its wall time (101 s -> 202 s, measured) if every file paid for
    # the scope map whether or not it needed one.
    timeout_calls: List[Tuple[ast.Call, List[Tuple[str, ast.expr]]]] = []
    funcs: List[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            kws = _timeout_kwargs(node)
            if kws:
                timeout_calls.append((node, kws))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node)

    # The marked census is built even for a file with no bounded call, because
    # it is a DISCLOSURE: a marked item that never appears is a raised ceiling
    # nobody can see.
    fn_marker: Dict[int, float] = {}
    marked: List[MarkedItem] = []
    mod_marker = module_item_marker(tree, consts)
    collectable_items = pytest_item_functions(tree)
    file_ceiling = ceiling
    if mod_marker is not None:
        file_ceiling = marker_ceiling(mod_marker[0], ceiling, stall)
        marked.append(MarkedItem(rel_path, mod_marker[1],
                                 "<pytestmark: every test in this file>",
                                 mod_marker[0], file_ceiling))
    for fn in funcs:
        if id(fn) not in collectable_items:
            continue
        mk = item_timeout_marker(fn, consts)
        if mk is not None:
            fn_marker[id(fn)] = mk
            marked.append(MarkedItem(rel_path, fn.lineno, fn.name, mk,
                                     marker_ceiling(mk, ceiling, stall)))

    findings: List[Finding] = []
    unresolved: List[Finding] = []
    total = 0
    if not timeout_calls:
        return {"findings": findings, "unresolved_above_ceiling": unresolved,
                "sites": total, "marked_items": marked}

    mods, names = _subprocess_aliases(tree)
    # The scope map answers two questions and is built only when one is asked:
    # which parameter default a bare name resolves to, and which marker (if
    # any) governs a call.
    needs_scopes = bool(fn_marker) or any(
        isinstance(v, ast.Name) and v.id not in consts
        for _c, kws in timeout_calls for _k, v in kws)
    scopes = _call_scopes(tree) if needs_scopes else {}
    fn_defaults: Dict[int, Dict[str, Tuple[float, int]]] = {}
    fn_rebound: Dict[int, Set[str]] = {}
    # The callee allowlist is only consulted for a bound that is ALREADY over
    # its ceiling, and deriving it walks every function to a fixed point, so it
    # is derived on first use rather than for every file.
    forwarders: Optional[Set[str]] = None

    for node, kws in timeout_calls:
        chain = scopes.get(id(node), ())
        # The bound that will really apply to THIS call: the innermost
        # enclosing item bound, which is the session's unless a marker on a
        # function this call sits inside replaced it.
        call_ceiling = file_ceiling
        for fn in reversed(chain):
            if id(fn) in fn_marker:
                call_ceiling = marker_ceiling(fn_marker[id(fn)], ceiling, stall)
                break
        for kw_name, val in kws:
            const_name = const_line = owner = None
            const_kind = VIA_MODULE_CONSTANT
            if (isinstance(val, ast.Constant)
                    and isinstance(val.value, (int, float))
                    and not isinstance(val.value, bool)):
                seconds = val.value
            elif isinstance(val, ast.Name) and val.id in consts:
                seconds, const_line = consts[val.id]
                const_name = val.id
            else:
                param = _resolve_parameter_default(
                    val, chain, fn_defaults, fn_rebound, consts)
                if param is None:
                    # A bound this file does not spell out — an attribute, an
                    # expression, a parameter with no readable default or one
                    # its own body rebinds. Not judged and not counted, so the
                    # denominator stays the set of bounds actually readable.
                    continue
                seconds, const_line, owner = param
                const_name = val.id
                const_kind = VIA_PARAMETER_DEFAULT
            total += 1
            if seconds <= call_ceiling:
                continue
            if forwarders is None:
                forwarders = _forwarding_helpers(tree, mods, names, funcs)
            why = _classify_callee(node.func, mods, names, forwarders)
            if why is NOT_A_BOUND:
                continue
            rec = Finding(rel_path, val.lineno, _dotted(node.func), kw_name,
                          seconds, why or "not resolvable from this file",
                          const_name, const_line, const_kind, owner)
            (findings if why else unresolved).append(rec)
    return {"findings": findings, "unresolved_above_ceiling": unresolved,
            "sites": total, "marked_items": marked}


def _resolve_parameter_default(val: ast.expr, chain: Tuple[ast.AST, ...],
                               fn_defaults: Dict[int, Dict[str,
                                                           Tuple[float, int]]],
                               fn_rebound: Dict[int, Set[str]],
                               consts: Dict[str, Tuple[float, int]]
                               ) -> Optional[Tuple[float, int, str]]:
    """`(seconds, declaration line, owning function)` when `val` is a name the
    enclosing scopes bind to a readable numeric parameter default.

    Scopes are read INNERMOST FIRST, and a scope that rebinds the name stops
    the search rather than deferring to an outer one: at that point the value
    reaching the call is whatever the body last assigned, which this file
    cannot claim to know.

    The two per-function facts are memoised on first use: only the scopes that
    actually enclose a name-valued bound are ever computed.
    """
    if not isinstance(val, ast.Name):
        return None
    for fn in reversed(chain):
        key = id(fn)
        if key not in fn_rebound:
            fn_rebound[key] = _rebound_in_scope(fn)
            fn_defaults[key] = parameter_defaults(fn, consts)
        if val.id in fn_rebound[key]:  # a local, not the parameter
            return None
        got = fn_defaults[key].get(val.id)
        if got is not None:
            return got[0], got[1], fn.name
    return None


def scan_tree(tests_root: Path, ceiling: int, glob: str = "*.py",
              stall: Optional[int] = None,
              anchor: Optional[Path] = None) -> Dict:
    findings: List[Finding] = []
    unresolved: List[Finding] = []
    marked: List[MarkedItem] = []
    files = 0
    sites = 0
    unparseable: List[str] = []
    root = Path(tests_root)
    # Report paths relative to the PLUGIN root when the scan root is the
    # shipped one, so a finding can be pasted straight into an editor; fall
    # back to the scan root for any other `--tests-root`, rather than raising.
    base = Path(anchor) if anchor else root.parent.parent
    for py in sorted(root.rglob(glob)):
        files += 1
        try:
            rel = str(py.relative_to(base))
        except ValueError:
            rel = str(py.relative_to(root))
        try:
            text = py.read_text(errors="replace")
        except OSError:
            unparseable.append(rel)
            continue
        try:
            one = scan_source_report(text, rel, ceiling, stall)
        except SyntaxError:
            unparseable.append(rel)
            continue
        findings.extend(one["findings"])
        unresolved.extend(one["unresolved_above_ceiling"])
        marked.extend(one["marked_items"])
        sites += one["sites"]
    return {"files": files, "bounded_sites": sites, "findings": findings,
            "unresolved_above_ceiling": unresolved, "marked_items": marked,
            "unparseable": unparseable}


def scan_roots(roots: Sequence[Tuple[Path, str, Optional[Path]]],
               ceiling: int, stall: Optional[int] = None) -> Dict:
    """Merge `scan_tree` over every root a pytest lane actually runs.

    Kept as a merge rather than one root with one glob because the two trees
    are not the same KIND of directory — see `TOOLS_DIR_REL` for why one is
    scanned whole and the other only for its test files.
    """
    merged = {"files": 0, "bounded_sites": 0, "findings": [],
              "unresolved_above_ceiling": [], "marked_items": [],
              "unparseable": [], "roots": []}
    for root, glob, anchor in roots:
        rep = scan_tree(root, ceiling, glob, stall=stall, anchor=anchor)
        merged["files"] += rep["files"]
        merged["bounded_sites"] += rep["bounded_sites"]
        merged["findings"].extend(rep["findings"])
        merged["unresolved_above_ceiling"].extend(
            rep["unresolved_above_ceiling"])
        merged["marked_items"].extend(rep["marked_items"])
        merged["unparseable"].extend(rep["unparseable"])
        merged["roots"].append({"root": str(root), "glob": glob,
                                "files": rep["files"],
                                "bounded_sites": rep["bounded_sites"]})
    return merged


# --- census (the measurement behind the divisor) ---------------------------

def bounded_calls_per_test_function(tests_root: Path) -> Dict[int, int]:
    """How many literal-bounded call SITES live inside one test function.

    This is the measurement the ceiling divisor is chosen against, so it ships
    with the gate rather than in a commit message nobody re-runs.
    """
    hist: Dict[int, int] = {}
    for py in sorted(Path(tests_root).rglob("test_*.py")):
        try:
            tree = ast.parse(py.read_text(errors="replace"))
        except (OSError, SyntaxError):
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("test_"):
                continue
            n = 0
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    for _kw, val in _timeout_kwargs(node):
                        if isinstance(val, ast.Constant) and isinstance(
                                val.value, (int, float)):
                            n += 1
            if n:
                hist[n] = hist.get(n, 0) + 1
    return hist


# --- CLI -------------------------------------------------------------------

def _scan_roots(repo_root: Optional[Path], explicit: Optional[str]
                ) -> List[Tuple[Path, str, Optional[Path]]]:
    """Every tree a pytest lane runs, as (root, glob, path-report anchor).

    `--tests-root` REPLACES the set rather than adding to it: a caller that
    narrowed the scan and silently also got the default would read the result
    as covering something it does not.
    """
    if explicit:
        p = Path(explicit)
        return [(p, "*.py", None)] if p.is_dir() else []
    roots: List[Tuple[Path, str, Optional[Path]]] = []
    plugins: List[Path] = []
    if repo_root:
        plugins.append(repo_root / "vibe-ic-marketplace" / "plugins" / "vibe-ic")
    plugins.append(Path(__file__).resolve().parent.parent)
    for b in plugins:
        cand = b / TESTS_DIR_REL
        if cand.is_dir():
            roots.append((cand, "*.py", None))
            break
    if repo_root and (repo_root / TOOLS_DIR_REL).is_dir():
        roots.append((repo_root / TOOLS_DIR_REL, TOOLS_GLOB, repo_root))
    return roots


# ---------------------------------------------------------------------------
# THE INSIDE OF THE SAME CLAIM (the chain edge)
# ---------------------------------------------------------------------------
# This gate's own concluding sentence is "elapsed time is not a test verdict",
# and it earns that about the OUTER harness: the landing lane supervises its
# pytest populations by semantic progress and sets no total runtime ceiling.
#
# It says nothing about the INSIDE. A test that kills its own subject on a
# 0.45 s forward-progress deadline and reports the kill as a finding is elapsed
# time used as a verdict, one level down, and this gate walks straight past it.
# MEASURED (vibe-ic#1327's neighbourhood): one identifier appeared as a NEW red
# on a candidate arm and was not one — re-run serially on an idle host it
# measured 8 of 8 failing on BOTH trees, so the family run's green on the base
# was a FALSE GREEN, and a single sample each side would have filed it as damage
# the change had done.
#
# `wall_clock_bound_standing_in_for_a_verdict` is the sweep that finds those,
# and it was reachable from nothing: no runner, no flow clause, no hygiene line,
# no skill, nothing importing it outside its own test. It is imported here, over
# the SAME repository root this gate already resolved.
#
# ADVISORY, AND THAT IS ITS OWN INSTRUCTION, NOT A CONVENIENCE. Its header reads
# "VERDICT CLASS: **ADVISORY** (rc 0 with findings)", and its floor is a
# parameter rather than a truth — 0.45 s against a two-way concurrent driver is
# indefensible and against a pure function is nobody's business. So the census
# is PRINTED and RECORDED on every run of this gate and CANNOT change its exit
# code. That is the same disposition `container exec deadlines` carries one
# gate over, and for the same stated reason: the count is published every run
# and cannot drift unseen.
def elapsed_verdict_advisory(repo_root: Optional[Path]) -> Dict[str, object]:
    """Run the inner-bound sweep. Never raises, never decides."""
    out: Dict[str, object] = {"available": False, "findings": [],
                              "denominators": {}}
    if repo_root is None:
        out["why"] = "no repository root resolved"
        return out
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import wall_clock_bound_standing_in_for_a_verdict as _wc
        findings, denom = _wc.scan(Path(repo_root), _wc._DEFAULT_FLOOR)
        out.update({"available": True, "findings": findings,
                    "denominators": denom, "floor_s": _wc._DEFAULT_FLOOR})
    except Exception as exc:                      # pragma: no cover - env
        out["why"] = f"{type(exc).__name__}: {exc}"
    return out


def print_elapsed_verdict_advisory(adv: Dict[str, object]) -> None:
    """Print the census with its denominator. ADVISORY — decides nothing."""
    if not adv.get("available"):
        print("  inner wall-clock bounds asserted as findings: NOT MEASURED "
              f"({adv.get('why', 'unknown')}) — this is a disclosure, not a "
              "clean census")
        return
    denom = adv.get("denominators") or {}
    findings = adv.get("findings") or []
    print(f"  inner wall-clock bounds below {adv.get('floor_s')}s that decide a "
          f"finding without stating the load: {len(findings)} "
          f"(of {denom.get('modules_that_spawn', 0)} process-spawning module(s) "
          f"in {denom.get('modules_parsed', 0)} parsed)")
    for f in findings[:20]:
        print(f"     advisory  {f['file']}:{f['line']}  {f['bound_s']}s -> "
              f"{f['reports']}")
    if len(findings) > 20:
        print(f"     ... and {len(findings) - 20} more (this line is the "
              f"disclosure, not a silent truncation)")
    if findings:
        print("     ADVISORY — this census does not change this gate's exit "
              "code; carry the load average beside the bound to clear a row.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("root", nargs="?", default=None,
                    help="repository root (default: the root of the checkout "
                         "this file is in — the walk stops there and never "
                         "borrows an enclosing checkout's workflows)")
    ap.add_argument("--tests-root", dest="tests_root", default=None,
                    help="directory to scan (default: the plugin's "
                         "programs/tests)")
    ap.add_argument("--table", action="store_true",
                    help="print the bounded-calls-per-test-function census "
                         "the ceiling divisor is chosen against")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the machine record to this path")
    args = ap.parse_args(argv)

    repo_root = find_repo_root(Path(args.root)) if args.root else \
        find_repo_root()
    if args.root and repo_root is None:
        repo_root = Path(args.root) if Path(args.root).is_dir() else None

    bounds = harness_bounds(repo_root) if repo_root else []
    harness = min((b.seconds for b in bounds), default=None)
    roots = _scan_roots(repo_root, args.tests_root)
    semantic = (landing_semantic_progress_contract(repo_root)
                if repo_root else {"declared": False, "errors": [],
                                   "lanes": []})

    # The live landing gate no longer has an elapsed harness bound.  Validate
    # that stronger contract before entering the legacy finite-bound audit used
    # by old/fake harness fixtures.  A half migration is a failure, not a reason
    # to fall back to whichever historical timeout still happens to parse.
    if semantic["declared"] and args.tests_root is None:
        if semantic["errors"]:
            print("[FAIL] ci_harness_timeout_ceiling_check: the landing gate "
                  "declares semantic pytest supervision but its contract is "
                  "incomplete:")
            for error in semantic["errors"]:
                print(f"   {error}")
            return 1
        if not roots:
            print("[CANNOT DETERMINE] ci_harness_timeout_ceiling_check: "
                  "semantic landing supervision is present, but no test tree "
                  f"to scan ({args.tests_root or TESTS_DIR_REL} not found) -- "
                  "0 files examined, which is NOT a pass.")
            return 2
        # A deliberately enormous finite comparison value lets the existing
        # AST census count readable blocking sites without emitting non-standard
        # JSON Infinity. Findings are not used in this mode: with no outer
        # elapsed ceiling, no finite child bound can outlive it.
        rep = scan_roots(roots, 10 ** 18)
        if rep["unparseable"]:
            print("[CANNOT DETERMINE] ci_harness_timeout_ceiling_check: "
                  "semantic harness is valid, but some test sources could not "
                  "be parsed, so the population is incomplete:")
            for path in rep["unparseable"][:20]:
                print(f"   {path}")
            return 2
        print("ci_harness_timeout_ceiling_check: semantic-progress landing "
              f"harness ({len(semantic['lanes'])} pytest population(s)); "
              "fixed elapsed ceiling: none")
        print(f"  scanned {rep['files']} file(s) in {len(rep['roots'])} "
              f"tree(s), {rep['bounded_sites']} readable inner diagnostic "
              "bound(s)")
        for lane in semantic["lanes"]:
            print(f"   gatekeeper-land.sh:{lane['line']}  "
                  "aggregate lifecycle-supervised lane")
        adv = elapsed_verdict_advisory(repo_root)
        print_elapsed_verdict_advisory(adv)
        if args.json_out:
            Path(args.json_out).write_text(json.dumps({
                "program": "ci_harness_timeout_ceiling_check",
                "mode": "semantic_progress",
                "inner_elapsed_verdict_advisory": adv,
                "harness_seconds": None,
                "ceiling_seconds": None,
                "ceiling_divisor": None,
                "harness_bounds": [],
                "semantic_lanes": semantic["lanes"],
                "roots": rep["roots"],
                "files": rep["files"],
                "bounded_sites": rep["bounded_sites"],
                "findings": [],
                "unresolved_above_ceiling": [],
                "marked_items": [],
                "unparseable": [],
                "passed": True,
            }, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print("[PASS] every landing pytest population is supervised by "
              "validated lifecycle progress with no total runtime ceiling; "
              "elapsed time is not a test verdict.")
        return 0

    # Two ways to have nothing to say, and neither of them is a pass. Reported
    # BEFORE the scan so the message names the missing input rather than an
    # empty result.
    if harness is None:
        print("[CANNOT DETERMINE] ci_harness_timeout_ceiling_check: no "
              f"`pytest --timeout=N` found in {WORKFLOW_DIR_REL} or "
              f"{', '.join(EXTRA_HARNESS_RELS)} "
              f"(searched from {repo_root}). The bound this gate judges "
              "against is unknown, so nothing was checked -- this is NOT a "
              "pass.")
        return 2
    ceiling = harness // CEILING_DIVISOR
    # The cap a contributor cannot supply. Resolved, not stated; None falls back
    # to the harness bound inside `marker_ceiling`, which is the tighter answer.
    stall = driver_stall_window(repo_root)
    if stall is None:
        # A run that cannot read the cap cannot judge a marked item, and a marked
        # item is exactly where the dial lives. Refusing is the only honest exit:
        # without the cap this gate would publish PASS over ceilings a contributor
        # set for themselves.
        print("[CANNOT DETERMINE] ci_harness_timeout_ceiling_check: could not read "
              f"{_STALL_SOURCE[1]} from {_STALL_SOURCE[0]}, so the cap on a "
              "marker-derived ceiling is unknown. A marked item cannot be judged "
              "without it, and that is NOT a pass.")
        return 2
    if not roots:
        print(f"[CANNOT DETERMINE] ci_harness_timeout_ceiling_check: harness "
              f"bound {harness}s resolved, but no test tree to scan "
              f"({args.tests_root or TESTS_DIR_REL} not found) -- 0 files "
              "examined, which is NOT a pass.")
        return 2

    rep = scan_roots(roots, ceiling, stall)

    print(f"ci_harness_timeout_ceiling_check: harness bound {harness}s "
          f"(minimum of {len(bounds)} pytest invocation(s) in "
          f"{len({b.workflow for b in bounds})} workflow file(s)); per-call "
          f"ceiling {ceiling}s (= {harness} // {CEILING_DIVISOR})")
    for b in bounds:
        marker = "  <- binding" if b.seconds == harness else ""
        print(f"   {b.workflow}:{b.line}  --timeout={b.seconds}{marker}")
    print(f"  scanned {rep['files']} file(s) in {len(rep['roots'])} tree(s), "
          f"{rep['bounded_sites']} readable bound(s) at call sites")
    for r in rep["roots"]:
        print(f"     {r['files']:5} file(s) ({r['glob']})  {r['root']}")
    if rep["unparseable"]:
        print(f"  {len(rep['unparseable'])} file(s) could not be parsed and "
              f"were NOT judged: {', '.join(rep['unparseable'][:5])}")

    # The exclusion, given a denominator. A reader must be able to see what
    # the allowlist declined to judge instead of inferring it from silence.
    unres = rep["unresolved_above_ceiling"]
    print(f"  above the ceiling but NOT judged (callee not resolvable from "
          f"the call site): {len(unres)}")
    for u in unres[:20]:
        print(f"     advisory  {u}")
    if len(unres) > 20:
        print(f"     ... and {len(unres) - 20} more (this line is the "
              f"disclosure, not a silent truncation)")

    # The OTHER exclusion, and it owes the reader the same denominator: an item
    # whose own marker replaces the session bound is not judged against this
    # ceiling. Printed with the value, so raising a ceiling is a visible act.
    marked = rep["marked_items"]
    print(f"  test(s) whose @pytest.mark.timeout replaces the {harness}s item "
          f"bound (judged against their own marker // {CEILING_DIVISOR}): "
          f"{len(marked)}")
    for m in marked[:20]:
        print(f"     marked  {m}")
    if len(marked) > 20:
        print(f"     ... and {len(marked) - 20} more (this line is the "
              f"disclosure, not a silent truncation)")

    if args.table:
        hist: Dict[int, int] = {}
        for root, _glob, _anchor in roots:
            for n, c in bounded_calls_per_test_function(root).items():
                hist[n] = hist.get(n, 0) + c
        print("  bounded call sites per test function (the census the "
              "divisor is chosen against):")
        for n in sorted(hist):
            print(f"     {n} site(s): {hist[n]} test function(s)")

    adv = elapsed_verdict_advisory(repo_root)
    print_elapsed_verdict_advisory(adv)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "program": "ci_harness_timeout_ceiling_check",
            "mode": "fixed_timeout_legacy",
            "inner_elapsed_verdict_advisory": adv,
            "harness_seconds": harness,
            "ceiling_seconds": ceiling,
            "ceiling_divisor": CEILING_DIVISOR,
            "harness_bounds": [b.as_dict() for b in bounds],
            "roots": rep["roots"],
            "files": rep["files"],
            "bounded_sites": rep["bounded_sites"],
            "findings": [f.as_dict() for f in rep["findings"]],
            "unresolved_above_ceiling": [u.as_dict() for u in unres],
            "marked_items": [m.as_dict() for m in rep["marked_items"]],
            "unparseable": rep["unparseable"],
            "passed": not rep["findings"],
        }, indent=2) + "\n", encoding="utf-8")

    if rep["findings"]:
        print(f"[FAIL] {len(rep['findings'])} inner bound(s) above the "
              f"{ceiling}s ceiling -- each one can outlive the {harness}s "
              f"harness, which kills the SESSION instead of the test:")
        for f in rep["findings"]:
            print(f"   {f}   [{f.resolved_via}]")
        print("  Remedy: lower the bound, or move the test out of the "
              "targeted subset if it genuinely needs longer.")
        return 1
    # THE SENTENCE MUST NOT OUTRUN WHAT WAS CHECKED (vibe-ic#1734, defect 2).
    # It used to read "bounded at or under {ceiling}s" flat. That is false the
    # moment any marked item is judged against its own, larger, ceiling -- the run
    # would assert a property two lines under its own printed counterexample. The
    # claim is now stated as what is actually true of every judged call: each is
    # under THE CEILING THAT APPLIES TO IT, and the cap on that ceiling is named
    # so a reader can see no marker can raise it without bound.
    cap = stall if stall else harness
    marked_n = len(rep["marked_items"])
    extra = (f"; {marked_n} marked item(s) are judged against their own marker, "
             f"capped at the {cap}s driver stall window") if marked_n else ""
    print(f"[PASS] every resolvable blocking call is bounded at or under the "
          f"ceiling that applies to it -- {ceiling}s by default (the {harness}s "
          f"harness bound // {CEILING_DIVISOR}){extra}. So no such call can "
          f"outlive the bound that would otherwise end the SESSION.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
