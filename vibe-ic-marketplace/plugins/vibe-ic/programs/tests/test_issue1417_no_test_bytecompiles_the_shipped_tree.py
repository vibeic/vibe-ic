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
"""
from __future__ import annotations

import ast
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_PLUGIN = _TESTS.parents[1]
_SKILLS = _PLUGIN / "skills"

#: The two names that make CPython write a `.pyc` next to the source.
_LOADERS = ("exec_module", "SourceFileLoader")

#: The suppression, as the house already writes it — `test_api_health.py`,
#: `test_matrix_63x8_census_freshness.py`, `test_issue972_census_probe_and_rollup.py`.
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
    expr = ast.unparse(args[1])
    # Bounded: a cycle in the assignments would otherwise not terminate, and a
    # path built through more than a few names is not a path this can judge.
    for _ in range(6):
        if "skills" in expr:
            return True
        nxt = expr
        for ident in sorted(set(n.id for n in ast.walk(ast.parse(expr, mode="eval"))
                                if isinstance(n, ast.Name)), key=len, reverse=True):
            if ident in names:
                nxt = nxt.replace(ident, f"({names[ident]})")
        if nxt == expr:
            break
        expr = nxt
    return "skills" in expr


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
        if _SUPPRESSION in text:
            continue
        try:
            tree = ast.parse(text, str(f))
        except SyntaxError:                        # pragma: no cover
            continue
        names = _assignments(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if fname not in ("spec_from_file_location", "SourceFileLoader"):
                continue
            if _loads_from_skills(node, names):
                offenders.append(f.name)
                break
    assert not offenders, (
        "these test modules load a module from a path under `skills/` without "
        "suppressing byte-code, so importing it writes a `.pyc` INTO the "
        "shipped tree — invisible to git, `git add -A` and suite_write_guard, "
        "and fatal to a landing via gatekeeper-land.sh:213. Wrap the "
        "`exec_module` call: `prev = sys.dont_write_bytecode; "
        "sys.dont_write_bytecode = True; try: ... finally: "
        f"sys.dont_write_bytecode = prev`. Offenders: {offenders}")


def test_the_known_writer_is_suppressed_at_its_call_site():
    """The specific instance, pinned to the CALL rather than to the file.

    `test_no_test_module_exec_modules_a_shipped_path_unsuppressed` is satisfied
    by the string appearing anywhere in the module. That is the right trade for
    a corpus sweep and the wrong one for the case we actually measured, so this
    asserts the suppression encloses the `exec_module` call in the AST — moving
    the assignment away from the call reddens it.
    """
    src = (_TESTS / "test_v0_2_97_issue481_482_triage_lessons.py")
    tree = ast.parse(src.read_text(encoding="utf-8"), str(src))

    guarded = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        calls_exec = any(
            isinstance(n, ast.Attribute) and n.attr == "exec_module"
            for n in ast.walk(node)
        )
        # The restore must be in `finally`, not merely somewhere in the module:
        # a suppression that is never restored leaks into every later test in
        # the session, which would trade this defect for a broader one.
        restores = any(
            isinstance(n, ast.Attribute) and n.attr == _SUPPRESSION
            for h in node.finalbody for n in ast.walk(h)
        )
        if calls_exec and restores:
            guarded = True
            break
    assert guarded, (
        f"{src.name} calls exec_module on a shipped `skills/` module without a "
        "try/finally that restores sys.dont_write_bytecode around it. This is "
        "the writer measured for vibe-ic#1417 batch R4; see this module's "
        "docstring for the two-file reproduction.")


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
