#!/usr/bin/env python3
"""A gate naming a project-ROOT file aborted the whole audit when it was absent.

THE DEFECT
==========
`_check_files_exist` hands each missing pattern to
`_sibling_self_skip_for_missing`, which probes the pattern's PARENT directory
so a sibling `*_not_run.json` self-skip can be honoured (#440/#608). For a
declaration with no directory component — `files_exist: ["build.flag"]` — that
parent is `Path("build.flag").parent`, i.e. `"."`, and it went straight into
`_glob_real` -> `Path.glob(".")`, which on 3.12 raises

    IndexError: tuple index out of range

because the pattern compiles to zero selectable parts. Two sibling spellings of
the same thing throw too, each with a DIFFERENT exception — `""` (which
`_glob_first`'s analog-remap branch computes itself, as the `tail` of a pattern
that equals its own prefix) raises ValueError, and `"./"` raises AttributeError
— so a guard written against only the one in the traceback leaves the other two
live. `check_step` runs in a
`ThreadPoolExecutor` and `main()` re-raises via `_fut.result()`, so this is not
one gate failing: the run produces NO report, NO verdict and NO exit code —
just a traceback. Strictly worse than the MISSING it was computing.

The canonical 63-step flow happens to declare no root-relative `files_exist`
pattern today, so the crash is reachable through `--flow-def` (a documented,
shipped option) and through any future flow entry that names a file the runner
drops at the project root. Nothing in the code said "never name a root file",
and a rule that exists only as an unwritten precondition is the kind this
suite is for.

Both directions are asserted: the absent case must be a clean FAIL/MISSING
verdict, and the PRESENT case must still be a PASS — a fix that made every
root-relative pattern unsatisfiable would silence the crash by breaking the
feature.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
CHECK = PLUGIN_ROOT / "programs" / "flow_compliance_check.py"

sys.path.insert(0, str(PLUGIN_ROOT / "programs"))
import flow_compliance_check as F  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_ROOT_FILE = "root_relative_gate_probe.flag"


def _flow(path: Path) -> None:
    """A one-step flow whose gate names a file at the project ROOT."""
    path.write_text(yaml.safe_dump({
        "flow": "root_relative_probe",
        "steps": [{"id": "R1", "name": "root-relative gate probe",
                   "stage": "stage1",
                   "gate": {"files_exist": [_ROOT_FILE]}}],
    }, sort_keys=False), encoding="utf-8")


def _run(tmp_path: Path, seed: bool):
    proj = tmp_path / ("present" if seed else "absent")
    proj.mkdir(parents=True)
    if seed:
        (proj / _ROOT_FILE).write_text("x\n", encoding="utf-8")
    flow = tmp_path / f"flow_{proj.name}.yaml"
    _flow(flow)
    out = tmp_path / f"report_{proj.name}.json"
    # A subprocess, not `main()` in-process: the defect is an exception
    # escaping the thread pool, and only a real process boundary shows that it
    # takes the exit code and the report with it.
    p = _pr.run(
        [sys.executable, str(CHECK), str(proj), "--json", str(out),
         "--flow-def", str(flow), "--lenient"],
        capture_output=True, text=True)
    return p, (json.loads(out.read_text()) if out.exists() else None)


#: Every spelling of "the root, not something under it". Each throws a
#: DIFFERENT exception from `Path.glob` on 3.12 — IndexError, ValueError and
#: AttributeError respectively — so a guard written against only the one in the
#: traceback would leave the other two live.
_ROOT_NAMING_PATTERNS = (".", "", "./")


@pytest.mark.parametrize("pattern", _ROOT_NAMING_PATTERNS)
def test_the_glob_primitive_does_not_raise_on_a_root_naming_pattern(pattern):
    """The unit, at the site the traceback named."""
    assert F._glob_real(PLUGIN_ROOT, pattern) == []


@pytest.mark.parametrize("pattern", _ROOT_NAMING_PATTERNS)
def test_the_caller_of_the_primitive_is_guarded_too(pattern):
    """`_glob_first` computes such a pattern itself.

    Its analog-remap branch strips a prefix off the pattern and re-probes with
    the remainder, which is `""` whenever a pattern equals its own prefix. So
    the degenerate value does not only arrive from a flow author — this program
    manufactures it.
    """
    assert F._glob_first(PLUGIN_ROOT, pattern) == []


def test_the_guard_is_not_a_blanket_return_empty():
    """THE CONTROL for the unit above: real patterns still resolve."""
    assert F._glob_real(PLUGIN_ROOT, "programs/flow_compliance_check.py")
    assert F._glob_first(PLUGIN_ROOT, "programs/flow_compliance_check.py")


def test_an_absent_root_relative_gate_file_yields_a_verdict_not_a_traceback(
        tmp_path):
    """THE DEFECT, through the shipped entry point."""
    p, report = _run(tmp_path, seed=False)
    assert "IndexError" not in (p.stdout + p.stderr), (
        f"the audit aborted instead of judging the step:\n"
        f"{(p.stdout + p.stderr)[-2000:]}")
    assert report is not None, "no JSON report was written at all"
    r1 = next(s for s in report["steps"] if s["id"] == "R1")
    assert r1["status"] in ("FAIL", "MISSING"), r1


def test_a_present_root_relative_gate_file_still_PASSES(tmp_path):
    """THE CONTROL. Making the pattern unsatisfiable would also stop the
    crash, and would be a worse bug than the one it replaced."""
    p, report = _run(tmp_path, seed=True)
    assert report is not None, (p.stdout + p.stderr)[-2000:]
    r1 = next(s for s in report["steps"] if s["id"] == "R1")
    assert r1["status"] == "PASS", r1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
