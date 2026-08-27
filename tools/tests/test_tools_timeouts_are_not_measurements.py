"""A tool that was killed did not measure anything, and must not say it did.

Two `tools/` entry points recorded a subprocess timeout as a finding:

  * `pipeline_run._run_yosys_synth` returned `(False, 0, "Yosys synthesis timed
    out")`. The caller then wrote `synth_cells: 0` into the metrics and pushed
    `Synthesis failed` onto the error list. Both are MEASUREMENTS — "this design
    synthesises to nothing" and "synthesis was run and it failed" — published
    about a run that was killed. The same function already had the right shape
    one branch away, for yosys-not-on-PATH.
  * `phase1_menu._regen_datasheet` / `_regen_appnote` returned "failed", the
    same word this menu prints when the generator RAN and exited non-zero.
    `_regen_appnote` did not even log the timeout, so the transcript kept a bare
    failure with no way to tell it from a real one.

NOTE ON WHERE THIS FILE LIVES. `tools/tests` is NOT in the plugin's pytest
`testpaths` (`programs/tests` only), so this file does not run in the plugin
lane. It is here because that is where the repo's other `tools/` test lives, and
because a test in `programs/tests` would have to reach up out of the plugin
directory for `tools/` and would hard-fail wherever the plugin is checked out
alone. The coverage gap is pre-existing and named here rather than worked
around.

Run: python3 -m pytest tools/tests/test_tools_timeouts_are_not_measurements.py -q
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_TOOLS = None
for _c in (Path(__file__).resolve().parents[1],
           Path(__file__).resolve().parents[3] / "tools"):
    if (_c / "pipeline_run.py").is_file():
        _TOOLS = _c
        break
assert _TOOLS is not None, "could not locate tools/ from this test's location"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


PR = _load("pipeline_run")


class _NeverFinishes:
    def __call__(self, argv, *a, **kw):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kw.get("timeout", 1))


# ── pipeline_run ────────────────────────────────────────────────────────────

def test_a_synthesis_that_did_not_finish_publishes_no_cell_count(
        tmp_path, monkeypatch):
    """THE FIX. `0` is a number somebody will read as a measurement."""
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    monkeypatch.setattr(PR.subprocess, "run", _NeverFinishes())
    ok, cells, log = PR._run_yosys_synth(str(rtl), str(tmp_path))
    assert ok is False, "a killed synthesis reported success"
    assert cells is None, (
        f"synth_cells={cells!r} — a cell count was published for a run that "
        f"never produced one")
    assert log.startswith(PR._SYNTH_NOT_MEASURED), log
    assert "not about the RTL" in log


def test_the_marker_is_shared_so_producer_and_reader_cannot_drift():
    """The caller branches on this string. Two spellings would put the timeout
    back on the `Synthesis failed` path without anyone editing that line."""
    src = (_TOOLS / "pipeline_run.py").read_text(encoding="utf-8")
    assert src.count("_SYNTH_NOT_MEASURED") >= 3, (
        "the marker is not shared between the producer, the constant and the "
        "reader")
    assert '"Yosys synthesis timed out"' not in src


def test_a_synthesis_that_really_failed_is_still_reported_as_failed(
        tmp_path, monkeypatch):
    """NON-VACUITY, and the half that must not move: a yosys that RAN and
    errored is still a synthesis failure with a real cell count of 0."""
    class _Errors:
        def __call__(self, argv, *a, **kw):
            return subprocess.CompletedProcess(
                argv, 1, stdout="ERROR: syntax\n", stderr="")
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    monkeypatch.setattr(PR.subprocess, "run", _Errors())
    ok, cells, log = PR._run_yosys_synth(str(rtl), str(tmp_path))
    assert ok is False
    # `getattr` so the PRE-FIX module can run this control too: an
    # AttributeError would make it observe nothing, and this arm must pass in
    # BOTH trees — that is exactly what makes it a non-vacuity check.
    marker = getattr(PR, "_SYNTH_NOT_MEASURED", "SYNTH_NOT_MEASURED")
    assert not log.startswith(marker), (
        "a real synthesis error is being excused as not-measured — that is a "
        "deletion of the check, not a fix")


# ── phase1_menu ─────────────────────────────────────────────────────────────

def test_the_menu_has_a_word_for_a_generator_that_did_not_finish():
    """Both handlers returned the same "failed" the menu uses for a generator
    that ran and exited non-zero. Read from source: the surrounding method is a
    long interactive prompt loop, and the branch is reached by a keystroke."""
    src = (_TOOLS / "phase1_menu.py").read_text(encoding="utf-8")
    assert src.count('return "not_measured"') == 2, (
        "one of the two timeout handlers still returns the accusing word")
    assert 'self._log("Datasheet re-generation: TIMEOUT")' not in src
    # the appnote handler logged NOTHING before; now it logs, like its sibling.
    # The literal is wrapped across two source lines, so match the stable half.
    assert src.count("re-generation: NOT MEASURED ") == 2, (
        "the two handlers do not both log the timeout as NOT MEASURED")
    assert 'print(f"  Error: Timed out after 120s")' not in src


def test_the_menu_still_only_advances_on_success():
    """THE HALF THAT MUST NOT MOVE. The caller branches on == "success", so a
    new word must not have become a new success path."""
    src = (_TOOLS / "phase1_menu.py").read_text(encoding="utf-8")
    assert src.count('if result == "success":') == 2
    assert 'if result == "not_measured":' not in src
