r"""A program may not import a PRIVATE HELPER that is not in the tree. (#1469)

WHY THIS EXISTS
---------------
vibe-ic#1469 reported that group (d) of the IDX batch prescribes a remedy —
"route the declared write through ``_atomic_artefact``" — naming a module that
is not on ``main``. MEASURED at ``24ff9530``, whole-tree, with a control:

    git ls-tree -r --name-only origin/main \
        | grep -cE '/_atomic_(artefact|output)\.py$'      ->  0
    git grep -l -E '_atomic_artefact|_atomic_output' origin/main | wc -l
                                                          ->  0
    CONTROL, a private helper that DOES exist:
    git grep -l '_prose_polarity' origin/main | wc -l     -> 14

The control is what makes the zeros mean something: the same instrument on the
same tree finds 14 files for a helper that is there, so the zero is a real zero
and not a broken search. (#1469 was filed after exactly that mistake was made
one issue earlier — a per-directory grep whose ``0`` meant "wrong directory",
not "no occurrences".)

The HARM is not that the gate reports an offender. It is that the program
CRASHES, and its own tests do not see it: seventeen programs were to be wired
to ``_atomic_artefact``, and a wiring done today dies with

    ModuleNotFoundError: No module named '_atomic_artefact'    rc=1

on the first ``--json`` run — a code path the converted programs' unit tests do
not exercise. Reproduced on an offender's branch by a second agent (#1469
comment, ``provenance_chain_check``). Seventeen PRs would each have shipped
that, one hour of discovery apiece.

Nothing in the tree could see it. There is no import-resolvability gate among
the 63 hygiene gates, and the plugin pytest suite has no tree-wide equivalent.
This test is that instrument, and it is deliberately NOT about atomic writes:
the defect class is "a call site is wired to a private helper that has not
landed", and the atomic-helper arbitration (``_atomic_artefact`` #1110 vs
``_atomic_output`` #1265, both open, neither on main) is a decision this test
does not make and must not prejudge. It fails the same way for either name
while that name is absent, and stops failing for whichever one lands.

SCOPE, AND WHAT IS NOT SCANNED
------------------------------
Scanned: every top-level ``programs/*.py`` — which is where all seventeen of
group (d)'s call sites live. NOT scanned, stated rather than implied:
``programs/tests/*.py`` (they resolve sibling helpers through a ``sys.path``
insert of the parent directory, so a name-vs-file comparison in their own
directory would fabricate findings) and every non-plugin tree.

"PRIVATE HELPER" is the repo's leading-underscore convention (``_provenance``,
``_gh_cli``, ``_prose_polarity``, …). Dunder modules (``__future__``) are
excluded; they are not siblings. The rule is name-based rather than
import-executing on purpose — actually importing 1138 modules would run their
top-level code, and a check that must execute the tree to audit it is a check
nobody can run in a hook.

THE TWO ARMS ARE BOTH ASSERTED BELOW, on synthetic trees rather than on the
real one, so neither arm decays when the real tree changes:
  * ``test_absent_private_helper_is_reported``   — RED when the property is
    genuinely violated (including the exact group-(d) remedy line).
  * ``test_present_private_helper_is_not_reported`` — the same resolver stays
    quiet when the helper IS there, so the red arm is not reporting on
    everything.
  * ``test_scan_is_not_vacuous``                 — a denominator, so a broken
    glob cannot buy a green by looking at nothing.
"""
import ast
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).resolve().parent.parent

#: The floor under the real scan's denominator. MEASURED at 24ff9530: 1138
#: programs scanned, 574 private-helper imports, 0 unresolvable. The floor is
#: set well below 574 so ordinary churn does not trip it, and far above zero so
#: a glob that stops matching cannot buy a green by looking at nothing — the
#: failure mode this repository keeps meeting.
MIN_PRIVATE_IMPORTS = 100


def _is_private_helper(module: str) -> bool:
    """True for the repo's ``_name`` sibling-helper convention.

    ``__future__`` and any other dunder is NOT a sibling: it starts with an
    underscore but names a Python builtin, and counting it would have made the
    first draft of this scan report 1000+ false offenders.
    """
    head = module.split(".")[0]
    return head.startswith("_") and not head.startswith("__")


def _resolvable(head: str, directory: Path) -> bool:
    """True when ``head`` names a module file or package IN ``directory``."""
    return ((directory / f"{head}.py").is_file()
            or (directory / head / "__init__.py").is_file())


def unresolvable_private_imports(directory: Path):
    """Every ``(file, lineno, module)`` importing an ABSENT private sibling.

    Returns a sorted list so a failure message is stable between runs.
    """
    found = []
    for path in sorted(directory.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            # A syntax error is a different defect with its own gate; reporting
            # it here as an import failure would misattribute it.
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                # `level > 0` is an explicit relative import — resolved by the
                # package machinery, not by this flat-directory convention.
                if node.level or not node.module:
                    continue
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            else:
                continue
            for module in modules:
                if not _is_private_helper(module):
                    continue
                if not _resolvable(module.split(".")[0], directory):
                    found.append((path.name, node.lineno, module))
    return sorted(found)


def count_private_imports(directory: Path) -> int:
    """The DENOMINATOR: private-helper imports seen, resolvable or not."""
    total = 0
    for path in sorted(directory.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and not node.level and node.module:
                total += int(_is_private_helper(node.module))
            elif isinstance(node, ast.Import):
                total += sum(_is_private_helper(a.name) for a in node.names)
    return total


def test_scan_is_not_vacuous():
    """A green here must mean "looked and found none", never "did not look"."""
    scanned = len(list(PROGRAMS_DIR.glob("*.py")))
    seen = count_private_imports(PROGRAMS_DIR)
    # Disclosed, not merely asserted: a reader of a green run should be able to
    # see WHAT was looked at, not just that something was.
    print(f"issue1469 scan: {scanned} program(s), "
          f"{seen} private-helper import(s), "
          f"{len(unresolvable_private_imports(PROGRAMS_DIR))} unresolvable")
    assert seen >= MIN_PRIVATE_IMPORTS, (
        f"only {seen} private-helper import(s) found under {PROGRAMS_DIR} "
        f"(floor {MIN_PRIVATE_IMPORTS}). The scan lost its subject; every "
        f"other assertion in this file is vacuous until that is repaired."
    )


def test_every_private_helper_import_resolves():
    """The property #1469 reports violated by the group-(d) remedy."""
    missing = unresolvable_private_imports(PROGRAMS_DIR)
    assert not missing, (
        "program(s) import a private helper that is NOT in the tree — the "
        "import raises ModuleNotFoundError the first time that code path "
        "runs, and a unit test that never reaches the path stays green "
        "(vibe-ic#1469):\n"
        + "\n".join(f"    {f}:{n}  ->  {m}" for f, n, m in missing)
        + "\n  Land the helper BEFORE the call sites, not the other way round."
    )


def test_absent_private_helper_is_reported(tmp_path):
    """RED ARM. The resolver must fail when the property is really violated.

    The offender is written with the EXACT line group (d) prescribes, so this
    arm reproduces #1469 rather than a paraphrase of it. It runs on a synthetic
    tree, so it keeps proving the resolver can go red after the real tree is
    repaired — and after whichever atomic helper lands.
    """
    (tmp_path / "offender.py").write_text(
        "from _atomic_artefact import write_json\n"
        "write_json('out.json', {})\n", encoding="utf-8")
    found = unresolvable_private_imports(tmp_path)
    assert found == [("offender.py", 1, "_atomic_artefact")], found

    # The plain-`import` spelling is the same defect and must not slip past.
    (tmp_path / "offender2.py").write_text(
        "import _atomic_output\n", encoding="utf-8")
    assert ("offender2.py", 1, "_atomic_output") in unresolvable_private_imports(tmp_path)


def test_present_private_helper_is_not_reported(tmp_path):
    """CONTROL. Without this the red arm above is satisfied by a resolver that
    reports EVERYTHING, which would pass the same assertion and mean nothing."""
    (tmp_path / "_atomic_artefact.py").write_text(
        "def write_json(p, o):\n    return p\n", encoding="utf-8")
    (tmp_path / "caller.py").write_text(
        "from _atomic_artefact import write_json\n", encoding="utf-8")
    assert unresolvable_private_imports(tmp_path) == []

    # A package-shaped helper resolves too — the convention is not file-only.
    pkg = tmp_path / "_pkg_helper"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "caller2.py").write_text(
        "from _pkg_helper.sub import thing\n", encoding="utf-8")
    assert unresolvable_private_imports(tmp_path) == []


def test_dunder_modules_are_not_treated_as_siblings(tmp_path):
    """``from __future__ import annotations`` opens nearly every program here.

    Counting it as an absent sibling made the first draft report a four-figure
    offender list, which is the shape of a check that would have been disabled
    within a day rather than fixed.
    """
    (tmp_path / "normal.py").write_text(
        "from __future__ import annotations\nimport __main__\n", encoding="utf-8")
    assert unresolvable_private_imports(tmp_path) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
