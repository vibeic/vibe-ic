#!/usr/bin/env python3
"""Does anything notice when a gate is made unable to fail?

The flow reads a gate's EXIT CODE.  A test that imports the module and calls
``audit()`` measures the finding logic and leaves the verdict-to-exit-code
mapping unmeasured — an audit that correctly finds the defect, a ``main`` that
does not return it, and a flow that reads PASS.  Five of the 127 gate programs
the flow names were in exactly that state, and every one of them had tests.

"A test mentions this program" is not the question.  "Can this program be made
unable to fail without anything reddening" is.  This probe asks the second one
the only way it can be answered: by doing it.

    neuter  -> the entry point returns 0 before it does anything
    run     -> every test file that names the program
    restore -> byte-for-byte, verified, in a finally
    report  -> CAUGHT (something reddened) or SILENT (nothing did)

A static proxy was measured against this probe over all 127 programs and
rejected: it produced 2 false comforts and 17 false alarms.  A guard that says
"protected" about a gate that is not is the very failure this repo is trying to
retire, so the expensive answer is the one that ships.

THE SHIPPED TREE IS NEVER MUTATED (measured 2026-08-04)
=======================================================
It used to be, by default, in the API rather than in the CLI: `main()` copied
the tree and `probe()` did not, so `PROBE.probe(name)` — which is how the
regression test drives this — neutered the SHIPPED gate.  Twice in one parallel
session a run was killed inside that window and left
`hold_area_budget_check.py` / `hold_corner_coverage_check.py` carrying an
injected early return beside a `.probe-orig` sidecar.  A neutered gate exits 0,
which the flow reads as PASS, so every later reader of that checkout was
measuring a gate that could no longer fail.  (The injected line is written out
once, in `_ENTRIES` below, and quoted nowhere else in this file:
`neutered_gate_tree_check` matches it as a WHOLE line, and prose that happened
to wrap onto exactly that line would become a permanent finding.)

The `finally` below is correct and was reached in neither case, because a
`finally` does not run on `SIGKILL`.  Reproduced deliberately: kill the probe
between `write_text(mutated)` and pytest and the tree is left in exactly the
state that was found by hand.

So the mutation moved OUT of the tree entirely.  Both entry points now probe a
disposable COPY, and there is no flag that mutates the shipped file — the
alternative, "keep `--in-place` and make the restore crash-safe", cannot be
made to work: every mechanism that could restore the file is code the killed
process would have had to run.  What is left is the cost of the copy, measured
at ~1 s once per process, against a failure mode that is silent, green, and
compounds one injected line per killed run.

Exit codes: 0 CAUGHT, 1 SILENT, 2 could not probe (no entry point, no test).
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import _crash_safe_scratch as _scratch

PROGRAMS = Path(__file__).resolve().parent
TESTS = PROGRAMS / "tests"

#: Scratch prefix for the disposable copies.  Shared with the reaper below, so
#: a copy a killed run left in /tmp is removed by the next run rather than
#: accumulating — the same self-healing contract the worktree probe uses.
_SCRATCH_PREFIX = "gate_cli_probe_"

#: ONE copy per process, made lazily.  A per-call copy would multiply the only
#: real cost of the copy-based design by the number of programs probed.
_DISPOSABLE: Optional[Path] = None

#: Entry shapes in this tree, in the order they are tried.  A wrapper that
#: delegates through ``run()`` and one that works under ``__main__`` are as much
#: an entry point as ``main()``; the first survey missed eight programs because
#: it only knew the third, and reported them as unmeasured rather than as
#: unprotected — which was right, and is why they are all handled here.
_ENTRIES: Tuple[Tuple[str, str, str], ...] = (
    (r"^(def main\([^)]*\)[^:]*:\n)", "    return 0  # NEUTERED\n", "main()"),
    (r"^(def run\([^)]*\)[^:]*:\n)", "    return 0  # NEUTERED\n", "run()"),
    (r"^(def _cli\([^)]*\)[^:]*:\n)", "    return 0  # NEUTERED\n", "_cli()"),
    (r"^(if __name__ == [\"']__main__[\"'][^\n]*:[^\n]*\n)",
     "    raise SystemExit(0)  # NEUTERED\n", "__main__"),
    # A CLI named `_cli()` is an entry point too. `xor_layout_check` delegates
    # `__main__` straight to it, and its guard line carries a trailing
    # `# pragma: no cover` — which the previous `:\n`-anchored pattern could not
    # match, so the program reported NO_ENTRY. That is "unmeasured", stated
    # honestly and still a gate nobody probed, for a reason belonging to this
    # program rather than to it.
)


def neuter(source: str) -> Optional[Tuple[str, str]]:
    """`(mutated_source, which_entry)` or None when there is nothing to neuter."""
    for pattern, injection, label in _ENTRIES:
        m = re.search(pattern, source, re.M)
        if m:
            return source[:m.end()] + injection + source[m.end():], label
    return None


def naming_tests(program: str, tests_dir: Optional[Path] = None) -> List[Path]:
    """Test files that name the program — the ones a regression would have to pass."""
    rx = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(program) + r"(?![A-Za-z0-9_])")
    drives = re.compile(
        r"(subprocess\.\w+\([^)]{0,200}%s|%s\.py|import %s|%s\.(main|run|audit)\()"
        % ((re.escape(program),) * 4), re.S)
    scored = []
    for t in sorted((tests_dir or TESTS).glob("test_*.py")):
        if _NOT_DRIVERS.match(t.name):
            continue
        try:
            text = t.read_text(errors="replace")
        except OSError:
            continue
        if not rx.search(text):
            continue
        # A file that DRIVES the program is what a regression has to get past;
        # one that merely names it in prose can neither catch nor clear it.
        scored.append((0 if drives.search(text) else 1, t.stat().st_size, t))
    return [t for _rank, _size, t in sorted(scored)]


#: Written beside the program while it is neutered.  A run that is killed
#: cannot reach its `finally`, and the next run would then read the NEUTERED
#: file as its "original" and restore TO it — the damage compounding silently,
#: one line per killed run.  Measured: a killed probe left three of them stacked
#: in one file.  The marker check below refuses that, and the sidecar makes the
#: interrupted state recoverable instead of merely detectable.
_BACKUP_SUFFIX = ".probe-orig"

#: Matrix modules that name dozens of programs in registries and prose without
#: driving any of them.  d8 alone is 284 tests, and a probe that pulls it in
#: costs minutes to measure nothing about the program under it.
#:
#: `test_matrix_d2_falsifiable` is DELIBERATELY NOT HERE.  It is the one matrix
#: module that genuinely drives gates — it runs them against broken fixtures and
#: asserts they refuse — so excluding it removes real protection and reports the
#: gate as unprotected.  Measured: it took `pvt_matrix_check` from CAUGHT to
#: SILENT, and it runs in five seconds, so the cost that justified the exclusion
#: was not there either.  An exclusion written for speed that changes a verdict
#: is not a speed optimisation; it is a wrong answer arriving sooner.
_NOT_DRIVERS = re.compile(r"^test_matrix_(d[13-8]_|63x8_)")


def stale_backups() -> List[Path]:
    """Sidecars a killed run left behind.  Non-empty means a gate may be neutered.

    Kept after the move to copy-only probing, and NOT as decoration: it is what
    a checkout carrying the damage from a build that predates this change still
    reads by, and `neutered_gate_tree_check` — the gate wired into
    `repo_hygiene_gates.sh` — is built on it.
    """
    return sorted(PROGRAMS.glob("*" + _BACKUP_SUFFIX))


def disposable_programs_root() -> Path:
    """A throwaway copy of the shipped programs tree, made once per process.

    Every mutation this module performs happens inside it, so a `SIGKILL` at
    any instant leaves a stale directory under /tmp and a repository that is
    byte-for-byte what it was.  The next call to `reserve` reaps that directory
    once its owner's `flock` is released, which the kernel does on death.
    """
    global _DISPOSABLE
    if _DISPOSABLE is None:
        res, _report = _scratch.reserve(_SCRATCH_PREFIX)
        root = res.path / "programs"
        shutil.copytree(PROGRAMS, root,
                        ignore=shutil.ignore_patterns("__pycache__",
                                                      ".pytest_cache"))
        atexit.register(res.release)
        _DISPOSABLE = root
    return _DISPOSABLE


def probe(program: str, limit: Optional[int] = None, timeout: int = 240,
          programs_root: Optional[Path] = None) -> dict:
    """`limit` exists for a caller that knows what it is doing; the default is
    NONE ON PURPOSE.

    A capped selection can report SILENT about a gate that IS protected, purely
    by which files sort first — measured: capping at three excluded the very
    test written to protect one of these gates, and the probe called it
    unprotected.  In a guard, a false alarm costs the same as a false comfort:
    both teach the reader to stop believing it.  With the registry-type modules
    excluded the uncapped run is affordable, so it is the default.
    """
    # #547 review — THE TREE THIS RUNS ON IS A PARAMETER. Neutering makes a
    # gate return 0, so while the mutation is in place a CONCURRENT reader of
    # that gate sees a PASS it did not earn: this repo demonstrably runs several
    # sessions against one checkout, and a green that is not real is worse than
    # a red that is not theirs (the shape measured at v1.7.97, where an injected
    # offender file made other sessions FAIL — wrong, but loud and self-
    # announcing).
    #
    # 2026-08-04 — and the DEFAULT used to be `PROGRAMS`, so the concurrent
    # reader above was not hypothetical and the killed run left the weakening
    # behind permanently. The default is now a disposable copy: there is no
    # argument value, and no CLI flag, that makes this function write inside the
    # repository. The restore-and-verify below still runs, on the copy, so a
    # second program probed by the same process starts from clean bytes.
    root = Path(programs_root) if programs_root else disposable_programs_root()
    src = root / f"{program}.py"
    if not src.is_file():
        return {"program": program, "state": "NO_SOURCE"}
    original = src.read_text()
    if "# NEUTERED" in original:
        # Probing this would store the neutered text as the original and make
        # the weakening permanent.  Refuse, and say what to do.
        return {"program": program, "state": "ALREADY_NEUTERED"}
    made = neuter(original)
    if made is None:
        return {"program": program, "state": "NO_ENTRY"}
    mutated, entry = made
    # `tests/` when there is one, the programs directory itself otherwise.
    # `--programs-root` exists so this probe can be pointed at another tree, and
    # that only half worked: vibeic-eda keeps its gates and its tests in the SAME
    # directory, so all five of its gates came back NO_TEST — reported as "a gap
    # in the MEASUREMENT, not a verdict", which is honest and still leaves five
    # gates unprobed for a reason that is this program's, not theirs.
    tests_dir = root / "tests" if (root / "tests").is_dir() else root
    sel = (naming_tests(program, tests_dir)[:limit] if limit
           else naming_tests(program, tests_dir))
    if not sel:
        return {"program": program, "state": "NO_TEST", "entry": entry}
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    backup = src.with_suffix(src.suffix + _BACKUP_SUFFIX)
    try:
        backup.write_text(original)
        src.write_text(mutated)
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *[str(p) for p in sel], "-q",
             "--no-header", "-p", "no:cacheprovider"],
            cwd=root.parent, capture_output=True, text=True, env=env,
            timeout=timeout)
        state = "CAUGHT" if r.returncode != 0 else "SILENT"
    except subprocess.TimeoutExpired:
        state = "TIMEOUT"
    finally:
        # Restoring is not best-effort.  A probe that leaves a neutered gate
        # behind has done more damage than the gap it was measuring.
        src.write_text(original)
        assert src.read_text() == original, (
            "FATAL: %s was not restored — restore it from git before continuing"
            % src)
        backup.unlink(missing_ok=True)
    return {"program": program, "state": state, "entry": entry,
            "tests": [p.name for p in sel]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("program", nargs="+", help="gate program name, without .py")
    ap.add_argument("--json", default=None)
    # #547 review — run against a DISPOSABLE COPY of the programs tree.
    #
    # `--in-place` USED TO EXIST HERE and is deliberately gone. It was justified
    # by "a maintainer working alone may want it, and the copy costs a second";
    # what it actually cost was two shipped gates left neutered in one session,
    # because the thing that removes the mutation is code the killed process
    # does not get to run. There is no crash-safe version of mutating a tracked
    # file, so the option is not made safer — it is removed. `--programs-root`
    # still takes a tree that is already a copy, which is how another repo's
    # gates are probed.
    ap.add_argument("--programs-root", default=None,
                    help="probe this programs/ tree instead of the shipped one")
    a = ap.parse_args(argv)

    root = Path(a.programs_root) if a.programs_root else None
    results = [probe(p, programs_root=root) for p in a.program]
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(
            {"program": "gate_cli_mutation_probe", "results": results}, indent=1))
    worst = 0
    for r in results:
        print("%-46s %s" % (r["program"], r["state"]))
        if r["state"] == "SILENT":
            print("    neutering %s reddened nothing in %d test file(s): %s"
                  % (r.get("entry"), len(r.get("tests", [])),
                     ", ".join(r.get("tests", []))), file=sys.stderr)
            worst = max(worst, 1)
        elif r["state"] in ("NO_ENTRY", "NO_TEST", "NO_SOURCE", "TIMEOUT"):
            print("    NOT PROBED (%s) — this is a gap in the MEASUREMENT, not a "
                  "verdict about the gate" % r["state"], file=sys.stderr)
            worst = max(worst, 2)
    return worst


if __name__ == "__main__":
    sys.exit(main())
