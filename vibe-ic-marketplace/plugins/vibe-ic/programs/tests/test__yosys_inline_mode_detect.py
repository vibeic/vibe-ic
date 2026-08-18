#!/usr/bin/env python3
"""Unit tests for programs/_yosys_inline_mode_detect.py.

Pins the real decision logic of detect_inline_mode(): a project's
Step-14 VACUOUS_PASS is positively *confirmed* (status "confirmed")
when a phase3-runner artefact OR an inline `yosys -p` invocation is
found; otherwise it stays *unconfirmed* (status "unconfirmed", empty
evidence). Logic-pinned.
"""
from __future__ import annotations

import _yosys_inline_mode_detect as mod


# ---------------------------------------------------------------------------
# unconfirmed (the FAIL-equivalent: vacuousness not positively justified)
# ---------------------------------------------------------------------------
def test_empty_project_is_unconfirmed(tmp_path):
    status, evidence = mod.detect_inline_mode(tmp_path)
    assert status == "unconfirmed"
    assert evidence == []


def test_zero_byte_runner_artefact_does_not_confirm(tmp_path):
    # A present-but-empty report must NOT confirm (st_size > 0 gate).
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "phase3_one_shot.json").write_text("")
    status, evidence = mod.detect_inline_mode(tmp_path)
    assert status == "unconfirmed"
    assert evidence == []


def test_unrelated_files_do_not_confirm(tmp_path):
    (tmp_path / "scripts").mkdir()
    # Mentions yosys but not the inline -p / --commands invocation.
    (tmp_path / "scripts" / "build.sh").write_text(
        "echo running synthesis with yosys synth.ys\n"
    )
    status, evidence = mod.detect_inline_mode(tmp_path)
    assert status == "unconfirmed"


# ---------------------------------------------------------------------------
# confirmed via runner artefact (path a)
# ---------------------------------------------------------------------------
def test_nonempty_runner_report_confirms(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "phase3_one_shot.json").write_text("{}")
    status, evidence = mod.detect_inline_mode(tmp_path)
    assert status == "confirmed"
    assert "reports/phase3_one_shot.json" in evidence


def test_synth_log_artefact_confirms(tmp_path):
    log = tmp_path / "phase3" / "stage2" / "synth"
    log.mkdir(parents=True)
    (log / "yosys.log").write_text("yosys done\n")
    status, evidence = mod.detect_inline_mode(tmp_path)
    assert status == "confirmed"
    assert "phase3/stage2/synth/yosys.log" in evidence


# ---------------------------------------------------------------------------
# confirmed via inline `yosys -p` grep (path b)
# ---------------------------------------------------------------------------
def test_inline_yosys_dash_p_in_shell_confirms(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.sh").write_text(
        'yosys -p "synth_sky130; write_verilog out.v"\n'
    )
    status, evidence = mod.detect_inline_mode(tmp_path)
    assert status == "confirmed"
    assert any("run.sh" in e for e in evidence)


def test_inline_commands_long_flag_confirms(tmp_path):
    (tmp_path / "phase3").mkdir()
    (tmp_path / "phase3" / "flow.tcl").write_text(
        "exec yosys --commands 'synth -top top'\n"
    )
    status, evidence = mod.detect_inline_mode(tmp_path)
    assert status == "confirmed"


def test_xyosys_word_boundary_does_not_falsely_confirm(tmp_path):
    # `\byosys` must not match `xyosys` — guards against false confirm.
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.sh").write_text("xyosys -p foo\n")
    status, _ = mod.detect_inline_mode(tmp_path)
    assert status == "unconfirmed"
