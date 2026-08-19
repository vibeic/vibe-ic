#!/usr/bin/env python3
"""A matrix test may not make a path APPEAR in the tree it reads.

WHY THIS EXISTS
---------------
`suite_write_guard` already refuses a pytest session that LEAVES a path behind:
it compares `git status --porcelain` at the end of the session against the
start. That catches a leak. It cannot catch a write that is undone before the
session ends, because it samples once — and a file that exists for only the
length of one subprocess is still, for that whole window, an untracked path in
a shared work tree that EVERY OTHER READER can see.

MEASURED, on origin/main 74ac9fa78, in the pinned container image.
`test_matrix_d2_falsifiable.test_d2_a_real_crash_is_disclosed_by_the_consumer_not_guessed`
wrote its four probe programs into the live `programs/` directory, ran each
through the real consumer, and removed them again. Its own session reported

    [PASS] suite_write_guard: this pytest session wrote nothing
           `git status --porcelain` would show.

while a `git status` poller running beside it recorded all four:

    ?? vibe-ic-marketplace/plugins/vibe-ic/programs/_d2_crash_probe_atexit_after_traceback.py
    ?? vibe-ic-marketplace/plugins/vibe-ic/programs/_d2_crash_probe_multiline_message.py
    ?? vibe-ic-marketplace/plugins/vibe-ic/programs/_d2_crash_probe_plain.py
    ?? vibe-ic-marketplace/plugins/vibe-ic/programs/_d2_crash_probe_syntax_error.py

and a CONCURRENT module paid for it. `test_matrix_d4_criteria_match.py`, run in
another lane against the same tree, exited rc=1 with `71 passed` and not one
failed test, on

    [FAIL] suite_write_guard: this pytest session WROTE INTO THE TREE — 1
    path(s) that `git add -A` would ship:
        ??  .../programs/_d2_crash_probe_multiline_message.py   (appeared)

That is a red on a module that did nothing, from a change nobody made — and it
is scheduling-dependent, so it appears and disappears between runs of an
identical tree. This suite already names that disease and built `--basetemp`
isolation to end it (see `_run_one_module_outcome` in
`test_matrix_63x8_coverage.py`: "a wandering FileNotFoundError in whichever
module lost — a red that belongs to no change and does not reproduce"). It came
back through a different door.

WHAT THIS GUARD MEASURES
------------------------
It watches the REAL `flow_compliance_check.PROGRAMS_DIR` while it drives the
REAL test function, and refuses any name that appears there.

It is a SAMPLER, so it carries the sampler's risk: a window shorter than the
poll interval is a false green. That risk is retired by a CONTROL that is not a
description of the subject's window but a REPRODUCTION of it — the control runs
the same `_check_program_exit_zero` over the same probe source through the same
dynamic dispatch, with `PROGRAMS_DIR` pointed at a watched scratch directory.
If the watcher cannot see THAT write, this module fails as unfit to judge
rather than passing. The control and the subject differ in exactly one thing:
the address the probe is written to.
"""

from __future__ import annotations

import inspect
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Set

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
for _p in (str(_TESTS_DIR), str(_TESTS_DIR.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import flow_compliance_check as FCC        # noqa: E402
import test_matrix_d2_falsifiable as D2    # noqa: E402

#: Fast enough that the subject's window — a Python interpreter spawn, which is
#: tens of milliseconds at the very least — is sampled many times over. The
#: control proves this empirically for the machine actually running the suite,
#: so this number is never load-bearing on its own.
_POLL_S = 0.0005


class _AppearanceWatcher:
    """Record every top-level name that appears in *directory* while running.

    Top-level only, deliberately: `__pycache__` is an existing entry and the
    `.pyc` files land INSIDE it, so bytecode caching — which the repository
    already classes as a regenerable artefact — cannot make this red.
    """

    def __init__(self, directory: Path, poll_s: float = _POLL_S) -> None:
        self._directory = directory
        self._poll_s = poll_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._baseline: Set[str] = set()
        self.appeared: Set[str] = set()
        self.samples = 0

    def _listdir(self) -> Set[str]:
        try:
            return set(os.listdir(self._directory))
        except OSError:
            return set(self._baseline)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.samples += 1
            self.appeared |= self._listdir() - self._baseline
            time.sleep(self._poll_s)

    def __enter__(self) -> "_AppearanceWatcher":
        self._baseline = self._listdir()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        # One final sample AFTER the subject finished: a name still present at
        # this point is a leak, and a leak must never be reported as "nothing
        # appeared" just because every poll happened to land before the write.
        self.appeared |= self._listdir() - self._baseline


def _drive(func: Callable, shape: str, tmp_path: Path) -> None:
    """Call the real test function with whichever fixtures it declares.

    Resolved from the live signature so that this guard states its verdict on
    the SUBJECT and never on its own call convention: on a tree where the
    subject takes no `monkeypatch`, this still runs it and still measures where
    it writes, instead of dying with a `TypeError` that proves nothing.
    """
    params = inspect.signature(func).parameters
    kwargs = {}
    if "shape" in params:
        kwargs["shape"] = shape
    if "tmp_path" in params:
        kwargs["tmp_path"] = tmp_path
    patcher = None
    if "monkeypatch" in params:
        patcher = pytest.MonkeyPatch()
        kwargs["monkeypatch"] = patcher
    try:
        func(**kwargs)
    finally:
        if patcher is not None:
            patcher.undo()


def test_the_watcher_can_see_a_write_of_the_subjects_own_shape(tmp_path):
    """CONTROL. Not a claim about the subject — a reproduction of its window.

    Same probe source, same `_check_program_exit_zero`, same
    `_resolve_program_cmd` dispatch, same subprocess. The only difference is
    that `PROGRAMS_DIR` points at a watched scratch directory, so the write
    this guard exists to catch happens where catching it proves nothing about
    the repository — and everything about the watcher.
    """
    scratch = tmp_path / "programs"
    scratch.mkdir()
    project = tmp_path.joinpath(*(["c" * 40] * 10))
    project.mkdir(parents=True)
    src, _overflows = D2._D2_CRASH_SHAPES["plain"]
    probe = scratch / "_d2_crash_probe_control.py"

    with pytest.MonkeyPatch().context() as patcher:
        patcher.setattr(FCC, "PROGRAMS_DIR", scratch)
        with _AppearanceWatcher(scratch) as watcher:
            probe.write_text(src, encoding="utf-8")
            try:
                FCC._check_program_exit_zero(project, f"{probe.stem} {project}")
            finally:
                probe.unlink(missing_ok=True)

    assert watcher.samples > 0, (
        "the watcher thread never sampled, so this module cannot judge "
        "anything and its other test is vacuous")
    assert probe.name in watcher.appeared, (
        f"the watcher took {watcher.samples} sample(s) across a real "
        f"`_check_program_exit_zero` window and did not see {probe.name!r} "
        f"appear. The sampler is unfit to judge where the subject writes, so "
        f"the guard beside this one would report a green it did not measure. "
        f"Saw: {sorted(watcher.appeared)!r}")


@pytest.mark.parametrize("shape", sorted(D2._D2_CRASH_SHAPES))
def test_the_crash_probe_is_not_written_into_the_tree_under_test(
        shape, tmp_path):
    """The subject may not make any name appear in the live `programs/` dir.

    The probe has to be reachable by NAME through `_resolve_program_cmd`,
    which is the whole point of driving the real consumer — so the fix is not
    to stop resolving it, it is to resolve it somewhere that is not the tree
    every other reader is watching.
    """
    programs = Path(FCC.PROGRAMS_DIR)
    with _AppearanceWatcher(programs) as watcher:
        _drive(D2.test_d2_a_real_crash_is_disclosed_by_the_consumer_not_guessed,
               shape, tmp_path)

    assert watcher.samples > 0, (
        "the watcher thread never sampled; this cell measured nothing")
    assert not watcher.appeared, (
        f"{shape}: the d2 crash-probe cell made {sorted(watcher.appeared)!r} "
        f"appear in {programs} — the tree this suite READS. It is undone "
        f"before the session ends, so this session's own `suite_write_guard` "
        f"reports 'wrote nothing', and every CONCURRENT reader of the same "
        f"tree sees an untracked path and fails on it. MEASURED: "
        f"test_matrix_d4_criteria_match.py exited rc=1 with 71 passed and no "
        f"failed test, on `suite_write_guard: ... _d2_crash_probe_"
        f"multiline_message.py (appeared)`. Point "
        f"`flow_compliance_check.PROGRAMS_DIR` at a tmp_path directory for "
        f"the call; the consumer reads that global at resolve time, so the "
        f"real dispatch is kept and only the address moves.")
