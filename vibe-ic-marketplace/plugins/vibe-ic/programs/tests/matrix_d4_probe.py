"""matrix_d4_probe — live measurement helpers for matrix dimension 4.

Dimension 4 asks: **does what a gate MEASURES match what it CLAIMS to
measure?** This module supplies the two live measurements
``test_matrix_d4_criteria_match.py`` builds its predicate from. It decides
nothing; it measures.

Nothing here reads ``.audit_63x8.json``. Every value is recomputed from the
current flow yaml, the current program sources, and — for the CLI contract —
from actually running the program.

====================================================================
MEASUREMENT 1 — CLI CONTRACT (behavioural, not textual)
====================================================================
:func:`probe_cli` takes the gate command **verbatim from the flow yaml**, runs
it in a fresh EMPTY scratch project, and reports whether the program's own
argument parser ACCEPTED the invocation.

This is a claim-vs-reality question, not a style question. The yaml says "step
33 measures power and writes its audit trail to ``reports/.../power_report.json``".
If the named program's parser has no ``--json``, argparse exits 2 — and
``flow_compliance_check._check_program_exit_zero`` maps ``rc == 2`` onto
``VACUOUS_PASS``, which is COUNTED AS A PASS. The clause then banks sign-off
credit while measuring nothing and writing nothing. That exact defect shipped
twice (``lvs_report_check`` #507, ``power_report_check`` — see that file's
docstring) and one instance is still live.

Why running it rather than scanning ``--help``: a text scan of help output is a
substring scan, and this codebase forwards argv through wrappers
(``power_report_check`` → ``eda_report_audit``), so the option set that matters
belongs to a module the wrapper imports, not to the file whose name is in the
yaml. Running the real invocation asks the real parser.

A violation is recognised by the CONJUNCTION of two independent signals —
``rc == 2`` (argparse's usage-error exit) AND a stderr line of argparse's own
``prog: error: <usage problem>`` shape. Neither alone is enough: rc 2 is also
the flow's honest "input absent" convention, and a program could legitimately
print the word "error".

Cost, measured on this tree 2026-07-27: 137 clauses, 4.6 s wall total.

====================================================================
MEASUREMENT 2 — ARTEFACT GROUNDING (static, with the dynamic forms resolved)
====================================================================
:func:`ground` answers, for one ``required_outputs`` entry of one step: does
ANY gate program of that step actually name a path that resolves to this
artefact — or does the gate's own invocation hand it over?

**CLAIM side** = the flow yaml's own statement of what the step delivers
(``required_outputs``). **ACTUAL side** = three channels, in this order:

  ``CODE``   a path-shaped string constant in the EXECUTABLE AST of a gate
             program or of a local helper it imports directly. Docstrings are
             excluded by construction (``ast`` drops comments; module / class /
             function docstring nodes are identified and skipped) — a path
             named only in prose is a CLAIM, never a read. This separation is
             the whole point: PR #460's lesson was that a grep counted a path
             inside a ``# e.g. "foo_check"`` comment as a call site.
  ``GATE``   a path the gate itself declares: a positional / ``--flag=value``
             argument of an exec clause, a ``files_exist`` entry, an
             ``optional_program_exit_zero`` ``condition_files_exist`` entry, or
             a ``json_field_true`` file. The gate is demonstrably wired to the
             artefact even when the program computes the path from argv.
  ``PREFIX`` a filename-PREFIX selector: an executable string constant of >= 3
             chars ending in ``_``/``-``/``.`` that is a prefix of the
             artefact's basename, held by a program that also names the
             artefact's directory. This resolves the one shape a path matcher
             cannot see — ``gd.glob("*.json")`` filtered by a
             ``_REQUIRED_PREFIXES`` table (``phase1_all_l_docs_present_check``).
             It fires on exactly ONE of the 122 entries; it is not a back door.

Dynamic forms are resolved explicitly rather than given up on:
  * f-strings are reconstructed, substituting module-level ``NAME = "literal"``
    constants where the interpolated value is such a name
    (``f"{_LAYER}_*.json"`` -> ``L11_*.json``) and ``*`` elsewhere;
  * ``Path(x) / "a" / "b"`` chains are folded into ``*/a/b``.

--------------------------------------------------------------------
Two deliberate limits, both measured
--------------------------------------------------------------------
**Import depth is 1** — a gate program plus the local modules it imports
DIRECTLY. Measured: depth 2 changes nothing (identical miss set); depth 3
reaches ``_path_layout.py``, the project's single-source-of-truth DIRECTORY
CATALOGUE, and grounds artefacts the gate demonstrably never opens. The
specimen that settled it, quoted as it stood then: step 25's
``reports/phase3/em.json`` came out "grounded" at depth 3 by the catalogue
while ``eda_report_audit._check_em`` searched ``*em*.rpt`` only. Depth 3
measured 7 ungrounded artefacts instead of 9 — the difference bought entirely
from a catalogue, not from a read. (``_check_em`` now really does open
``em.json``; the depth-3 objection is unaffected, because what made depth 3
wrong was that it could not tell the two cases apart.)

CHANNEL SPLIT — RE-DERIVED 2026-07-28, because the numbers that stood here
before traced to no artifact. The figures previously written in this paragraph
("122 declared artefacts ... 112 CODE / 9 GATE / 1 PREFIX / 0 NONE", and
"103 / 9 / 1 / 9" for the pre-fix tree) reproduce under no definition: they
understated the weak yaml-vs-yaml GATE channel by roughly four times, which is
the one number a reader would use to judge how strong these closures are.

Re-measured with this module's own :func:`ground` over every ``required_outputs``
entry of every step that declares any::

    this tree: 61 steps, 133 artefacts -> CODE 90, GATE 40, PREFIX 1, NONE 2
    test/matrix-63x8-coverage (241563f66):
               61 steps, 126 artefacts -> CODE 79, GATE 35, PREFIX 1, NONE 11

Reproduce on either tree with::

    PYTHONPATH=programs:programs/tests python3 -c "
    import sys; sys.path[:0]=['programs','programs/tests']
    import matrix_d4_probe as PR
    from matrix import flowref as F
    from collections import Counter
    c=Counter()
    for s in F.step_ids():
        for e in F.required_outputs(s):
            g=PR.ground(s,e); c[g.channel if g else 'NONE']+=1
    print(dict(c))"

The 9 artefacts that were UNGROUNDED when this module was written moved into
the CODE column by CHANGING THE GATES, not this measurement: each of those
steps' programs now opens the artefact its step declares. The artefact total
moved 126 -> 133 because the dimension-7 work DECLARED seven more of them, so
the two rows are not the same denominator and must not be subtracted.

READ THE **GATE** COLUMN AS THE WEAK ONE. 40 of 133 declared artefacts are
grounded only by the gate's own yaml declaration — a yaml-vs-yaml agreement,
not evidence that any program opens the file.

**``_path_layout`` is excluded outright** (:data:`CATALOGUE_MODULES`), because
50 gate programs import it directly and it carries 163 path literals: at depth
1 it would put the flow's whole canonical layout into every one of those steps'
"reads". Excluding it changes nothing today (measured: identical miss set) and
keeps a future edit from silently turning the predicate vacuous. The exclusion
is itself machine-checked — see ``test_d4_catalogue_exclusion_is_justified``.

--------------------------------------------------------------------
Matching rule (why not a substring test)
--------------------------------------------------------------------
:func:`covers` matches on PATH COMPONENTS, not substrings, with ``**``
absorbing any number of components and per-component ``fnmatch`` in both
directions. Component granularity is load-bearing: it is what separates
``manufacturing/mask_set_received.json`` from
``phase3/stage5_manufacturing/mask_set_received.json`` — same basename,
different directory, which is exactly the step-40/42 defect the July audit
found and someone has since fixed. A substring or basename test would call
that a match and re-hide the defect the moment it came back.

A shape match alone is not enough; :func:`_strong` then requires the match to
rest on something distinctive:
  * the two basename stems share an alphanumeric token (>= 2 chars), OR
  * both basenames are bare-extension globs of the same extension
    (``*.sdc`` grounding ``.../constraints/*.sdc`` — the artefact declaration
    itself carries nothing but the extension, so nothing more can be asked), OR
  * one side is a bare-extension glob of the same extension AND the pattern
    carries at least one LITERAL directory component that aligned.
Without that guard a program's own ``flow_compliance_check.log`` "grounds" a
step's ``phase2/stage1/sim/*.log`` — measured, and rejected.
"""
from __future__ import annotations

import ast
import fnmatch
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from matrix import flowref as F

PROGRAMS_DIR: Path = F.PROGRAMS_DIR

#: Modules excluded from the read closure: shared path CATALOGUES whose
#: literals describe the FLOW's canonical layout, not what any one gate reads.
CATALOGUE_MODULES: Tuple[str, ...] = ("_path_layout",)

#: How far the read closure follows local imports. See the module docstring.
IMPORT_DEPTH = 1

# ──────────────────────────────────────────────────────────────────────
# MEASUREMENT 1 — CLI contract
# ──────────────────────────────────────────────────────────────────────

#: argparse's own usage-error shapes. Anchored to a ``prog: error:`` line so a
#: program that merely PRINTS the word "error" is not mistaken for a parser
#: rejection.
_ARGPARSE_ERROR = re.compile(
    r"^\S*:\s*error:\s*("
    r"unrecognized arguments?"
    r"|argument [^\n:]*: invalid choice"
    r"|argument [^\n:]*: expected"
    r"|the following arguments are required"
    r"|ambiguous option"
    r"|expected one argument"
    r"|invalid [\w<> ]*value"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

#: argparse exits 2 on a usage error. Required IN ADDITION to the stderr shape.
ARGPARSE_USAGE_EXIT = 2

PROBE_TIMEOUT_S = 60


@dataclass(frozen=True)
class CliProbe:
    """The result of running one gate command verbatim in an empty project."""

    command: str
    program: str
    returncode: Optional[int]
    stderr_tail: str
    parser_error: Optional[str]
    timed_out: bool

    @property
    def rejected(self) -> bool:
        """True when the program's OWN parser refused the yaml's invocation."""
        return (
            not self.timed_out
            and self.returncode == ARGPARSE_USAGE_EXIT
            and self.parser_error is not None
        )


@lru_cache(maxsize=None)
def probe_cli(command: str) -> CliProbe:
    """Run *command* (a flow-yaml gate command) in a fresh empty project.

    Cached per command string: the 137 clauses of the flow resolve to 137
    subprocess runs for the whole module, ~5 s total.

    The scratch project is empty on purpose. Whether the parser accepts the
    invocation is a property of the program, not of the project, and an empty
    tree keeps every gate program on its fast "nothing to audit" path.
    """
    tokens = shlex.split(command)
    program = tokens[0] if tokens else ""
    path = F.program_path(program)
    if path is None:
        return CliProbe(command, program, None, "", None, False)

    env = dict(os.environ)
    env["VIBE_IC_NO_DASHBOARD"] = "1"
    env["VIBE_IC_MATRIX_D4_PROBE"] = "1"
    env.pop(F.FLOW_YAML_ENV, None)

    with tempfile.TemporaryDirectory(prefix="matrix_d4_probe_") as scratch:
        argv = [sys.executable, str(path)] + tokens[1:]
        try:
            run = subprocess.run(
                argv,
                cwd=scratch,
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT_S,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return CliProbe(command, program, None, "", None, True)

    stderr = run.stderr or ""
    hit = _ARGPARSE_ERROR.search(stderr)
    tail = "\n".join(stderr.strip().splitlines()[-3:])[:400]
    return CliProbe(
        command=command,
        program=program,
        returncode=run.returncode,
        stderr_tail=tail,
        parser_error=hit.group(0) if hit else None,
        timed_out=False,
    )


def cli_violations(step_id) -> Tuple[CliProbe, ...]:
    """Every exec clause of *step_id* whose declared invocation is REJECTED."""
    out: List[CliProbe] = []
    for clause in F.gate_clauses(step_id):
        if clause.command is None or F.program_path(clause.program or "") is None:
            continue
        probe = probe_cli(clause.command)
        if probe.rejected or probe.timed_out:
            out.append(probe)
    return tuple(out)


# ──────────────────────────────────────────────────────────────────────
# MEASUREMENT 2 — artefact grounding
# ──────────────────────────────────────────────────────────────────────
_ARTEFACT_EXT = (
    "json", "jsonl", "rpt", "log", "txt", "def", "gds", "gds2", "spef", "sdc",
    "sdf", "v", "sv", "sp", "spice", "lef", "lib", "mag", "csv", "flag", "md",
    "done", "xml", "yaml", "yml", "tcl", "sby", "vcd", "sof", "pof", "lyrdb",
    "report", "ngspice", "cir", "bit", "dat", "out", "saif", "cdl", "il",
    "bsdl", "stat", "db", "gz",
)
_EXT_RE = re.compile(r"\.(" + "|".join(_ARTEFACT_EXT) + r")$", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_WILDCARD_CHARS = "*?["
_PREFIX_TERMINATORS = ("_", "-", ".")

#: Grounding channels, strongest evidence first in the failure message.
CH_CODE = "CODE"
CH_GATE = "GATE"
CH_PREFIX = "PREFIX"


@dataclass(frozen=True)
class Grounding:
    """Why one declared artefact counts as measured by its step's gate."""

    artefact: str
    alternative: str
    pattern: str
    channel: str
    source: str

    def describe(self) -> str:
        return (
            f"{self.channel} evidence: {self.source} names {self.pattern!r}, "
            f"which resolves the declared alternative {self.alternative!r}"
        )


# ---------- source extraction -------------------------------------------------
@lru_cache(maxsize=None)
def _module_facts(path: Path) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """``(executable string constants, locally-importable module names)``.

    Docstrings are removed; comments never enter the AST at all. f-strings and
    ``Path / "a" / "b"`` chains are folded into glob-shaped strings, with
    module-level ``NAME = "literal"`` constants substituted where they are the
    interpolated value.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):  # pragma: no cover - defensive
        return ((), ())

    consts: Dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            consts[node.targets[0].id] = node.value.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            consts[node.target.id] = node.value.value

    doc_ids: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                doc_ids.add(id(body[0].value))

    def fold(node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return consts.get(node.id)
        if isinstance(node, ast.JoinedStr):
            parts: List[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                elif isinstance(value, ast.FormattedValue):
                    parts.append(fold(value.value) or "*")
                else:  # pragma: no cover - defensive
                    parts.append("*")
            return "".join(parts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            right = fold(node.right)
            if right is None:
                return None
            left = fold(node.left)
            return (left if left is not None else "*") + "/" + right
        return None

    strings: List[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in doc_ids
        ):
            strings.append(node.value)
        elif isinstance(node, (ast.JoinedStr, ast.BinOp)):
            folded = fold(node)
            if folded:
                strings.append(folded)

    imports: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])

    return (tuple(strings), tuple(sorted(imports)))


@lru_cache(maxsize=None)
def read_closure(basename: str, depth: int = IMPORT_DEPTH) -> Tuple[str, ...]:
    """Executable string constants of *basename* + its direct local imports."""
    seen: Set[str] = set()
    frontier = [basename]
    out: List[str] = []
    for _ in range(depth + 1):
        nxt: List[str] = []
        for name in frontier:
            if name in seen or name in CATALOGUE_MODULES:
                continue
            seen.add(name)
            path = PROGRAMS_DIR / f"{name}.py"
            if not path.is_file():
                continue
            strings, imports = _module_facts(path)
            out.extend(strings)
            nxt.extend(
                imp
                for imp in imports
                if imp not in CATALOGUE_MODULES
                and (PROGRAMS_DIR / f"{imp}.py").is_file()
            )
        frontier = nxt
    return tuple(out)


def is_path_shaped(text: str) -> bool:
    """True when *text* could name a file: no whitespace, and a path or ext."""
    stripped = (text or "").strip()
    if not stripped or len(stripped) > 160:
        return False
    if any(ch in stripped for ch in " \n\t"):
        return False
    return bool(_EXT_RE.search(stripped)) or "/" in stripped


@lru_cache(maxsize=None)
def code_patterns(step_id) -> Tuple[Tuple[str, str], ...]:
    """``((pattern, owning program), ...)`` from the step's gate programs."""
    seen: Dict[str, str] = {}
    for program in F.gate_programs(step_id):
        for text in read_closure(program):
            if is_path_shaped(text):
                seen.setdefault(_normalise(text), program)
    return tuple(sorted(seen.items()))


@lru_cache(maxsize=None)
def gate_declared_paths(step_id) -> Tuple[Tuple[str, str], ...]:
    """``((path, where it was declared), ...)`` from the gate itself."""
    seen: Dict[str, str] = {}
    for clause in F.gate_clauses(step_id):
        if clause.command:
            for token in shlex.split(clause.command)[1:]:
                if token.startswith("--"):
                    if "=" not in token:
                        continue
                    token = token.split("=", 1)[1]
                elif token.startswith("-"):
                    continue
                if is_path_shaped(token):
                    seen.setdefault(
                        _normalise(token), f"gate command `{clause.program}`"
                    )
        for entry in clause.files:
            seen.setdefault(_normalise(entry), "gate files_exist clause")
        # `condition_files_exist` is DELIBERATELY NOT a grounding source.
        # WITHDRAWN 2026-07-28 at the convergence merge, with the measurement
        # that forced it. A `files_exist` clause ASSERTS the artefact; a
        # `--json` argument is where the gate WRITES it; `json_field_true`
        # READS it. `condition_files_exist` does none of those: it is a RUN
        # GUARD on the clause — "only bother running this if X is on disk" —
        # and it says nothing whatever about any program opening X.
        #
        # MEASURED: step 32's declared `phase3/stage3/eco/eco_trigger_decision.json`
        # gained a `condition_files_exist` entry so that the ECO gate clause
        # would be REACHABLE on the no-ECO branch (a correct and needed yaml
        # change). With `condition_files_exist` grounding, the step-32
        # dimension-4 cell then passed on the flow file alone: restoring the
        # ORIGINAL defective `programs/eco_loop_audit.py` — in which
        # `grep -c eco_trigger_decision` is 0, i.e. no program reads the record
        # at all — left
        # `test_d4_gate_measures_what_it_claims[step32]` GREEN (`1 passed`).
        # The cell certified a gate that does not read what it claims to
        # measure, which is the exact defect the cell exists to catch.
        #
        # BLAST RADIUS of the withdrawal, measured on this tree over all 133
        # declared artefacts of the exec-gated steps: exactly ONE entry was
        # grounded through this channel (step A9's any-of, via
        # `phase3/analog/*/hw_measurements.json`). See the A9 row of
        # `grounding_report` for where it lands now.
        if clause.json_file:
            seen.setdefault(_normalise(clause.json_file), "gate json_field_true")
    return tuple(sorted(seen.items()))


# ---------- matching ----------------------------------------------------------
def _normalise(path: str) -> str:
    return (path or "").strip().lstrip("./").rstrip("/")


def _components(path: str) -> List[str]:
    return [c for c in _normalise(path).split("/") if c not in ("", ".")]


def _basename(path: str) -> str:
    parts = _components(path)
    return parts[-1] if parts else ""


def _extension(path: str) -> str:
    hit = _EXT_RE.search(_basename(path))
    return hit.group(1).lower() if hit else ""


def _stem_tokens(path: str) -> Set[str]:
    return set(_TOKEN_RE.findall(_EXT_RE.sub("", _basename(path)).lower()))


def _component_match(pattern_part: str, actual_part: str) -> bool:
    return fnmatch.fnmatchcase(actual_part, pattern_part) or fnmatch.fnmatchcase(
        pattern_part, actual_part
    )


def _walk(pattern: Sequence[str], actual: Sequence[str]) -> bool:
    if not pattern:
        return not actual
    if pattern[0] == "**":
        return any(_walk(pattern[1:], actual[i:]) for i in range(len(actual) + 1))
    if not actual:
        return False
    if not _component_match(pattern[0], actual[0]):
        return False
    return _walk(pattern[1:], actual[1:])


def shape_match(pattern: str, artefact: str) -> bool:
    """Component-wise glob match, anchored at the right, either direction."""
    p, a = _components(pattern), _components(artefact)
    if not p or not a:
        return False
    return (
        _walk(p, a)
        or _walk(["**"] + p, a)
        or _walk(a, p)
        or _walk(["**"] + a, p)
    )


def _strong(pattern: str, artefact: str) -> bool:
    """Reject shape matches that rest on nothing distinctive."""
    a_tokens, p_tokens = _stem_tokens(artefact), _stem_tokens(pattern)
    if a_tokens & p_tokens:
        return True
    a_ext, p_ext = _extension(artefact), _extension(pattern)
    if not a_ext or a_ext != p_ext:
        return False
    if not a_tokens and not p_tokens:
        return True
    literal_dirs = [
        c
        for c in _components(pattern)[:-1]
        if c != "**" and not any(ch in c for ch in _WILDCARD_CHARS)
    ]
    return bool(literal_dirs)


@lru_cache(maxsize=1)
def _flow_namespaces() -> frozenset:
    """Top-level directory names the FLOW ITSELF uses for declared artefacts.

    Derived from the flow's own ``required_outputs``, never hand-typed. A list
    of directory names written into this file would rot the moment the project
    layout moved, and a rotting list inside a matcher is a matcher that
    silently starts agreeing — the defect class this whole dimension exists to
    catch, sited in the ruler.
    """
    out = set()
    for sid in F.step_ids():
        try:
            entries = F.required_outputs(sid)
        except Exception:                                    # pragma: no cover
            continue
        for entry in entries:
            for alt in F.split_any_of(entry):
                comps = _components(alt)
                if comps and not F.is_glob(comps[0]):
                    out.add(comps[0])
    return frozenset(out)


def _namespace_anchor_ok(pattern: str, artefact: str) -> bool:
    """Refuse a float-match that crosses a top-level NAMESPACE boundary.

    ``shape_match`` is "anchored at the right, either direction" — it prepends
    ``**`` so a pattern may float. That is what lets a read of
    ``phase1/*.json`` ground the artefact ``reports/phase1/ZZZ.json``: the
    pattern's components are a contiguous tail of the artefact's. But
    ``phase1/`` and ``reports/phase1/`` are two different trees, and a gate that
    reads the first has not looked at the second.

    MEASURED, which is why this is a guard and not a rewrite: over every gated
    step, **132 declared entries are grounded and exactly 1** rests on a
    cross-namespace match — ``*/phase3/erc.rpt`` covering
    ``reports/phase3/erc.rpt``, where the pattern's root is a GLOB and
    therefore legitimately spans namespaces. That case is exempted below, so
    this guard removes no grounding the flow actually relies on. What it
    removes is the ability to ground an artefact NOBODY READS, which is the
    whole point: a canary output injected into a step's ``required_outputs``
    used to pass dimension 4, so the EXEC branch could not fail.

    This is the step-40/42 shape (``manufacturing/...`` vs
    ``phase3/stage5_manufacturing/...``) that this module already has a
    self-check for. That self-check's pair happens to be one the matcher
    already got right, because ``stage5_manufacturing`` is not the same
    COMPONENT as ``manufacturing``. The pair it missed is the one where the
    components match exactly and only the ROOT differs.
    """
    pc, ac = _components(pattern), _components(artefact)
    if not pc or not ac:
        return True
    if F.is_glob(pc[0]) or F.is_glob(ac[0]):
        # a wildcard root is a deliberate "anywhere under the project" read
        return True
    namespaces = _flow_namespaces()
    first_p = next((c for c in pc if c in namespaces), None)
    first_a = next((c for c in ac if c in namespaces), None)
    if first_p is None or first_a is None:
        # one side names no namespace the flow declares — this guard has no
        # opinion, and inventing one would be a second matcher nobody measured
        return True
    return first_p == first_a


def covers(pattern: str, artefact: str) -> bool:
    """Does *pattern*, as read from the tree, resolve *artefact*?"""
    p, a = _normalise(pattern), _normalise(artefact)
    if not p or not a:
        return False
    if p == a:
        return True
    return shape_match(p, a) and _strong(p, a) and _namespace_anchor_ok(p, a)


def _specificity(pattern: str, artefact: str) -> int:
    """Rank competing groundings so the failure message quotes the best one."""
    p, a = _normalise(pattern), _normalise(artefact)
    score = 100 if p == a else 0
    score += 10 * len(set(_components(p)) & set(_components(a)))
    score += 5 * len(_stem_tokens(p) & _stem_tokens(a))
    return score + min(len(_components(p)), 5)


# ---------- the prefix-selector channel ---------------------------------------
def prefix_selector_grounding(step_id, alternative: str) -> Optional[Grounding]:
    """Ground an artefact selected by a filename-PREFIX table plus a dir glob.

    ``phase1_all_l_docs_present_check`` globs ``*.json`` inside the
    generated-docs directory and then keeps only the names starting with each
    entry of ``_REQUIRED_PREFIXES`` (``"L1_"``, ... ``"L5_"``, ...). No path
    matcher can see that; the prefix constant plus a directory pattern that
    aligns with the artefact's directory can.

    The prefix constant and the directory evidence may come from DIFFERENT gate
    programs of the same step. The unit of a dimension-4 cell is the step's
    gate as a whole — D1 runs 18 checkers over one ``generated_docs``
    directory — and the directory itself is often reached through a shared
    layout helper rather than a literal in the checker that holds the prefix
    table. Measured cost of that latitude: this channel fires on exactly 1 of
    the flow's 122 declared artefacts.
    """
    artefact = _normalise(alternative)
    base = _basename(artefact)
    parent = "/".join(_components(artefact)[:-1])
    if not parent or not base:
        return None

    owned: List[Tuple[str, str]] = []
    for program in F.gate_programs(step_id):
        owned.extend((text, program) for text in read_closure(program))
    dirs = [(text, program) for text, program in owned if is_path_shaped(text)]

    for text, program in owned:
        if len(text) < 3 or not text.endswith(_PREFIX_TERMINATORS):
            continue
        if any(ch in text for ch in " \n\t/"):
            continue
        if not base.startswith(text):
            continue
        for candidate, owner in dirs:
            if shape_match(candidate, parent) and (
                set(_components(candidate)) & set(_components(parent))
            ):
                return Grounding(
                    artefact=alternative,
                    alternative=alternative,
                    pattern=f"{text}* under {candidate}",
                    channel=CH_PREFIX,
                    source=(
                        f"programs/{program}.py (prefix table) + "
                        f"programs/{owner}.py (directory)"
                    ),
                )
    return None


# ---------- the public entry point --------------------------------------------
def ground(step_id, entry: str) -> Optional[Grounding]:
    """The best evidence that *entry* is measured by *step_id*'s gate, or None.

    ``entry`` is a raw ``required_outputs`` element; ``" OR "`` inside it is
    any-of, so grounding ANY alternative grounds the entry — that is exactly
    what ``flow_compliance_check`` does when it satisfies the entry.
    """
    candidates: List[Tuple[str, str, str]] = [
        (pattern, CH_CODE, f"programs/{owner}.py")
        for pattern, owner in code_patterns(step_id)
    ]
    candidates += [
        (pattern, CH_GATE, where) for pattern, where in gate_declared_paths(step_id)
    ]

    best: Optional[Tuple[int, Grounding]] = None
    for alternative in F.split_any_of(entry):
        for pattern, channel, source in candidates:
            if not covers(pattern, alternative):
                continue
            rank = _specificity(pattern, alternative)
            if best is None or rank > best[0]:
                best = (
                    rank,
                    Grounding(
                        artefact=entry,
                        alternative=alternative,
                        pattern=pattern,
                        channel=channel,
                        source=source,
                    ),
                )
    if best is not None:
        return best[1]

    for alternative in F.split_any_of(entry):
        hit = prefix_selector_grounding(step_id, alternative)
        if hit is not None:
            return Grounding(
                artefact=entry,
                alternative=hit.alternative,
                pattern=hit.pattern,
                channel=CH_PREFIX,
                source=hit.source,
            )
    return None


def nearest_patterns(step_id, entry: str, limit: int = 4) -> Tuple[str, ...]:
    """The patterns closest to *entry* — quoted when grounding FAILS.

    A failure message that says only "not grounded" is useless; naming what the
    gate DOES read is what lets a reader judge the finding.
    """
    ranked: List[Tuple[int, str]] = []
    alternatives = F.split_any_of(entry)
    for pattern, owner in code_patterns(step_id) + gate_declared_paths(step_id):
        rank = max(_specificity(pattern, alt) for alt in alternatives)
        ranked.append((rank, f"{pattern} ({owner})"))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return tuple(text for _, text in ranked[:limit])


def grounding_report(step_id) -> Tuple[Tuple[str, Optional[Grounding]], ...]:
    """``((entry, grounding-or-None), ...)`` for every declared output."""
    return tuple(
        (entry, ground(step_id, entry)) for entry in F.required_outputs(step_id)
    )


__all__ = [
    "CATALOGUE_MODULES",
    "IMPORT_DEPTH",
    "ARGPARSE_USAGE_EXIT",
    "PROBE_TIMEOUT_S",
    "CliProbe",
    "probe_cli",
    "cli_violations",
    "Grounding",
    "CH_CODE",
    "CH_GATE",
    "CH_PREFIX",
    "code_patterns",
    "gate_declared_paths",
    "read_closure",
    "is_path_shaped",
    "covers",
    "shape_match",
    "ground",
    "grounding_report",
    "nearest_patterns",
    "prefix_selector_grounding",
]
