"""A directory named in `pytest.ini` that does not exist is a silent zero.

`pytest.ini` carried this since v1.0.0 (`86cacb4b`), unchanged:

    # HARD RULE: the full suite is BOTH test trees. programs/tests/ holds unit
    # tests; tests/ holds the integration/regression gates ... never
    # `pytest programs/tests/` alone (that misses the gates).
    testpaths = programs/tests

`plugins/vibe-ic/tests` has NEVER been tracked in this repository, and the
gates the comment says live there are under `programs/tests` with everything
else. So the rule instructed a command shape that cannot work — and pytest's
behaviour on a missing path is the dangerous half. It does not fail usefully;
it collects nothing. Measured on `a38902d16`:

    pytest                        ->  32700 tests collected
    pytest programs/tests tests   ->  no tests collected in 0.11s

A reader obeying the HARD RULE got a clean-looking ZERO. That is the shape this
suite hunts everywhere else — a verdict over an empty population — sitting in
the file that decides what the population IS.

WHAT THIS PINS, AND WHAT IT DELIBERATELY DOES NOT
-------------------------------------------------
Every DIRECTORY REFERENCE in `pytest.ini` must resolve, whether it is in
`testpaths` or in prose telling a human what to run. A directory reference is a
token ending in `/` — that is what the defect looked like, and it is what
distinguishes an instruction from ordinary prose. `integration/regression` and
`and/or` are not directory references and are not checked; requiring them to
exist would make the guard unusable in the only file it guards.

It does NOT run a full collection to prove the suite is non-empty. Bare
collection takes ~52 s here, and `ci_harness_timeout_ceiling_check` (BLOCKING)
permits any one bounded call at most `180 // 3` = 60 s — a 1.15x margin, which
is the squeeze that gate exists to refuse. The structural check below
(`testpaths` resolves AND contains `test_*.py`) answers the same question
without a subprocess.
"""
from __future__ import annotations

import re
from pathlib import Path

_PLUGIN = Path(__file__).resolve().parents[2]
_INI = _PLUGIN / "pytest.ini"

#: A DIRECTORY REFERENCE: path-shaped, with a TERMINAL `/`. The trailing slash
#: is the whole discrimination — `tests/` in the v1.0.0 comment was an
#: instruction to run a directory; `integration/regression` in the same
#: sentence was prose.
#:
#: The lookahead is load-bearing and I got it wrong first: without it,
#: `(?:[\w.-]+/)+` happily matches the `integration/` PREFIX of
#: `integration/regression`, so every slash in prose became a missing
#: directory. The slash must be the last character of the token.
#: The lookbehind keeps `--import-mode=importlib` and `https://…` out.
_DIR_REF = re.compile(r"(?<![\w/.:-])((?:[\w.-]+/)+)(?![\w.-])")


def _ini_text() -> str:
    assert _INI.is_file(), f"pytest.ini not found at {_INI}"
    return _INI.read_text()


def _testpaths() -> list:
    out = []
    for line in _ini_text().splitlines():
        s = line.strip()
        if s.startswith("#") or "=" not in s:
            continue
        key, _, val = s.partition("=")
        if key.strip() == "testpaths":
            out += val.split()
    return out


def dir_references(text: str) -> set:
    """Every directory reference in `text`, comments INCLUDED.

    Deliberately does not skip comments: the v1.0.0 defect was in a comment,
    while `testpaths` on the line below it was correct.
    """
    return {m.group(1).rstrip("/") for m in _DIR_REF.finditer(text)
            if "://" not in m.group(0)}


def test_every_testpaths_entry_exists_and_holds_tests():
    """`testpaths` naming a missing directory collects nothing, silently."""
    paths = _testpaths()
    assert paths, "pytest.ini declares no testpaths — the suite has no population"
    for rel in paths:
        target = _PLUGIN / rel
        assert target.is_dir(), (
            f"pytest.ini testpaths names {rel!r}, which does not exist under "
            f"{_PLUGIN}. pytest does not error on this — it collects nothing.")
        assert next(target.rglob("test_*.py"), None) is not None, (
            f"testpaths entry {rel!r} exists but contains no test_*.py, so a "
            f"bare run would report a pass over an empty population")


def test_no_directory_named_anywhere_in_pytest_ini_is_missing():
    """Including in the comments — that is exactly where the defect lived."""
    missing = sorted(d for d in dir_references(_ini_text())
                     if not (_PLUGIN / d).is_dir())
    assert not missing, (
        f"pytest.ini names director(ies) that do not exist under {_PLUGIN}: "
        f"{missing}. In `testpaths` that collects nothing; in a comment it is "
        "an instruction a human will follow, and following it produces "
        "`no tests collected` rather than an error.")


# ── controls ──────────────────────────────────────────────────────────


def test_PAIRED_GUARD_the_v1_0_0_shape_is_CAUGHT(tmp_path):
    """Correct `testpaths`, lying comment — the exact shape that shipped.

    Without this, the test above could be green because the regex matched
    nothing rather than because every directory resolves.
    """
    (tmp_path / "programs" / "tests").mkdir(parents=True)
    ini = ("[pytest]\n"
           "# HARD RULE: the full suite is BOTH test trees. programs/tests/\n"
           "# holds unit tests; tests/ holds the integration/regression gates.\n"
           "testpaths = programs/tests\n")

    refs = dir_references(ini)
    assert "programs/tests" in refs, refs
    assert "tests" in refs, f"the bare `tests/` was not seen as a directory: {refs}"

    missing = sorted(d for d in refs if not (tmp_path / d).is_dir())
    assert missing == ["tests"], missing


def test_NEGATIVE_CONTROL_prose_and_flags_are_not_directory_references():
    """Proof this is a check, not a ban on writing a slash in a comment.

    `integration/regression` is the live example: it sits in the very sentence
    the defect was in, and requiring it to exist would force the fix to mangle
    the explanation rather than correct the instruction.
    """
    text = ("addopts = --import-mode=importlib\n"
            "# the integration/regression gates, and/or the unit tests\n"
            "# see https://docs.pytest.org/en/stable/reference.html\n")
    assert dir_references(text) == set(), (
        f"prose, a flag or a URL was read as a directory reference: "
        f"{dir_references(text)}")
