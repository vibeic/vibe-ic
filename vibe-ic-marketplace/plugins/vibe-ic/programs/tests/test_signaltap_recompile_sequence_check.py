"""Tests for signaltap_recompile_sequence_check.py.

Validates the deterministic Quartus SignalTap recompile pipeline policy from
skills/fpga-signaltap/SKILL.md: the four stages
  quartus_stp --stp_file=<x>.stp -> quartus_map -> quartus_fit -> quartus_asm
must all be present, in canonical order, with a real .stp attached.

Covers PASS, FAIL (each finding kind), and edge/honesty (absent/empty input).
"""
from __future__ import annotations

import json
from pathlib import Path

import signaltap_recompile_sequence_check as M


GOOD = (
    "#!/bin/bash\n"
    "set -e\n"
    "quartus_stp cd4013b_fpga --stp_file=cd4013b_debug.stp\n"
    "quartus_map cd4013b_fpga\n"
    "quartus_fit cd4013b_fpga\n"
    "quartus_asm cd4013b_fpga\n"
)


# --------------------------------------------------------------------------
# PASS
# --------------------------------------------------------------------------
def test_pass_canonical_sequence(tmp_path: Path):
    f = tmp_path / "recompile.sh"
    f.write_text(GOOD)
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--json", str(out)])
    assert rc == 0
    res = json.loads(out.read_text())
    assert res["status"] == "PASS"
    assert res["stages_found"] == ["quartus_stp", "quartus_map",
                                   "quartus_fit", "quartus_asm"]
    assert res["stp_file"] == "cd4013b_debug.stp"


def test_pass_expect_stp_matches(tmp_path: Path):
    f = tmp_path / "recompile.sh"
    f.write_text(GOOD)
    rc = M.main([str(f), "--expect-stp", "cd4013b_debug.stp"])
    assert rc == 0


def test_pass_stp_file_space_form(tmp_path: Path):
    f = tmp_path / "recompile.sh"
    f.write_text(GOOD.replace("--stp_file=cd4013b_debug.stp",
                              "--stp_file cd4013b_debug.stp"))
    rc = M.main([str(f)])
    assert rc == 0


# --------------------------------------------------------------------------
# FAIL — missing stage (the headline defect: no quartus_stp)
# --------------------------------------------------------------------------
def test_fail_missing_quartus_stp(tmp_path: Path):
    f = tmp_path / "recompile.sh"
    f.write_text(
        "quartus_map cd4013b_fpga\n"
        "quartus_fit cd4013b_fpga\n"
        "quartus_asm cd4013b_fpga\n")
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--json", str(out)])
    assert rc == 1
    res = json.loads(out.read_text())
    assert res["status"] == "FAIL"
    fnd = res["findings"]
    assert any(x["rule"] == "STAGE_MISSING"
               and "quartus_stp" in x["detail"] for x in fnd)
    # The headline warning must be present.
    assert any("NO logic analyzer" in x["detail"] for x in fnd)


def test_fail_missing_asm(tmp_path: Path):
    f = tmp_path / "recompile.sh"
    f.write_text(
        "quartus_stp p --stp_file=x.stp\n"
        "quartus_map p\n"
        "quartus_fit p\n")
    rc = M.main([str(f)])
    assert rc == 1


# --------------------------------------------------------------------------
# FAIL — wrong order
# --------------------------------------------------------------------------
def test_fail_wrong_order_stp_after_fit(tmp_path: Path):
    f = tmp_path / "recompile.sh"
    f.write_text(
        "quartus_map p\n"
        "quartus_fit p\n"
        "quartus_stp p --stp_file=x.stp\n"
        "quartus_asm p\n")
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--json", str(out)])
    assert rc == 1
    assert "WRONG_ORDER" in {x["rule"]
                             for x in json.loads(out.read_text())["findings"]}


# --------------------------------------------------------------------------
# FAIL — stp file problems
# --------------------------------------------------------------------------
def test_fail_stp_no_stp_file(tmp_path: Path):
    f = tmp_path / "recompile.sh"
    f.write_text(
        "quartus_stp cd4013b_fpga\n"   # no --stp_file
        "quartus_map cd4013b_fpga\n"
        "quartus_fit cd4013b_fpga\n"
        "quartus_asm cd4013b_fpga\n")
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--json", str(out)])
    assert rc == 1
    assert "STP_NO_STP_FILE" in {x["rule"]
                                 for x in json.loads(out.read_text())["findings"]}


def test_fail_stp_file_not_dot_stp(tmp_path: Path):
    f = tmp_path / "recompile.sh"
    f.write_text(GOOD.replace("cd4013b_debug.stp", "cd4013b_debug.sdc"))
    rc = M.main([str(f)])
    assert rc == 1


def test_fail_expect_stp_mismatch(tmp_path: Path):
    f = tmp_path / "recompile.sh"
    f.write_text(GOOD)
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--expect-stp", "other_debug.stp", "--json", str(out)])
    assert rc == 1
    assert "STP_FILE_MISMATCH" in {x["rule"]
                                   for x in json.loads(out.read_text())["findings"]}


# --------------------------------------------------------------------------
# Edge / honesty
# --------------------------------------------------------------------------
def test_skip_no_input(capsys):
    """CONTRACT CHANGE (2026-08-03, vibe-ic#693): rc 2, not 0.

    The old assertion and its own comment contradicted each other — it said
    "not a vacuous PASS" while asserting the exit code that IS one.
    `flow_compliance_check._check_program_exit_zero` reads rc==0 as a plain
    PASS and rc==2 as the disclosed VACUOUS_PASS tier.
    """
    assert M.main([]) == 2
    err = capsys.readouterr().err
    # `gate_skip_routing_check._skip_token` matches at LINE START.
    assert err.lstrip().startswith("[SKIP]"), err


def test_skip_unrelated_file(tmp_path: Path, capsys):
    # A file with NONE of the quartus_* stages -> SKIP, not a vacuous PASS.
    # rc 2 (the disclosed-skip tier) is what makes that sentence true; see
    # test_skip_no_input.
    f = tmp_path / "notes.txt"
    f.write_text("This file talks about make and gcc, no quartus here.\n")
    out = tmp_path / "r.json"
    rc = M.main([str(f), "--json", str(out)])
    assert rc == 2
    assert json.loads(out.read_text())["status"] == "SKIP"
    assert capsys.readouterr().err.lstrip().startswith("[SKIP]")


def test_missing_input_is_io_error(tmp_path: Path):
    assert M.main([str(tmp_path / "nope.sh")]) == 2


def test_comment_lines_ignored(tmp_path: Path):
    # A commented-out quartus_stp must NOT count as present.
    f = tmp_path / "recompile.sh"
    f.write_text(
        "# quartus_stp p --stp_file=x.stp   (disabled)\n"
        "quartus_map p\n"
        "quartus_fit p\n"
        "quartus_asm p\n")
    rc = M.main([str(f)])
    assert rc == 1  # STAGE_MISSING quartus_stp
