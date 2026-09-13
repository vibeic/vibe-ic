#!/usr/bin/env python3
"""#2230 — a container guard that asks RUNNING and never asks WHICH IMAGE.

THE DEFECT, MEASURED
====================
`vibeic-eda` is a bare, shared, guessable container name. Six test modules
carried their own copy of

    docker inspect -f {{.State.Running}} vibeic-eda   ->  "true"  ->  guard OK

and a seventh (`test_v0_2_97_issue472_473_476_phase2.py`) handed that name to
the runner with no container guard at all. Running is not usable: the answer is
`True` for whatever process reached the name first.

MEASURED 2026-09-10, 8HD-8, clean main `9c653d47f`, against a container named
`vibeic-eda` started 2026-09-05 on `sha256:06537f7e…` while the pin is
`sha256:89a8fd72…`:

    7 files RED, 10 test ids, ONE cause — and none of them about the tree.

The attach check one layer down (`_eda_pin`, #2076) refuses correctly; the
guard had already committed the test to a red instead of the skip an ABSENT
container has always got.

WHAT THESE TESTS PIN, AND WHY THEY CANNOT PASS BY ACCIDENT
==========================================================
Every fact here is arranged, never observed: docker is faked present, the
container is faked RUNNING, and the digest is faked — matching in one direction
and mismatching in the other. So the verdict is a property of the guard, not of
whichever container happens to hold the name on the machine running the suite.
That is the whole point of the issue, and a test that read the host would
inherit the defect it is pinning.

The mismatch direction is the one that fails on the unfixed tree: presence-only
guards answer True there. The MATCH direction is asserted too — a guard that
refused everything would satisfy the first half and disable seven files.

chip-AGNOSTIC: container identity only.
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_PROGRAMS = _TESTS_DIR.parent
for _p in (str(_PROGRAMS), str(_TESTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _eda_pin as _pin  # noqa: E402

#: The digest of some other build. Any value that is not the pin will do; it is
#: written as an obvious fake so nobody reads it as a real image.
_OTHER = "sha256:" + "de" * 32

#: The seven files the issue names, and the module-level flag each one derives
#: from its guard. The flag is what a `skipif` consumes, so it is the thing
#: whose value decides RED-or-SKIP.
_GUARDED = [
    # REMOVED 2026-09-14. `980e7d877` ("run firmware staging verification in
    # the selected runtime") deleted this module's
    # `_HAVE_PINNED_CONTAINER = _cg.container_usable(_ORACLE_CONTAINER)` and
    # the skipif that consumed it: it no longer reaches for a SECOND named
    # container, it runs in the runtime it was invoked in and skips on tool
    # availability instead. There is no container guard left here to audit,
    # and naming one that does not exist made this file raise
    # AttributeError twice rather than checking the six that do.
    # Do not re-add without first confirming the module grew a guard back.
    ("test_v1_0_78_issue729_ppa_area_threshold", "_HAVE_CONTAINER"),
    ("test_v1_0_80_issue739_ppa_unreachable_target_escape", "_HAVE_CONTAINER"),
    ("test_v1_0_83_issue756_ppa_disjunctive_clauses", "_HAVE_CONTAINER"),
    ("test_v1_0_85_issue768_ppa_reachability_submission_independent",
     "_HAVE_CONTAINER"),
    ("test_v1_0_85_issue769_ppa_generic_meets_target", "_HAVE_CONTAINER"),
    # This one evaluates its guard inside the decorator rather than storing a
    # flag, so the callable IS what the `skipif` consumes.
    ("test_v1_0_86_issue771_ppa_metric_window", "_container_up"),
]


def _arrange(monkeypatch, *, digest: str) -> None:
    """A host that HAS docker, HAS the container RUNNING, on image `digest`.

    Both halves are arranged because the two guard generations read different
    facts: the unfixed one reads `docker inspect .State.Running`, the fixed one
    reads the digest through `_eda_pin`. Arranging only one of them would let a
    guard pass for the wrong reason.
    """
    real_which = shutil.which

    def _which(name, *a, **kw):
        return "/usr/bin/docker" if name == "docker" else real_which(name, *a, **kw)

    real_run = subprocess.run

    def _run(argv, *a, **kw):
        if isinstance(argv, (list, tuple)) and argv and argv[0] == "docker":
            return subprocess.CompletedProcess(list(argv), 0, "true\n", "")
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(shutil, "which", _which)
    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setattr(_pin, "container_image_digest",
                        lambda _container: (digest, ""))


def _decided(mod, flag):
    """What the module's `skipif` actually consumes — a stored flag, or the
    predicate the decorator calls inline. Both are decided at import."""
    value = getattr(mod, flag)
    return value() if callable(value) else value


# ════════════════════════════════════════════════════════════════════════════
# (1) the predicate itself
# ════════════════════════════════════════════════════════════════════════════
def test_a_running_container_on_another_image_is_not_usable(monkeypatch):
    """THE ISSUE, in one line: RUNNING is not the question."""
    import _container_guard as cg
    _arrange(monkeypatch, digest=_OTHER)
    assert cg.container_usable("vibeic-eda") is False


def test_a_running_container_on_the_pinned_image_is_usable(monkeypatch):
    """The guard must still say YES, or it has disabled seven files."""
    import _container_guard as cg
    _arrange(monkeypatch, digest=_pin.IMAGE_DIGEST)
    assert cg.container_usable("vibeic-eda") is True


def test_an_unreadable_container_is_not_usable(monkeypatch):
    """Absent / undescribable is not-here, exactly as it always was."""
    import _container_guard as cg
    _arrange(monkeypatch, digest=_OTHER)
    monkeypatch.setattr(_pin, "container_image_digest",
                        lambda _c: (None, "no such container"))
    assert cg.container_usable("vibeic-eda") is False


def test_no_docker_client_is_not_usable(monkeypatch):
    import _container_guard as cg
    monkeypatch.setattr(shutil, "which", lambda *a, **kw: None)
    assert cg.container_usable("vibeic-eda") is False


# ════════════════════════════════════════════════════════════════════════════
# (2) every file the issue names, through its OWN module-level guard
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("mod_name,flag", _GUARDED,
                         ids=[m for m, _ in _GUARDED])
def test_each_named_file_skips_when_the_container_holds_other_bytes(
        monkeypatch, mod_name, flag):
    """Re-import each module with a RUNNING container on the WRONG image.

    Reloaded rather than read, because the question is what the module DECIDES
    at import time — the value a `skipif` will consume. A grep for the
    predicate's name would pass on a file that imported it and never called it.
    """
    _arrange(monkeypatch, digest=_OTHER)
    mod = importlib.reload(importlib.import_module(mod_name))
    assert _decided(mod, flag) is False, (
        f"{mod_name}.{flag} vouched for a container running {_OTHER} while the "
        f"pin is {_pin.IMAGE_DIGEST} — presence answered a question about "
        f"identity, and the tests behind this flag will RED about the host")


@pytest.mark.parametrize("mod_name,flag", _GUARDED,
                         ids=[m for m, _ in _GUARDED])
def test_each_named_file_still_runs_on_the_pinned_image(
        monkeypatch, mod_name, flag):
    """The other direction: the guard must not have become a blanket skip."""
    _arrange(monkeypatch, digest=_pin.IMAGE_DIGEST)
    mod = importlib.reload(importlib.import_module(mod_name))
    assert _decided(mod, flag) is True, (
        f"{mod_name}.{flag} refused a container that IS the pinned image — a "
        f"guard that refuses everything disables the file it guards")


# ════════════════════════════════════════════════════════════════════════════
# (3) THE ANCHOR — red on the unfixed tree by CONTENT, importing nothing of mine
# ════════════════════════════════════════════════════════════════════════════
#: The literal a presence-only guard passes to `docker inspect`. Matched as a
#: whole STRING CONSTANT through the AST, never by grep: this file and
#: `_container_guard` both quote it inside prose, and a substring search would
#: find its own documentation and call it a defect. An argv element is a
#: constant equal to the token; a docstring never is.
_RUNNING_FORMAT = "{{.State.Running}}"

#: What a guard must consult to be about identity. Either name is enough — the
#: predicate itself, or the shared helper that is nothing but the predicate.
_IDENTITY_NAMES = ("container_matches_pin", "container_usable",
                   "container_pin_state", "container_attach_refusal")


def _presence_only_guards() -> list[str]:
    """Files asking docker whether a container is RUNNING and nothing else."""
    import ast
    out: list[str] = []
    for path in sorted(_TESTS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:                             # pragma: no cover
            continue
        asks_running = any(
            isinstance(n, ast.Constant) and n.value == _RUNNING_FORMAT
            for n in ast.walk(tree))
        if not asks_running:
            continue
        if any(name in text for name in _IDENTITY_NAMES):
            continue
        out.append(path.name)
    return out


def test_no_test_module_guards_a_container_on_running_alone():
    """#2230, as a rule the tree can be held to.

    This is the assertion that fails on the unfixed tree WITHOUT importing
    anything this change adds — six files ask `docker inspect` for
    `.State.Running` and consult no identity predicate at all. It is here
    because the other tests in this file reach the defect through the modules
    they fixed, and a control arm that dies on an ImportError has measured the
    shape of my patch rather than the behaviour of the tree.

    A file may still ask about RUNNING. It may not do so as its ONLY question.
    """
    offenders = _presence_only_guards()
    assert offenders == [], (
        "presence-only container guard(s): " + ", ".join(offenders) +
        " — each asks docker whether SOMETHING is running under a shared, "
        "guessable name and never whether it is the pinned image, so a stale "
        "container on a multi-lane host turns their live-path tests into reds "
        "about the machine (#2230)")
