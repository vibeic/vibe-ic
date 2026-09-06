"""H2 — the runner must write a real antenna report or none, never an empty one.

THE DEFECT, MEASURED (lane czspmfp2, spm).  The PnR Tcl runs
`check_antennas -report_violating_nets -report_file $_ant_rf` once per
iteration. OpenROAD CREATES that file and writes ZERO BYTES when nothing
violates, so a converged iteration leaves a report that exists and says nothing:
`phase3/stage3/pnr/antenna_iter_0.rpt` and `_1.rpt` were both 0 bytes on a run
whose antenna sequence converged `[1, 0]`. `eda_report_audit` discovers them,
judges them, and writes four ERROR findings; since v1.17.103 a verdict over a
report holding no bytes is NOT_MEASURED, so those two unreadable files cost spm
its `Checker.KLayoutAntenna` row outright.

A 0-byte report is the ONE state a consumer cannot read as either "clean" or
"absent" — the two answers it is entitled to. Absent is legitimate and readable.

MUTATIONS THESE MUST KILL:
  * Deleting the `_vic_ant_rm_empty` proc, or any of its three call sites, fails
    `test_the_cleanup_is_defined_and_called_on_every_path`.
  * Widening the guard to delete a NON-empty report (dropping `file size == 0`)
    fails `test_only_an_empty_report_is_removed` — that is the control: a run
    WITH antenna violations must still write and KEEP its report.
"""

import re
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402

SRC = (PROGRAMS / "phase3_one_shot_runner.py").read_text()


def test_the_cleanup_is_defined_and_called_on_every_path():
    assert "proc _vic_ant_rm_empty" in SRC, "the cleanup proc is gone"
    # every place a per-iteration report is opened must be followed by it:
    # the loop's normal path, the loop's check-failed path, and the final check
    assert SRC.count("_vic_ant_rm_empty $_ant_rf") == 3, (
        "each of the three report-writing paths must clean up after itself")


def test_only_an_empty_report_is_removed():
    """THE CONTROL. A run WITH antenna violations writes a non-empty report and
    must keep it — the guard is on SIZE, never on existence alone."""
    body = SRC.split("proc _vic_ant_rm_empty")[1].split('"  }\\n"')[0]
    assert "file size $f] == 0" in body, body
    assert "file exists $f" in body, body
    # and it must not delete unconditionally
    assert re.search(r"file delete[^\n]*\n(?!.*file size)", body) is None or \
        "== 0" in body


def test_the_reader_still_tolerates_an_absent_report():
    """Removing the file is only safe because the consumer already treats an
    unopenable report as 'no membership answer' rather than as 'clean'."""
    i = SRC.index("proc _vic_ant_nets")
    seg = SRC[i:i + 900]
    assert "catch {set fh [open $f r]}" in seg and "return {}" in seg


def test_the_cleanup_runs_after_the_report_is_read():
    """Order is load-bearing: `_vic_ant_nets` must get its chance before the
    file is removed, or a report WITH content would be parsed from nothing."""
    loop = SRC.split("set _ant_now [_vic_ant_nets $_ant_rf $_nv]")[1]
    assert loop.lstrip().startswith('\\n"\n        "    _vic_ant_rm_empty') or \
        "_vic_ant_rm_empty" in loop[:120], loop[:160]
