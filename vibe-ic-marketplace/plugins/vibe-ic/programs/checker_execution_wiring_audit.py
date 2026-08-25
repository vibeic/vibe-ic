#!/usr/bin/env python3
"""checker_execution_wiring_audit.py — a checker only its own TEST runs has
zero coverage of real inputs.

THIS GATE BLOCKS (rc=1) on a NEW test-only checker.

WHY THIS GATE EXISTS
--------------------
vibe-ic#381 stated the problem precisely while arguing about a different
one:

    "If the new checker is run against benchmark-data/, main is currently
     red by its own rule. If it is NOT run there, then the check does not
     cover the artefacts the issue was about."

Both halves matter, and the second one is the silent half. A checker can
be authored, reviewed, tested, merged, and cited as the fix for an issue
while NOTHING ever invokes it on a real input. Its own unit test proves
the logic works on a fixture the author wrote. It proves nothing about
production artefacts, because it never sees one.

That is the repo's recurring shape one more time: an empty result is
indistinguishable from a clean one. Here the emptiness is upstream of the
checker — it is never handed anything to judge.

THE POPULATION IS A FILENAME GLOB, AND IT LET ONE THROUGH (#693)
-----------------------------------------------------------------
Until 2026-08-03 the population was `*_check.py` + `*_audit.py` — 533 of the
1091 programs. `gitignore_scratch_guard.py` is a gate, was wired to nothing,
and ends in NEITHER suffix, so this audit reported

    checker_execution_wiring_audit: 533 checker(s)
    [PASS] no NEW test-only checker (31 recorded)

over a population that structurally could not contain the one real instance
in its own class. A confident clean answer from a denominator that excluded
the finding by naming alone is the exact defect this file's docstring is
about, one level up.

WHY THE FIX IS `+ _guard/_lint/_gate` AND NOT `programs/*.py`. Measured on
2026-08-03 in 581a8759, both ways, before choosing — a RECORD of the input to
that decision, not a claim about this checkout:

    population 533 (as shipped)      test_only 31   no_runner  0
    population 560 (+ the 3 suffixes) test_only 33   no_runner  0   -> +2 entries
    population 1091 (every program)   test_only 91   no_runner 20   -> +80 entries

The 80 were `a2b_protocol_synth.py`, `crc_vector_gen.py`, `benchmark_setup.py`
and their kind — GENERATORS and harness helpers, not checkers. A register whose
`_comment` says "checkers that NOTHING but their own unit test ever runs" does
not describe them, and filling it with 80 non-checkers to catch one guard is
the same defect as the glob: a population chosen for convenience rather than
for the question. The suffix set is widened to the CHECKER-SHAPED names and
nothing else; the programs still outside it are disclosed by the verdict line
rather than silently absent.

Those three populations on THIS checkout, recomputed rather than remembered —
`*_check.py` + `*_audit.py` is {figure:as_shipped_population}, the shipped
CHECKER-SHAPED set is {figure:checker_shaped_population}, every program is
{figure:all_programs}, and {figure:programs_outside_population} stay outside
the population and are disclosed by the verdict line. Reading those next to the
pinned table above is the only way to see whether the 2026-08-03 argument still
holds; typing them here instead would put this docstring back in the state that
`derived_corpus_figure_check` exists to end.

WHAT IT MEASURES
----------------
For every `*_check.py` / `*_audit.py` / `*_guard.py` / `*_lint.py` /
`*_gate.py` under `programs/`, which of these can actually INVOKE it:

    CI     a GitHub workflow step
    FLOW   the canonical flow definition (a gate entry)
    PROG   another program (import or subprocess)
    SKILL  a skill / agent / command document an agent follows
    TOOLS  a repo tool script
    TEST   its own unit tests

A checker whose ONLY runner is TEST is the finding.

WHY `SKILL` COUNTS AS A RUNNER. An agent following a skill document does
execute the program, so counting it avoids a false positive. It is the
weakest of the runners — it depends on an agent reaching that step — and
that weakness is deliberately NOT modelled here, because grading the
strength of a reference would need a judgement call, and a gate whose
output needs triage gets ignored.

WHAT IT DELIBERATELY DOES NOT COUNT AS A RUNNER
-----------------------------------------------
`programs/INDEX.md`, the architecture docs and the community backlog
YAMLs all NAME checkers without running any. Counting a catalogue as a
runner would let a checker be "wired" by being listed, which is the exact
paper-only wiring this gate exists to find.

`unwired_by_decision` — WHERE AN ORPHAN GATE'S DISCLOSURE GOES (vibe-ic#693)
---------------------------------------------------------------------------
#693 measured 130 programs referenced from no executable location, 29 of
them gate-shaped. The three registries that look like they should hold that
disclosure all refuse it, because each is a RATCHET OVER A MEASURED
POPULATION and an unwired gate is not in any of those populations:

  * `gate_skip_routing_check._UNROUTED_INVENTORY` counts UNROUTED SKIP PATHS
    per gate. A gate with 0 skip paths is not in `measured`, so an entry for
    it lands in `fixed` -> drift -> rc 1. VERIFIED: adding
    `checkpoint_gate_check: 0` turns a green `98 in 53` ratchet red with
    "checkpoint_gate_check: 0 -> 0; delete the inventory entry".
  * `known` in THIS file's baseline is the TEST-ONLY set. A checker a SKILL
    document names has a runner by this gate's own rule, so recording it here
    lands it in `paid` -> rc 1. VERIFIED the same way.
  * `flow_compliance_check._UNDRIVABLE_BY_STRUCTURAL_UMBRELLA` requires
    membership in `_STRUCTURAL_RTL_GATES`, requires the gate to argparse-REJECT
    the umbrella argv, and anchors EVERY entry by test — registered, still
    rejecting, and carrying a categorised measured reason. The population is
    whatever that register holds (twelve at v1.9.8, and it has grown since);
    stating the size here is a count in prose that stops tracking what it
    counts, so it is not restated. `checkpoint_gate_check` satisfies none of
    the three requirements.

So the disclosure gets a home with its OWN rule, here, where a gate already
runs in CI. An entry says: this checker is deliberately not machine-wired, and
here is why. It is enforced in both directions —

  * the named file must exist (a stale name is rc 1);
  * it must still have NO machine runner. The moment CI / the flow / another
    program / a repo tool invokes it, the "deliberately unwired" record is
    false and this gate says so (rc 1) instead of licensing it forever;
  * it may not also sit in `known` (those are different claims);
  * the reason must be a measurement, not a gesture (>= 120 chars).

Being listed is a DISCLOSURE, not permission.

METHOD NOTE — THE MATCHER MUST NOT ASSUME QUOTING
--------------------------------------------------
The first version of this measurement searched for the quoted stem and
the `.py` filename. The flow definition writes gate names BARE, so that
matcher reported 12 checkers as wired NOWHERE when every one of them was
in fact wired — a false accusation produced entirely by the matcher's own
assumption. Match the stem on WORD BOUNDARIES and nothing else.

chip-AGNOSTIC: operates on this repo's own layout. No design, PDK or
vendor literal appears here.

USAGE
-----
    python3 checker_execution_wiring_audit.py [--repo-root DIR]
                                              [--json OUT] [--write-baseline]

EXIT CODES
----------
    0 = PASS      1 = FAIL (new test-only checker, baseline not shrunk, or a
                            SKILL-only disclosure that claims a reason without
                            stating one — #1270; SILENCE never blocks)
    2 = NOT CHECKED (layout not found, or the residual baseline states no
                     readable measurement: absent, unreadable, truncated)

An explicitly empty ``{"known": []}`` baseline IS a measurement of a clean
tree. The first test-only checker against it is therefore NEW and still exits
1; only the absence of a readable measurement declines attribution.
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
import warnings
from pathlib import Path
from typing import Dict, List, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _derived_corpus_figure import CorpusFigures  # noqa: E402

_BASELINE_NAME = "checker_execution_wiring_baseline.json"
#: Checker-shaped filename suffixes. See "THE POPULATION IS A FILENAME GLOB".
_CHECKER_SUFFIXES = ("*_check.py", "*_audit.py", "*_guard.py", "*_lint.py",
                     "*_gate.py")
#: The SKILL-only disclosure (#693). Not a baseline and not permission: a
#: register of checkers whose only non-TEST runner is an agent choosing to
#: follow a skill document, WITH the reason each one is still there. The COUNT
#: is reported and never blocks — see `skill_only_register`. An ENTRY is a
#: claim, and is held to the bar this file already sets for its other register
#: — see `classify_disclosures` (#1270).
_SKILL_ONLY_NAME = "checker_skill_only_reasons.json"
# Matched as path COMPONENTS, never as substrings: `".git" in path` also
# swallows `.github/`, which would empty the CI haystack and make this gate
# systematically blind to the strongest form of wiring there is — while
# still printing a confident finding for every checker CI already runs.
_SKIP_PARTS = frozenset((".claude", "node_modules", ".git", "worktrees"))


def _docstring_lines(tree: "ast.AST") -> Set[int]:
    """Line numbers occupied by DOCSTRINGS — prose names a checker, never runs one.

    This is not a nicety. Adding a docstring to THIS file that named
    `skill_doc_section_present_check` while explaining why that entry is
    hard to wire made the entry look wired, and silently removed it from a
    register that may only shrink for a real reason. Any program whose
    comments discuss another checker would do the same.

    Walks STATEMENTS only. A docstring is by definition the first statement of
    a module, class or function body, so descending into expressions finds
    nothing and costs 32 of this gate's 45 seconds -- `ast.walk` visits every
    node in ~2900 files to reach a few thousand that can qualify.
    """
    drop: Set[int] = set()
    stack = [tree]
    while stack:
        node = stack.pop()
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                drop.update(range(first.lineno,
                                  (first.end_lineno or first.lineno) + 1))
        for field in ("body", "orelse", "finalbody", "handlers"):
            kids = getattr(node, field, None)
            if isinstance(kids, list):
                stack.extend(k for k in kids
                             if isinstance(k, (ast.stmt, ast.excepthandler)))
    return drop


def _parse(text: str):
    """`ast.parse` or None. One parse serves BOTH prose-stripping and evidence."""
    try:
        with warnings.catch_warnings():
            # Some sources carry invalid escape sequences in docstrings;
            # that is their own (separate) defect, not this gate's news.
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None


def _strip_prose(path: Path, text: str, tree=None) -> str:
    """Remove COMMENTS and DOCSTRINGS. See `_docstring_lines`.

    String LITERALS are kept, because the question this text answers is
    "is the name PRESENT at all, ignoring prose" — presence is necessary for
    a runner and is not sufficient for one. Whether a surviving literal is an
    argv or a sentence is decided on the RAW source by `_py_evidence`, never
    here: this function's output is tokenize's, ONE TOKEN PER LINE, so no
    multi-token shape can ever be matched against it. vibe-ic#1347 lost two
    attempts to that before measuring it.
    """
    if path.suffix == ".py":
        if tree is None:
            # Unparseable source: keep it whole. Over-counting a reference is
            # the safe direction for an ACCUSATION, and this branch is loud
            # in the report rather than silent -- see `_FileFacts.parsed`.
            return text
        drop = _docstring_lines(tree)
        lines = text.splitlines()
        kept = [("" if i + 1 in drop else ln) for i, ln in enumerate(lines)]
        src = "\n".join(kept)
        try:
            toks = tokenize.generate_tokens(io.StringIO(src).readline)
            return "\n".join(t.string for t in toks
                             if t.type != tokenize.COMMENT)
        except (tokenize.TokenError, IndentationError, SyntaxError):
            return src
    if path.suffix in (".yml", ".yaml", ".sh"):
        return "\n".join(ln for ln in text.splitlines()
                         if not ln.lstrip().startswith("#"))
    return text


# ── INVOCATION vs MENTION (vibe-ic#1347) ─────────────────────────────────────
#
# This gate used to answer "is the checker's name one of the tokens in some
# non-test file?" and REPORT that answer as "something runs this checker".
# Those are different questions, and the gap between them is not academic:
# four checkers nothing has ever executed were counted as wired, each held up
# solely by another program's MESSAGE TEXT naming it —
#
#     "; agent_report_presence_check owns that failure mode."
#     "... see analog_block_list_emit_check for whether a list SHOULD ..."
#     "... emits a deprecation warning that trips eda_log_check)"
#     "... rule 7 says run sv_compat_check first to confirm ..."
#
# `_strip_prose` drops comments and docstrings and deliberately KEEPS string
# literals, because `subprocess.run([..., "foo_check.py"])` is a real
# invocation. A sentence in an error message is a string literal too, and that
# is the whole of the defect: the instrument could see "this string occurs in
# this file" and reported "this program is invoked".
#
# So the shape is decided on the RAW source, structurally:
#
#   INVOCATION  an import, an `import_module("<stem>")`, a `<stem>.py` written
#               as a filename (a subprocess argv, a `run "<label>" ...` line in
#               tools/ci/repo_hygiene_gates.sh, a CI `run:` block), a
#               structural gate clause in the flow, or a bare name inside a
#               DISPATCHER -- a module that builds a program filename
#               dynamically (`PROGRAMS_DIR / f"{prog_name}.py"`). A registry a
#               dispatcher executes IS an execution path, and forgetting that
#               is what made a first attempt at this accuse ~195 checkers that
#               `flow_compliance_check.py` genuinely runs.
#
#   MENTION     the name inside a longer natural-language string, a comment, a
#               docstring, a variable name, a log line. Python folds implicit
#               concatenation at parse time, so `"...that trips "
#               "eda_log_check)"` arrives here as ONE constant, and it reads as
#               the sentence it is rather than as the fragment it looks like.
#
#   UNDETERMINED  the name stands alone as a string literal in a module that
#               does NOT build program filenames, or it appears in a source
#               this gate could not parse. That shape is a registry key or a
#               log tag and nothing here can tell which. It is REPORTED AS
#               NOT DETERMINED and counted separately: an accusation this gate
#               cannot support is the same defect it exists to find, and so is
#               a clean bill of health it cannot support.
#
# WHICH HAYSTACKS GET READ FOR SHAPE, AND WHY NOT THE OTHER FOUR
#
# PROG and TOOLS only. The other four keep PRESENCE semantics, each for its
# own reason, and none of them can hide a #1347 instance: all four findings
# were held up by a PROG reference.
#
#   FLOW  the flow definition writes gate names BARE, and this file already
#         has a regression test saying so -- `test_bare_unquoted_flow_
#         reference_counts`. A matcher that demands a filename or an import
#         reports wired gates as wired nowhere; that bug has been fixed here
#         once already. The flow is a DECLARATION the engine executes, so a
#         name in it is a declaration, not a sentence about one.
#   CI    same shape, same reason: a workflow names what it runs.
#   TEST  "only its own test runs it" is this gate's blocking ratchet.
#   SKILL already disclosed as the weakest runner there is.
#
# Tightening TEST or SKILL would move a different population under cover of
# this repair, and tightening FLOW or CI would re-break a fixed bug. #1347 is
# about a MACHINE runner that was never a runner at all.
_SHAPE_KINDS = ("TOOLS", "PROG")
_INVOCATION, _MENTION, _UNDETERMINED = "INVOCATION", "MENTION", "UNDETERMINED"

#: A `<stem>.py` written anywhere the prose-stripper left standing. The suffix
#: is what makes it an argv rather than a sentence.
_PY_FILE_RE = re.compile(r"([A-Za-z0-9_]+)\.py\b")
#: A string literal that is EXACTLY one identifier: a registry-key shape.
_BARE_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
#: A program filename built from a VARIABLE, in a shell or YAML haystack:
#: `python3 "$PROGRAMS/${gate}.py"`. The same dispatcher shape as the Python
#: one below, one language over -- and it holds six real gates in
#: `tools/ci/run_plugin_self_audit.sh` alone. Requiring a literal `<stem>.py`
#: there accuses every one of them.
_SHELL_DISPATCH_RE = re.compile(r"\}\s*\.py\b|\$[A-Za-z_][A-Za-z0-9_]*\.py\b")

#: A shell script named in a shape that EXECUTES it: `bash x.sh`, `sh x.sh`,
#: `./x.sh`, `source x.sh`, `. x.sh`, or a subprocess list element. Naming a
#: script in prose is not running it, and the prose-stripper has already
#: removed comments by the time this is applied.
_SHELL_EXEC_RE = re.compile(
    r"(?:\b(?:bash|sh|zsh|source)\s+|\.\s+|\./|[\"\'])"
    r"(?:[\w./$={}-]*/)?([\w.-]+\.sh)\b")


def _executed_scripts(hay: Dict[str, Dict[str, "_Source"]]) -> Set[str]:
    """Basenames of every `.sh` some file EXECUTES, across every haystack.

    WHY A DISPATCHER MUST EARN ITS ENTRY-PATH STATUS (vibe-ic#693, one level
    up). `_shapes` credits every name inside a `GATES=(...)` shell dispatcher as
    invoked, because requiring a literal `<stem>.py` there would accuse every
    gate the dispatcher runs through a variable. That reasoning is sound for a
    dispatcher something RUNS. It was applied to every dispatcher, including
    `tools/ci/run_plugin_self_audit.sh`, whose six gates it therefore scores as
    wired — while `.github/workflows/` is empty and every reference to that
    script in the tree is a comment or a docstring. The audit that answers
    "did we forget to plug something in" was answering it wrong by six, in the
    direction of complacency.

    ONE HOP, DELIBERATELY. This asks whether ANYTHING executes the script, not
    whether that caller is itself reached. Full transitive reachability needs a
    declared root set, and inventing one would trade a known false-clean for an
    unknown false-accusation. One hop is decidable from the tree alone and
    catches the documented case: `repo_hygiene_gates.sh` is executed by
    `gatekeeper-land.sh` and keeps its credit; `run_plugin_self_audit.sh` is
    executed by nothing and loses it.
    """
    out: Set[str] = set()
    for files in hay.values():
        for src in files.values():
            for m in _SHELL_EXEC_RE.finditer(src.stripped):
                out.add(m.group(1))
    return out


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _py_evidence(tree: "ast.AST"):
    """`(invoked, undetermined)` stems, decided on the RAW parse tree.

    ONE walk. Whether the module is a DISPATCHER is only known once the whole
    tree has been seen, so bare-name literals are held aside and resolved at
    the end rather than by walking twice.
    """
    invoked: Set[str] = set()
    pending: Set[str] = set()
    docstrings: Set[int] = set()
    dispatcher = False
    # An explicit stack rather than `ast.walk`: that helper builds a generator
    # per node through `iter_child_nodes`/`iter_fields`, and over ~2000 trees
    # the machinery costs more than the work. A parent is popped and handled
    # BEFORE its children are pushed, which is what `docstrings` relies on.
    stack = [tree]
    while stack:
        node = stack.pop()
        for field in node._fields:
            value = getattr(node, field, None)
            if isinstance(value, list):
                stack.extend(v for v in value if isinstance(v, ast.AST))
            elif isinstance(value, ast.AST):
                stack.append(value)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str) and id(node) not in docstrings:
                value = node.value
                if ".py" in value:
                    # An argv, wherever it is written: a subprocess list, a
                    # `run "<label>" ... "$PG/<stem>.py"` line, a CI `run:`.
                    for m in _PY_FILE_RE.finditer(value):
                        invoked.add(m.group(1))
                bare = value.strip()
                if _BARE_NAME_RE.match(bare):
                    pending.add(bare)
            continue
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            first = body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                # `ast.walk` is breadth-first, so a docstring's parent is
                # always seen before the docstring itself.
                docstrings.add(id(first.value))
        if isinstance(node, ast.Import):
            for alias in node.names:
                invoked.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and not node.level:
                invoked.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else "")
            if name in ("import_module", "find_spec", "reload"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        invoked.add(arg.value.split(".")[0])
                    else:
                        # `importlib.import_module(mod)` over a table of names
                        # is a dispatcher without the filename:
                        # `pdk_table_coverage_check` runs
                        # `analog_tb_supply_pdk_check` exactly this way.
                        dispatcher = True
        elif isinstance(node, ast.JoinedStr):
            # `PROGRAMS_DIR / f"{prog_name}.py"` — `flow_compliance_check.py`
            # holds ~520 checker names bare and runs each one like this.
            # Requiring a literal `<stem>.py` calls every one of them unwired.
            for v in node.values:
                if (isinstance(v, ast.Constant) and isinstance(v.value, str)
                        and ".py" in v.value):
                    dispatcher = True
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            r = node.right
            if (isinstance(r, ast.Constant) and isinstance(r.value, str)
                    and r.value.strip().endswith(".py")):
                dispatcher = True
    if dispatcher:
        # A registry a dispatcher executes IS an execution path.
        return invoked | pending, set()
    # Exactly one identifier and nothing else, in a module that runs nothing by
    # name: a registry key or a log tag, and this gate cannot tell which.
    return invoked, pending - invoked


class _Source:
    """One haystack file: the RAW text (shape) and the STRIPPED text (presence).

    The parse tree is NOT retained. Holding ~4000 of them alive for the length
    of a run costs 12s of allocator and GC pressure — measured, `compile` went
    3.9s -> 15.7s for the same 3926 calls — and only a hundred or so files are
    ever adjudicated for shape. So each file is parsed once to find its
    docstrings, the tree is dropped, and the few that need a shape are parsed
    again on demand.
    """

    __slots__ = ("path", "raw", "stripped", "parsed", "_tokens")

    def __init__(self, path: Path, raw: str):
        self.path = path
        self.raw = raw
        tree = _parse(raw) if path.suffix == ".py" else None
        self.parsed = tree is not None or path.suffix != ".py"
        self.stripped = _strip_prose(path, raw, tree)
        self._tokens = None

    def tree(self):
        """Re-parse for shape analysis. Called for a hundred files, not four
        thousand — see `_Index`, which reads a file only to settle a mention."""
        return _parse(self.raw) if self.path.suffix == ".py" else None

    def tokens_of(self) -> Set[str]:
        """Every `[A-Za-z0-9_]+` run left after comments and docstrings."""
        if self._tokens is None:
            self._tokens = set(_TOKEN_RE.findall(self.stripped))
        return self._tokens


class _FileFacts:
    """What one file says about EVERY checker name at once.

    Built once per file rather than once per (checker, file). The audit asks
    604 questions of ~2900 files; asking each as its own search costs 86s and
    blows two existing runtime bounds, so the shapes are extracted in a single
    pass and every question is then a set membership.

    The SHAPES are LAZY. `tokens` answers "is the name present at all", and a
    file that names no checker in the population cannot be evidence for or
    against one — so its tree is never walked. That is most of the corpus.
    """

    __slots__ = ("tokens", "_kind", "_src", "_shapes", "_executed")

    def __init__(self, kind: str, src: "_Source", tokens: Set[str],
                 executed: Set[str] = frozenset()):
        self.tokens = tokens
        self._kind = kind
        self._src = src
        self._shapes = None
        self._executed = executed

    def _resolve(self):
        if self._shapes is None:
            self._shapes = _shapes(self._kind, self._src, self._executed)
        return self._shapes

    @property
    def invoked(self) -> Set[str]:
        return self._resolve()[0]

    @property
    def undetermined(self) -> Set[str]:
        return self._resolve()[1]

    @property
    def parsed(self) -> bool:
        return self._src.parsed

    @property
    def unread(self) -> bool:
        """Has this file's tree not been walked yet? Used only to ORDER work."""
        return self._shapes is None

    def __contains__(self, stem: object) -> bool:
        # Kept so `stem in facts` still reads as "is the name present at all".
        return stem in self.tokens


def _rel_parts(f: Path, root: Path):
    """Path components BELOW `root`.

    Third time this file has had the same bug. `_SKIP_PARTS` is meant to skip
    a nested `.claude/worktrees/` copy INSIDE the checkout; matched against
    the ABSOLUTE parts it also matches the checkout's own ancestors, so a
    repo that happens to live under `.../.claude/worktrees/<name>/` has EVERY
    haystack file skipped. Measured: every haystack empty -> `no runner at
    all: 494`, i.e. a confident false accusation against every checker in the
    repo, from a matcher's own assumption. Anchor to the scan root.
    """
    try:
        return set(f.resolve().relative_to(root).parts)
    except (ValueError, OSError):
        return set(f.parts)


def _read(paths, root: Path) -> Dict[str, "_Source"]:
    root = root.resolve()
    out: Dict[str, _Source] = {}
    for f in paths:
        s = str(f)
        if _SKIP_PARTS & _rel_parts(f, root):
            continue
        try:
            out[s] = _Source(f, f.read_text(errors="replace"))
        except OSError:
            continue
    return out


def _haystacks(plugin: Path, repo_root: Path) -> Dict[str, Dict[str, "_Source"]]:
    programs = plugin / "programs"
    pys = list(programs.rglob("*.py"))
    is_test = lambda p: "/tests/" in str(p) or p.name.startswith("test_")
    return {
        "CI": _read(list((repo_root / ".github").rglob("*.yml"))
                    + list((repo_root / ".github").rglob("*.yaml")), repo_root),
        "FLOW": _read(list((plugin / "flow").rglob("*.yml"))
                      + list((plugin / "flow").rglob("*.yaml")), repo_root),
        "TOOLS": _read(list((repo_root / "tools").rglob("*.py"))
                       + list((repo_root / "tools").rglob("*.sh")), repo_root),
        "SKILL": _read(list((plugin / "skills").rglob("*.md"))
                       + list((plugin / "agents").rglob("*.md"))
                       + list((plugin / "commands").rglob("*.md")), repo_root),
        # `programs/` AND `benchmark/`. The benchmark directory is not test
        # scaffolding — it holds `cvdp_gate.py`, `score_iverilog_tb.py` and
        # `gates_atomic.py`, which are the live emit and scoring paths. Leaving
        # it out made this audit accuse `harness_verdict_forgery_gate` of having
        # no runner while `benchmark/score_iverilog_tb.py:153` imports it: the
        # same defect as the dispatcher rule above, one directory over — a
        # confident verdict from a corpus that could not contain the evidence.
        "PROG": _read([p for p in pys if not is_test(p)]
                      + [p for p in (plugin / "benchmark").rglob("*.py")
                         if not is_test(p)], repo_root),
        "TEST": _read([p for p in pys if is_test(p)]
                      + list((plugin / "tests").rglob("*.py")), repo_root),
    }


def _shapes(kind: str, src: "_Source",
            executed: Set[str] = frozenset()):
    """`(invoked, undetermined)` for one file — the INVOCATION/MENTION split."""
    if src.path.suffix == ".py":
        tree = src.tree()
        if tree is None:
            # Nothing was parsed, so nothing here is a shape. Every name
            # present is NOT DETERMINED rather than silently either verdict.
            return set(), set(src.tokens_of())
        return _py_evidence(tree)
    if _SHELL_DISPATCH_RE.search(src.stripped) and src.path.name in executed:
        # A dispatcher executes the names it holds: `GATES=(...)` then
        # `python3 "$PROGRAMS/${gate}.py"`. Over-counting inside one such file
        # is the safe direction for an ACCUSATION; the alternative, measured,
        # is six false accusations from `tools/ci/run_plugin_self_audit.sh`
        # alone — the same trap as `flow_compliance_check.py`, one language
        # over.
        return set(src.tokens_of()), set()
    # A `<stem>.py` on a line the comment-stripper left is an argv. The flow
    # ALSO writes gate names bare, and those are read from the YAML STRUCTURE
    # (never its text — vibe-ic#1012 is why: a substring test counted a
    # program named in a COMMENT as wired).
    invoked = {m.group(1) for m in _PY_FILE_RE.finditer(src.stripped)}
    if kind == "FLOW":
        invoked |= {n[:-3] for n in flow_declared_gate_programs(src.path)
                    if n.endswith(".py")}
    return invoked, set()


def _tokenise(hay: Dict[str, Dict[str, "_Source"]]) -> Dict[str, Dict[str, "_FileFacts"]]:
    executed = _executed_scripts(hay)
    return {k: {p: _FileFacts(k, s, s.tokens_of(), executed) for p, s in v.items()}
            for k, v in hay.items()}


class _Index:
    """Where each checker name is MENTIONED, and the shape of it — on demand.

    Two costs are being traded here and both were measured.

    Extracting shapes for every file up front walks ~2000 parse trees and puts
    the gate at 31s against an inner ceiling of 30s (vibe-ic#1241) — a bound
    derived from the harness, so the repair is to be faster and not to widen
    it. Re-scanning every haystack per checker is worse: 604 questions over
    ~2900 files is 86s.

    So the MENTIONS are indexed eagerly (one cheap set intersection per file)
    and the SHAPES are read only when a mention has to be adjudicated. Most
    checkers are settled by the first file that answers, and a file's tree is
    walked at most once, so the dispatcher holding ~520 names is read once and
    then settles all of them. Files already read are consulted FIRST, which is
    what makes that happen.
    """

    __slots__ = ("hay", "mentions")

    def __init__(self, hay: Dict[str, Dict[str, "_FileFacts"]], stems):
        pop = set(stems)
        self.hay = hay
        self.mentions: Dict[str, Dict[str, List[str]]] = {}
        for kind, files in hay.items():
            where: Dict[str, List[str]] = {}
            for path, facts in files.items():
                for stem in facts.tokens & pop:
                    where.setdefault(stem, []).append(path)
            self.mentions[kind] = where

    def level(self, kind: str, stem: str, self_path: str):
        """The strongest shape `kind` carries for `stem`, ignoring its own file."""
        paths = [p for p in self.mentions[kind].get(stem, ()) if p != self_path]
        if not paths:
            return None
        if kind not in _SHAPE_KINDS:
            # PRESENCE semantics — see _SHAPE_KINDS.
            return _INVOCATION
        files = self.hay[kind]
        # Already-read trees first: whichever file settled the last checker is
        # usually a dispatcher and settles this one too, without a new walk.
        paths.sort(key=lambda p: files[p].unread)
        weak = False
        for path in paths:
            facts = files[path]
            if stem in facts.invoked:
                return _INVOCATION
            if stem in facts.undetermined:
                weak = True
        return _UNDETERMINED if weak else _MENTION


def evidence(stem: str, hay: Dict[str, Dict[str, "_FileFacts"]],
             self_path: str, idx: "_Index" = None) -> Dict[str, str]:
    """The STRONGEST shape each category carries for `stem`.

    `INVOCATION` > `UNDETERMINED` > `MENTION`; a category with nothing is
    absent from the result. See `_SHAPE_KINDS` for which haystacks are read
    for shape at all.
    """
    if idx is None:
        idx = _Index(hay, {stem})
    out: Dict[str, str] = {}
    for kind in hay:
        lvl = idx.level(kind, stem, self_path)
        if lvl is not None:
            out[kind] = lvl
    return out


def runners(stem: str, hay: Dict[str, Dict[str, "_FileFacts"]],
            self_path: str) -> Set[str]:
    """Which categories INVOKE `stem` — not which ones name it (vibe-ic#1347).

    A mention is not a runner and neither is a shape this gate could not read;
    both are visible through `evidence`, and the second is reported as NOT
    DETERMINED rather than folded into either verdict.
    """
    return {k for k, v in evidence(stem, hay, self_path).items()
            if v == _INVOCATION}


_FLOW_GATE_CACHE: Dict[tuple, Set[str]] = {}


def flow_declared_gate_programs(flow_yaml: Path) -> Set[str]:
    """Programs the FLOW ITSELF declares as gate clauses (vibe-ic#1130).

    THE FILENAME GLOB IS STILL A NAME LIST, and #693 only made it a longer one.
    That fix was right about its instance — `gitignore_scratch_guard.py` was a
    gate outside `*_check/_audit` — and left the STRUCTURE untouched: a checker
    whose name ends in none of the five suffixes is invisible to this audit, and
    renaming one is enough to remove it from the population silently.

    Widening to `programs/*.py` is not the answer either, and this file already
    measured why: it adds 80 entries that are generators, not checkers
    (`crc_vector_gen.py`, `a2b_protocol_synth.py`, …). Deciding by SHAPE has the
    same problem — measured for #1130, 58 programs are verdict-shaped but
    outside the glob, and most are emitters that exit non-zero on error.

    The set that is neither a guess nor a name list is the one the FLOW states:
    a program named in a `program_exit_zero` / `advisory_program_exit_zero` /
    `optional_program_exit_zero` clause IS a gate, whatever it is called. Parsed
    from the YAML STRUCTURE, never its text — vibe-ic#1012 is why: a substring
    test counted a program named in a COMMENT as wired.

    MEASURED on a38902d1: the flow declares 127 gate programs and SEVEN of them
    fall outside the filename glob — four of those BLOCKING:

        bsdl_emit                          BLOCKING   step 11
        fmeda_fault_injection_coverage     BLOCKING   step FS1
        phase1_expert_parse_track          BLOCKING   step D1
        verilator_coverage_measure         BLOCKING   step 4
        coverage_closure                   advisory   step 4
        mixed_signal_top_lvs_run           advisory   step M1
        route_congestion_trade_disclosure  advisory   step 21

    An audit asking "does anything but its own test run this checker?" was not
    asking it of seven programs the flow runs as gates.
    """
    # Parsed by `checker_population` AND by the FLOW haystack's shape analysis.
    # Keyed on identity AND mtime/size, so a test that rewrites a flow in place
    # gets the new answer rather than the cached one.
    try:
        st = flow_yaml.stat()
        key = (str(flow_yaml), st.st_mtime_ns, st.st_size)
    except OSError:
        return set()
    if key in _FLOW_GATE_CACHE:
        return _FLOW_GATE_CACHE[key]
    try:
        import yaml  # noqa: PLC0415
        doc = yaml.safe_load(flow_yaml.read_text(errors="replace"))
    except Exception:                                          # noqa: BLE001
        _FLOW_GATE_CACHE[key] = set()
        return set()
    found: Set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key in ("program_exit_zero", "advisory_program_exit_zero") \
                        and isinstance(val, str) and val.split():
                    found.add(val.split()[0] + ".py")
                elif key == "optional_program_exit_zero" and isinstance(val, dict):
                    cmd = str(val.get("command") or "")
                    if cmd.split():
                        found.add(cmd.split()[0] + ".py")
                else:
                    walk(val)
        elif isinstance(node, list):
            for val in node:
                walk(val)

    walk(doc)
    _FLOW_GATE_CACHE[key] = found
    return found


def checker_population(programs: Path, flow_yaml: Optional[Path] = None) -> List[str]:
    """Every checker-shaped program name, deduplicated and sorted.

    The filename glob UNION the programs the flow declares as gates — see
    `flow_declared_gate_programs`. A gate is in this population because the flow
    runs it, not because somebody named it `*_check.py`.
    """
    names = {p.name for suf in _CHECKER_SUFFIXES for p in programs.glob(suf)}
    flow = flow_yaml if flow_yaml is not None else (
        programs.parent / "flow" / "phase1_phase2_phase3.yaml")
    if flow.is_file():
        # only programs that EXIST here: a clause naming a program this
        # checkout does not ship is a different defect, and `gate_is_wired`
        # owns it. Silently inventing a population entry would be this audit
        # reporting on a file it never opened.
        names |= {n for n in flow_declared_gate_programs(flow)
                  if (programs / n).is_file()}
    return sorted(names)


def _named(programs: Path, *suffixes: str) -> int:
    return len({p.name for suf in suffixes for p in programs.glob(suf)})


#: The populations this file's docstring argues from, bound to the code that
#: produces them so the prose cannot drift away from the predicate. LAZY --
#: nothing here runs on the audit path. `all_programs` deliberately mirrors
#: `audit()`'s own expression (`glob("*.py")`, not deduplicated by name) so the
#: docstring and the verdict line cannot disagree about the denominator.
CORPUS_FIGURES = CorpusFigures({
    "as_shipped_population":
        lambda root: _named(root / "programs", "*_check.py", "*_audit.py"),
    "checker_shaped_population":
        lambda root: len(checker_population(root / "programs")),
    "all_programs":
        lambda root: len(list((root / "programs").glob("*.py"))),
    "programs_outside_population":
        lambda root: (len(list((root / "programs").glob("*.py")))
                      - len(checker_population(root / "programs"))),
})


def audit(plugin: Path, repo_root: Path) -> dict:
    programs = plugin / "programs"
    checkers = checker_population(programs)
    hay = _tokenise(_haystacks(plugin, repo_root))
    test_only: List[str] = []
    unrun: List[str] = []
    skill_only: List[str] = []
    # A MACHINE runner: something that invokes the checker without an agent
    # deciding to. SKILL is excluded here (and only here) because that is the
    # precise question `unwired_by_decision` asks; the test-only classification
    # above is unchanged, so this adds no finding to the existing ratchet.
    machine_runners: Dict[str, List[str]] = {}
    # NOT DETERMINED (vibe-ic#1347). A name this gate can SEE but whose shape it
    # cannot read is not evidence for either verdict. Folded into "wired" it
    # hides a checker nothing runs; folded into "unwired" it is an accusation
    # the gate cannot support. It is its own population and it never blocks.
    undetermined: List[str] = []
    idx = _Index(hay, [n[:-3] for n in checkers])
    for name in checkers:
        stem = name[:-3]
        ev = evidence(stem, hay, str(programs / name), idx)
        r = {k for k, v in ev.items() if v == _INVOCATION}
        machine_runners[name] = sorted(r - {"TEST", "SKILL"})
        weak = [k for k in _SHAPE_KINDS if ev.get(k) == _UNDETERMINED]
        if r - {"TEST", "SKILL"}:
            pass                                   # a real machine runner
        elif weak:
            # Decided BEFORE test-only and skill-only: the honest answer to
            # "does anything run this?" here is "this gate cannot tell", and
            # ranking it under a verdict it did not reach would state one.
            undetermined.append(name)
        elif not r:
            unrun.append(name)
        elif r == {"TEST"}:
            test_only.append(name)
        elif r - {"TEST"} == {"SKILL"}:
            # The WEAKEST runner there is: it fires only if an agent reads that
            # skill and chooses to run the program. #693 counts it as a runner
            # deliberately (counting it avoids a false positive) and says so;
            # what it does NOT do is say how many there are. 51 of 560 on
            # origin/main. Disclosed here so a gate parked behind a skill line
            # is at least COUNTED, which is the difference between a decision
            # and an oversight.
            skill_only.append(name)
    return {"program": "checker_execution_wiring_audit",
            "checkers": len(checkers),
            "all_programs": len(list(programs.glob("*.py"))),
            "test_only": sorted(test_only),
            "no_runner_at_all": sorted(unrun),
            "skill_only": sorted(skill_only),
            "not_determined": sorted(undetermined),
            "machine_runners": machine_runners,
            "passed": True}


def skill_only_register(path: Path) -> Dict[str, str]:
    """`{checker.py: reason}` for SKILL-only checkers that were investigated.

    A DISCLOSURE, not permission and not a ratchet. `_UNROUTED_INVENTORY` in
    `gate_skip_routing_check` is the wrong home — it is an exact-equality
    ratchet over unrouted SKIP PATHS (98 in 53 gates), and putting a
    never-wired program in it would make that balance mean two things at once.
    `checker_execution_wiring_baseline.json` is also the wrong home, and it
    says so by FAILING: it computes `paid = [c for c in baseline if c not in
    test_only_now]` and any entry that HAS a runner is reported as
    "(resolved) — shrink the baseline so it cannot become permission".
    Measured with both #693 inventory candidates added to a copy of it:

        RC=1
        [FAIL] 2 recorded checker(s) now HAVE a real runner
           (resolved) benchmark_triage_absorption_audit.py
           (resolved) organic_issue_body_lint.py

    Both have a SKILL runner, so neither is test-only, so neither belongs
    there. This file is the third register the two of them actually need.
    """
    if not path.is_file():
        return {}
    try:
        d = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError):
        return {}
    r = d.get("reasons") if isinstance(d, dict) else None
    return {str(k): str(v) for k, v in r.items()} if isinstance(r, dict) else {}

_MIN_DECISION_REASON = 120


def classify_disclosures(skill_only: List[str], reasons: Dict[str, str]):
    """Split the SKILL-only checkers into `(disclosed, gestured)` — #1270.

    Membership was the whole test:

        named = [c for c in so if c in reasons]

    so the reason was never READ. Measured on 2efa6af35: setting a recorded
    reason to `""` left this audit BYTE-IDENTICAL to the unmutated tree — still
    counted in "2 carry a written reason", still printed as "(skill-only,
    reason recorded)", still `[PASS]` rc 0. An entry that says nothing is WORSE
    than no entry, because silence does not misreport itself and a blank claim
    does. A register checked for membership only is a comment with a schema.

    THREE STATES, AND THE THIRD IS WHY THIS IS NOT THE BIGGER CHANGE:

      * NO entry -> in NEITHER list, and never blocking. 28 of the 30 SKILL-only
        checkers on 2efa6af35 are in this state; requiring a reason from them is
        a DIFFERENT decision with a 28-row blast radius, and it is not this one.
        SILENCE STAYS NON-BLOCKING.
      * an entry that STATES a measurement -> `disclosed`, reported as before.
      * an entry that GESTURES at one -> `gestured`, and that BLOCKS.

    The bar is `_MIN_DECISION_REASON`, the number this same file already applies
    to `unwired_by_decision` in `check_unwired_by_decision`. Both registers
    answer the identical question — why is this checker not machine-wired — and
    only one of them was enforced, so this imports a policy rather than
    inventing one. Its blast radius was measured on 2efa6af35 BEFORE choosing
    it: of the 2 entries the register holds (1341 and 1489 chars), entries below
    120 chars = 0. Today's output and rc are unchanged, which is the point.
    """
    disclosed: List[str] = []
    gestured: List[str] = []
    for name in sorted(set(skill_only)):
        if name not in reasons:
            continue
        reason = reasons[name]
        if isinstance(reason, str) and len(reason.strip()) >= _MIN_DECISION_REASON:
            disclosed.append(name)
        else:
            gestured.append(name)
    return disclosed, gestured


def check_unwired_by_decision(rep: dict, decisions: Dict[str, str],
                              known: List[str]) -> List[str]:
    """Enforce the `unwired_by_decision` block. Returns problem lines.

    Bidirectional on purpose: an entry is a disclosure that a checker is
    deliberately not machine-wired, so it must go stale the moment that stops
    being true. A record nothing re-derives decays into an assertion nobody
    can check — which is the shape #693 is about.
    """
    problems: List[str] = []
    in_scope = set(rep.get("machine_runners") or {})
    for name in sorted(decisions):
        reason = decisions[name]
        if name not in in_scope:
            problems.append(
                f"   {name}: recorded as deliberately unwired, but it is not a "
                f"checker in scope (*_check.py / *_audit.py under programs/). "
                f"Stale entry — delete it.")
            continue
        real = rep["machine_runners"].get(name) or []
        if real:
            problems.append(
                f"   {name}: recorded as deliberately unwired, but {real} now "
                f"invoke(s) it. The record is false — delete the entry (and if "
                f"the wiring was not intended, remove the wiring).")
        if name in set(known):
            problems.append(
                f"   {name}: is in BOTH `known` (test-only) and "
                f"`unwired_by_decision`. Those are different claims; pick one.")
        if not isinstance(reason, str) or len(reason.strip()) < _MIN_DECISION_REASON:
            problems.append(
                f"   {name}: reason must state the MEASUREMENT that decided it "
                f"(>= {_MIN_DECISION_REASON} chars), not gesture at one: "
                f"{str(reason)[:80]!r}")
    return problems


def _load_decisions(p: Path) -> Dict[str, str]:
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return {}
    v = d.get("unwired_by_decision") if isinstance(d, dict) else None
    return v if isinstance(v, dict) else {}


def measure_triage(programs: Path, names: List[str], timeout: int = 200) -> Dict[str, str]:
    """Run each recorded checker with NO arguments and record what happened.

    EMPIRICAL rather than static, for a reason this repo keeps re-learning.
    A first version of this annotation read `required=True` out of the
    argparse calls; `skill_doc_section_present_check` enforces `--marker`
    manually AFTER parsing (`action="append", default=[]`), so the static
    read reported only `--doc` and made the entry look one flag away from
    wireable when it is a parameterised helper. Running it says rc=2 and
    prints the real reason.

    A bare register invites the worst repair — deleting the test so the
    entry disappears — so every entry has to carry what was found when it
    was investigated, and that finding has to be REGENERABLE rather than a
    one-off someone typed in.
    """
    import subprocess
    out: Dict[str, str] = {}
    for name in names:
        p = programs / name
        try:
            r = subprocess.run([__import__("sys").executable, str(p)],
                               capture_output=True, text=True, timeout=timeout)
            rc, blob = r.returncode, (r.stderr or "") + "\n" + (r.stdout or "")
        except subprocess.TimeoutExpired:
            out[name] = f"no-arg run TIMED OUT after {timeout}s"
            continue
        except OSError as e:
            out[name] = f"no-arg run could not start: {e}"
            continue
        why = next((ln.strip() for ln in blob.splitlines()
                    if ln.strip() and not ln.strip().startswith(("usage:", "  ", "\t"))),
                   "(no output)")
        verdict = {0: "rc=0 runs green with no arguments",
                   1: "rc=1 FAILs with no design to judge",
                   2: "rc=2 SKIPs / refuses without its input"}.get(rc, f"rc={rc}")
        out[name] = f"{verdict} — {why[:180]}"
    return out


def _load_baseline(p: Path):
    """The measured test-only residual, or ``None`` if none can be read.

    Do not collapse ``None`` into ``[]``: the former says no comparison was
    available, while the latter says the tree was measured and found clean.
    """
    if not p.is_file():
        return None
    try:
        # A replacement character is not evidence that the persisted member
        # name was measured.  Decode strictly so corrupt UTF-8 takes the same
        # NOT CHECKED path as truncated JSON instead of fabricating a renamed
        # baseline entry.
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    k = d.get("known") if isinstance(d, dict) else d
    if not isinstance(k, list) or any(not isinstance(x, str) for x in k):
        return None
    return sorted(set(k))


def _resolve(repo_root: Path):
    plugin = repo_root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    if (plugin / "programs").is_dir():
        return plugin
    here = Path(__file__).resolve().parent.parent
    return here if (here / "programs").is_dir() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--scope-expanded", metavar="REASON",
                    help="permit a GROWING baseline for this write, because "
                         "the audit now LOOKS at more than it did (a wider "
                         "scope finds pre-existing debt; that is not a "
                         "regression). Requires a reason >=30 chars, recorded "
                         "in the baseline beside the previous size")
    ap.add_argument("--refresh-triage", action="store_true",
                    help="with --write-baseline: re-MEASURE each entry by "
                         "running it with no arguments (opt-in; it executes "
                         "every recorded program, so it is off the gate path)")
    a = ap.parse_args(argv)

    here = Path(__file__).resolve()
    root = (Path(a.repo_root).resolve() if a.repo_root
            else next((b for b in here.parents
                       if (b / "vibe-ic-marketplace").is_dir()), here.parents[3]))
    plugin = _resolve(root)
    if plugin is None:
        print("[SKIP] checker_execution_wiring_audit: plugin layout not found.")
        return 2

    bl = Path(a.baseline) if a.baseline else here.parent / _BASELINE_NAME
    base = _load_baseline(bl)
    if base is None:
        # Writing is the operation that can CREATE an absent measurement. It
        # may bootstrap a missing path, but must never overwrite an existing
        # unreadable/truncated artefact as though its old value were zero.
        bootstrapping = (a.write_baseline and not bl.exists()
                         and not bl.is_symlink())
        if not bootstrapping:
            print(
                "NOT CHECKED: no checker-execution wiring baseline states a "
                f"readable measurement at {bl} — absent, unreadable, or "
                "truncated is not a measurement of zero, so no checker can "
                "be called NEW. Measure this tree and record the baseline "
                "before asking this audit to attribute anything. See "
                "vibe-ic#1705.",
                file=sys.stderr)
            return 2

    rep = audit(plugin, root)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, indent=2) + "\n")
    now = sorted(rep["test_only"] + rep["no_runner_at_all"])

    if a.write_baseline:
        if a.scope_expanded is not None and len(a.scope_expanded.strip()) < 30:
            print("[FAIL] --scope-expanded needs a real reason (>=30 chars) "
                  "naming what the audit now looks at that it did not before.")
            return 1
        prev = base
        if (prev is not None and len(now) > len(prev)
                and a.scope_expanded is None):
            print(f"[FAIL] refusing to GROW the baseline "
                  f"({len(prev)} -> {len(now)}): a checker losing its only "
                  f"real runner is a regression, not a fact to record. If the "
                  f"audit now LOOKS at more than it did, say so with "
                  f"--scope-expanded '<why>'.")
            return 1
        prev_triage = {}
        if bl.is_file():
            try:
                prev_triage = json.loads(bl.read_text()).get("triage") or {}
            except (OSError, ValueError):
                prev_triage = {}
        if a.refresh_triage:
            prev_triage = measure_triage(plugin / "programs", now)
        bl.write_text(json.dumps(
            {"_comment": ("Checkers that NOTHING but their own unit test ever "
                          "runs (vibe-ic#381). MAY ONLY SHRINK — each entry is "
                          "a checker with zero coverage of real inputs. "
                          "`triage` records why an entry is still here; the "
                          "wrong repair is to delete the test so the entry "
                          "disappears."),
             "previous_size": None if prev is None else len(prev),
             "scope_expanded": a.scope_expanded,
             "known": now,
             "triage": {k: v for k, v in prev_triage.items() if k in now},
             # Carried through a rewrite: this block is a separate claim from
             # `known` and a --write-baseline must not silently drop it.
             "unwired_by_decision": _load_decisions(bl)},
            indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {bl} ({len(now)} entr(ies))")
        return 0

    print(f"checker_execution_wiring_audit: {rep['checkers']} checker-shaped "
          f"program(s) of {rep['all_programs']} in programs/")
    # Read from the plugin UNDER AUDIT, not from wherever this file happens to
    # sit: `--repo-root` already redirects every other input, and a register
    # that ignores it describes a different checkout than the verdict does. On
    # an in-repo run the two paths are the same file.
    reasons = skill_only_register(plugin / "programs" / _SKILL_ONLY_NAME)
    so = rep.get("skill_only") or []
    disclosed, gestured = classify_disclosures(so, reasons)
    print(f"  SKILL-only (the weakest runner): {len(so)} — "
          f"{len(disclosed)} carry a written reason in {_SKILL_ONLY_NAME}, "
          f"{len(so) - len(disclosed) - len(gestured)} do not. "
          + ("REPORTED, never blocking."
             if not gestured else
             f"The COUNT is REPORTED and never blocks — but "
             f"{len(gestured)} entr{'y' if len(gestured) == 1 else 'ies'} below "
             f"claim{'s' if len(gestured) == 1 else ''} a reason without "
             f"stating one, and that BLOCKS."))
    for c in disclosed:
        print(f"   (skill-only, reason recorded) {c}")
    stale = sorted(set(reasons) - set(so))
    if stale:
        # The register may not outlive what it describes: an entry that has
        # gained a real runner, or lost its SKILL one, is describing a state
        # that no longer exists.
        print(f"  NOTE {len(stale)} recorded reason(s) no longer match a "
              f"SKILL-only checker (wired since, or renamed): "
              + ", ".join(stale[:6]))
    new = [c for c in now if base is None or c not in set(base)]
    paid = [c for c in (base or []) if c not in set(now)]
    # EVERY POPULATION, INCLUDING THE ZEROS. vibe-ic#1130.
    #
    # `no runner at all` used to print only when it was non-zero. At zero the
    # gate said nothing about it, and a count that appears only when it is
    # non-zero cannot be told apart from a check that did not run — which is
    # the same defect this program exists to find, one level up. The audit
    # that reports "N checkers nothing but a fixture runs" was itself
    # reporting one of its own populations conditionally.
    #
    # Printed unconditionally now, so a reader can distinguish "I looked and
    # found none" from "this line is missing because nobody looked".
    nd = rep.get("not_determined") or []
    print(f"  population     : test-only {len(rep['test_only'])}, "
          f"no-runner-at-all {len(rep['no_runner_at_all'])}, "
          f"skill-only {len(so)}, not-determined {len(nd)}, "
          f"baseline {0 if base is None else len(base)} "
          f"— stated even at zero (#1130)")
    for c in rep["no_runner_at_all"][:10]:
        print(f"   (no runner at all) {c}")
    # REPORTED, never blocking — the point of the population is that this gate
    # did NOT reach a verdict on these, and blocking on one would state the
    # verdict it just said it could not reach (#1347).
    for c in nd[:10]:
        print(f"   (not determined — name present, shape unreadable) {c}")
    if paid:
        print(f"[FAIL] {len(paid)} recorded checker(s) now HAVE a real runner "
              f"— shrink the baseline so it cannot become permission:")
        for c in paid:
            print(f"   (resolved) {c}")
    if new:
        print(f"[FAIL] {len(new)} checker(s) that NOTHING but their own test "
              f"runs — a fixture the author wrote proves the logic, never the "
              f"artefacts:")
        for c in new:
            print(f"   {c}")
    if gestured:
        # NOT the same finding as "28 do not carry a reason". Those 28 are
        # silent, and silence is honest. These CLAIM a reason and then do not
        # state one, which is the only state that misreports itself.
        print(f"[FAIL] {len(gestured)} SKILL-only disclosure(s) claim a reason "
              f"and do not state one — an entry that says nothing is worse "
              f"than no entry, because silence does not misreport itself:")
        for c in gestured:
            print(f"   {c}: reason must state the MEASUREMENT that decided it "
                  f"(>= {_MIN_DECISION_REASON} chars), not gesture at one: "
                  f"{str(reasons.get(c))[:80]!r}")
    decisions = _load_decisions(bl)
    stale = check_unwired_by_decision(rep, decisions, base or [])
    if stale:
        print(f"[FAIL] {len(stale)} problem(s) in `unwired_by_decision` — a "
              f"'deliberately unwired' record that is no longer true is a "
              f"licence, not a disclosure:")
        for line in stale:
            print(line)
    if new or paid or stale or gestured:
        return 1
    print(f"[PASS] no NEW test-only checker ({len(now)} recorded)"
          + (f"; {len(decisions)} deliberately unwired, disclosed"
             if decisions else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
