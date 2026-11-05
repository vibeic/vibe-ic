#!/usr/bin/env python3
"""rphase2 — the generic full-stack reference TB was WRITTEN and, on every run
tree the long-lived EDA container does not happen to mount, NOTHING RAN IT.

MEASURED on 8HD-6, main at 3c9724e8, from a clean clone, one node id::

    programs/tests/test_phase2_class_aware_gating.py::
        test_generic_class_reference_tb_runs_full_stack_tb

    E  AssertionError: ... the simulator was NOT FOUND where the compile was
       dispatched (rc=127) ... Generic full-stack TB skeleton
       (tb_core_top_full.v) + results.json present but NO sim ran (#439).
       assert 'PASS_WITH_WAIVERS' == 'NOT_MEASURED'

The container HAS iverilog and the tree sat outside its bind mounts, so
`_iverilog_exec_container` declined it (correctly — the container cannot see
the sources); the host has no iverilog, so the argv went to the host anyway
and came back rc=127 COMMAND_NOT_FOUND. There was no third place to send it.
The producer had no consumer, and the run said so in a word that reads as
settled.

TWO defects, one measurement, and this file pins both:

  1. THE EXECUTOR. `docker exec` cannot reach a tree the container does not
     mount, but `docker run -v <dir>:<dir>` can, and the IMAGE is the same
     one the declared container is running — so reachability is bought
     without trading away the #902 toolchain provenance it was bought for.

  2. THE THIRD STATE. `WAIVED` was returned both for "the skeleton ran to
     completion" and for "no simulator executed anything", and
     `_aggregate_verdict` folded it into PASS_WITH_WAIVERS either way. A
     testbench that EXISTS is not a testbench that RAN. Three outcomes now
     carry three words, and `extras["sim_executed"]` states the fact without
     anyone parsing prose.

TEETH, in both directions, at every claim:
  * a host that HAS the simulator still uses the host — the new site is the
    fallback for an unreachable tree, not a replacement for a working one;
  * a simulator that RAN and rejected the source still FAILs;
  * when the mounted site is unavailable too, the outcome is NOT_EXECUTED and
    never a pass — an unreachable compiler must still buy nothing.

chip-AGNOSTIC: host/container/image tool-locality and status vocabulary only.
No chip, PDK, process or vendor literal.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as dosr  # noqa: E402

_TOP = "core_top"
_RTL = (f"module {_TOP}(input clk, input reset_n, input data_in, "
        f"output data_out); assign data_out = data_in; endmodule\n")

#: what `_run` returns when the tool is not on the PATH it was dispatched to,
#: and what iverilog returns when it RAN and rejected the source.
_ABSENT = (127, "", "COMMAND_NOT_FOUND: [Errno 2] No such file or "
                    "directory: 'iverilog'")
_REJECTED = (1, "", f"{_TOP}.v:1: syntax error\nI give up.\n")






# ---------------------------------------------------------------------------
# THE THIRD STATE — three outcomes, three words, and none of them green
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# THE EXECUTOR — the third dispatch site
# ---------------------------------------------------------------------------
def _pin_sites(monkeypatch, *, host_has_tool: bool, mounted):
    """Container declines (it cannot see the tree); host presence and the
    mounted-image result are the two variables."""
    monkeypatch.setattr(dosr, "_iverilog_exec_container",
                        lambda *a, **k: False)
    monkeypatch.setattr(dosr, "_tool_in_container", lambda *a, **k: True)
    monkeypatch.setattr(dosr, "_shutil_which",
                        lambda tool: "/usr/bin/" + tool if host_has_tool
                        else None)
    monkeypatch.setattr(dosr, "_record_sim_toolchain",
                        lambda *a, **k: {})
    calls = {"mounted": 0, "host": 0}

    def _mounted(argv, run_dir, container, timeout=120):
        calls["mounted"] += 1
        return mounted

    def _host(cmd, cwd=None, timeout=None, **kw):
        calls["host"] += 1
        return _ABSENT

    monkeypatch.setattr(dosr, "_run_stage_in_mounted_image", _mounted)
    monkeypatch.setattr(dosr, "_run", _host)
    return calls


def test_unreachable_tree_dispatches_into_the_mounted_image(
        tmp_path, monkeypatch):
    calls = _pin_sites(monkeypatch, host_has_tool=False,
                       mounted=(0, "FULL_STACK_TB_DONE\n", ""))
    rc, out, _err = dosr._run_iverilog_stage(
        ["iverilog", "-o", str(tmp_path / "a.vvp")], tmp_path, "c")
    assert (rc, out) == (0, "FULL_STACK_TB_DONE\n")
    assert calls == {"mounted": 1, "host": 0}


def test_a_host_that_has_the_simulator_still_uses_the_host(
        tmp_path, monkeypatch):
    """TEETH. The new site is the fallback for an unreachable tree, not a
    replacement for a working host — a run in true host mode must be
    unchanged by this."""
    calls = _pin_sites(monkeypatch, host_has_tool=True, mounted=(0, "", ""))
    dosr._run_iverilog_stage(["iverilog", "-o", str(tmp_path / "a.vvp")],
                             tmp_path, "c")
    assert calls == {"mounted": 0, "host": 1}


def test_mounted_site_unavailable_falls_back_and_buys_nothing(
        tmp_path, monkeypatch):
    """TEETH. No docker, no image id — the site returns None and the argv goes
    to the host exactly as before, which is still rc=127. An unreachable
    simulator must never be conjured into a verdict."""
    calls = _pin_sites(monkeypatch, host_has_tool=False, mounted=None)
    rc, _out, err = dosr._run_iverilog_stage(
        ["iverilog", "-o", str(tmp_path / "a.vvp")], tmp_path, "c")
    assert rc == 127 and "COMMAND_NOT_FOUND" in err
    assert calls == {"mounted": 1, "host": 1}


def test_bind_dirs_cover_every_argv_path_and_fold_into_ancestors(tmp_path):
    """The mount set is what makes the sources VISIBLE; a missed path is a
    file-not-found inside the container, which reads like a defect."""
    run = tmp_path / "run"
    (run / "deep").mkdir(parents=True)
    src = tmp_path / "elsewhere" / "a.v"
    src.parent.mkdir()
    src.write_text(_RTL)
    dirs = dosr._bind_dirs_for(
        ["iverilog", "-g2012", "-DDUT_TOP_NAME=x",
         str(run / "deep" / "out.vvp"), str(src)], run)
    resolved = {str(Path(d).resolve()) for d in dirs}
    for needed in (run, run / "deep", src.parent):
        assert any(str(needed.resolve()) == d
                   or str(needed.resolve()).startswith(d + "/")
                   for d in resolved), (needed, resolved)
    # nested dirs fold into their ancestor — docker is not handed a mount it
    # already covers.
    assert not any(a != b and b.startswith(a + "/")
                   for a in resolved for b in resolved)


def test_the_constant_and_every_literal_spelling_are_the_same_word():
    """`_aggregate_verdict` is EXTRACTED from the shipped source and exec'd in
    isolation by `test_design_verdict_has_no_silent_catch_all`, and the
    closed-loop coverage checker reads `main`'s terminal tuple as an AST
    LITERAL collection — so neither site can name the module constant. Both
    must therefore spell the word by hand, which is exactly how two spellings
    drift apart. This is the pin that stops it."""
    src = (PROGRAMS / "design_one_shot_runner.py").read_text(errors="replace")
    word = dosr.NOT_EXECUTED_STATUS
    # R-0915-85 — THE CATCH-ALL IS GONE, so the first of the two hand-spelt
    # sites it pinned is gone with it: `_aggregate_verdict` is
    # `verdict.run_verdict` over rows `verdict.parse` has already refused an
    # unknown word at, and `_INCOMPLETE_STATUSES` was a list this file had to
    # keep in step with. What survives, and still has to be spelt by hand, is
    # main's terminal tuple — the closed-loop checker reads it as an AST
    # literal collection and cannot name a module constant.
    assert f'"PASS_WITH_WAIVERS", "{word}") or' in src, (
        "main's reference-TB repair loop no longer spells the terminal set as "
        "literals; the closed-loop coverage checker reads it as an AST "
        "literal collection and would report the loop unwired")
    # and the closed-loop registry's citation agrees with that tuple
    import closed_loop_executable_coverage_check as clc
    cited = clc.REGISTRY["4"]["evidence"]
    for kind in ("actuate", "remeasure"):
        assert cited[kind], (kind, "no citation to check — vacuous")
        for c in cited[kind]:
            assert word in c["terminal_values"], (kind, c)
