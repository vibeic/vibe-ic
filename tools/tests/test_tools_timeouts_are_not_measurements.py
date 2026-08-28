"""A tool is bounded by whether it is WORKING, never by how long it has run.

RETRACTED PREMISE. The first version of this file asserted that these two entry
points had stopped calling a killed run a failure — that they now said NOT
MEASURED. That is the last-resort shape used as a first resort: the run was
still killed while it was working, and no wording gives the result back. Ending
work because a clock expired does not make sense.

Both sites now load the plugin's `programs/_watchdog.py` and run under
`run_host_supervised`, which bounds NO PROGRESS: CPU and I/O read from `/proc`
across the whole tree, plus output growth. The old constants survive as GRACE
windows, which can only kill LESS than they did as runtime caps.

Two `tools/` entry points recorded a subprocess timeout as a finding:

  * `pipeline_run._run_yosys_synth` capped yosys at 120 s and then wrote
    `synth_cells: 0` and `Synthesis failed`. Both are MEASUREMENTS — "this
    design synthesises to nothing", "synthesis ran and failed" — published about
    a run that was killed mid-synthesis.
  * `phase1_menu._regen_datasheet` / `_regen_appnote` capped the generator at
    120 s and returned "failed", the word this menu uses when the generator RAN
    and exited non-zero. `_regen_appnote` did not even log the event.

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
import time
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

def test_a_synthesis_that_is_running_is_never_stopped(tmp_path, monkeypatch):
    """THE HALF THE RETRACTED VERSION DID NOT DELIVER. yosys is stood in for by
    a subject that runs far past its grace while burning CPU and printing; the
    supervisor must let it finish. A runtime cap kills it at the grace however
    the handler beside it is worded."""
    monkeypatch.setattr(PR, "_SYNTH_STALL_GRACE_S", 1)
    body = ("import sys, time\n"
            "end = time.monotonic() + 3.0\n"
            "x = 0\n"
            "while time.monotonic() < end:\n"
            "    x += 1\n"
            "    if x % 200000 == 0:\n"
            "        print('Number of cells:      7', flush=True)\n")
    script = tmp_path / "slow_yosys.py"
    script.write_text(body, encoding="utf-8")
    started = time.monotonic()
    proc = PR._supervised([sys.executable, str(script)],
                          PR._SYNTH_STALL_GRACE_S, PR._StalledSynth)
    took = time.monotonic() - started
    assert proc.returncode == 0, proc.stderr
    assert took > 2.0, (
        f"the subject finished in {took:.1f}s against a 1s grace — it never "
        f"outlived the bound, so this proves nothing")


def test_a_wedged_synthesis_is_stopped_and_publishes_no_cell_count(
        tmp_path, monkeypatch):
    """THE HALF THAT MUST NOT MOVE. Idle and silent across the grace: stopped,
    and still no cell count — `0` is a number somebody reads as a measurement."""
    monkeypatch.setattr(PR, "_SYNTH_STALL_GRACE_S", 1)
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")

    def _stall(argv, grace, exc, **kw):
        raise exc("no forward progress for 1s; it was doing nothing.")

    monkeypatch.setattr(PR, "_supervised", _stall)
    ok, cells, log = PR._run_yosys_synth(str(rtl), str(tmp_path))
    assert ok is False, "a wedged synthesis reported success"
    assert cells is None, (
        f"synth_cells={cells!r} — a cell count was published for a run that "
        f"never produced one")
    assert log.startswith(PR._SYNTH_NOT_MEASURED), log
    assert "doing nothing" in log


def test_the_marker_is_shared_so_producer_and_reader_cannot_drift():
    """The caller branches on this string. Two spellings would put the timeout
    back on the `Synthesis failed` path without anyone editing that line."""
    src = (_TOOLS / "pipeline_run.py").read_text(encoding="utf-8")
    assert src.count("_SYNTH_NOT_MEASURED") >= 3, (
        "the marker is not shared between the producer, the constant and the "
        "reader")
    assert '"Yosys synthesis timed out"' not in src
    assert PR._WATCHDOG is not None, (
        "the plugin watchdog did not load, so this script silently fell back "
        "to the runtime bound it was supposed to have lost")


def test_a_synthesis_that_really_failed_is_still_reported_as_failed(
        tmp_path, monkeypatch):
    """NON-VACUITY, and the half that must not move: a yosys that RAN and
    errored is still a synthesis failure with a real cell count of 0."""
    rtl = tmp_path / "top.v"
    rtl.write_text("module top; endmodule\n")
    monkeypatch.setattr(PR, "_supervised", lambda argv, g, e, **kw:
                        subprocess.CompletedProcess(argv, 1, "ERROR: syntax\n", ""))
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
    assert src.count('return "stalled"') == 2, (
        "one of the two handlers still returns the accusing word")
    assert 'self._log("Datasheet re-generation: TIMEOUT")' not in src
    assert src.count("STALLED (no forward ") == 2, (
        "the two handlers do not both log the stall")
    assert 'print(f"  Error: Timed out after 120s")' not in src
    assert "run_host_supervised" in src, (
        "the menu dropped its bound without gaining a watchdog")


def test_the_menu_still_only_advances_on_success():
    """THE HALF THAT MUST NOT MOVE. The caller branches on == "success", so a
    new word must not have become a new success path."""
    src = (_TOOLS / "phase1_menu.py").read_text(encoding="utf-8")
    assert src.count('if result == "success":') == 2
    assert 'if result == "stalled":' not in src
