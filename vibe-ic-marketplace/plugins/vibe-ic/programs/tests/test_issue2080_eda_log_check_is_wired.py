#!/usr/bin/env python3
"""vibe-ic#2080 — `eda_log_check` was credited by a closing parenthesis.

WHAT WAS MEASURED ON THE PRE-FIX TIP (94617408759e)
===================================================
`checker_execution_wiring_baseline.json` recorded the whole of it under #1347:

    "Never wired; held up solely by the fragment `eda_log_check)` at the end of
     a sentence in `openroad_tcl_deprecation_check`'s deprecation table."

    programs/openroad_tcl_deprecation_check.py:123
        "eda_log_check)"

One string fragment, and both wiring registers read it as an execution path.
Its own triage note names the home this commit uses: "Takes --log-file, so it is
per-design and belongs ... at the step that produces the log it should read."

WHAT THE ROW BUYS
=================
`step_yosys_synth` writes `phase2/stage2/synth/yosys.log` unconditionally, and
NOTHING in the tree asked whether that file exists, is non-empty, or carries the
`stat` table the step dropped `-q` (v1.6.193) in order to capture. The step's
own sibling comment names the failure mode it does not cover —
`_ystat.emit_stats_json` refuses to write accounting because "the docker-fallback
path can return rc=0 with an empty stdout capture" — but that guard reads the
IN-MEMORY capture, and the FILE is the artefact every later reader has. A
zero-byte `yosys.log` beside a netlist has read exactly like a complete one.

BOTH DIRECTIONS
===============
`test_a_log_carrying_the_tools_own_stat_table_is_a_PASS` and the three FINDING
cases beside it are one fixture apart: same project, same synth verdict, the
log's CONTENT the only variable. And the discriminator that must not be got
wrong is measured on its own:
`test_a_design_that_never_synthesised_is_NOT_APPLICABLE_not_a_FINDING` — a
pure-analog design has no digital RTL, `step_yosys_synth` answers SKIP by
design, and reading the log's absence directly would accuse every such design.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as DOSR                # noqa: E402

_DISPATCH = "plan.append(step_synth_log_audit(project, _synth_row))"
_GATE = "eda_log_check"

#: SPELLED HERE, and pinned to the runner's constants by
#: `test_this_file_measures_the_same_log_and_the_same_skip_set`.
#:
#: A module-level `DOSR._SYNTH_LOG_REL` / `DOSR._SYNTH_NOT_ATTEMPTED` would be
#: read at COLLECTION time, so on the pre-fix tree this file aborted collection
#: with one AttributeError instead of failing seventeen tests by name — and a
#: collection abort scrapes as zero failures, which is the weakest possible
#: negative control. Literals here, membership asserted below.
_SYNTH_LOG_REL = "phase2/stage2/synth/yosys.log"
# R-0915-85 — the five spellings collapse to the two words that mean NO TOOL
# RAN. A row is built for each below, so each needs the field its word requires.
_NOT_ATTEMPTED = ("NOT_MEASURED", "NOT_APPLICABLE")

_REAL_STAT_LOG = (
    "\n=== chip_top ===\n"
    "\n   Number of wires:                 12\n"
    "   Number of cells:                   42\n"
    "     $_AND_                            8\n"
)








# ---------------------------------------------------------------------------
# THE WIRING
# ---------------------------------------------------------------------------
def test_the_runner_dispatches_the_gate_at_a_real_call_site() -> None:
    src = Path(DOSR.__file__).read_text(errors="replace")
    assert _DISPATCH in src, (
        f"design_one_shot_runner no longer dispatches {_GATE} ({_DISPATCH!r} "
        f"absent). Its only other credit in this tree is the fragment "
        f"'eda_log_check)' inside a string — vibe-ic#2080.")


def test_the_dispatch_follows_the_step_that_writes_the_log() -> None:
    """The gate reads a file; it must run after the step that writes it, and it
    must be handed THAT step's verdict rather than a later one."""
    src = Path(DOSR.__file__).read_text(errors="replace")
    synth = src.index("step_yosys_synth, project, args.top_name, args.container")
    here = src.index(_DISPATCH)
    binding = src.index("_synth_row = plan[-1]")
    assert synth < binding < here, (
        "the synth-log audit moved ahead of the step that writes the log; it "
        "would then judge the PREVIOUS run's file, or none.")
    qsf = src.index("plan.append(step_qsf_gen(project, args.top_name, ic_class))")
    assert here < qsf, (
        "the synth-log audit no longer sits immediately after the synth "
        "dispatch, so `plan[-1]` is some other step's verdict and the "
        "NOT_APPLICABLE discriminator is reading the wrong row.")


def test_the_gate_left_both_unwired_registers() -> None:
    wired = json.loads((_PROGRAMS / "gate_is_wired_baseline.json").read_text())
    assert _GATE not in wired["unwired"], (
        "gate_is_wired_baseline.json still records this gate as unwired.")
    checkers = json.loads(
        (_PROGRAMS / "checker_execution_wiring_baseline.json").read_text())
    assert _GATE + ".py" not in checkers["known"], (
        "checker_execution_wiring_baseline.json still records this checker as "
        "test-only; its audit FAILs on a recorded checker that gained a runner.")
    assert _GATE + ".py" not in (checkers.get("triage") or {}), (
        "the triage note outlived its `known` row.")


def test_the_step_can_never_move_the_run_verdict() -> None:
    src = Path(DOSR.__file__).read_text(errors="replace")
    step = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef)
                and n.name == "step_synth_log_audit")
    calls = [c for c in ast.walk(step)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
             and c.func.id == "StepResult" and len(c.args) >= 2
             and isinstance(c.args[1], ast.Constant)]
    statuses = {c.args[1].value for c in calls}
    # R-0915-85 — `ADVISORY` was a STATUS that meant "this row cannot move the
    # verdict". It is a DISCLOSURE beside a `PASS` now, and the property #2080
    # pins is unchanged: `run_verdict` gives a disclosure no arithmetic at all,
    # so the row still cannot move anything. Asserted in BOTH halves, because
    # a PASS without the disclosure would be a row that CAN move the verdict.
    assert statuses == {"PASS"}, (
        f"step_synth_log_audit returns {sorted(statuses)}; vibe-ic#2080 wires a "
        f"recorded-unwired gate as non-moving unless its docstring declares it "
        f"BLOCKING, and this gate's does not.")
    for c in calls:
        kw = {k.arg: k.value for k in c.keywords}
        disc = ast.unparse(kw["disclosures"]) if "disclosures" in kw else ""
        assert "ADVISORY" in disc, (
            f"a StepResult in step_synth_log_audit is a bare PASS: without "
            f"Disclosure.ADVISORY beside it, the row CAN move the run verdict, "
            f"which is exactly what #2080 forbids")


# ---------------------------------------------------------------------------
# THE VERDICT MOVES ON THE LOG'S CONTENT — BOTH DIRECTIONS
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# THE DISCRIMINATOR THAT MUST NOT BE GOT WRONG
# ---------------------------------------------------------------------------
