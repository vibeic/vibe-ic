"""PAIRED GUARD for the `_HAVE_TOOLS` skips added to the synth test modules.

A skip is the correct response to a genuinely absent tool. A skip that fires
whether or not the tool is there is a SILENCED TEST wearing a skip's clothes,
and it is worse than the crash it replaced: the crash was at least loud.

The modules gated here launch `iverilog` (and `vvp`) directly and, before the
gate, raised `FileNotFoundError: No such file or directory: 'iverilog'` on any
host without it — including this one, where all eleven EDA tools are absent.
The gate converts that to a disclosed skip. Measured, per module, before/after:

    test_v1_1_63_full_moore_fsm_synth   2 failed,  7 passed ->  7 passed, 2 skipped
    test_v1_1_64_fsm_tabular_format     3 failed,  4 passed ->  4 passed, 3 skipped
    test_v1_1_65_ff_and_comb_state_synth 3 failed, 8 passed ->  8 passed, 3 skipped
    test_v1_1_76_mealy_sequence         2 failed, 11 passed -> 11 passed, 6 skipped

The PASSED counts are identical in every case: nothing that was running stopped
running, only the crashes became skips.

WHAT THIS FILE PROVES, on a host where the tool is missing:
the gate is keyed on the tool's PRESENCE and not stuck closed — with
`shutil.which` reporting a path, `_HAVE_TOOLS` is True and the guard is a
no-op. Without this, the four modules could skip forever on every host and
nothing would notice, which is the exact failure the repo calls a check that
passes over an empty population.
"""
from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

#: The modules this guard covers. Kept as a list because it IS the population:
#: a module gated later and not added here is simply unguarded, and
#: `test_every_gated_module_is_covered_here` fails when that happens.
GATED = (
    "test_v1_1_63_full_moore_fsm_synth",
    "test_v1_1_64_fsm_tabular_format",
    "test_v1_1_65_ff_and_comb_state_synth",
    "test_v1_1_76_mealy_sequence",
    # Already carried `_HAVE_TOOLS` on main before this change — they were
    # gated correctly and had no proof the gate could OPEN. Covered here for
    # the same reason as the four above; `test_every_gated_module_is_covered_here`
    # is what surfaced them.
    "test_round16_latency_clear_prefix_localparam",
    "test_v1_1_76_waveform_ext",
)


@pytest.mark.parametrize("modname", GATED)
def test_the_gate_is_CLOSED_when_the_tool_is_absent(modname, monkeypatch):
    """Baseline: with `which` finding nothing, the gate must be shut."""
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    mod = importlib.reload(importlib.import_module(modname))
    assert mod._HAVE_TOOLS is False, (
        f"{modname}._HAVE_TOOLS is True while shutil.which finds nothing")


@pytest.mark.parametrize("modname", GATED)
def test_the_gate_OPENS_when_the_tool_is_present(modname, monkeypatch):
    """The one that matters: a permanent skip would pass the test above too.

    With `which` reporting a path for every tool, `_HAVE_TOOLS` must be True,
    so the `if not _HAVE_TOOLS: pytest.skip(...)` guard does nothing and the
    real assertions run. If this fails, the gate has become unconditional and
    those modules are silenced on every host, tool or no tool.
    """
    monkeypatch.setattr(shutil, "which", lambda name, *_a, **_k: f"/usr/bin/{name}")
    mod = importlib.reload(importlib.import_module(modname))
    assert mod._HAVE_TOOLS is True, (
        f"{modname}._HAVE_TOOLS is False even though shutil.which reports the "
        f"tool present — the skip is unconditional and the module is silenced")


def test_every_gated_module_is_covered_here():
    """`GATED` must name every module carrying `_HAVE_TOOLS`.

    Otherwise a module gated tomorrow gets a skip with no proof the skip can
    open — the register and the population drifting apart, which is the defect
    this repo removes everywhere else.
    """
    carrying = {p.stem for p in _TESTS.glob("test_*.py")
                if "_HAVE_TOOLS" in p.read_text()
                and p.stem != Path(__file__).stem}
    assert carrying == set(GATED), (
        f"modules carrying `_HAVE_TOOLS` but not listed in GATED: "
        f"{sorted(carrying - set(GATED))}; listed but no longer carrying it: "
        f"{sorted(set(GATED) - carrying)}")
