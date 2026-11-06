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

import ast
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


def _fn(name):
    """The `ast` node of a top-level function in the runner, by name."""
    for node in ast.parse(_SRC).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from phase3_one_shot_runner")


def _calls_to(node, dotted):
    """Every Call to `dotted` anywhere inside `node`, as (lineno, source)."""
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and ast.unparse(sub.func) == dotted:
            out.append((sub.lineno, ast.unparse(sub)))
    return out


NORMALISER = "_tool_status_not_the_log_sinks"


def _normalised_value_reaches(call):
    """Does the command handed to this outbound `call` carry the normalisation?

    Asked by following the DATA, not a line or a name, because the runner uses
    two legitimate spellings and has changed between them:

      INLINE   `_dwd.run_docker_supervised(c, _tool_status_...(cmd), marker)`
      REBOUND  `cmd = _tool_status_...(cmd)`, then `cmd` is built into
               `_wrapped`, and `_wrapped` is what crosses the seam.

    So: start from the expressions the seam receives, and walk BACKWARDS through
    the assignments they depend on. If that closure contains the normaliser
    call, the value crossing the seam is normalised. Normalising into a variable
    nobody forwards, or forwarding the raw parameter, is not reached and is the
    defect this test exists for.
    """
    fn = _enclosing_fn(call)
    assigns = [st for st in ast.walk(fn)
               if isinstance(st, ast.Assign) and st.lineno < call.lineno]
    frontier = list(call.args) + [k.value for k in call.keywords]
    expanded, names = set(), set()
    while frontier:
        node = frontier.pop()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and ast.unparse(sub.func) == NORMALISER:
                return True
            if isinstance(sub, ast.Name):
                names.add(sub.id)
        for st in assigns:
            if id(st) in expanded:
                continue
            if any(isinstance(t, ast.Name) and t.id in names
                   for t in st.targets):
                expanded.add(id(st))
                frontier.append(st.value)
    return False


def _enclosing_fn(node):
    """The runner function whose body contains `node` (by line span)."""
    best = None
    for cand in ast.parse(_SRC).body:
        if (isinstance(cand, ast.FunctionDef)
                and cand.lineno <= node.lineno <= (cand.end_lineno or 0)):
            best = cand
    assert best is not None, "node is not inside a top-level function"
    return best


def test_both_container_exec_paths_normalise():
    """The runner has two ways into a container — the bounded probe path and
    the stall-watchdog path used by every long tool run. A fix on one of them
    is a fix on one of them.

    ASSERTED STRUCTURALLY, NOT BY SPELLING (vibe-ic#2097). This test used to
    count the statement `cmd = _tool_status_not_the_log_sinks(cmd)` and require
    exactly 2, and to look for the landmark
    `_wrapped = _dwd.wrap_with_container_timeout(` inside `_docker_exec`. Both
    are spellings, and v1.18.28 replaced them: `_docker_exec` now normalises
    INLINE, as the argument to the delegated `_dwd.run_docker_supervised(...)`,
    and the landmark went away with the outer clock #2051 removed. The count
    fell to 1 and the red said "the normalisation is missing" about a runner
    that normalises on both paths. The property below survives either spelling:
    each entry point calls the normaliser, and it does so BEFORE it hands the
    command onward — where "onward" is named by the SEAM each function crosses
    (`_exec_argv`, `_dwd.run_docker_supervised`), which is semantic, not a
    line of formatting.
    """
    for fn_name, seam in (("_docker_exec_raw", "_exec_argv"),
                          ("_docker_exec", "_dwd.run_docker_supervised")):
        fn = _fn(fn_name)
        norm = _calls_to(fn, NORMALISER)
        assert len(norm) == 1, (
            f"{fn_name} must normalise its command exactly once before it "
            f"crosses {seam}; found {len(norm)}: {[c for _, c in norm]}")
        onward = [n for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and ast.unparse(n.func) == seam]
        assert onward, (
            f"{fn_name} no longer reaches the container through {seam} — this "
            f"test is pinned to that seam and must be re-pointed, not deleted")
        assert any(_normalised_value_reaches(call) for call in onward), (
            f"{fn_name} calls {NORMALISER} but the value that reaches {seam} "
            f"is not the normalised one — the log sink can answer for the "
            f"tool again")


def test_every_tee_pipeline_in_this_file_is_covered_by_the_helper():
    """There are eleven of them today. The point of fixing it centrally is
    that this count may grow without anyone re-deriving the fix — so assert
    they exist and that nothing bypasses the two exec entry points."""
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
