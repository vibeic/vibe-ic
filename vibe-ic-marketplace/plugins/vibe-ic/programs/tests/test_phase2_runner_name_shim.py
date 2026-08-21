#!/usr/bin/env python3
"""Regression: vibe_ic_one_shot_runner must resolve phase-2 to an EXISTING file.

The v1.1.95 rename (#76) moved the phase-2 author to design_one_shot_runner.py
but left no phase2_one_shot_runner.py, so the orchestrator's uniform
`_phase_runner("phase2")` → `<phase>_one_shot_runner.py` derivation pointed at a
missing file and every orchestrator-driven phase-2 step halted with
"No such file" (phase-1 PASS, phase-2 fail). These tests pin the convention-
restoring shim so the regression cannot silently return.

Cases:
  1. SHIM_RESOLVES — _phase_runner("phase2") points at an EXISTING file (the
     exact bug: it did not).
  2. SHIM_REEXPORTS_DESIGN_MAIN — phase2_one_shot_runner.main IS
     design_one_shot_runner.main (verbatim re-export, no behaviour fork).
  3. ALL_PHASES_RESOLVE — phase1/phase2/phase3 runners all resolve to existing
     files (the convention holds uniformly).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent


def _load(mod_name: str, filename: str):
    # programs/ must be importable so the shim's `from design_one_shot_runner
    # import main` resolves exactly as it does when run as a script.
    if str(PROGRAMS) not in sys.path:
        sys.path.insert(0, str(PROGRAMS))
    # Reuse an already-loaded instance so a shim's `from X import main` binds the
    # SAME module object the test compares against (else two instances → main
    # functions differ by identity even though the re-export is correct).
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    path = PROGRAMS / filename
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_shim_resolves_to_existing_file():
    orch = _load("vibe_ic_one_shot_runner", "vibe_ic_one_shot_runner.py")
    resolved = orch._phase_runner("phase2")
    assert resolved.exists(), (
        f"_phase_runner('phase2') -> {resolved} which does not exist; "
        "the phase2_one_shot_runner.py convention shim is missing (#76 rename)."
    )
    assert resolved.name == "phase2_one_shot_runner.py"


def test_shim_reexports_design_main():
    # load design FIRST so the shim's `from design_one_shot_runner import main`
    # binds this same instance (see _load sys.modules reuse).
    design = _load("design_one_shot_runner", "design_one_shot_runner.py")
    shim = _load("phase2_one_shot_runner", "phase2_one_shot_runner.py")
    assert shim.main is design.main, (
        "phase2_one_shot_runner must re-export design_one_shot_runner.main "
        "verbatim (no behavioural fork)."
    )


def test_all_phase_runners_resolve():
    orch = _load("vibe_ic_one_shot_runner", "vibe_ic_one_shot_runner.py")
    for phase in ("phase1", "phase2", "phase3"):
        resolved = orch._phase_runner(phase)
        assert resolved.exists(), f"_phase_runner('{phase}') -> missing {resolved}"
