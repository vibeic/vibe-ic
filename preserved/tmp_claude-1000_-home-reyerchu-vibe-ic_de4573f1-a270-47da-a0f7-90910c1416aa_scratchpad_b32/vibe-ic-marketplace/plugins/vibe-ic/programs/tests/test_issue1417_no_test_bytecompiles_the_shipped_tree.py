"""Importing a shipped `skills/**` module writes into the shipped tree, and
every instrument except one digest reports the tree as clean.

THE DEFECT, reproduced on clean main `3d13e2c59` (vibe-ic#1417, batch R4)::

    programs/tests/test_v0_2_97_issue481_482_triage_lessons.py   34 passed, 0 pyc
    programs/tests/test_tools_and_integration.py                 19 passed, 0 pyc
    the two together, one session                          1 FAILED, 33 passed, 1 pyc

    left behind:
      skills/open-benchmark-methodology/tests/__pycache__/test_compliance.cpython-310.pyc

`spec.loader.exec_module()` on a path under `skills/` makes CPython cache the
byte-code NEXT TO THE SOURCE, i.e. inside the shipped tree. `__pycache__/` is
gitignored, so:

  * `git status skills/`      -> empty
  * `git add -A`              -> takes nothing
  * `suite_write_guard`       -> skips it as a regenerable cache artefact

Three independent "the tree is clean" answers, all of them wrong, and the only
instrument that disagrees is
`test_tools_and_integration.test_shipped_skills_tree_is_untouched_by_this_module`,
which digests BYTES instead of asking git. That is why the failure "presents
with no obvious author" — its own message says so.

It is not cosmetic: `gatekeeper-land.sh:213` fails the WHOLE landing when the
tree moves under the gates, so one cached byte-code file costs a batch its
stamp. Batch R4 is the instance.

WHY THIS FILE EXISTS RATHER THAN JUST THE FIX
=============================================
The digest guard catches this only when the writer runs in the SAME session and
AFTER that module was imported. Split the two across shards — which every sweep
of this suite does — and the digest sees nothing. So the digest is a real
detector with a scheduling precondition, and this file removes the precondition:
it reads the corpus and fails on the SOURCE SHAPE, in any session, alone.

WHAT IT DOES **NOT** DO
=======================
It does not relax, replace or duplicate the digest assertion. The digest owns
"was the tree written"; this owns "can it be". A source-shape check cannot see a
writer that does not look like one, which is exactly why the digest stays.

THE EXEMPTION DEFECT THIS FILE CARRIED (vibe-ic#1417)
=====================================================
Both checks below exempted a module by SUBSTRING over its whole text: the spawn
check on `PYTHONDONTWRITEBYTECODE` or `-B`, the loader check on
`dont_write_bytecode`. A token in a docstring, a comment or an assertion
message therefore exempted the file from the AST walk that would have found its
unsuppressed call — and those tokens are the ones this guard's OWN remedy
message names, so quoting the remedy silenced the guard.

Measured on `75776dbbb`, this file byte-identical across both arms, the only
change a two-line COMMENT naming `PYTHONDONTWRITEBYTECODE` added to the live
offender `test_v0_3_4_issue501_verbatim_lessons.py`::

    offender pristine   (md5 2700ca29…)   1 failed, 2 passed
    offender + comment  (md5 6b4157e4…)   3 passed
    its spawn, byte-identical in both     0 -> 4 `.pyc` under `skills/`

The exemptions the substring form actually granted on this corpus were
"Bucket-B" (twice, in docstrings), "OVER-BLOCKS" (a comment) and an assertion
STRING — and the only literal `-B` argv elements in the tree are
`git checkout -B <branch>`, which is git's flag, not CPython's.

Each token is now read off the CALL: `-B` as an argv ELEMENT, the env var
inside THAT call's `env=`. The loader check requires the module to ASSIGN
`sys.dont_write_bytecode` rather than to mention it.
"""
from __future__ import annotations

import ast
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_PLUGIN = _TESTS.parents[1]
_SKILLS = _PLUGIN / "skills"

#: The two names that make CPython write a `.pyc` next to the source.
_LOADERS = ("exec_module", "SourceFileLoader")

#: …and the OTHER way in, which the first version of this file could not see.
#: A SPAWNED child pointed at a path under `skills/` writes there too, and
#: `sys.dont_write_bytecode` is per-interpreter so it never reaches the child.
#: Found by #1485, which fixes a real instance this guard was green on:
#: `test_v0_3_4_issue501_verbatim_lessons.py` runs
#: `subprocess.run([sys.executable, "-m", "pytest", <skills path>])`, depositing
#: both `__pycache__/*.pyc` and pytest's own assertion-rewrite caches.
#: A guard that names a CLASS and covers one of its two mechanisms is worse than
#: one that names the mechanism, because the gap is invisible.
_SPAWNERS = ("run", "Popen", "check_call", "check_output", "call")

#: What makes a spawned child safe — and, the half this file first got wrong,
#: WHERE each token has to appear before it means anything. `-B` is looked for
#: as an ARGV ELEMENT and the env var inside that call's `env=`; see the module
#: docstring for what the whole-file form exempted instead.
_ENV_SUPPRESSOR = "PYTHONDONTWRITEBYTECODE"
_ARGV_SUPPRESSOR = "-B"

#: The in-process suppression, as the house already writes it — `test_api_health.py`,
#: `test_matrix_63x8_census_freshness.py`, `test_issue972_census_probe_and_rollup.py`.
#: Required to be ASSIGNED, not merely named: both modules that load from
#: `skills/` today assign it, so the tightening flags neither.
_SUPPRESSION = "dont_write_bytecode"


def _assignments(tree: ast.AST) -> dict:
    """`name -> source of the expression assigned to it`, anywhere in the file.

    One flat namespace on purpose. Resolving scopes properly would be more
    faithful and would buy nothing here: the question is only which literal
    path a name stands for, and a test module that binds one name to two
    different paths would make BOTH visible, which errs toward looking.
    """
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.value is not None:
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    out.setdefault(tgt.id, ast.unparse(node.value))
    return out


def _mentions_skills_path(text: str) -> bool:
    """Cheap pre-filter. Broad on purpose — the AST decides, this only skips."""
    return '"skills"' in text or "'skills'" in text or "/skills/" in text


def _expanded_source(expr: str, names: dict, stop: str | None = None) -> str:
    """*expr* with this module's own assignments substituted in, bounded.

    Bounded because a cycle would otherwise not terminate, and an expression
    built through more than a few names is not one this can judge. *stop*
    short-circuits as soon as the answer can no longer change.
    """
    for _ in range(6):
        if stop is not None and stop in expr:
            return expr
        try:
            idents = sorted({n.id for n in ast.walk(ast.parse(expr, mode="eval"))
                             if isinstance(n, ast.Name)}, key=len, reverse=True)
        except SyntaxError:                        # pragma: no cover
            return expr
        nxt = expr
        for ident in idents:
            if ident in names:
                nxt = nxt.replace(ident, f"({names[ident]})")
        if nxt == expr:
            break
        expr = nxt
    return expr


def _expand(expr: str, names: dict) -> bool:
    """Does *expr* resolve to a path under `skills/`, following this module's
    own assignments?"""
    return "skills" in _expanded_source(expr, names, stop="skills")


def _argv_strings(call: ast.Call, names: dict) -> list:
    """The string constants of THIS call's argv.

    Follows the module's own assignments, so a hoisted
    `_ARGV = [sys.executable, "-B", "-m", "pytest"]` used as
    `subprocess.run(_ARGV + [path])` is still read, and unwraps the `+` that
    such a call splices with.
    """
    if not call.args:
        return []
    try:
        node = ast.parse(_expanded_source(ast.unparse(call.args[0]), names),
                         mode="eval").body
    except SyntaxError:                            # pragma: no cover
        return []
    out, stack = [], [node]
    while stack:
        item = stack.pop()
        if isinstance(item, (ast.List, ast.Tuple)):
            stack.extend(item.elts)
        elif isinstance(item, ast.BinOp):
            stack.extend((item.left, item.right))
        elif isinstance(item, ast.Constant) and isinstance(item.value, str):
            out.append(item.value)
    return out


def _spawn_suppresses_bytecode(call: ast.Call, names: dict) -> bool:
    """Does byte-code suppression reach THIS child?

    Read off the call, never off the file — the whole-file form this replaces
    is described in the module docstring. Two shapes:

      * `-B` as an argv ELEMENT, `[sys.executable, "-B", "-m", "pytest", …]`.
        Element and not substring, because the corpus's only literal `-B`
        occurrences are `git checkout -B <branch>` and a `-B` inside
        "Bucket-B" is prose.
      * `PYTHONDONTWRITEBYTECODE` inside this call's `env=`, expanded through
        the module's assignments so the house idiom
        `env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}` … `env=env`
        is seen where it is written rather than only where it is inlined.

    A `**kwargs` spawn is NOT read as safe. It may carry `env=` and it may not;
    reporting an unreadable spawn errs toward looking, which is how
    `_assignments` above already resolves the same kind of doubt.
    """
    for s in _argv_strings(call, names):
        if s == _ARGV_SUPPRESSOR or _ARGV_SUPPRESSOR in s.split():
            return True
    for kw in call.keywords:
        if kw.arg == "env" and _ENV_SUPPRESSOR in _expanded_source(
                ast.unparse(kw.value), names, stop=_ENV_SUPPRESSOR):
            return True
    return False


def _suppresses_in_process(tree: ast.AST) -> bool:
    """Does the module ASSIGN `sys.dont_write_bytecode`, rather than name it?

    Module-wide rather than per-call, and deliberately so: the idiom brackets
    the loader — `prev = sys.dont_write_bytecode; sys.dont_write_bytecode =
    True; try: … finally: sys.dont_write_bytecode = prev` — so the suppression
    is a surrounding STATEMENT, and asking which call it covers needs flow
    analysis this does not have. The narrowing that IS available is taken: a
    docstring, a comment or an assertion message no longer exempts a module.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Attribute) and tgt.attr == _SUPPRESSION:
                    return True
    return False


def _child_executes_from_skills(call: ast.Call, names: dict) -> bool:
    """Does this spawn make the CHILD import code out of `skills/`?

    PASSING a skills path is not executing from it, and the first version of
    this check could not tell the difference. Measured false positive:

        test_v1_1_6_core_agent_pr_method.py
          subprocess.run([sys.executable, str(_CHECK), "--doc", str(SKILL)])
          -> 5 passed, 0 pyc under skills/

    The script is `_CHECK`, under `programs/`; the skills path is the VALUE of
    `--doc`. The child never imports from `skills/` and writes nothing there.
    Demanding a suppression would have been a token added to silence a check
    that had nothing to say — the habit this file's other half already rejects.

    So the skills path must be the EXECUTION TARGET, which is one of two
    shapes in this corpus:

      * the child is pytest, which COLLECTS and imports whatever path it is
        given — `[sys.executable, "-m", "pytest", ..., <skills path>]`;
      * the skills path is the script itself, i.e. the argument immediately
        after the interpreter.
    """
    if not call.args:
        return False
    seq = call.args[0]
    items = seq.elts if isinstance(seq, (ast.List, ast.Tuple)) else [seq]
    src = [ast.unparse(a) for a in items]
    hits = [i for i, s in enumerate(src) if _expand(s, names)]
    if not hits:
        return False
    # pytest imports every path it is handed, so any skills path is executed.
    if any("pytest" in s for s in src):
        return True
    # …otherwise only the script position counts. Index 0 is the interpreter.
    return 1 in hits


def _loads_from_skills(call: ast.Call, names: dict) -> bool:
    """Does this loader call resolve to a path under `skills/`?

    THE FIRST VERSION OF THIS ASKED WHETHER THE FILE MENTIONED `skills` AT ALL,
    and it was wrong in the direction that matters least but costs most: four
    modules flagged that load `programs/backlog_sanitize_check.py`,
    `programs/enhancement_emit.py`, `programs/gen_skill_inventory.py` and
    `benchmark/cvdp_task_router.py` and merely NAME a SKILL.md in an assertion.
    Measured: each leaves 0 `.pyc` under `skills/`. Demanding a suppression
    there would have been four edits that fix nothing, and the habit of adding
    a token to silence a check is how a check stops meaning anything.

    So the path EXPRESSION is resolved instead — one name at a time, through
    the module's own assignments — and the decision is made on what the loader
    is actually pointed at. For the measured writer that chain is::

        comp_test = SKILL_MD.parent / "tests" / "test_compliance.py"
        SKILL_MD  = ... / "skills" / "open-benchmark-methodology" / "SKILL.md"
    """
    args = call.args
    if len(args) < 2:
        return False
    return _expand(ast.unparse(args[1]), names)


def _unsuppressed_loader_line(text: str):
    """Line of the first loader call in *text* that resolves into `skills/`
    while the module never assigns the suppression, else None.

    Factored out so the paired control below drives the SAME code path that is
    enforced against the corpus, and cannot drift from it.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:                            # pragma: no cover
        return None
    if _suppresses_in_process(tree):
        return None
    names = _assignments(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if fname not in ("spec_from_file_location", "SourceFileLoader"):
            continue
        if _loads_from_skills(node, names):
            return node.lineno
    return None


def _unsuppressed_spawn_line(text: str):
    """Line of the first spawn in *text* that executes from `skills/` without
    suppression reaching that child, else None. Shared with the control."""
    try:
        tree = ast.parse(text)
    except SyntaxError:                            # pragma: no cover
        return None
    names = _assignments(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr in _SPAWNERS):
            continue
        if (_child_executes_from_skills(node, names)
                and not _spawn_suppresses_bytecode(node, names)):
            return node.lineno
    return None


def test_no_test_module_exec_modules_a_shipped_path_unsuppressed():
    """The corpus-wide property, checked by SHAPE so it holds in any session.

    Named per file rather than counted: a number tells the next reader that
    something is wrong and not which file to open, and this defect already cost
    one bisection precisely because it had no obvious author.
    """
    offenders = []
    for f in sorted(_TESTS.glob("test_*.py")):
        if f.name == Path(__file__).name:
            continue
        text = f.read_text(errors="replace")
        if not any(n in text for n in _LOADERS):
            continue
        line = _unsuppressed_loader_line(text)
        if line is not None:
            offenders.append(f"{f.name}:{line}")
    assert not offenders, (
        "these test modules load a module from a path under `skills/` without "
        "suppressing byte-code, so importing it writes a `.pyc` INTO the "
        "shipped tree — invisible to git, `git add -A` and suite_write_guard, "
        "and fatal to a landing via gatekeeper-land.sh:213. Wrap the "
        "`exec_module` call: `prev = sys.dont_write_bytecode; "
        "sys.dont_write_bytecode = True; try: ... finally: "
        f"sys.dont_write_bytecode = prev`. Offenders: {offenders}")


def test_no_test_module_spawns_a_child_into_the_shipped_tree_unsuppressed():
    """THE MECHANISM THE FIRST VERSION OF THIS FILE WAS BLIND TO.

    `sys.dont_write_bytecode` is per-interpreter, so it cannot reach a SPAWNED
    child. A test that runs `subprocess.run([sys.executable, "-m", "pytest",
    <path under skills/>])` writes `__pycache__/*.pyc` — and pytest's own
    assertion-rewrite caches — straight into the shipped tree, and every
    in-process check here stays green while it happens.

    Measured: this file's first version passed on clean main `3d13e2c59` with
    exactly such a writer live in `test_v0_3_4_issue501_verbatim_lessons.py`.
    #1485 is the fix for that instance; this is the guard that would have
    named it.

    The child is safe if its environment carries `PYTHONDONTWRITEBYTECODE` or
    its argv carries `-B`. `-p no:cacheprovider` is ALSO wanted for the pytest
    cache, but it is not asserted here: this file is about byte-code, and a
    check that quietly widens its own subject is how a guard stops meaning one
    thing.
    """
    offenders = []
    for f in sorted(_TESTS.glob("test_*.py")):
        if f.name == Path(__file__).name:
            continue
        text = f.read_text(errors="replace")
        if "subprocess" not in text or not _mentions_skills_path(text):
            continue
        line = _unsuppressed_spawn_line(text)
        if line is not None:
            offenders.append(f"{f.name}:{line}")
    assert not offenders, (
        "these test modules SPAWN a child pointed at a path under `skills/` "
        "without suppressing byte-code in it. `sys.dont_write_bytecode` is "
        "per-interpreter and does not reach a child; pass "
        "`env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}` or `-B`. "
        f"Offenders: {offenders}")


def test_the_shipped_tree_carries_no_committed_bytecode():
    """The other direction, and the reason the suppression is not optional.

    If a `.pyc` were ever COMMITTED under `skills/`, the digest would be stable
    and every one of the checks above would pass while the shipped tree carried
    build output. Cheap, and it states the invariant the rest of this file is
    protecting rather than assuming it.
    """
    if not _SKILLS.is_dir():                       # pragma: no cover
        return
    stray = sorted(str(p.relative_to(_PLUGIN))
                   for p in _SKILLS.rglob("*.pyc"))
    assert not stray, (
        f"byte-code is present in the shipped skills/ tree: {stray[:10]}")


#: Modules built to be JUDGED, not run. Each is the smallest thing that carries
#: one shape, and the flag is what `_unsuppressed_spawn_line` must say about it.
#: `_HEAD` binds a path under `skills/` the way the corpus does, through a name,
#: so the control also exercises the expansion rather than a literal.
_HEAD = ('import os, subprocess, sys\n'
         'from pathlib import Path\n'
         '_T = Path("skills") / "core-agent-loop" / "tests"\n')

_SPAWN_CASES = (
    # (label, body, must this spawn be REPORTED?)
    ("bare",
     'subprocess.run([sys.executable, "-m", "pytest", str(_T)])', True),

    # THE REGRESSION ARM. The remedy this file prints names both tokens, so
    # before the fix, quoting it in a comment took the guard green while the
    # spawn beside it still wrote into the shipped tree.
    ("remedy quoted in a comment",
     '# pass env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"} or -B\n'
     'subprocess.run([sys.executable, "-m", "pytest", str(_T)])', True),

    # The same, as a docstring — a string node the AST really does contain,
    # which a naive "is the token anywhere in the tree" fix would still miss.
    ("remedy quoted in a docstring",
     '"""Bucket-B, OVER-BLOCKS, and PYTHONDONTWRITEBYTECODE."""\n'
     'subprocess.run([sys.executable, "-m", "pytest", str(_T)])', True),

    # `-B` must be an argv ELEMENT. "Bucket-B" is prose, and prose that reached
    # argv is still prose.
    ("-B only as a substring of an element",
     'subprocess.run([sys.executable, "-m", "pytest", "-k", "Bucket-B",'
     ' str(_T)])', True),

    # An env that is passed but carries no suppression is not suppression.
    ("env= without the variable",
     'subprocess.run([sys.executable, "-m", "pytest", str(_T)],'
     ' env={**os.environ})', True),

    # …and the three shapes that genuinely do reach the child.
    ("env= inline",
     'subprocess.run([sys.executable, "-m", "pytest", str(_T)],'
     ' env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})', False),
    ("env= through a name",
     '_E = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}\n'
     'subprocess.run([sys.executable, "-m", "pytest", str(_T)], env=_E)', False),
    ("-B as an argv element",
     'subprocess.run([sys.executable, "-B", "-m", "pytest", str(_T)])', False),
)


def test_the_spawn_check_reads_the_call_and_not_the_files_prose():
    """The other direction: this check must still go RED when the property is
    genuinely violated, and must not be silenceable by text.

    A whole-file substring exemption made this guard SELF-silencing, because
    the tokens it exempted on are the ones its own remedy message names.
    Measured on `75776dbbb` with this file byte-identical and a two-line
    comment added to the live offender: `1 failed, 2 passed` became
    `3 passed`, while that unchanged spawn still deposited 4 `.pyc` under
    `skills/`. A green bought that way is worse than the defect it hides.

    Both arms are asserted together on purpose. A control that only proves the
    check can pass is the shape that let the substring form survive review.
    """
    wrong = []
    for label, body, must_report in _SPAWN_CASES:
        reported = _unsuppressed_spawn_line(_HEAD + body) is not None
        if reported != must_report:
            wrong.append(f"{label}: reported={reported}, expected={must_report}")
    assert not wrong, (
        "the spawn check no longer decides on the CALL. Each case above is a "
        "module whose verdict is fixed by vibe-ic#1417; a case that flipped to "
        "reported=False is an exemption granted by text, which is exactly the "
        f"defect this file was repaired for. Wrong: {wrong}")


_LOADER_HEAD = ('import importlib.util, sys\n'
                'from pathlib import Path\n'
                '_P = Path("skills") / "core-agent-loop" / "x.py"\n')

_LOADER_CASES = (
    ("bare",
     'importlib.util.spec_from_file_location("m", _P)', True),
    ("suppression only NAMED, in a docstring",
     '"""Wrap it: sys.dont_write_bytecode = True."""\n'
     'importlib.util.spec_from_file_location("m", _P)', True),
    ("suppression only NAMED, in an assertion message",
     'assert _P, "set sys.dont_write_bytecode first"\n'
     'importlib.util.spec_from_file_location("m", _P)', True),
    ("suppression ASSIGNED",
     'sys.dont_write_bytecode = True\n'
     'importlib.util.spec_from_file_location("m", _P)', False),
)


def test_the_loader_check_requires_the_suppression_to_be_assigned():
    """Same defect, same repair, the in-process half.

    `dont_write_bytecode` appearing anywhere in the text used to exempt the
    module. Both corpus modules that load from `skills/` today ASSIGN it, so
    this costs nothing now and closes the way a future one could be exempted
    by its own prose.
    """
    wrong = []
    for label, body, must_report in _LOADER_CASES:
        reported = _unsuppressed_loader_line(_LOADER_HEAD + body) is not None
        if reported != must_report:
            wrong.append(f"{label}: reported={reported}, expected={must_report}")
    assert not wrong, (
        "the loader check no longer requires `sys.dont_write_bytecode` to be "
        f"ASSIGNED rather than mentioned. Wrong: {wrong}")
