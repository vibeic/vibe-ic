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


class Finding:
    def __init__(self, path: str, line: int, callee: str, keyword: str,
                 seconds: float, resolved_via: str,
                 constant: Optional[str] = None,
                 constant_line: Optional[int] = None):
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

    def as_dict(self) -> Dict:
        return {"path": self.path, "line": self.line, "callee": self.callee,
                "keyword": self.keyword, "seconds": self.seconds,
                "resolved_via": self.resolved_via,
                "constant": self.constant,
                "constant_line": self.constant_line}

    def __str__(self) -> str:
        via = (f" [via {self.constant} = {self.seconds}, declared at line "
               f"{self.constant_line}]") if self.constant else ""
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


def _forwarding_helpers(tree: ast.AST, mods: Set[str],
                        names: Set[str]) -> Set[str]:
    """Names of same-file functions that pass a caller's timeout into a
    blocking call, iterated to a fixed point so a chain resolves.

    Derived rather than listed: a hand-written list of helper names would be a
    second registry beside the code, free to drift from it.
    """
    funcs: List[ast.AST] = [n for n in ast.walk(tree)
                            if isinstance(n, (ast.FunctionDef,
                                              ast.AsyncFunctionDef))]
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


def scan_source(text: str, rel_path: str, ceiling: int
                ) -> Tuple[List[Finding], List[Finding], int]:
    """(findings, unresolved_above_ceiling, bounded_call_sites) for one file.

    Raises nothing: an unparseable file yields empty lists and is counted by
    the caller, because a syntax error is a different defect.
    """
    tree = ast.parse(text)
    mods, names = _subprocess_aliases(tree)
    forwarders = _forwarding_helpers(tree, mods, names)
    consts = module_constants(tree)
    findings: List[Finding] = []
    unresolved: List[Finding] = []
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw_name, val in _timeout_kwargs(node):
            const_name = const_line = None
            if (isinstance(val, ast.Constant)
                    and isinstance(val.value, (int, float))
                    and not isinstance(val.value, bool)):
                seconds = val.value
            elif isinstance(val, ast.Name) and val.id in consts:
                seconds, const_line = consts[val.id]
                const_name = val.id
            else:
                # A bound this file does not spell out — a parameter, an
                # attribute, an expression. Not judged and not counted, so the
                # denominator below stays the set of bounds actually readable.
                continue
            total += 1
            if seconds <= ceiling:
                continue
            why = _classify_callee(node.func, mods, names, forwarders)
            if why is NOT_A_BOUND:
                continue
            rec = Finding(rel_path, val.lineno, _dotted(node.func), kw_name,
                          seconds, why or "not resolvable from this file",
                          const_name, const_line)
            (findings if why else unresolved).append(rec)
    return findings, unresolved, total


def scan_tree(tests_root: Path, ceiling: int, glob: str = "*.py",
              anchor: Optional[Path] = None) -> Dict:
    findings: List[Finding] = []
    unresolved: List[Finding] = []
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
            f, u, n = scan_source(text, rel, ceiling)
        except SyntaxError:
            unparseable.append(rel)
            continue
        findings.extend(f)
        unresolved.extend(u)
        sites += n
    return {"files": files, "bounded_sites": sites, "findings": findings,
            "unresolved_above_ceiling": unresolved,
            "unparseable": unparseable}


def scan_roots(roots: Sequence[Tuple[Path, str, Optional[Path]]],
               ceiling: int) -> Dict:
    """Merge `scan_tree` over every root a pytest lane actually runs.

    Kept as a merge rather than one root with one glob because the two trees
    are not the same KIND of directory — see `TOOLS_DIR_REL` for why one is
    scanned whole and the other only for its test files.
    """
    merged = {"files": 0, "bounded_sites": 0, "findings": [],
              "unresolved_above_ceiling": [], "unparseable": [], "roots": []}
    for root, glob, anchor in roots:
        rep = scan_tree(root, ceiling, glob, anchor)
        merged["files"] += rep["files"]
        merged["bounded_sites"] += rep["bounded_sites"]
        merged["findings"].extend(rep["findings"])
        merged["unresolved_above_ceiling"].extend(
            rep["unresolved_above_ceiling"])
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
            "findings": [f.as_dict() for f in rep["findings"]],
            "unresolved_above_ceiling": [u.as_dict() for u in unres],
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
    print(f"[PASS] every resolvable blocking call is bounded at or under "
          f"{ceiling}s, so its own timeout can fire before the {harness}s "
          f"harness ends the session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
