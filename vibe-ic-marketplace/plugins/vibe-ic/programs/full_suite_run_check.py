from __future__ import annotations


import importlib.util


import sys


from pathlib import Path


from typing import Dict, List, Optional, Sequence, Tuple


_PROGRAMS = Path(__file__).resolve().parent


_LIST_TIERS_TIMEOUT = 30


_LIST_TIERS_POLL = 1


_LIST_TIERS_FLAG = "--list-tiers"


_WATCHDOG = None


def _watchdog():
    """The supervision primitive, loaded the same way every other sibling is.

    A bare `import _watchdog` works when this file is run as a script and dies
    under `spec_from_file_location`, which is how the gates load it.
    """
    global _WATCHDOG
    if _WATCHDOG is None:
        _WATCHDOG = _load_sibling("_watchdog")
    return _WATCHDOG


def _load_sibling(name: str):
    """Import a sibling program by path, however this file was invoked."""
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


def runner_tiers(script: Path) -> Optional[List[str]]:
    """Ask a shell runner which directories it runs. None == it is not one.

    A candidate is interrogated because of what it ANSWERS, never because of
    what it is named:

      * it must resolve to a file inside the plugin;
      * `--list-tiers` must exit 0 within the timeout;
      * every line it prints must be an existing directory in the plugin;
      * it must print at least two of them.

    A hygiene script, a benchmark driver or an invented `some_other_script.sh`
    fails one of those and contributes NO coverage — so it is a subset, which
    is the honest verdict for a command that is not a test runner at all.
    """
    if not script.is_file():
        return None
    plugin = script.parent
    # THE PRECONDITION IS STATIC, AND IT IS NOT A NAME CHECK. Spawning a script
    # because a command string mentioned it is a side effect a VERIFICATION
    # program has no business causing: eleven `.sh` files ship inside this
    # plugin and `hooks/post_install.sh` is one of them. So a candidate must
    # DECLARE the protocol in its own text before it is run. A `run_tests.sh`
    # mutated to drop a tree still declares it — the cheat arm is untouched —
    # and a script that does not implement it is never executed and reads as a
    # subset, which is the safe direction and also the true one.
    try:
        if _LIST_TIERS_FLAG not in script.read_text(encoding="utf-8", errors="replace"):
            return None
    except OSError:                                         # pragma: no cover
        return None
    # SUPERVISED. The script is chosen at RUNTIME, so what it launches cannot be
    # read from here — which is exactly `loop_watchdog_compliance_check`'s class
    # (c): an opaque runner whose contents no AST pass can inspect. The rule it
    # enforces is that such a launch goes through the one supervision primitive
    # this tree has, so its discipline is the same as every other sub-process's
    # and its outcome is a VALUE rather than an exception thrown past a child.
    #
    # ONE number is set rather than defaulted: the STALL GRACE, because the
    # 30-minute default would let a silent listing sit for half an hour. That
    # grace is the whole control, and it is the one this file's own
    # `test_a_hanging_candidate_is_killed_at_the_deadline` exercises -- its
    # planted `sleep 600` emits nothing and burns no CPU, so the grace is what
    # stops it.
    #
    # THE HARD CEILING WAS SET TO THE SAME NUMBER AND IS NOW GONE. Beside an
    # equal grace it could add exactly one behaviour: killing a listing that
    # was still PRINTING at 30 s, which is a slow host reported as "this
    # candidate is not a runner" -- a false negative manufactured by the
    # machine. `_watchdog`'s own contract reserves that parameter for a
    # pathological non-idle loop, and this is not one.
    # THE ORPHAN GAP RECORDED HERE IS CLOSED. This comment used to read
    # "neither this call nor the timeout-bounded `subprocess` launch it
    # replaces kills a process GROUP (`_watchdog._default_kill` is
    # `proc.kill()`), so a script that backgrounds work still orphans it."
    # That was true and it was measurable from outside: this file's own
    # `test_a_hanging_candidate_is_killed_at_the_deadline` plants `sleep 600`
    # behind a 3 s deadline, the deadline killed `bash` and left `sleep`
    # running, and the per-file landing driver then reported the WHOLE file as
    # "pytest exited with unfinished live descendants" -- no verdict at all.
    # `_watchdog` now launches with `start_new_session=True` and signals the
    # child's process GROUP, so the deadline reaches what the script launched.
    proc = _watchdog().run_supervised(
        ["bash", str(script), _LIST_TIERS_FLAG],
        cwd=str(plugin), merge_stderr=False, output_progress=True,
        stall_grace_s=_LIST_TIERS_TIMEOUT,
        poll_s=_LIST_TIERS_POLL,
    )
    # Every non-zero outcome — a natural failure, a launch error (rc 127) and a
    # stall kill (199) — reads the same here as it did before: this candidate is
    # not a runner. That is the safe direction and also the true one.
    if proc.rc != 0:
        return None
    lines = [ln.strip() for ln in proc.out.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    if not all((plugin / ln).is_dir() for ln in lines):
        return None
    return lines
