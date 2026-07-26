#!/usr/bin/env python3
"""#365 third ask — one provenance entry per EDA invocation, with a REAL
duration.

The ledger previously held a handful of BACK-FILLED entries per flow, written
for artefacts found on disk with a `duration_ms` nobody measured. This records
one entry per SUPERVISED tool run and measures it.

SCOPE is the runner's own signal: `_docker_exec(marker=...)` is how this file
already distinguishes an open-ended TOOL RUN from a bounded shell probe
(`command -v`, `ls`, `ps`). Logging the probes as well would bury the tool runs
in noise — the opposite of what the issue asks for.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402


def _entries(d: Path):
    f = d / "provenance.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.is_file() else []


def test_365_an_invocation_is_recorded_with_a_measured_duration(tmp_path):
    p3.set_invocation_provenance_sink(tmp_path)
    try:
        p3._log_invocation("openroad -no_init -exit pnr.tcl", 0, 12345,
                           marker="PNR")
    finally:
        p3.set_invocation_provenance_sink(None)
    e = _entries(tmp_path)
    assert len(e) == 1
    assert e[0]["tool"] == "openroad" and e[0]["duration_ms"] == 12345
    assert e[0]["measured"] is True and e[0]["exit_code"] == 0
    assert e[0]["marker"] == "PNR"


def test_365_tool_name_is_the_commands_own_first_token(tmp_path):
    """chip/tool-AGNOSTIC: the name comes from the command, never from a
    known-tools list, and an absolute path is reduced to its basename."""
    p3.set_invocation_provenance_sink(tmp_path)
    try:
        p3._log_invocation("/foss/tools/bin/yosys -p 'synth'", 1, 42)
        p3._log_invocation("some_future_tool --flag", 0, 7)
    finally:
        p3.set_invocation_provenance_sink(None)
    assert [e["tool"] for e in _entries(tmp_path)] == ["yosys",
                                                       "some_future_tool"]


def test_365_tool_name_survives_the_runners_real_export_prologue(tmp_path):
    """REGRESSION, found on a REAL run and invisible to the test above.

    Every container command this runner emits is prefixed with
    `export PATH=... &&`, so taking argv[0] recorded `tool: "export"` for
    EVERY EDA invocation — a ledger column that looks populated while naming
    a shell builtin, which is the very defect #365 was filed about.

    The pre-existing unit test passed throughout because its fixture used a
    bare `yosys ...` command; production never looks like that. The command
    below is the shape the runner actually produced, copied from the ledger
    of a real OpenROAD run.
    """
    real = ("export PATH=/foss/tools/openroad/bin:/foss/tools/bin:$PATH && "
            "openroad -no_init -exit /w/reports/phase3/ir_em_spm.tcl 2>&1 "
            "| tee /w/reports/phase3/ir_em.log")
    p3.set_invocation_provenance_sink(tmp_path)
    try:
        p3._log_invocation(real, 0, 798)
        p3._log_invocation("cd /w && yosys -s synth.ys", 0, 12)
        p3._log_invocation("FOO=1 netgen -batch source lvs.tcl", 0, 5)
    finally:
        p3.set_invocation_provenance_sink(None)
    assert [e["tool"] for e in _entries(tmp_path)] == ["openroad", "yosys",
                                                       "netgen"]


def test_365_a_chain_that_is_only_prologue_still_names_something(tmp_path):
    """The paired half: never return an empty tool. If the whole chain is
    shell prologue there IS no program, and reporting the prologue is honest
    — inventing one would not be."""
    p3.set_invocation_provenance_sink(tmp_path)
    try:
        p3._log_invocation("export A=1 && export B=2", 0, 1)
        p3._log_invocation("   ", 0, 1)
    finally:
        p3.set_invocation_provenance_sink(None)
    assert [e["tool"] for e in _entries(tmp_path)] == ["export", "sh"]


def test_365_the_other_writers_duration_key_is_populated(tmp_path):
    """`provenance_logger.py` writes `duration_s` into this SAME file. Emitting
    only `duration_ms` would leave every existing consumer of `duration_s`
    reading nothing for these rows — a new reader-without-producer split
    (#312 family) manufactured by the fix for #365."""
    p3.set_invocation_provenance_sink(tmp_path)
    try:
        p3._log_invocation("openroad x.tcl", 0, 2500)
    finally:
        p3.set_invocation_provenance_sink(None)
    e = _entries(tmp_path)[0]
    assert e["duration_ms"] == 2500
    assert e["duration_s"] == 2.5
    assert e["record"] == "invocation"


def test_365_no_sink_means_no_writes_anywhere(tmp_path):
    """A library caller must not have entries appear in someone else's tree."""
    p3.set_invocation_provenance_sink(None)
    p3._log_invocation("openroad x", 0, 1)
    assert _entries(tmp_path) == []


def test_365_logging_never_breaks_the_run(tmp_path):
    """A ledger that can break the run it documents would be traded away the
    first time it did. An unwritable sink must be swallowed."""
    bad = tmp_path / "nope"
    bad.write_text("not a directory")          # <sink>/provenance.jsonl fails
    p3.set_invocation_provenance_sink(bad)
    try:
        p3._log_invocation("openroad x", 0, 1)   # must not raise
    finally:
        p3.set_invocation_provenance_sink(None)


def test_365_the_duration_is_measured_at_the_supervised_call_site():
    """Wiring pin: the watchdog branch must TIME the run and log it, or the
    feature exists in the helper and not in the flow."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    i = src.index("res = _wd.run_supervised(")
    window = src[max(0, i - 200):i + 400]
    assert "time.monotonic()" in window and "_log_invocation(" in window


def test_365_the_sink_is_pointed_at_the_project_by_the_runner():
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert "set_invocation_provenance_sink(project)" in src


def test_365_bounded_probes_are_not_logged():
    """`_docker_exec_raw` handles the short probes; it must NOT log, or the
    ledger fills with `command -v` / `ls` / `ps` and the tool runs are lost
    in it."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    i = src.index("def _docker_exec_raw(")
    j = src.index("\ndef ", i + 1)
    assert "_log_invocation(" not in src[i:j]
