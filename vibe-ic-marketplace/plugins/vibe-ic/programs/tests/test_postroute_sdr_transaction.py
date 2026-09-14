"""Transactional post-route SDR repair must either prove an improved route or restore.

These are Tcl-level tests because the implementation is emitted OpenROAD Tcl.
The tool actions are mocked, but the immutable checkpoint, receipt, strict DRC
comparison, connectivity refusal, and database restoration all execute.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")


def _drc(n: int) -> str:
    return "".join("violation type: spacing\n" for _ in range(n))


def _run(tmp_path: Path, *, before: int, after: int,
         connectivity_ok: bool = True, nonfatal: bool = False):
    out = tmp_path / "pnr"
    out.mkdir()
    report = out / R.ROUTER_DRC_REPORT_NAME
    report.write_text(_drc(before))
    begin = R._postroute_sdr_transaction_begin_tcl(str(out))
    finish = R._postroute_sdr_transaction_finish_tcl()
    connectivity = "return" if connectivity_ok else 'error "disconnected"'
    script = tmp_path / "trial.tcl"
    script.write_text(
        "set ::db BASE\n"
        "proc write_def {path} {\n"
        "  set f [open $path w]; puts -nonewline $f $::db; close $f\n"
        "}\n"
        "proc read_def {path} {\n"
        "  set f [open $path r]; set ::db [read $f]; close $f\n"
        "}\n"
        f"proc check_connectivity {{}} {{ {connectivity} }}\n"
        + begin
        + "set ::db CANDIDATE\n"
        + "set _sdr_tx_mutated 1\n"
        + "set _sdr_tx_route_ok 1\n"
        + ("set _sdr_tx_error 1\n" if nonfatal else "")
        + f"set f [open {{{report}}} w]; puts -nonewline $f {{{_drc(after)}}}; close $f\n"
        + finish
        + 'puts "FINAL:$::db ABORT:$::_vic_postroute_transaction_failed"\n')
    return subprocess.run([tclsh, str(script)], text=True, capture_output=True), out


@needs_tclsh
def test_accepts_only_connected_strictly_improved_candidate(tmp_path):
    run, out = _run(tmp_path, before=4, after=2)
    assert run.returncode == 0, run.stderr
    assert "SDR_TRANSACTION_ACCEPTED: router_drc=4 -> 2" in run.stdout
    assert "FINAL:CANDIDATE ABORT:0" in run.stdout
    receipt = (out / "sdr_transaction" / "receipt.tsv").read_text()
    assert "ACCEPTED\tstrict_router_drc_improvement\t4\t2" in receipt


@needs_tclsh
def test_accepts_drv_candidate_when_clean_router_drc_is_preserved(tmp_path):
    """DRV repair can change cells while a DRC-clean route correctly stays 0."""
    run, out = _run(tmp_path, before=0, after=0)
    assert run.returncode == 0, run.stderr
    assert "SDR_TRANSACTION_ACCEPTED: router_drc clean-preserved (0 -> 0)" in run.stdout
    assert "FINAL:CANDIDATE ABORT:0" in run.stdout
    receipt = (out / "sdr_transaction" / "receipt.tsv").read_text()
    assert "ACCEPTED\trouter_drc_preserved_clean\t0\t0" in receipt


@needs_tclsh
def test_rejects_when_router_drc_does_not_strictly_improve(tmp_path):
    run, out = _run(tmp_path, before=4, after=4)
    assert run.returncode != 0
    assert "SDR_TRANSACTION_REJECTED_UNRESTORABLE: reason=router_drc_not_strictly_improved" in run.stdout
    assert "ODB-0251" not in run.stderr
    tx = out / "sdr_transaction"
    assert (tx / "pre_repair.def").read_text() == "BASE"
    assert "REJECTED_UNRESTORABLE\trouter_drc_not_strictly_improved\t4\t4" in (
        tx / "receipt.tsv").read_text()


@needs_tclsh
def test_nonfatal_error_refuses_candidate_even_when_count_improves(tmp_path):
    run, out = _run(tmp_path, before=4, after=1, nonfatal=True)
    assert run.returncode != 0
    assert "SDR_TRANSACTION_REJECTED_UNRESTORABLE: reason=nonfatal_or_route_error" in run.stdout
    assert "ODB-0251" not in run.stderr
    assert "REJECTED_UNRESTORABLE\tnonfatal_or_route_error\t4\t-1" in (
        out / "sdr_transaction" / "receipt.tsv").read_text()


@needs_tclsh
def test_does_not_call_unavailable_openroad_connectivity_command(tmp_path):
    """Pinned OpenROAD has no ``check_connectivity`` command; LVS owns that proof."""
    run, out = _run(tmp_path, before=0, after=0, connectivity_ok=False)
    assert run.returncode == 0, run.stderr
    assert "SDR_TRANSACTION_ACCEPTED: router_drc clean-preserved (0 -> 0)" in run.stdout
    assert "FINAL:CANDIDATE ABORT:0" in run.stdout
    assert "check_connectivity" not in run.stdout
    assert "ACCEPTED\trouter_drc_preserved_clean\t0\t0" in (
        out / "sdr_transaction" / "receipt.tsv").read_text()
