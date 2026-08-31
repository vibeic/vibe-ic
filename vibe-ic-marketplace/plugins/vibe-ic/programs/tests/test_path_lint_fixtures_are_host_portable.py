#!/usr/bin/env python3
"""Shipped path-lint fixtures name no one's home directory (R1 pin).

`shipped_path_portability_check` R1 refuses a personal home path anywhere in
shipped source, for the same reason benchmark-data PR#4 was refused: a literal
`/home/<someone>/...` pins ONE machine's layout into a tree everybody else
clones, and it reads as a real value rather than as an example.

The two path-lint fixtures below each needed a path that is genuinely OUTSIDE
the project root, and each reached for a fictional home to get one. They do not
need a home directory for that — a sibling directory of the test's own
`tmp_path`, built for real, is outside containment on every host. That is what
R1's remedy means by "resolve from the caller's project argument".

The first test is the narrow RED-without/GREEN-with pin on those two files; the
second is the general sweep, so the next fixture that reaches for a home dir is
caught here and not only in the hygiene shard.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import shipped_path_portability_check as P  # noqa: E402

PLUGIN = PROGRAMS.parent
TESTS = Path(__file__).resolve().parent

#: The two fixtures the v1.14.71 hygiene shard named.
_THE_TWO = (
    "test_path_lint_accepts_project_staged_pdk.py",
    "test_path_lint_staged_verify_uses_real_root.py",
)


def _scan(path: Path):
    return P.scan_file(path, path.relative_to(PLUGIN))


def test_the_two_named_path_lint_fixtures_carry_no_personal_home() -> None:
    offenders = {}
    for name in _THE_TWO:
        f = TESTS / name
        assert f.is_file(), f"{name} moved — repoint this pin"
        hits = _scan(f)
        if hits:
            offenders[name] = [(h.line, h.path) for h in hits]
    assert offenders == {}, f"personal home path in shipped source: {offenders}"


def test_no_shipped_test_fixture_names_a_personal_home() -> None:
    """General sweep over the shipped test tree, not just the two known ones."""
    offenders = {}
    for f in sorted(TESTS.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        hits = _scan(f)
        if hits:
            offenders[f.name] = [(h.line, h.path) for h in hits]
    assert offenders == {}, (
        "personal home path(s) in shipped test source — resolve from tmp_path, "
        f"an env var, or the project argument: {offenders}")


def test_the_fixtures_still_test_a_path_outside_containment() -> None:
    """The portable rewrite must not have made the path project-INTERNAL.

    A fixture that silences R1 by moving the foreign path inside the project
    root would leave both files green and the rung they pin untested, so this
    asserts the replacement path is still built beside the project, not in it.
    """
    for name in _THE_TWO:
        src = (TESTS / name).read_text()
        assert "outside_the_project" in src, (
            f"{name} no longer builds a path outside the project root")
