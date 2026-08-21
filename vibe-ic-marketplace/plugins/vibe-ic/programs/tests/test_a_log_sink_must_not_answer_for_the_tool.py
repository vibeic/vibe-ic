"""`tee` answered for the tool, and one PnR failure was reported as a
power-grid audit gap.

The defect
----------
Every long tool run in `phase3_one_shot_runner` is composed as

    <tool> ... 2>&1 | tee <log>

and a shell pipeline's exit status is the LAST command's. `tee` succeeds
whenever it can write its file, so the TOOL's status never reaches the runner.
Eleven such pipelines exist in that one file — openroad (PnR, RC extraction,
IR/EM, antenna, metal fill, ERC, …), OpenSTA, yosys and magic.

MEASURED, through the exact wrapper the module uses
(`docker exec -e IIC_OSIC_TOOLS_QUIET=1 <c> bash -lc <cmd>`), OpenROAD
26Q3-1066-g29e3e63e45 on a design whose netlist it cannot parse:

    openroad -no_init -exit t.tcl 2>&1 | tee /tmp/or.log        ->  rc 0
    set -o pipefail; openroad ... 2>&1 | tee /tmp/or.log        ->  rc 1
    set -o pipefail; <same command, on a design that links>     ->  rc 0

The third line is the negative control: `pipefail` does not manufacture
failures, it stops discarding them.

What it cost on a real run
--------------------------
`openroad -no_init -exit pnr.tcl` aborted after 15 s with

    [ERROR STA-0171] .../<top>_synth.v line 1293425, syntax error
    Error: pnr.tcl, 8 STA-0171

`step_pnr`'s completion test is `if rc != 0 or not def_file.is_file()`. `rc`
was 0 because of `tee`, and `def_file.is_file()` was satisfied by a DEF left
by an EARLIER run — so both halves of the test passed on a run that placed and
routed nothing. The step was reported as

    BLOCKED pnr  PG_NET_OWNERSHIP_UNMEASURED

a power-grid audit gap, with `duration_s: 15.05` in the orchestrator record.
The next reader spent a session on the power grid.

This is the same class as the provenance version probe that read `head`'s
status instead of the tool's: *a downstream filter answered for the tool.*
That was fixed at one site. This fixes it at the one place every container
command passes through, so the twelfth pipeline cannot reintroduce it.

Scope
-----
Only a pipeline into `tee`. `tee` is a pure logging sink; it never expresses a
decision, so its exit status is never the answer. Pipelines into
`head`/`grep`/`awk` are untouched — there the filter's status can legitimately
be the question.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_PLUGIN = _PROGRAMS.parent
for _p in (str(_PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phase3_one_shot_runner as _runner                     # noqa: E402

_SRC = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")


def test_a_tee_logged_tool_command_is_run_under_pipefail():
    cmd = "openroad -no_init -exit /x/pnr.tcl 2>&1 | tee /x/openroad.log"
    got = _runner._tool_status_not_the_log_sinks(cmd)
    assert got.startswith("set -o pipefail; "), got
    assert got.endswith(cmd), "the tool command itself must be unchanged"


def test_normalisation_is_idempotent():
    cmd = "yosys -s /x/a.ys 2>&1 | tee /x/a.log"
    once = _runner._tool_status_not_the_log_sinks(cmd)
    twice = _runner._tool_status_not_the_log_sinks(once)
    assert once == twice, twice
    assert twice.count("set -o pipefail;") == 1, twice


def test_commands_without_a_log_sink_are_untouched():
    """NEGATIVE CONTROL — the short probes and the filter pipelines that
    legitimately read the FILTER's status must not change."""
    for cmd in (
        "command -v openroad",
        "ps -eo pid,cmd",
        "pkill -TERM -f /x/pnr.tcl",
        "openroad --version 2>&1 | head -3",
        "grep -c foo /x/bar | awk '{print $1}'",
    ):
        assert _runner._tool_status_not_the_log_sinks(cmd) == cmd, cmd


def test_both_container_exec_paths_normalise():
    """The runner has two ways into a container — the bounded probe path and
    the stall-watchdog path used by every long tool run. A fix on one of them
    is a fix on one of them."""
    assert _SRC.count("cmd = _tool_status_not_the_log_sinks(cmd)") == 2, (
        "expected the normalisation on BOTH _docker_exec_raw and the "
        "_docker_exec watchdog branch")
    for fn_head, tail in (
            ("def _docker_exec_raw(", "_inner = max(1, timeout - 5)"),
            ("def _docker_exec(", "_ceil_inner = max(1, int(ceiling) - 5)")):
        i = _SRC.index(fn_head)
        j = _SRC.index(tail, i)
        assert "cmd = _tool_status_not_the_log_sinks(cmd)" in _SRC[i:j], (
            f"{fn_head} builds its bash wrapper without normalising the "
            f"command first")


def test_every_tee_pipeline_in_this_file_is_covered_by_the_helper():
    """There are eleven of them today. The point of fixing it centrally is
    that this count may grow without anyone re-deriving the fix — so assert
    they exist and that nothing bypasses the two exec entry points."""
    n_tee = _SRC.count("| tee ")
    assert n_tee >= 11, f"expected the known tee-logged tool runs; found {n_tee}"
    # No COMMAND STRING may hard-code its own pipefail: one owner, one place,
    # so a site that opts out locally is visible as a diff on this assertion.
    local = [ln.strip() for ln in _SRC.splitlines()
             if "| tee " in ln and "pipefail" in ln
             and not ln.strip().startswith("#")]
    assert local == [], (
        "a tee-logged command spells its own pipefail; the composition rule "
        f"belongs to _tool_status_not_the_log_sinks alone: {local}")
    # And the helper is the single owner of the prefix literal.
    assert _SRC.count('_PIPEFAIL_PREFIX = "set -o pipefail; "') == 1
