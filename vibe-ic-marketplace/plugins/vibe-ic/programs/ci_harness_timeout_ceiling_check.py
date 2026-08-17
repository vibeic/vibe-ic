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

THERE IS NO PER-FILE EXEMPTION, AND ``timeout(0)`` IS NOT ONE (vibe-ic#1734)
----------------------------------------------------------------------------
``pytest.mark.timeout(0)`` is pytest-timeout's "no clock for this item". The
withheld v1.10.62 attempt read that as an INFINITE bound and skipped judging
the file — which made one added line, ``pytestmark = pytest.mark.timeout(0)``
at the top of ``test_matrix_mutation_ledger.py``, turn a standing
``timeout=900`` into ``rc=0`` and ``[PASS]``, and retire a RECORDED ADVISORY
with it. A gate that exists to stop a test silencing the harness had grown a
one-line silencer of its own.

So a marker value of 0 (or any non-positive one) is NOT A READABLE ITEM BOUND
here. It is DISCLOSED — the item is printed with its marker, exactly like every
other marked item — and its calls stay judged against the session ceiling.

That is not a convention chosen for tidiness; it is what the harness does.
Turning off pytest-timeout's clock does not take the item out of the landing
harness. ``tools/gatekeeper-land.sh`` drives the whole selection through
``programs/pytest_per_file_junit.py``, whose ``--stall-after`` and
``--aggregate-stall-after`` both default to 300 s there, and NO pytest marker
can raise either: a call that blocks longer than the window with no validated
pytest lifecycle event costs the run its AGGREGATE_NORECORD — the same "every
other file loses its verdict" outcome this gate was written for, arriving
through the driver instead of through pytest-timeout. ``timeout(0)`` moves the
executioner; it does not remove one.

(The window is RENEWED by validated progress, which is why the one file in this
tree that really does run a long nested census emits ``domain_progress`` relay
events — a mechanism, in its own source, that a reader can check. That is what
buying room actually costs. A marker is not a substitute for it, and this gate
does not price it as one.)

"It genuinely needs longer" therefore has exactly ONE honest spelling, and it
is the gate's own second remedy: the module runs OUTSIDE this harness. A zero
marker is not that spelling, and this gate no longer accepts it as one.

WHAT A POSITIVE MARKER IS, SO THE TWO ARE NOT CONFUSED
-------------------------------------------------------
``@pytest.mark.timeout(600)`` is a DECLARED BOUND, not an exemption: the call
is still judged, against ``600 // 3``, the number is printed, and the file
stays in the judged denominator. Nothing is removed from the judged set, so
nothing has to be subtracted from the verdict sentence. The difference from 0
is the whole of it — a declared bound can be checked against, "no clock" cannot.

Consequently a marker can only ever be read as the TIGHTEST of the positive
marks (see ``module_item_marker``). Under the withheld attempt ``min`` over
``[timeout(0), timeout(300)]`` picked 0 — the MOST permissive value — while its
docstring still claimed to be picking the tightest ceiling. 0 is no longer a
candidate, so the tie-break means again what it says.

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
                                                [--self-check-only]

EXIT CODES
----------
    0 = PASS   1 = FAIL (a bound above the ceiling, or a failed SELF-CHECK)
    2 = CANNOT DETERMINE (no workflow bound, or nothing to scan) -- not a pass

The SELF-CHECK runs on every invocation, before the scan, and is the reason
this gate's falsifiability does not depend on a test file being selected --
see ``_SELF_CHECK``.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
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
#: `pip install pytest-timeout` names the plugin, not a bound; it carries no
#: `--timeout=N` and so cannot match, but the negative is stated because a
#: future looser pattern would pick it up.

#: The harness bound is divided by this to get the per-call ceiling. See the
#: module docstring: 2 clears the prior art's "room to REPORT" reason and still
#: dies on the two-call shape that 19 test functions in this corpus have; 3
#: survives two full-length calls and keeps a third of the budget in reserve.
CEILING_DIVISOR = 3

#: The clock a contributor CANNOT move, and therefore the only honest cap on one
#: they can. `tools/gatekeeper-land.sh` wraps the whole selection in
#: `pytest_per_file_junit.py --stall-after 300 --aggregate-stall-after 300`, and NO
#: pytest marker raises either.
#:
#: WHY THIS EXISTS, AND WHY THE PREVIOUS TWO ATTEMPTS DID NOT NEED IT UNTIL THEY DID.
#: Round 1 let `pytest.mark.timeout(0)` disable the ceiling; that was closed. Round 2
#: kept `marker_ceiling` refusing non-positive values and left the RAISED key in the
#: lock: `pytest.mark.timeout(2700)` bought a 900 s ceiling and retired a recorded
#: advisory, on the fixed gate, with the same file and the same bound. Closing `0`
#: and leaving `2700` is pinning the value that was reported instead of the door that
#: was open.
#:
#: A ceiling the author supplies must be bounded by something the author cannot also
#: supply. 300 s is that thing. Above it the marker is not a bound at all — it is a
#: statement about a clock that will not be the one to end the run.
#:
#: MEASURED, LIVE ON MAIN WHEN THIS WAS WRITTEN:
#: `test_vibe_ic_one_shot_runner.py:138` carries `@pytest.mark.timeout(1200)` over
#: `:154 subprocess.run(..., timeout=400)`, in a file that emits ZERO progress relay
#: events. 400 s > 300 s with no renewal, so that launch reaching its bound costs the
#: file its record — the "loses its verdict" outcome this gate exists for — while the
#: gate printed `largest applied: 400s` and `[PASS]`.
DRIVER_STALL_S = 300

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


def _logical_lines(text: str) -> Iterable[Tuple[int, str]]:
    """Yield (first_line_number, joined_command) with backslash continuations
    folded, so a flag on a continuation line belongs to its own command."""
    buf: List[str] = []
    start = 0
    for i, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.rstrip()
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
                 owner: Optional[str] = None,
                 ceiling: Optional[int] = None):
        #: The ceiling this call was ACTUALLY judged against — the session's,
        #: or a positive marker's `N // 3`. Carried on the record rather than
        #: formatted from the session ceiling at print time, because a report
        #: that says "above the 60s ceiling" about a call judged at 200s is
        #: describing a comparison it did not make (vibe-ic#1734 defect 2).
        self.ceiling = ceiling
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
                "owner": self.owner,
                "judged_against_seconds": self.ceiling}

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
                 ceiling: int, raises: bool = True):
        self.path = path
        self.line = line
        self.test = test
        self.seconds = seconds
        #: The ceiling that really applies to this item's calls. For a
        #: non-positive marker that is the SESSION ceiling, unchanged.
        self.ceiling = ceiling
        #: False for `timeout(0)` — disclosed, but it buys nothing. Recording
        #: the distinction on the item is what stops the two lanes being told
        #: apart by their printed text alone.
        self.raises = raises

    def as_dict(self) -> Dict:
        return {"path": self.path, "line": self.line, "test": self.test,
                "item_seconds": self.seconds, "ceiling_seconds": self.ceiling,
                "raises_ceiling": self.raises}

    def __str__(self) -> str:
        if not self.raises:
            return (f"{self.path}:{self.line}  {self.test}  "
                    f"@pytest.mark.timeout({self.seconds}) -> NOT a bound this "
                    f"gate can read (0 is pytest-timeout's 'no clock', not a "
                    f"longer bound, and no marker raises the driver's stall "
                    f"window): its calls are STILL judged against "
                    f"{self.ceiling}s")
        return (f"{self.path}:{self.line}  {self.test}  "
                f"@pytest.mark.timeout({self.seconds}) -> its calls are judged "
                f"against {self.ceiling}s")


def marker_ceiling(seconds: Optional[float]) -> Optional[int]:
    """`N // 3` for a marker that DECLARES a bound, else None (vibe-ic#1734).

    None means "this marker is not a bound this gate can read", and the ONLY
    thing a caller may do with None is leave the ceiling where it was. It must
    never be spelled as "skip this call": that is the withheld attempt's
    `if call_ceiling is None: continue`, which fired ahead of the
    forwarder/advisory lane and so retired a RECORDED ADVISORY as well as a
    finding. There is no code path in this file that turns a marker into a
    skip, and `self_check` fails the whole gate if one is reintroduced.

    Non-positive is refused rather than divided. `0 // 3 == 0` was the other
    half of the same defect from the opposite side: it read "no clock" as a
    ZERO-second ceiling, which made every bound in such a file a finding —
    including `relay_queue.get(timeout=0.1)`. One quirk, two false verdicts.
    """
    if seconds is None or seconds <= 0:
        return None
    if seconds > DRIVER_STALL_S:
        # ABOVE THE CLOCK THAT ACTUALLY ENDS THE RUN, so it is not a bound and it
        # does not become one by being written down. Returning None leaves the
        # ceiling at the default — the SAFE direction — rather than granting the
        # room the marker asked for. `raised_above_driver_stall()` reports it
        # separately, because silently ignoring a marker somebody wrote on purpose
        # would leave them believing they had raised something.
        return None
    return int(seconds) // CEILING_DIVISOR


def raised_above_driver_stall(seconds: Optional[float]) -> bool:
    """Is this marker asking for more room than any clock in the run will give?

    Separate from :func:`marker_ceiling` on purpose. That function answers "what
    ceiling does this marker buy" and must answer conservatively; this one answers
    "should somebody be told", and the two have different failure directions. A
    marker that is ignored AND unreported is how a contributor comes to believe a
    file is exempt when it is not.
    """
    return seconds is not None and seconds > DRIVER_STALL_S


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

    …AND ONLY THE POSITIVE ONES ARE CANDIDATES (vibe-ic#1734 defect 4). The
    sentence above is only true while every candidate is a BOUND, because
    "smallest" and "tightest" are the same word only then. The withheld attempt
    made 0 mean total exemption and left `min` alone, so
    `pytestmark = [pytest.mark.timeout(0), pytest.mark.timeout(300)]` around
    `subprocess.run(timeout=900)` returned rc=0 — `min` had silently become the
    most-PERMISSIVE pick while its docstring still argued for the tightest. A
    non-positive mark is not a bound (see `marker_ceiling`), so it is not in the
    running; the tie-break is over bounds again and means what it says.
    """
    best: Optional[Tuple[float, int]] = None
    for secs, line in module_timeout_marks(tree, consts):
        if secs <= 0:
            continue
        if best is None or secs < best[0]:
            best = (secs, line)
    return best


def module_timeout_marks(tree: ast.AST, consts: Dict[str, Tuple[float, int]]
                         ) -> List[Tuple[float, int]]:
    """Every readable `pytestmark = pytest.mark.timeout(N)` value, in order.

    Split out from `module_item_marker` so a NON-POSITIVE mark still reaches
    the disclosure. It is not a bound and must not move the ceiling, but it is
    a declaration a reader has to be able to see: an exclusion nobody can see
    is indistinguishable from a clean result, and that is as true of a
    declaration that buys nothing as of one that buys something.
    """
    out: List[Tuple[float, int]] = []
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
            if got is not None:
                out.append((got[0], node.lineno))
    return out


def scan_source(text: str, rel_path: str, ceiling: int
                ) -> Tuple[List[Finding], List[Finding], int]:
    """(findings, unresolved_above_ceiling, bounded_call_sites) for one file.

    Kept as the three-value shape every caller and test already uses; the
    marked-item census is the fourth thing `scan_source_report` returns.
    """
    rep = scan_source_report(text, rel_path, ceiling)
    return rep["findings"], rep["unresolved_above_ceiling"], rep["sites"]


def scan_source_report(text: str, rel_path: str, ceiling: int) -> Dict:
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
    fn_marker: Dict[int, int] = {}
    marked: List[MarkedItem] = []
    mod_marker = module_item_marker(tree, consts)
    collectable_items = pytest_item_functions(tree)
    file_ceiling = ceiling
    if mod_marker is not None:
        # Positive by construction — `module_item_marker` refuses the rest —
        # but read through `marker_ceiling` anyway, so there is exactly ONE
        # place in this file where a marker becomes a ceiling.
        raised = marker_ceiling(mod_marker[0])
        file_ceiling = ceiling if raised is None else raised
        # A marker ABOVE the driver's stall window bought nothing (marker_ceiling
        # returned None), and saying nothing about it would leave its author
        # believing the file was exempt. `raises=False` because it is exactly that:
        # a declaration that raised no ceiling.
        _over = raised_above_driver_stall(mod_marker[0])
        marked.append(MarkedItem(rel_path, mod_marker[1],
                                 "<pytestmark: every test in this file>",
                                 mod_marker[0], file_ceiling,
                                 raises=not _over))
    for secs, line in module_timeout_marks(tree, consts):
        if secs > 0:
            continue
        # Disclosed, and buys nothing: `file_ceiling` is not touched here.
        marked.append(MarkedItem(rel_path, line,
                                 "<pytestmark: every test in this file>",
                                 secs, file_ceiling, raises=False))
    for fn in funcs:
        if id(fn) not in collectable_items:
            continue
        mk = item_timeout_marker(fn, consts)
        if mk is None:
            continue
        mc = marker_ceiling(mk)
        if mc is None:
            marked.append(MarkedItem(rel_path, fn.lineno, fn.name, mk,
                                     file_ceiling, raises=False))
            continue
        fn_marker[id(fn)] = mc
        marked.append(MarkedItem(rel_path, fn.lineno, fn.name, mk, mc))

    findings: List[Finding] = []
    unresolved: List[Finding] = []
    total = 0
    # The census the verdict sentence is written from (vibe-ic#1734 defect 2).
    # `judged` must equal `sites` on every path through the loop below: this
    # gate judges every bound it can read, and the PASS line says so by
    # printing both. A future exemption that skipped a call would show up here
    # as `judged < sites` before it could show up as a false green.
    judged = 0
    at_session = 0
    at_raised = 0
    max_applied = ceiling
    if not timeout_calls:
        return {"findings": findings, "unresolved_above_ceiling": unresolved,
                "sites": total, "marked_items": marked, "judged": judged,
                "judged_at_session_ceiling": at_session,
                "judged_at_raised_ceiling": at_raised,
                "max_applied_ceiling": max_applied}

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
        # ALWAYS an int. A marker that this file cannot read as a bound leaves
        # it where it was; there is no `None` for a later `continue` to key
        # off, which is the vibe-ic#1734 defect stated as a type.
        call_ceiling = file_ceiling
        for fn in reversed(chain):
            if id(fn) in fn_marker:
                call_ceiling = fn_marker[id(fn)]
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
            judged += 1
            if call_ceiling > ceiling:
                at_raised += 1
                max_applied = max(max_applied, call_ceiling)
            else:
                at_session += 1
            if seconds <= call_ceiling:
                continue
            if forwarders is None:
                forwarders = _forwarding_helpers(tree, mods, names, funcs)
            why = _classify_callee(node.func, mods, names, forwarders)
            if why is NOT_A_BOUND:
                continue
            rec = Finding(rel_path, val.lineno, _dotted(node.func), kw_name,
                          seconds, why or "not resolvable from this file",
                          const_name, const_line, const_kind, owner,
                          call_ceiling)
            (findings if why else unresolved).append(rec)
    return {"findings": findings, "unresolved_above_ceiling": unresolved,
            "sites": total, "marked_items": marked, "judged": judged,
            "judged_at_session_ceiling": at_session,
            "judged_at_raised_ceiling": at_raised,
            "max_applied_ceiling": max_applied}


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
              anchor: Optional[Path] = None) -> Dict:
    findings: List[Finding] = []
    unresolved: List[Finding] = []
    marked: List[MarkedItem] = []
    files = 0
    sites = 0
    judged = 0
    at_session = 0
    at_raised = 0
    max_applied = ceiling
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
            one = scan_source_report(text, rel, ceiling)
        except SyntaxError:
            unparseable.append(rel)
            continue
        findings.extend(one["findings"])
        unresolved.extend(one["unresolved_above_ceiling"])
        marked.extend(one["marked_items"])
        sites += one["sites"]
        judged += one["judged"]
        at_session += one["judged_at_session_ceiling"]
        at_raised += one["judged_at_raised_ceiling"]
        max_applied = max(max_applied, one["max_applied_ceiling"])
    return {"files": files, "bounded_sites": sites, "findings": findings,
            "unresolved_above_ceiling": unresolved, "marked_items": marked,
            "unparseable": unparseable, "judged": judged,
            "judged_at_session_ceiling": at_session,
            "judged_at_raised_ceiling": at_raised,
            "max_applied_ceiling": max_applied}


def scan_roots(roots: Sequence[Tuple[Path, str, Optional[Path]]],
               ceiling: int) -> Dict:
    """Merge `scan_tree` over every root a pytest lane actually runs.

    Kept as a merge rather than one root with one glob because the two trees
    are not the same KIND of directory — see `TOOLS_DIR_REL` for why one is
    scanned whole and the other only for its test files.
    """
    merged = {"files": 0, "bounded_sites": 0, "findings": [],
              "unresolved_above_ceiling": [], "marked_items": [],
              "unparseable": [], "roots": [], "judged": 0,
              "judged_at_session_ceiling": 0, "judged_at_raised_ceiling": 0,
              "max_applied_ceiling": ceiling}
    for root, glob, anchor in roots:
        rep = scan_tree(root, ceiling, glob, anchor)
        merged["files"] += rep["files"]
        merged["bounded_sites"] += rep["bounded_sites"]
        merged["judged"] += rep["judged"]
        merged["judged_at_session_ceiling"] += rep["judged_at_session_ceiling"]
        merged["judged_at_raised_ceiling"] += rep["judged_at_raised_ceiling"]
        merged["max_applied_ceiling"] = max(merged["max_applied_ceiling"],
                                            rep["max_applied_ceiling"])
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


# --- the gate's own falsifiability, run on EVERY invocation -----------------

#: WHY THIS LIVES IN THE PROGRAM AND NOT ONLY IN ITS PYTEST FILE (#1734 defect
#: 3). The paired guard for the withheld attempt was written as pytest cases in
#: `programs/tests/test_ci_harness_timeout_ceiling_check.py`. That file is not
#: in `SMOKE_BASENAMES`, and `tools/gatekeeper-land.sh` builds its pytest list
#: from `ci_targeted_test_select.py --base $BASE`. MEASURED on the exact diff
#: that reintroduces the defect — one line, `pytestmark =
#: pytest.mark.timeout(0)`, added to `test_matrix_mutation_ledger.py` — the
#: real selector chose 18 files and that guard was not among them. So the guard
#: could not run on the only PR it exists for, while `repo_hygiene_gates.sh`
#: (which DOES run on every landing, line `inner timeouts fit the harness`)
#: returned rc=0 PASS.
#:
#: The rule the whole of #1734 is an instance of: A CHANGE WHOSE PURPOSE IS TO
#: MAKE SOMETHING SKIP NEEDS ITS GUARD WIRED AT THE LAYER THAT ALWAYS RUNS, NOT
#: AT THE LAYER THE CHANGE ITSELF SELECTS. The layer that always runs is this
#: program, so the assertions live here, execute before the scan on every run,
#: and fail the gate. The pytest file keeps them too — `SMOKE_BASENAMES` now
#: carries it — but neither copy depends on the other being reached.
#:
#: Each case is (label, source, ceiling, expected findings, expected
#: advisories, expected readable sites). ~1 ms for all of them: six ast.parse
#: calls on strings, no filesystem.
_SELF_CHECK: Tuple[Tuple[str, str, int, int, int, int], ...] = (
    ("a zero module marker does not retire a FINDING",
     "import pytest, subprocess\n"
     "pytestmark = pytest.mark.timeout(0)\n"
     "def test_x():\n"
     "    subprocess.run(['x'], timeout=900)\n", 60, 1, 0, 1),
    ("a zero module marker does not retire a recorded ADVISORY",
     "import pytest\n"
     "pytestmark = pytest.mark.timeout(0)\n"
     "def test_x():\n"
     "    L.replay_many(timeout=900)\n", 60, 0, 1, 1),
    ("a zero PER-TEST marker does not retire a finding either",
     "import pytest, subprocess\n"
     "@pytest.mark.timeout(0)\n"
     "def test_x():\n"
     "    subprocess.run(['x'], timeout=900)\n", 60, 1, 0, 1),
    ("the tie-break over [timeout(0), timeout(300)] picks 300, not 0",
     "import pytest, subprocess\n"
     "pytestmark = [pytest.mark.timeout(0), pytest.mark.timeout(300)]\n"
     "def test_x():\n"
     "    subprocess.run(['x'], timeout=900)\n", 60, 1, 0, 1),
    ("a marker still TIGHTENS: 30 // 3 = 10 catches a 60 s call",
     "import pytest, subprocess\n"
     "pytestmark = pytest.mark.timeout(30)\n"
     "def test_x():\n"
     "    subprocess.run(['x'], timeout=60)\n", 60, 1, 0, 1),
    ("a positive marker is a DECLARED bound, still judged, not an exemption",
     "import pytest, subprocess\n"
     "pytestmark = pytest.mark.timeout(600)\n"
     "def test_x():\n"
     "    subprocess.run(['x'], timeout=201)\n", 60, 1, 0, 1),

    # ── ONE CASE PER DOOR, NOT PER NUMBER ────────────────────────────────────
    #
    # The six above are all about `0` or about tightening, and that is precisely
    # how the second attempt at #1734 shipped a live silencer: it closed the value
    # that had been reported and left the door beside it open. A contributor wrote
    # `2700` instead of `0` and got a 900 s call to PASS on the fixed gate.
    #
    # These four are keyed to the DOOR — raise the ceiling, retire an advisory,
    # retire a finding, out-run the clock nobody can move — so a future spelling of
    # any of them fails here rather than in production.

    ("a marker ABOVE the driver stall window buys NOTHING (the 2700 door)",
     "import pytest, subprocess\n"
     "pytestmark = pytest.mark.timeout(2700)\n"
     "def test_x():\n"
     "    subprocess.run(['x'], timeout=900)\n", 60, 1, 0, 1),

    ("…and it cannot retire a recorded ADVISORY either",
     "import pytest\n"
     "pytestmark = pytest.mark.timeout(2700)\n"
     "def test_x():\n"
     "    L.replay_many(timeout=900)\n", 60, 0, 1, 1),

    ("one second over the stall window already buys nothing",
     "import pytest, subprocess\n"
     "pytestmark = pytest.mark.timeout(301)\n"
     "def test_x():\n"
     "    subprocess.run(['x'], timeout=900)\n", 60, 1, 0, 1),

    # THE PAIRED HALF. Without it the four above pass against a gate that ignores
    # every marker — which would be a different defect with the same green.
    ("a marker AT the stall window is still honoured: 300 // 3 = 100 clears 90 s",
     "import pytest, subprocess\n"
     "pytestmark = pytest.mark.timeout(300)\n"
     "def test_x():\n"
     "    subprocess.run(['x'], timeout=90)\n", 60, 0, 0, 1),
)


def self_check() -> List[str]:
    """Failures of this gate's own falsifiability cases, empty when sound.

    Also asserts the invariant the verdict sentence is written from: every
    readable bound is JUDGED. `judged != sites` is what an exemption looks like
    one step before it becomes a false green, whatever spelling it arrives in.
    """
    bad: List[str] = []
    for label, src, ceil, want_f, want_u, want_sites in _SELF_CHECK:
        try:
            rep = scan_source_report(src, "<self-check>", ceil)
        except SyntaxError as exc:            # pragma: no cover - fixture typo
            bad.append(f"{label}: the fixture does not parse ({exc})")
            continue
        got = (len(rep["findings"]), len(rep["unresolved_above_ceiling"]),
               rep["sites"])
        if got != (want_f, want_u, want_sites):
            bad.append(f"{label}: expected "
                       f"{(want_f, want_u, want_sites)} "
                       f"(finding(s), advisory(ies), readable bound(s)), got "
                       f"{got}")
        if rep["judged"] != rep["sites"]:
            bad.append(f"{label}: {rep['sites']} readable bound(s) but "
                       f"{rep['judged']} judged — a bound was dropped from the "
                       "judged set, which is the exemption shape this gate "
                       "refuses (vibe-ic#1734)")
    if marker_ceiling(0) is not None or marker_ceiling(-1) is not None:
        bad.append("marker_ceiling accepted a non-positive marker as a bound")
    # …and the tie-break STRUCTURALLY, not only through the verdict. With
    # `marker_ceiling` refusing 0 the behaviour above survives a `min` that
    # still considers 0, because the refusal happens downstream — so a mutant
    # that puts 0 back in the running would slip past a behaviour-only case.
    # Defence in depth is the point: either edit alone must be caught, since
    # the withheld attempt needed both and a future one might need one.
    tie = module_item_marker(ast.parse(
        "pytestmark = [pytest.mark.timeout(0), pytest.mark.timeout(300)]"), {})
    if tie is None or tie[0] != 300:
        bad.append("the min() tie-break over [timeout(0), timeout(300)] "
                   f"returned {tie} — 0 is not a bound and must not be a "
                   "candidate, or `smallest` stops meaning `tightest`")
    return bad


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
    ap.add_argument("--self-check-only", action="store_true",
                    help="run only the falsifiability cases below and exit "
                         "(they run on EVERY invocation regardless; this flag "
                         "is for reading them without a tree)")
    args = ap.parse_args(argv)

    # BEFORE anything else, and unconditionally. This is the assertion that
    # `repo_hygiene_gates.sh` always reaches; see `_SELF_CHECK`.
    broken = self_check()
    if broken:
        print("[FAIL] ci_harness_timeout_ceiling_check SELF-CHECK: this gate "
              "can no longer catch what it exists to catch, so its verdict "
              "about the tree would not mean anything:")
        for b in broken:
            print(f"   {b}")
        print("  Nothing was scanned. This is NOT a pass.")
        return 1
    if args.self_check_only:
        print(f"[PASS] ci_harness_timeout_ceiling_check SELF-CHECK: "
              f"{len(_SELF_CHECK)} falsifiability case(s), including that a "
              "`pytestmark = pytest.mark.timeout(0)` retires neither a finding "
              "nor a recorded advisory. No tree was scanned.")
        return 0

    repo_root = find_repo_root(Path(args.root)) if args.root else \
        find_repo_root()
    if args.root and repo_root is None:
        repo_root = Path(args.root) if Path(args.root).is_dir() else None

    bounds = harness_bounds(repo_root) if repo_root else []
    harness = min((b.seconds for b in bounds), default=None)
    roots = _scan_roots(repo_root, args.tests_root)

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
    if not roots:
        print(f"[CANNOT DETERMINE] ci_harness_timeout_ceiling_check: harness "
              f"bound {harness}s resolved, but no test tree to scan "
              f"({args.tests_root or TESTS_DIR_REL} not found) -- 0 files "
              "examined, which is NOT a pass.")
        return 2

    rep = scan_roots(roots, ceiling)

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
    raising = [m for m in marked if m.raises]
    print(f"  test(s) carrying @pytest.mark.timeout: {len(marked)} — "
          f"{len(raising)} declare a bound that replaces the {harness}s item "
          f"bound (judged against their own marker // {CEILING_DIVISOR}), "
          f"{len(marked) - len(raising)} are timeout(0), which is NOT a bound "
          f"and exempts nothing (vibe-ic#1734)")
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

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "program": "ci_harness_timeout_ceiling_check",
            "harness_seconds": harness,
            "ceiling_seconds": ceiling,
            "ceiling_divisor": CEILING_DIVISOR,
            "harness_bounds": [b.as_dict() for b in bounds],
            "roots": rep["roots"],
            "files": rep["files"],
            "bounded_sites": rep["bounded_sites"],
            "judged": rep["judged"],
            "judged_at_session_ceiling": rep["judged_at_session_ceiling"],
            "judged_at_raised_ceiling": rep["judged_at_raised_ceiling"],
            "max_applied_ceiling": rep["max_applied_ceiling"],
            "findings": [f.as_dict() for f in rep["findings"]],
            "unresolved_above_ceiling": [u.as_dict() for u in unres],
            "marked_items": [m.as_dict() for m in rep["marked_items"]],
            "unparseable": rep["unparseable"],
            "passed": not rep["findings"],
        }, indent=2) + "\n", encoding="utf-8")

    # The judged denominator, stated next to the readable one. #1734 defect 2
    # was a PASS sentence that had stopped describing the judged set; the two
    # numbers below are what make that detectable by reading the output.
    print(f"  judged: {rep['judged']} of {rep['bounded_sites']} readable "
          f"bound(s) — {rep['judged_at_session_ceiling']} against the "
          f"{ceiling}s session ceiling, {rep['judged_at_raised_ceiling']} "
          f"against a declared marker's own ceiling (largest applied: "
          f"{rep['max_applied_ceiling']}s). No readable bound is exempt.")

    if rep["findings"]:
        print(f"[FAIL] {len(rep['findings'])} inner bound(s) above the ceiling "
              f"that will really apply to them -- each one can outlive the "
              f"item bound that governs it, and under "
              f"`--timeout-method=thread` that kills the SESSION instead of "
              f"the test:")
        for f in rep["findings"]:
            print(f"   {f}   [{f.resolved_via}]  "
                  f"[judged against {f.ceiling}s]")
        print("  Remedy: lower the bound, or move the test out of the "
              "targeted subset if it genuinely needs longer. "
              "`pytest.mark.timeout(0)` is NOT that second remedy -- it turns "
              "off pytest-timeout's clock without taking the item out of the "
              "harness, and this gate does not read it as a bound.")
        return 1
    # TRUE OF WHAT WAS ACTUALLY JUDGED. The old sentence named one number,
    # `{ceiling}s`, and was safe only while the sole exclusion removed
    # UNRESOLVABLE callees -- which is why the word "resolvable" was in it. A
    # marker does not remove a call from the judged set, it changes the number
    # it is judged against, so the sentence names both the count and the
    # largest ceiling actually applied.
    against = f"{ceiling}s"
    if rep["judged_at_raised_ceiling"]:
        against = (f"{ceiling}s for {rep['judged_at_session_ceiling']} of "
                   f"them and their own marker // {CEILING_DIVISOR} for the "
                   f"{rep['judged_at_raised_ceiling']} inside the marked "
                   f"item(s) listed above, largest applied "
                   f"{rep['max_applied_ceiling']}s")
    # The advisory lane is NAMED in the sentence rather than left for the
    # reader to subtract. `judged` counts every readable bound, and an
    # unresolvable callee above the ceiling is one of them — so a sentence that
    # said "all N resolvable calls" while N included that bound would be
    # describing a set it does not have.
    caveat = ("" if not unres else
              f" The {len(unres)} bound(s) above the ceiling whose callee this "
              f"file cannot resolve are listed above as advisory and are NOT "
              f"covered by that claim.")
    print(f"[PASS] all {rep['judged']} readable bound(s) were judged, and "
          f"every one whose callee resolves to a blocking call is at or under "
          f"the ceiling that will really apply to it ({against}), so its own "
          f"timeout can fire before the bound that ends the session. Nothing "
          f"was exempted from the judged set.{caveat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
