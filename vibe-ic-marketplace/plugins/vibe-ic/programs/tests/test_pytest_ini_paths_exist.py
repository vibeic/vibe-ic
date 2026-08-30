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

AND IT PINNED ONE CONFIG WHILE TWO SHIP
---------------------------------------
`_INI` was a module-level constant naming `pytest.ini`, so the guard was itself
an instance of the shape it hunts: a rule stated over a population defined by a
spelling. The repository ships a SECOND pytest configuration —
`vibe-ic-marketplace/pyproject.toml`, `[tool.pytest.ini_options]` — and every
one of its four `testpaths` named `plugins/vibe-ic-d/…`, a directory that has
never existed here. MEASURED on `612b5a94d` from `vibe-ic-marketplace/`:

    as shipped     no tests collected, 1 error in 0.07s
    repaired       42894 tests collected in 82s

Worse than the silent zero this file was written about: with no testpath
resolving, pytest falls back to the rootdir and dies in
`plugins/vibe-ic/conftest.py` on `pytest_plugins` in a non-top-level conftest.
Both configs are now subjects, and the record for each is its own `_Config`
below — the rule did not change, only the population it is asked over.

TOML IS PARSED, INI IS LINE-READ, AND NEITHER IS GUESSED. `tomllib` is stdlib
from 3.11 and `tomli` is pytest's own dependency below that, so the parser is
present wherever this suite can run at all; there is no hand-rolled TOML here.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pytest

try:                                    # stdlib from 3.11
    import tomllib as _toml
except ModuleNotFoundError:             # pytest's own dependency below that
    import tomli as _toml               # type: ignore[no-redef]

_PLUGIN = Path(__file__).resolve().parents[2]
_MARKETPLACE = _PLUGIN.parents[1]


class _Config(NamedTuple):
    """One pytest configuration file, and the root its paths are relative to."""
    label: str
    path: Path
    root: Path


#: EVERY pytest configuration this repository ships. A config absent from this
#: tuple is a config nothing holds to the rule, which is how
#: `vibe-ic-marketplace/pyproject.toml` carried four never-existing testpaths
#: through every green run. `test_every_shipped_pytest_config_is_a_subject`
#: re-derives the tuple from the tree so a third one cannot be added silently.
_CONFIGS = (
    _Config("plugin pytest.ini", _PLUGIN / "pytest.ini", _PLUGIN),
    _Config("marketplace pyproject.toml",
            _MARKETPLACE / "pyproject.toml", _MARKETPLACE),
)

#: Kept: the module used to expose these two names and a reader may still grep
#: for them. They now mean "the FIRST config", not "the only one".
_INI = _CONFIGS[0].path

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


def _ini_text(cfg: _Config = None) -> str:
    cfg = cfg or _CONFIGS[0]
    assert cfg.path.is_file(), f"{cfg.label} not found at {cfg.path}"
    return cfg.path.read_text()


def _testpaths(cfg: _Config = None) -> list:
    """`testpaths` as the config's own format declares it.

    The INI is line-read because that is what pytest's `configparser` sees; the
    TOML is parsed, because `testpaths` there is a real array and a regex over
    it would be a second, weaker parser of a format that already has one.
    """
    cfg = cfg or _CONFIGS[0]
    if cfg.path.suffix == ".toml":
        data = _toml.loads(_ini_text(cfg))
        ini = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
        val = ini.get("testpaths", [])
        return list(val) if isinstance(val, list) else val.split()
    out = []
    for line in _ini_text(cfg).splitlines():
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


_IDS = [c.label for c in _CONFIGS]


@pytest.mark.parametrize("cfg", _CONFIGS, ids=_IDS)
def test_every_testpaths_entry_exists_and_holds_tests(cfg):
    """`testpaths` naming a missing directory collects nothing, silently."""
    paths = _testpaths(cfg)
    assert paths, (
        f"{cfg.label} declares no testpaths — the suite has no population")
    for rel in paths:
        target = cfg.root / rel
        assert target.is_dir(), (
            f"{cfg.label} testpaths names {rel!r}, which does not exist under "
            f"{cfg.root}. pytest does not error on this — it collects nothing "
            f"from the entry, and where NO entry resolves it falls back to the "
            f"rootdir, which is how this file's own sibling config produced "
            f"`no tests collected, 1 error` for every run that ever used it.")
        assert next(target.rglob("test_*.py"), None) is not None, (
            f"{cfg.label} testpaths entry {rel!r} exists but contains no "
            f"test_*.py, so a bare run would report a pass over an empty "
            f"population")


@pytest.mark.parametrize("cfg", _CONFIGS, ids=_IDS)
def test_no_directory_named_anywhere_in_the_config_is_missing(cfg):
    """Including in the comments — that is exactly where the defect lived."""
    missing = sorted(d for d in dir_references(_ini_text(cfg))
                     if not (cfg.root / d).is_dir())
    assert not missing, (
        f"{cfg.label} names director(ies) that do not exist under {cfg.root}: "
        f"{missing}. In `testpaths` that collects nothing; in a comment it is "
        "an instruction a human will follow, and following it produces "
        "`no tests collected` rather than an error.")


def test_every_shipped_pytest_config_is_a_subject():
    """The roster of configs, re-derived from the tree rather than trusted.

    A guard parameterised over a hand list is the same defect one level up: the
    list goes stale silently, and in the direction that still prints PASS. So
    the tree is searched for anything pytest would read as a configuration, and
    a file that is not a subject is a red here rather than a gap nobody sees.
    """
    found = set()
    for name in ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"):
        for path in _MARKETPLACE.parent.rglob(name):
            if any(part in {".git", "node_modules", "__pycache__",
                            "benchmark-data", ".venv"}
                   for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "[pytest]" in text or "[tool.pytest" in text or \
                    "[tool:pytest]" in text:
                found.add(path.resolve())
    known = {c.path.resolve() for c in _CONFIGS}
    unheld = sorted(str(p) for p in found - known)
    assert not unheld, (
        f"pytest configuration file(s) that no case here is asked over: "
        f"{unheld}. Every directory a pytest config names must resolve; a "
        f"config outside `_CONFIGS` is held to nothing, which is exactly how "
        f"the marketplace pyproject.toml shipped four testpaths that had never "
        f"existed.")
    assert known <= found, (
        f"a config in `_CONFIGS` is no longer a pytest config in the tree: "
        f"{sorted(str(p) for p in known - found)}")


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
