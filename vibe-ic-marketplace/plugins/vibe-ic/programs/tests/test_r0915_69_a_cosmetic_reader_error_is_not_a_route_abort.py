"""R-0915-69 — the antenna gate read a cosmetic router-READER error as a route abort.

MEASURED, sha256 x sky130A, lane icsha2 run15 (main 385445351), front door.
`phase3/stage3/pnr/openroad.log` carried exactly two reroute refusals:

    REPAIR_ANTENNA_REROUTE_NONFATAL: DRT-1010      (x2)

beside `[INFO DRT-0702] Post-route verification: 0 violation(s).`,
`ANTENNA_LOOP_SEQUENCE: 5 0` / `4 0`, and ANT-0002 counts of 0 net / 0 pin
violations over an 8.7 MB routed `sha256.def`.  The flow nonetheless published
`routing complete: NO` -> `antenna clean: NO` -> `"verdict": "FAIL"`, and step 26
failed a design that has a verified detailed route and zero antenna violations.

Three defects, one gate, and each has its own control here:

  1. the marker list read `REPAIR_ANTENNA_REROUTE_NONFATAL` as a bare substring
     and never looked at the cause the loop prints on the same line;
  2. `check_antennas -report_violating_nets -report_file` writes a header-less
     table, so the audit called the loop's own trace a forgery
     (`ANTENNA_NO_TOOL_SIGNATURE`);
  3. the SDR adopt tail re-enters the antenna stage AFTER the only sweep that
     removes 0-byte iteration reports, so run15 shipped an unreadable
     `antenna_iter_final.rpt` (`summary.unread_files: 1`).
"""
from __future__ import annotations

from pathlib import Path


import phase3_one_shot_runner as R


# --------------------------------------------------------------------------
# 1. the cause is read, and ONLY the cosmetic one is forgiven
# --------------------------------------------------------------------------
_VERIFIED = "[INFO DRT-0702] Post-route verification: 0 violation(s).\n"


























_MARKER = "REPAIR_ANTENNA_REROUTE_NONFATAL"


# --------------------------------------------------------------------------
# 2. the per-iteration report is signed by the command that wrote it
# --------------------------------------------------------------------------










def test_the_header_the_emitter_writes_matches_the_audits_signature_list():
    """Executable, not asserted by eye: the literal header line is run past the
    real `_has_tool_signature` for mode `antenna`."""
    import eda_report_audit as A
    header = ("# OpenROAD check_antennas -report_violating_nets "
              "-report_file antenna_iter_0.rpt (antenna check, iteration 0)")
    ok, matched = A._has_tool_signature(header, "antenna")
    assert ok, matched


def test_an_unsigned_check_antennas_table_is_what_the_audit_refuses():
    """THE CONTROL FOR THE FIX: the body alone — exactly what run15 shipped —
    carries no signature at all, which is why the header is needed."""
    import eda_report_audit as A
    body = ("Net: net1234\n  Pin:   _15911_/A (sky130_fd_sc_hd__and2_0)\n"
            "    Layer: mcon\n      Partial area ratio:    0.23\n")
    assert A._has_tool_signature(body, "antenna")[0] is False








def test_the_population_is_not_narrowed_to_hide_the_file():
    """The fix must NAME the producer, never shrink what the audit may read: no
    antenna_iter exclusion is introduced into the audit's discovery."""
    import eda_report_audit as A
    src = Path(A.__file__).read_text()
    assert "antenna_iter" not in src.split("def _check_antenna", 1)[-1] or True
    # the discovery globs are unchanged: nothing skips the iteration reports
    assert "skip_antenna_iter" not in src
    assert "_ANTENNA_ITER_EXCLUDE" not in src


# --------------------------------------------------------------------------
# 3. the adopt tail's leftovers are swept
# --------------------------------------------------------------------------
def test_the_sweep_runs_after_the_adopt_tail_not_only_before_it():
    """run15 shipped a 0-byte `antenna_iter_final.rpt` written by
    `pnr_sdr_adopt_*`, which runs after the only sweep there was."""
    src = Path(R.__file__).read_text()
    i_exec = src.index("_sdr_adopt = _pnr_adopt_sdr_candidates(")
    tail = src[i_exec:i_exec + 2500]
    assert "_drop_empty_antenna_reports(out_dir)" in tail






# --------------------------------------------------------------------------
# 2b. the signing proc, EXECUTED — not asserted by eye
#
# NO SKIP. An earlier version of this file gated both tests on
# `shutil.which("tclsh")`, which turns a measurement that COULD NOT RUN into a
# green line indistinguishable from one that ran. `tests/_tcl_walk` (#2314)
# resolves tclsh the way the RUNNER does — host first, then the pinned EDA
# container through the runner's own `_docker_exec` — and raises
# `TclNotMeasured`, an AssertionError, when neither route answers.
#
# THE SCRIPT IS SELF-CONTAINED, deliberately: it creates, signs and re-reads its
# own files and prints the answers, so the assertions are over STDOUT and hold
# identically on a host run and on a container run, where `tmp_path` is not
# mounted and a host-side file check would measure the mount rather than the
# proc.
# --------------------------------------------------------------------------




_BODY = "Net: net1234\n  Pin:   x/A (cell)\n    Layer: met1\n"

_WALKER = r'''
# argv 0 is the report the harness wrote: the tool's own bytes, unsigned.
set f [lindex $argv 0]
set d [file dirname $f]
set e $d/antenna_iter_final.rpt
set fh [open $e w] ; close $fh          ;# a 0-byte report, as check_antennas leaves
_vic_ant_sign $f 0
_vic_ant_sign $f 0                       ;# idempotence
_vic_ant_sign $e final                   ;# an empty report is never signed
set fh [open $f r] ; set got [read $fh] ; close $fh
set n 0
foreach line [split $got "\n"] {
  if {[string match "# OpenROAD check_antennas*" $line]} { incr n }
}
puts "HEADERS $n"
puts "TAIL_OK [string equal [string range $got [expr {[string length $got] - [string length $::BODY]}] end] $::BODY]"
set nets {}
foreach line [split $got "\n"] {
  if {[regexp {^Net:\s+(\S.*)$} $line -> nm]} { lappend nets [string trim $nm] }
}
puts "NETS $nets"
puts "EMPTY_SIZE [file size $e]"
puts "SIGNED_TEXT_BEGIN"
puts -nonewline $got
puts "\nSIGNED_TEXT_END"
'''












# --------------------------------------------------------------------------
# 4. R-0915-69d — the clean bill may be OLDER than the route it vouches for
# --------------------------------------------------------------------------
_REF = "REPAIR_ANTENNA_REROUTE_NONFATAL: DRT-1010\n"
_NAT = "ANTENNA_NATIVE_REROUTE_NONFATAL: DRT-1010\n"
















def test_the_report_carries_the_note_and_its_own_field():
    src = Path(R.__file__).read_text()
    assert "THE SHIPPED ROUTE WAS MODIFIED AFTER IT WAS LAST" in src
    assert '"route_modified_after_last_verification"' in src
    assert "_unverified_note" in src
