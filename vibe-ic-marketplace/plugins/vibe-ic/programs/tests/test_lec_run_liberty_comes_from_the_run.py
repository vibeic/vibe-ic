#!/usr/bin/env python3
"""LEC compared a gate netlist against a DIFFERENT PDK's Liberty and blamed the design.

THE MEASURED DEFECT, on a real run at v1.13.66. `lec_run.DEFAULT_LIBERTY` is a single
hardcoded vendor path. `_discover_project_liberty` replaces it only from a Liberty the
design VENDORED under `input/pdk/`. A run whose PDK is MOUNTED in the container — this
flow's normal shape — vendors none, so the constant stands, on a design that is not that
PDK. Yosys then cannot resolve the gate netlist's cells, `hierarchy -check` aborts before
`equiv_make`, and the run records:

    verdict INCONCLUSIVE | equivalent false | compared_points 0
    undefined_macro_modules ["<a standard cell of the design's own PDK>"]
    "the netlist instantiates hard macro/submodule(s) ... whose definition was not
     staged ... Close with sign-off LEC (Conformal/VC LEC)"

The named cell is not a hard macro. It is an ordinary standard cell, defined in the
Liberty the run itself synthesised against. Same program, same files, same container,
one variable changed — the Liberty — takes that run from 0 compared points to
64 of 64 proven. So the INCONCLUSIVE was a statement about which library the checker
opened, wearing the costume of a statement about the netlist.

THE RULE THIS RESTORES is not a preference, it is correct by construction: a gate
netlist is only meaningful against the library it was MAPPED to, and the run records
which that was. So where the built-in constant would otherwise have been used, read the
Liberty this run's own synthesis loaded.

ORDER IS PRESERVED wherever it already worked — cli > staged > run_synth > default —
and the tests below assert the first two are untouched.

ON THE CONTROL. Pre-fix, `resolve_liberty` does not exist. A test that imported it would
raise and collect NOTHING, which measures nothing (a control whose every failure is an
absence is not a control). So `_effective` below reproduces the PRE-FIX decision from
symbols that exist in both trees, and every assertion is on the resulting PATH. Pre-fix
these assertions observe the vendor constant and fail on its VALUE.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _hostpaths  # noqa: E402

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "lec_run.py"


def _mod():
    spec = importlib.util.spec_from_file_location("_lec_run_lib", _PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_lec_run_lib"] = mod
    spec.loader.exec_module(mod)
    return mod


def _effective(mod, project: Path, cli=None, visible=lambda _p: True):
    """(liberty, source) this program WOULD read — post-fix from its own resolver,
    pre-fix reproduced from the symbols that existed then, so the control observes
    a value instead of an ImportError."""
    cli = mod.DEFAULT_LIBERTY if cli is None else cli
    fn = getattr(mod, "resolve_liberty", None)
    if fn is not None:
        return fn(project, cli, visible)
    staged = mod._discover_project_liberty(project)
    if staged is not None:
        return str(staged), "staged"
    return cli, "default"


# --------------------------------------------------------------- fixtures
# Synthesized neutral data. The library paths below are invented; nothing in the
# rule under test depends on which PDK, vendor or corner they name.
def _project(tmp_path: Path, *, synth_line: str | None = None,
             synth_name: str = "synth.log", staged: str | None = None) -> Path:
    root = tmp_path / "proj"
    (root / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (root / "phase2" / "stage2" / "synth" / "post_dft_netlist.v").write_text(
        "module top(); endmodule\n")
    if synth_line is not None:
        (root / "phase2" / "stage2" / "synth" / synth_name).write_text(
            "reading design\n" + synth_line + "\ndone\n")
    if staged is not None:
        d = root / "input" / "pdk" / "liberty"
        d.mkdir(parents=True)
        (d / staged).write_text("library (x) { }\n")
    return root


# --------------------------------------------------------- the defect itself
def test_the_liberty_comes_from_the_run_not_from_a_constant(tmp_path):
    """THE REGRESSION. The run recorded which library it mapped against; the check
    must read that one, not a constant belonging to some other PDK."""
    want = "/opt/pdk_alpha/libs/lib_alpha__typ.lib"
    proj = _project(tmp_path, synth_line=f"  abc -liberty {want} -script +strash")
    got, source = _effective(_mod(), proj)
    assert got == want, (
        f"resolved {got!r}; the run's own synthesis recorded mapping against "
        f"{want!r}, and a gate netlist is only meaningful against the library it "
        "was mapped to")
    assert source == "run_synth", f"source was {source!r}"


def test_read_liberty_syntax_is_read_too(tmp_path):
    """The two spellings a mapping tool uses. `read_liberty` is script syntax,
    `-liberty` is a flag; both are TOOL syntax, neither is a PDK literal."""
    want = "/opt/pdk_beta/libs/lib_beta__nom.lib"
    proj = _project(tmp_path, synth_name="synth.ys",
                    synth_line=f"read_liberty {want}")
    got, _src = _effective(_mod(), proj)
    assert got == want, f"resolved {got!r} from a read_liberty line naming {want!r}"


def test_the_last_recorded_mapping_wins(tmp_path):
    """A script that reads several corners mapped with the one it read last."""
    first = "/opt/pdk_gamma/libs/lib__slow.lib"
    last = "/opt/pdk_gamma/libs/lib__typ.lib"
    proj = _project(
        tmp_path, synth_name="synth.ys",
        synth_line=f"read_liberty {first}\nread_liberty {last}")
    got, _src = _effective(_mod(), proj)
    assert got == last, f"resolved {got!r}, expected the last-read {last!r}"


# ------------------- CONTROLS: same answer before AND after, or this fix is a mute
def test_a_staged_liberty_still_wins_over_the_run_evidence(tmp_path):
    """CONTROL. A design that VENDORS its PDK keeps today's behaviour exactly."""
    proj = _project(tmp_path, staged="vendored__typ.lib",
                    synth_line="  abc -liberty /opt/other/ignored.lib")
    got, _src = _effective(_mod(), proj)
    assert got.endswith("vendored__typ.lib"), (
        f"resolved {got!r}; a staged Liberty must still win — this fix may not "
        "change any run that already worked")


def test_an_explicit_liberty_still_wins(tmp_path):
    """CONTROL. --liberty is the caller's decision and outranks all discovery."""
    explicit = "/opt/caller/chosen.lib"
    proj = _project(tmp_path, synth_line="  abc -liberty /opt/other/ignored.lib")
    got, _src = _effective(_mod(), proj, cli=explicit)
    assert got == explicit, f"resolved {got!r}, expected the caller's {explicit!r}"


def test_no_evidence_at_all_still_falls_back_to_the_constant(tmp_path):
    """CONTROL. Nothing staged, nothing recorded: the constant is still the answer,
    so this fix removes no behaviour, it only stops guessing where a fact exists."""
    mod = _mod()
    got, _src = _effective(mod, _project(tmp_path))
    assert got == mod.DEFAULT_LIBERTY, f"resolved {got!r}"


def test_evidence_outside_the_synthesis_stage_is_not_consulted(tmp_path):
    """CONTROL on SCOPE. Only the stage that PRODUCED the netlist under test may
    decide its library. A Liberty named anywhere else in the project is ignored."""
    proj = _project(tmp_path)
    stray = proj / "phase3" / "stage3" / "sta"
    stray.mkdir(parents=True)
    (stray / "sta.tcl").write_text("read_liberty /opt/elsewhere/unrelated.lib\n")
    mod = _mod()
    got, _src = _effective(mod, proj)
    assert got == mod.DEFAULT_LIBERTY, (
        f"resolved {got!r} from outside the synthesis stage; only the stage that "
        "produced the gate netlist may decide which library it is judged against")


# ------------------------------------------------- backed by a real artefact
def test_a_shipped_tool_script_yields_the_library_it_names(tmp_path):
    """REAL ARTEFACT (§4). Driven by a checked-in tool script rather than by a
    fixture authored alongside this fix: whatever library that file names is the
    library the resolution must return."""
    real = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "ppa", "power", "activity_basis_pair", "power_vcd.tcl")
    text = real.read_text()
    import re
    named = re.findall(r"read_liberty\s+(/\S+\.lib)", text)
    if not named:
        pytest.skip(f"{real} no longer names a Liberty to read")
    proj = _project(tmp_path)
    (proj / "phase2" / "stage2" / "synth" / "mapping.tcl").write_text(text)
    got, _src = _effective(_mod(), proj)
    assert got == named[-1], (
        f"resolved {got!r}; the shipped script names {named[-1]!r} and that is the "
        "library the netlist it describes was mapped against")


def test_the_record_discloses_which_path_produced_the_library(tmp_path):
    """DEGRADE LOUDLY (§6). A reader must not have to infer which of four paths
    chose the library a verdict was computed over."""
    mod = _mod()
    fn = getattr(mod, "build_report", None)
    assert fn is not None, "build_report is the record builder"
    parsed = {"equivalent": False, "proven": 0, "unproven": 0,
              "verdict": "INCONCLUSIVE", "verdict_explanation": "x",
              "sat_model_unsupported_cells": [], "unproven_cells": [],
              "undefined_macro_modules": []}
    try:
        rep = fn(parsed, "top", "gate.v", "/opt/x/lib.lib", "run_synth")
    except TypeError:
        rep = fn(parsed, "top", "gate.v", "/opt/x/lib.lib")
    assert rep.get("liberty_source") == "run_synth", (
        f"record carried liberty_source={rep.get('liberty_source')!r}; the chosen "
        "resolution path must be recorded, not inferred")


def test_a_recorded_library_the_container_cannot_open_is_not_an_answer(tmp_path):
    """A path the run recorded but the tool cannot OPEN is not a resolution. Without
    this guard the run would end with no Liberty at all, where before it had the
    constant — this fix may not make any corner worse."""
    mod = _mod()
    proj = _project(tmp_path, synth_line="  abc -liberty /opt/gone/missing.lib")
    got, source = _effective(mod, proj, visible=lambda p: p != "/opt/gone/missing.lib")
    assert got == mod.DEFAULT_LIBERTY, (
        f"resolved {got!r}; a recorded library that is not visible where the tool "
        "runs must fall back, not be handed on")
    assert source == "default", f"source was {source!r}"
