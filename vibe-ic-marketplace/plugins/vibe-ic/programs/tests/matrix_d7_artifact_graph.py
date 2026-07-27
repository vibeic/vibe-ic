"""matrix_d7_artifact_graph — LIVE producer/consumer graph for dimension 7.

Dimension 7 asks one question of every flow step:

    Is ``required_outputs`` COMPLETE — does the step emit a load-bearing
    artefact that the list never names?

The failure mode this dimension exists to catch is not "the declared file is
missing" (that is dimension 3). It is the quieter one: **a step produces an
artefact nothing declares, so nothing checks it exists, so its absence is
invisible.** Nobody gets a red light; a downstream gate simply reads a file
that is not there and takes its "absent" branch.

====================================================================
EVERYTHING HERE IS RECOMPUTED FROM THE SOURCE TREE
====================================================================
Nothing in this module reads ``.audit_63x8.json``. The inputs are

  * ``flow/phase1_phase2_phase3.yaml``  (via ``matrix_63x8.flowref``), and
  * the **AST** of every ``programs/*.py``.

AST, not grep. The campaign's own cautionary tale (PR #460) is a change that
shipped broken because a substring scan could not see dynamic dispatch, and a
``# e.g. "foo_check"`` comment that a scan counted as a call site. Parsing to
an AST removes comments for free and makes "is this literal in a write
position" a structural question instead of a textual guess. Where a path is
built dynamically this module resolves what it can (``Path`` division chains,
straight-line local assignments, f-string skeletons) and **says so in
:data:`RESOLUTION_LIMITS` where it cannot** — an unresolved write is reported
as a known gap, never silently dropped.

====================================================================
THE FOUR RULES
====================================================================
Each rule below is a different, independently falsifiable way for the
``required_outputs`` list to be incomplete. A step fails dimension 7 when ANY
of them fires.

``W1  gate_output_read_elsewhere``  — LOAD_BEARING
    A gate command of step S designates an output path
    (``--json``/``--out``/``--output``/``--report``/``--summary`` target — see
    :data:`OUTPUT_FLAGS`), and that exact path is consumed by **someone other
    than the program that wrote it**: another program's source references it,
    or another gate clause anywhere in the flow takes it as an input /
    ``files_exist`` / ``condition_files_exist`` / ``json_field_true.file``.
    Written by one thing, read by another, declared by nothing — the artefact
    is load-bearing and undeclared.

    The exclusion matters. The audit's own standard for "correctly
    undeclared" is *self-verifying*: "the gate program both produces and
    checks them in the same invocation" (audit note, step 2). So a path whose
    ONLY reader is its own writer is INCIDENTAL and is not enforced here.

``W2  produced_consumed_undeclared``  — LOAD_BEARING
    An artefact path that
      * some program in ``programs/`` **writes** (AST write position), and
      * some gate — a gate program's own source, or a gate command / condition
        / ``files_exist`` in the yaml — **reads**, and
      * **no** ``required_outputs`` entry anywhere in the flow names.

    Produced, depended on, declared by nobody: exactly the artefact whose
    absence is invisible.

    ATTRIBUTION. The producer is usually a one-shot runner, and the runners
    carry no machine-readable step segmentation (see :data:`RESOLUTION_LIMITS`),
    so "which step emitted it" cannot be read off the source. This module
    resolves the owning step by a fixed, published cascade — never by guessing
    from the file's name:

      1. the step that both DECLARES an output in the same directory and
         CONSUMES the artefact, if exactly one does;
      2. otherwise the sole CONSUMING step, if there is exactly one;
      3. otherwise the sole step declaring an output in the same directory;
      4. otherwise UNATTRIBUTABLE — recorded by
         :func:`unattributable_findings` and enforced against no step, because
         charging a shared artefact to an arbitrary one of eleven candidates
         would be a guess reported as a finding.

    Step-level ``condition`` files are excluded from W2 by basename: a step's
    applicability precondition is an UPSTREAM input by construction, so the
    consuming step is never its emitter. Without this, one undeclared file
    (``analog_block_list.json``) would be charged to all thirteen analog and
    mixed-signal steps at once.

``W3  gate_required_file_undeclared``  — LOAD_BEARING
    Step S's gate asserts a file exists (``files_exist`` clause, or a
    ``json_field_true`` file). If NO step's ``required_outputs`` names that
    artefact, then the flow depends on a file it never declares. Every
    ``files_exist`` path in the current yaml IS declared somewhere, so this
    rule fires on nothing today — it is a live invariant, not a dead branch:
    deleting a declaration reddens the step that gates on it.

``W4  no_required_outputs_but_gate_writes``  — LOAD_BEARING
    Step S declares no ``required_outputs`` key at all, yet its gate
    designates output paths. An absent list cannot be complete.

Everything else a step writes — a ``--json`` evidence file nobody else reads,
a log, a cache — is classified :data:`EVIDENCE` or :data:`INCIDENTAL` and is
**reported, not enforced** (:func:`evidence_findings`). That split is the
brief's, and keeping it means a green test means something.

====================================================================
THE BASENAME RELAXATION — a deliberate precision/recall trade
====================================================================
An artefact is treated as DECLARED when some ``required_outputs`` entry
anywhere in the flow either

  a) matches the path (exact or ``fnmatch``), or
  b) carries the same **basename**.

(b) is deliberate and it costs recall. ``erc_density_check`` probing
``reports/density.json`` while step 34 declares ``reports/phase3/density.json``
is *path drift*, and path drift is dimensions 3 and 4's question ("is the
declared output genuinely produced", "does the gate measure what it claims").
Dimension 7 asks whether the LIST mentions the artefact at all. Without (b)
this module would re-file every legacy-fallback candidate path baked into a
checker's search list as a d7 defect and drown the real findings — the
checkers carry many such candidates on purpose. The cost is recorded in
:data:`RESOLUTION_LIMITS`.
"""
from __future__ import annotations

import ast
import fnmatch
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from matrix_63x8 import flowref as F

# ──────────────────────────────────────────────────────────────────────
# Vocabulary
# ──────────────────────────────────────────────────────────────────────
#: CLI flags whose value is an OUTPUT path in this flow's gate commands.
#:
#: Measured, not assumed: these are the only flags among the 30 distinct flags
#: appearing in the 137 gate commands whose value the receiving program writes.
#: ``--coverage-json``/``--layer``/``--spec``/``--sdc``/``--netlist``/``--rtl``
#: and friends are INPUTS and are deliberately absent. :func:`flag_value_is_written`
#: re-verifies the write direction against the receiving program's own source,
#: so a flag added to this set that turns out to be an input is caught rather
#: than believed.
OUTPUT_FLAGS: FrozenSet[str] = frozenset(
    {"--json", "--out", "--output", "--report", "--summary"}
)

#: Suffixes that make a string an *artefact* path rather than an identifier,
#: a URL fragment or a format template. Anything outside this set is ignored.
ARTIFACT_SUFFIXES: FrozenSet[str] = frozenset(
    {
        ".json", ".rpt", ".md", ".csv", ".flag", ".log", ".txt", ".sdf",
        ".spef", ".def", ".gds", ".v", ".sv", ".lef", ".lib", ".sp", ".xml",
        ".lyrdb", ".ys", ".sdc", ".vcd", ".yaml", ".yml", ".tcl", ".spi",
        ".cir", ".sof", ".raw", ".bsdl", ".mag", ".ext", ".svg", ".png",
        ".pdf", ".html", ".sdc", ".db", ".v.gz",
    }
)

#: ``open()`` modes that write. ``r`` alone never matches; ``r+`` does.
_WRITE_MODE_RE = re.compile(r"[waxWAX+]")

#: Classification of an undeclared artefact.
LOAD_BEARING = "LOAD_BEARING"
EVIDENCE = "EVIDENCE"
INCIDENTAL = "INCIDENTAL"

W1 = "W1:gate_output_read_elsewhere"
W2 = "W2:produced_consumed_undeclared"
W3 = "W3:gate_required_file_undeclared"
W4 = "W4:no_required_outputs_but_gate_writes"

#: What this module provably CANNOT see. Quoted verbatim into `known_gap`.
RESOLUTION_LIMITS: Tuple[str, ...] = (
    "A write whose path root is a function PARAMETER (`def _find(root): "
    "root / 'density.json'`) resolves to a bare 1-segment tail. Those are "
    "matched by basename only, so the producer is identified but its "
    "DIRECTORY is not: reports/density.json and reports/phase3/density.json "
    "are indistinguishable to this module.",
    "The one-shot runners carry no machine-readable per-step segmentation, "
    "so a runner write can never be attributed to the step whose RUNNER "
    "SEGMENT emitted it — only to the step that declares/consumes it (W2's "
    "cascade). Artefacts whose cascade is ambiguous are enforced against no "
    "step at all; see unattributable_findings().",
    "A path assembled at runtime from data (a block name read out of "
    "analog_block_list.json, a corner name out of pvt_matrix.json) is "
    "reduced to its f-string skeleton with `*` per interpolation; the "
    "concrete value set is not enumerable statically.",
    "The basename relaxation (see module docstring) hides location drift: an "
    "artefact declared at the WRONG PATH still counts as declared here, "
    "because that is dimension 3's and dimension 4's question.",
    "A write performed inside a shelled-out tool script (an OpenROAD/KLayout "
    "TCL heredoc embedded as a Python string) is not a Python write "
    "position and is invisible to this module.",
)


# ──────────────────────────────────────────────────────────────────────
# Findings
# ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Finding:
    """One undeclared artefact attributed to one step."""

    step_id: str
    rule: str
    path: str
    klass: str
    producer: str
    consumers: Tuple[str, ...]
    detail: str = ""

    def __str__(self) -> str:
        cons = ", ".join(self.consumers[:4]) or "-"
        if len(self.consumers) > 4:
            cons += f", +{len(self.consumers) - 4} more"
        return (
            f"[{self.rule}] {self.path!r} "
            f"(written by {self.producer}; read by {cons})"
            + (f" — {self.detail}" if self.detail else "")
        )


# ──────────────────────────────────────────────────────────────────────
# AST helpers
# ──────────────────────────────────────────────────────────────────────
def _const_str(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _fstring_skeleton(node: ast.JoinedStr) -> str:
    """``f"{d}/x_{n}.json"`` -> ``"*/x_*.json"``.

    Interpolations become ``*`` rather than vanishing: an f-string path is a
    real write, and collapsing it to its literal fragments would silently
    change which artefact it names. ``*`` keeps it honest AND keeps it
    fnmatch-comparable.
    """
    out: List[str] = []
    for v in node.values:
        s = _const_str(v)
        out.append(s if s is not None else "*")
    return "".join(out)


def is_artifact_path(text: str) -> bool:
    """True when *text* looks like a project artefact path, not prose.

    Rejects anything with whitespace (which is what keeps docstrings and log
    messages out) and anything whose suffix is not in
    :data:`ARTIFACT_SUFFIXES`.
    """
    t = text.strip()
    if not t or len(t) > 200:
        return False
    if any(c.isspace() for c in t):
        return False
    return Path(t).suffix.lower() in ARTIFACT_SUFFIXES


class _PathResolver:
    """Resolve path EXPRESSIONS in one module to their literal tail segments.

    ``project / "reports" / "density.json"``      -> ``("reports","density.json")``
    ``cts_out / "clock_plan.json"``               -> ``("clock_plan.json",)``
    ``x = rpt / "phase3"`` ; ``x / "em.json"``    -> ``("phase3","em.json")``

    Straight-line assignments are folded in up to a fixpoint (3 sweeps), which
    is what makes the second and third forms above resolvable at all — the
    dominant idiom in the runners is "build the directory into a local, then
    join the filename onto it". No flow analysis, no scoping: a name bound
    more than once keeps its LONGEST resolution, which over-approximates the
    tail. Over-approximating a *write* set is the safe direction here: a
    spurious tail can only make an artefact look produced, and an artefact
    that is produced-but-declared is not a finding.
    """

    __slots__ = ("env",)

    def __init__(self, tree: ast.AST) -> None:
        self.env: Dict[str, Tuple[str, ...]] = {}
        for _ in range(3):
            changed = False
            for n in ast.walk(tree):
                if (
                    isinstance(n, ast.Assign)
                    and len(n.targets) == 1
                    and isinstance(n.targets[0], ast.Name)
                ):
                    tail = self.tail(n.value)
                    if not tail:
                        continue
                    name = n.targets[0].id
                    prev = self.env.get(name)
                    if prev is None or len(tail) > len(prev):
                        self.env[name] = tail
                        changed = True
            if not changed:
                break

    def tail(self, node: ast.AST, depth: int = 0) -> Tuple[str, ...]:
        if depth > 8:
            return ()
        segs: List[str] = []
        cur = node
        while True:
            if isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Div):
                right = _const_str(cur.right)
                if right is None and isinstance(cur.right, ast.JoinedStr):
                    right = _fstring_skeleton(cur.right)
                if right is None:
                    break
                segs = [p for p in right.split("/") if p] + segs
                cur = cur.left
                continue
            if (
                isinstance(cur, ast.Call)
                and isinstance(cur.func, ast.Name)
                and cur.func.id == "Path"
                and cur.args
            ):
                segs = list(self.tail(cur.args[0], depth + 1)) + segs
                break
            if isinstance(cur, ast.Name):
                segs = list(self.env.get(cur.id, ())) + segs
                break
            lit = _const_str(cur)
            if lit is None and isinstance(cur, ast.JoinedStr):
                lit = _fstring_skeleton(cur)
            if lit is not None:
                segs = [p for p in lit.strip().lstrip("./").split("/") if p] + segs
            break
        return tuple(segs)


def _collect_writes(tree: ast.AST) -> Set[Tuple[str, ...]]:
    """Tail segments of every path this module WRITES.

    Write positions recognised, all structurally (never by name matching):
      * ``open(p, "w"|"a"|"wb"|...)`` and ``p.open("w")``
      * ``p.write_text(...)`` / ``p.write_bytes(...)``
      * ``shutil.copy/copy2/copyfile/move(src, DEST)`` — the DEST argument
      * ``json.dump(obj, fh)`` is NOT a path write: ``fh`` is a handle, and
        the handle's path was already captured at its ``open()``.
    """
    resolver = _PathResolver(tree)
    out: Set[Tuple[str, ...]] = set()

    def add(node: ast.AST) -> None:
        tail = resolver.tail(node)
        if tail and Path(tail[-1]).suffix.lower() in ARTIFACT_SUFFIXES:
            out.add(tail)

    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        fn = n.func
        if isinstance(fn, ast.Name) and fn.id == "open" and n.args:
            mode = _const_str(n.args[1]) if len(n.args) > 1 else None
            for kw in n.keywords:
                if kw.arg == "mode":
                    mode = _const_str(kw.value)
            if mode and _WRITE_MODE_RE.search(mode):
                add(n.args[0])
            continue
        if isinstance(fn, ast.Attribute):
            if fn.attr in ("write_text", "write_bytes"):
                add(fn.value)
            elif fn.attr == "open" and n.args:
                mode = _const_str(n.args[0])
                if mode and _WRITE_MODE_RE.search(mode):
                    add(fn.value)
            elif fn.attr in ("copy", "copy2", "copyfile", "move") and len(n.args) > 1:
                add(n.args[1])
    return out


def _collect_path_literals(tree: ast.AST) -> Set[str]:
    """Project-relative artefact paths named as LITERALS in this module.

    Module / class / function docstrings are excluded by identity, so prose
    that happens to mention a path cannot be mistaken for a reference to it.
    Only literals containing ``/`` are kept: a bare ``"summary.json"`` carries
    no location and collides across the tree.
    """
    docstrings: Set[int] = set()
    for n in ast.walk(tree):
        if isinstance(
            n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            body = getattr(n, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))

    out: Set[str] = set()
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and id(n) not in docstrings
        ):
            text = n.value.strip().lstrip("./")
            if "/" in text and is_artifact_path(text):
                out.add(text)
    return out


# ──────────────────────────────────────────────────────────────────────
# Whole-tree indices (parsed once per process)
# ──────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _trees() -> Dict[str, ast.AST]:
    out: Dict[str, ast.AST] = {}
    for path in sorted(F.PROGRAMS_DIR.glob("*.py")):
        try:
            out[path.stem] = ast.parse(
                path.read_text(encoding="utf-8", errors="replace")
            )
        except SyntaxError:  # pragma: no cover - a program that will not parse
            continue          # is dimension 2's problem, not this module's
    return out


@lru_cache(maxsize=1)
def write_index() -> Dict[Tuple[str, ...], FrozenSet[str]]:
    """``{tail_segments: {program basenames that write it}}`` for the whole tree."""
    acc: Dict[Tuple[str, ...], Set[str]] = {}
    for name, tree in _trees().items():
        for tail in _collect_writes(tree):
            acc.setdefault(tail, set()).add(name)
    return {k: frozenset(v) for k, v in acc.items()}


@lru_cache(maxsize=1)
def literal_index() -> Dict[str, FrozenSet[str]]:
    """``{path literal: {program basenames whose source names it}}``."""
    acc: Dict[str, Set[str]] = {}
    for name, tree in _trees().items():
        for lit in _collect_path_literals(tree):
            acc.setdefault(lit, set()).add(name)
    return {k: frozenset(v) for k, v in acc.items()}


@lru_cache(maxsize=None)
def program_literals(basename: str) -> FrozenSet[str]:
    tree = _trees().get(basename)
    return frozenset(_collect_path_literals(tree)) if tree is not None else frozenset()


@lru_cache(maxsize=None)
def writers_of(path: str) -> FrozenSet[str]:
    """Programs that write *path*, matched on resolved literal TAIL segments.

    A write resolved to ``("reports","density.json")`` matches the read
    ``"reports/density.json"``. A 1-segment tail (the path root was a function
    parameter this module cannot follow) matches on basename alone — which
    identifies the PRODUCER correctly but not the DIRECTORY, and is recorded
    as such in :data:`RESOLUTION_LIMITS`.
    """
    segs = tuple(p for p in path.split("/") if p)
    hits: Set[str] = set()
    for tail, progs in write_index().items():
        if not tail or len(tail) > len(segs):
            continue
        if segs[len(segs) - len(tail):] == tail:
            hits |= set(progs)
    return frozenset(hits)


# ──────────────────────────────────────────────────────────────────────
# Is an OUTPUT_FLAGS flag really an output? — checked, not assumed
# ──────────────────────────────────────────────────────────────────────
def _arg_dest(flag: str) -> str:
    return flag.lstrip("-").replace("-", "_")


def _mentions_args_attr(node: ast.AST, dest: str, aliases: Set[str]) -> bool:
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Attribute)
            and sub.attr == dest
            and isinstance(sub.value, ast.Name)
            and sub.value.id in ("args", "ns", "opts")
        ):
            return True
        if isinstance(sub, ast.Name) and sub.id in aliases:
            return True
    return False


@lru_cache(maxsize=None)
def _local_modules(program: str) -> Tuple[str, ...]:
    """Sibling ``programs/*`` modules *program* imports.

    Needed because several gate entries are THIN WRAPPERS that forward argv
    verbatim to another program's ``main`` (``em_report_check`` ->
    ``signoff_report_check``, and the docstring of that file says so in as
    many words). A flag classifier that stopped at the wrapper would conclude
    "this program never writes its --json" and be wrong for a whole family of
    steps — the same shape of mistake as the grep in PR #460.
    """
    tree = _trees().get(program)
    if tree is None:
        return ()
    known = _trees()
    acc: List[str] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                root = a.name.split(".")[0]
                if root in known and root != program and root not in acc:
                    acc.append(root)
        elif isinstance(n, ast.ImportFrom) and n.module:
            root = n.module.split(".")[0]
            if root in known and root != program and root not in acc:
                acc.append(root)
    return tuple(acc)


@lru_cache(maxsize=None)
def flag_value_is_written(program: str, flag: str, _depth: int = 0) -> Optional[bool]:
    """Does *program* WRITE the path it receives via *flag*?

    ``True``  — a write position's path expression traces to ``args.<dest>``
                (directly, or through a straight-line local alias, or through
                a sibling module the program forwards argv to).
    ``False`` — the program owns the flag and provably does not write it.
                ``provenance_check --output`` is the live example: its
                ``--output`` names the artefact whose PROVENANCE is checked —
                an INPUT wearing an output-shaped flag name.
    ``None``  — cannot be decided (not in the tree, does not parse, or the
                flag is neither owned nor traceably forwarded).

    This exists so that :data:`OUTPUT_FLAGS` is a per-``(program, flag)``
    CHECKED classification rather than a believed global one. Believing it
    globally would invent an emitted artefact for every step using a flag that
    is actually an input — measuring something adjacent and reporting it as
    the answer.
    """
    tree = _trees().get(program)
    if tree is None:
        return None
    dest = _arg_dest(flag)

    owns = any(
        isinstance(sub, ast.Attribute)
        and sub.attr == dest
        and isinstance(sub.value, ast.Name)
        and sub.value.id in ("args", "ns", "opts")
        for sub in ast.walk(tree)
    )
    if not owns:
        # A wrapper that forwards argv: resolve through what it delegates to.
        if _depth >= 2:
            return None
        verdicts = [
            flag_value_is_written(m, flag, _depth + 1) for m in _local_modules(program)
        ]
        if any(v is True for v in verdicts):
            return True
        if verdicts and all(v is False for v in verdicts):
            return False
        return None
    aliases: Set[str] = set()
    for _ in range(3):
        grew = False
        for n in ast.walk(tree):
            if (
                isinstance(n, ast.Assign)
                and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id not in aliases
                and _mentions_args_attr(n.value, dest, aliases)
            ):
                aliases.add(n.targets[0].id)
                grew = True
        if not grew:
            break

    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        fn = n.func
        target: Optional[ast.AST] = None
        if isinstance(fn, ast.Name) and fn.id == "open" and n.args:
            mode = _const_str(n.args[1]) if len(n.args) > 1 else None
            for kw in n.keywords:
                if kw.arg == "mode":
                    mode = _const_str(kw.value)
            if mode and _WRITE_MODE_RE.search(mode):
                target = n.args[0]
        elif isinstance(fn, ast.Attribute):
            if fn.attr in ("write_text", "write_bytes"):
                target = fn.value
            elif fn.attr == "open" and n.args:
                mode = _const_str(n.args[0])
                if mode and _WRITE_MODE_RE.search(mode):
                    target = fn.value
            elif fn.attr in ("copy", "copy2", "copyfile", "move") and len(n.args) > 1:
                target = n.args[1]
        if target is not None and _mentions_args_attr(target, dest, aliases):
            return True
    return False


@lru_cache(maxsize=1)
def output_flag_pairs() -> Tuple[Tuple[str, str, str], ...]:
    """``((step, program, flag), ...)`` for every OUTPUT_FLAGS use in the yaml."""
    out: List[Tuple[str, str, str]] = []
    for sid in F.step_ids():
        key = F.normalize_id(sid)
        for clause in F.gate_clauses(sid):
            if clause.command is None or not clause.program:
                continue
            toks = clause.command.split()
            for tok in toks[1:]:
                flag = tok.split("=", 1)[0] if tok.startswith("--") and "=" in tok else tok
                if flag in OUTPUT_FLAGS:
                    triple = (key, clause.program, flag)
                    if triple not in out:
                        out.append(triple)
    return tuple(out)


# ──────────────────────────────────────────────────────────────────────
# Gate-command argument split
# ──────────────────────────────────────────────────────────────────────
def split_command(command: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """``(outputs, inputs)`` of one gate command.

    A value is an OUTPUT when its flag is in :data:`OUTPUT_FLAGS`; every other
    flag value and every positional is an INPUT. Both ``--json X`` and
    ``--json=X`` spellings occur in the yaml and both are handled. The bare
    project-dir positional ``.`` is dropped.
    """
    toks = command.split()
    outs: List[str] = []
    ins: List[str] = []
    i = 1  # toks[0] is the program basename
    while i < len(toks):
        tok = toks[i]
        if tok.startswith("--") and "=" in tok:
            flag, value = tok.split("=", 1)
            (outs if flag in OUTPUT_FLAGS else ins).append(value)
            i += 1
            continue
        if tok.startswith("-"):
            if i + 1 < len(toks) and not toks[i + 1].startswith("-"):
                (outs if tok in OUTPUT_FLAGS else ins).append(toks[i + 1])
                i += 2
                continue
            i += 1
            continue
        ins.append(tok)
        i += 1
    return (
        tuple(o.lstrip("./") for o in outs if o not in (".", "")),
        tuple(v.lstrip("./") for v in ins if v not in (".", "")),
    )


@lru_cache(maxsize=None)
def gate_output_targets(step_id) -> Tuple[Tuple[str, str], ...]:
    """``((path, writing_program), ...)`` the gate designates as OUTPUTS.

    A flag in :data:`OUTPUT_FLAGS` only counts once
    :func:`flag_value_is_written` has PROVEN the receiving program writes it.
    ``False`` and inconclusive both drop the target, so this set never invents
    an emitted artefact. Two live examples of why that matters:

      * ``provenance_check --output <artefact>`` — the artefact whose
        provenance is being checked. An INPUT.
      * ``fpga_verification_audit --report <md>`` — ``add_argument("--report",
        required=True, help="markdown report to audit")``
        (``fpga_verification_audit.py:326``). Also an INPUT.

    Both are spelled exactly like an output flag. Trusting the spelling would
    have charged step 6 with emitting a file it only reads.
    """
    out: List[Tuple[str, str]] = []
    for clause in F.gate_clauses(step_id):
        if clause.command is None or not clause.program:
            continue
        toks = clause.command.split()
        i = 1
        while i < len(toks):
            tok = toks[i]
            if tok.startswith("--") and "=" in tok:
                flag, value = tok.split("=", 1)
                step = 1
            elif tok.startswith("-") and i + 1 < len(toks) and not toks[i + 1].startswith("-"):
                flag, value = tok, toks[i + 1]
                step = 2
            else:
                i += 1
                continue
            i += step
            if flag not in OUTPUT_FLAGS:
                continue
            if flag_value_is_written(clause.program, flag) is not True:
                continue
            path = value.lstrip("./")
            if path in (".", "") or (path, clause.program) in out:
                continue
            out.append((path, clause.program))
    return tuple(out)


@lru_cache(maxsize=None)
def gate_input_paths(step_id) -> FrozenSet[str]:
    """Every path S's gate CONSUMES: command inputs, files_exist, conditions."""
    acc: Set[str] = set()
    cond = F.step_condition(step_id)
    if cond:
        for f in cond.get("files_exist") or []:
            acc.add(str(f).lstrip("./"))
    for clause in F.gate_clauses(step_id):
        if clause.command is not None:
            _, ins = split_command(clause.command)
            acc.update(ins)
        acc.update(f.lstrip("./") for f in clause.files)
        acc.update(f.lstrip("./") for f in clause.condition_files)
        if clause.json_file:
            acc.add(clause.json_file.lstrip("./"))
    return frozenset(acc)


@lru_cache(maxsize=1)
def flow_consumers() -> Dict[str, FrozenSet[str]]:
    """``{path: {step ids whose gate consumes it}}`` across the whole flow."""
    acc: Dict[str, Set[str]] = {}
    for sid in F.step_ids():
        key = F.normalize_id(sid)
        for p in gate_input_paths(sid):
            acc.setdefault(p, set()).add(key)
    return {k: frozenset(v) for k, v in acc.items()}


# ──────────────────────────────────────────────────────────────────────
# "Is it declared?"
# ──────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def declared_entries() -> Dict[str, FrozenSet[str]]:
    """``{normalised step id: {required_outputs alternatives}}`` — any-of split."""
    out: Dict[str, FrozenSet[str]] = {}
    for sid in F.step_ids():
        acc: Set[str] = set()
        for entry in F.required_outputs(sid):
            for alt in F.split_any_of(entry):
                acc.add(alt.strip().lstrip("./"))
        out[F.normalize_id(sid)] = frozenset(acc)
    return out


@lru_cache(maxsize=1)
def _all_declared() -> FrozenSet[str]:
    acc: Set[str] = set()
    for v in declared_entries().values():
        acc |= set(v)
    return frozenset(acc)


@lru_cache(maxsize=1)
def _all_declared_basenames() -> FrozenSet[str]:
    return frozenset(os.path.basename(d) for d in _all_declared() if d)


def declaring_entry(path: str) -> Optional[str]:
    """The ``required_outputs`` entry that captures *path*, or ``None``.

    Three ways to be captured, weakest last:
      1. exact string equality;
      2. ``fnmatch`` against a declared GLOB (``phase1/generated_docs/L13_*.json``)
         or the reverse, when the probed path is itself a glob;
      3. same BASENAME as some declared entry — the deliberate relaxation
         documented in the module docstring, which keeps location drift (a d3 /
         d4 question) out of this dimension's findings.
    """
    declared = _all_declared()
    if path in declared:
        return path
    for d in declared:
        if fnmatch.fnmatch(path, d) or fnmatch.fnmatch(d, path):
            return d
    base = os.path.basename(path)
    if base and base in _all_declared_basenames():
        return f"<same basename declared: {base}>"
    return None


# ──────────────────────────────────────────────────────────────────────
# The rules
# ──────────────────────────────────────────────────────────────────────
def _consumers_of_output(path: str, writer: str) -> Tuple[str, ...]:
    """Everything that reads *path* other than the program that wrote it.

    The exclusion of *writer* is the audit's own "self-verifying" standard:
    a report a gate program writes AND checks inside one invocation cannot go
    missing unnoticed, so it is EVIDENCE, not LOAD_BEARING.
    """
    acc: Set[str] = set()
    for prog in literal_index().get(path, frozenset()):
        if prog != writer:
            acc.add(f"program:{prog}")
    for sid in flow_consumers().get(path, frozenset()):
        acc.add(f"gate:step{sid}")
    return tuple(sorted(acc))


# ---- W2 support: the produced/consumed/undeclared population -------------
@lru_cache(maxsize=1)
def _step_condition_basenames() -> FrozenSet[str]:
    """Basenames used as a step-level applicability ``condition``.

    Such a file is an UPSTREAM input by construction, so the step that
    conditions on it is never the step that emitted it. Excluded from W2 so
    one undeclared artefact is not charged to thirteen steps at once.
    """
    acc: Set[str] = set()
    for sid in F.step_ids():
        cond = F.step_condition(sid)
        if not cond:
            continue
        for f in cond.get("files_exist") or []:
            acc.add(os.path.basename(str(f)))
    return frozenset(acc)


@lru_cache(maxsize=1)
def _same_dir_declarers() -> Dict[str, FrozenSet[str]]:
    """``{directory: {steps declaring a required_output in it}}``."""
    acc: Dict[str, Set[str]] = {}
    for key, alts in declared_entries().items():
        for alt in alts:
            acc.setdefault(os.path.dirname(alt), set()).add(key)
    return {k: frozenset(v) for k, v in acc.items()}


@lru_cache(maxsize=1)
def _gate_consumers() -> Dict[str, FrozenSet[str]]:
    """``{path: {steps whose gate reads it}}`` — program source AND yaml."""
    acc: Dict[str, Set[str]] = {}
    for sid in F.step_ids():
        key = F.normalize_id(sid)
        for prog in F.gate_programs(sid):
            for lit in program_literals(prog):
                acc.setdefault(lit, set()).add(key)
        for p in gate_input_paths(sid):
            acc.setdefault(p, set()).add(key)
    return {k: frozenset(v) for k, v in acc.items()}


@lru_cache(maxsize=1)
def _w2_population() -> Tuple[Tuple[str, Optional[str], FrozenSet[str], FrozenSet[str]], ...]:
    """``((path, owner_or_None, producers, consuming_steps), ...)`` for W2.

    ``owner`` follows the published cascade in the module docstring. ``None``
    means UNATTRIBUTABLE: real finding, no step it can honestly be charged to.
    """
    same_dir = _same_dir_declarers()
    consumers = _gate_consumers()
    skip_basenames = _step_condition_basenames()

    out: List[Tuple[str, Optional[str], FrozenSet[str], FrozenSet[str]]] = []
    for path in sorted(consumers):
        if "*" in path or "?" in path:
            continue
        if not is_artifact_path(path):
            continue
        if os.path.basename(path) in skip_basenames:
            continue
        if declaring_entry(path):
            continue
        producers = writers_of(path)
        if not producers:
            continue  # externally supplied by design — not an emitted artefact
        cons = consumers[path]
        decl = same_dir.get(os.path.dirname(path), frozenset())
        both = decl & cons
        if len(both) == 1:
            owner: Optional[str] = next(iter(both))
        elif len(cons) == 1:
            owner = next(iter(cons))
        elif len(decl) == 1:
            owner = next(iter(decl))
        else:
            owner = None
        out.append((path, owner, producers, cons))
    return tuple(out)


def unattributable_findings() -> Tuple[Finding, ...]:
    """W2 artefacts real enough to name but not chargeable to one step.

    Surfaced deliberately. Silently dropping them would be the silent-absence
    failure; charging them to an arbitrary candidate would be a guess reported
    as a finding. They are enforced against no cell and are named in the
    dimension's ``known_gap``.
    """
    out: List[Finding] = []
    for path, owner, producers, cons in _w2_population():
        if owner is not None:
            continue
        out.append(
            Finding(
                step_id="<unattributable>",
                rule=W2,
                path=path,
                klass=LOAD_BEARING,
                producer=",".join(sorted(producers)[:3]),
                consumers=tuple(f"gate:step{c}" for c in sorted(cons)),
                detail=(
                    "produced and consumed but declared by no step; the "
                    "attribution cascade found no unique owner"
                ),
            )
        )
    return tuple(out)


@lru_cache(maxsize=None)
def findings_for(step_id) -> Tuple[Finding, ...]:
    """Every LOAD_BEARING undeclared artefact attributed to *step_id*."""
    key = F.normalize_id(step_id)
    out: List[Finding] = []

    # ---- W4: no list at all, yet the gate designates outputs -----------
    targets = gate_output_targets(step_id)
    seen_w4: Set[str] = set()
    if targets and not F.declares_required_outputs(step_id):
        for path, writer in targets:
            seen_w4.add(path)
            out.append(
                Finding(
                    step_id=key,
                    rule=W4,
                    path=path,
                    klass=LOAD_BEARING,
                    producer=writer,
                    consumers=_consumers_of_output(path, writer),
                    detail=(
                        "the step declares no required_outputs key at all, so "
                        "no list can capture this gate-designated output"
                    ),
                )
            )

    # ---- W1: gate-designated output somebody else reads ----------------
    for path, writer in targets:
        if path in seen_w4 or declaring_entry(path):
            continue
        consumers = _consumers_of_output(path, writer)
        if not consumers:
            continue  # self-verifying -> EVIDENCE, reported not enforced
        out.append(
            Finding(
                step_id=key,
                rule=W1,
                path=path,
                klass=LOAD_BEARING,
                producer=writer,
                consumers=consumers,
                detail=(
                    "gate-designated output that something other than its own "
                    "writer reads"
                ),
            )
        )

    # ---- W2: produced + consumed + declared by nobody ------------------
    for path, owner, producers, cons in _w2_population():
        if owner != key:
            continue
        if any(f.path == path for f in out):
            continue
        out.append(
            Finding(
                step_id=key,
                rule=W2,
                path=path,
                klass=LOAD_BEARING,
                producer=",".join(sorted(producers)[:3]),
                consumers=tuple(f"gate:step{c}" for c in sorted(cons)),
                detail=(
                    "produced by the flow and read by a gate, but no step's "
                    "required_outputs names it"
                ),
            )
        )

    # ---- W3: the gate requires a file no step declares -----------------
    for clause in F.gate_clauses(step_id):
        probes: List[str] = [f.lstrip("./") for f in clause.files]
        if clause.json_file:
            probes.append(clause.json_file.lstrip("./"))
        for path in probes:
            if declaring_entry(path) or any(f.path == path for f in out):
                continue
            out.append(
                Finding(
                    step_id=key,
                    rule=W3,
                    path=path,
                    klass=LOAD_BEARING,
                    producer="<none found in programs/>",
                    consumers=(f"gate:step{key}",),
                    detail=(
                        "the step's own gate asserts this file exists; no "
                        "step's required_outputs names it"
                    ),
                )
            )

    return tuple(out)


@lru_cache(maxsize=None)
def evidence_findings(step_id) -> Tuple[Finding, ...]:
    """Undeclared gate outputs whose ONLY reader is their own writer.

    Reported, never enforced. These are the audit's "self-verifying gate
    bookkeeping": the program writes the JSON and checks it in the same
    invocation, so its absence cannot go unnoticed.
    """
    key = F.normalize_id(step_id)
    out: List[Finding] = []
    for path, writer in gate_output_targets(step_id):
        if declaring_entry(path):
            continue
        if _consumers_of_output(path, writer):
            continue
        out.append(
            Finding(
                step_id=key,
                rule="EVIDENCE",
                path=path,
                klass=EVIDENCE,
                producer=writer,
                consumers=(),
                detail="self-verifying gate report — undeclared but not load-bearing",
            )
        )
    return tuple(out)


def na_precondition(step_id) -> Optional[str]:
    """Why *step_id* is NA for dimension 7, or ``None`` when it is answerable.

    A step is NA only when there is nothing at all to compare: it declares no
    ``required_outputs`` AND its gate designates no output. That is one step
    (P0). The NA is checked LIVE by the test, so adding either half
    self-invalidates it.
    """
    if F.declares_required_outputs(step_id):
        return None
    if gate_output_targets(step_id):
        return None
    if F.has_gate(step_id):
        return (
            "declares no required_outputs and its gate designates no output "
            "path, so there is no emitted artefact to compare a list against"
        )
    return "declares neither a gate nor required_outputs"


__all__ = [
    "OUTPUT_FLAGS",
    "ARTIFACT_SUFFIXES",
    "RESOLUTION_LIMITS",
    "LOAD_BEARING",
    "EVIDENCE",
    "INCIDENTAL",
    "W1",
    "W2",
    "W3",
    "W4",
    "Finding",
    "is_artifact_path",
    "split_command",
    "gate_output_targets",
    "gate_input_paths",
    "flow_consumers",
    "declared_entries",
    "declaring_entry",
    "program_literals",
    "literal_index",
    "write_index",
    "writers_of",
    "findings_for",
    "evidence_findings",
    "unattributable_findings",
    "flag_value_is_written",
    "output_flag_pairs",
    "na_precondition",
]
