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


# ---------------------------------------------------------------------------
# vibe-ic#2157 — THE ASSERTIONS ABOVE READ THE SOURCE. THESE DRIVE THE RUN.
#
# Every test above this line greps `phase3_one_shot_runner.py` for the SPELLING
# of the fix.  MEASURED (vibe-ic#2157, lane rbsub6 on 8HD-9, run tree
# `~/_lane_rbsub6/d/subservient`): with `8000bb196` an ancestor of the run,
# `phase3/stage3/pnr/antenna_iter_0.rpt` and `_1.rpt` were BOTH 0 bytes in the
# published tree, `antenna_report_check` returned rc 1 with verdict
# NOT_MEASURED, and not one assertion above could see it — they were all green
# on the very tree that carried the escape.  A test that can only see the
# spelling of a fix, never its effect, is not a guard on the fix.
#
# So: drive the PRODUCER and assert on the ARTEFACT.
#   * `_antenna_repair_tcl` is the producer of the Tcl.  Its output is executed
#     under a real `tclsh` with the three tool commands stubbed to the MEASURED
#     OpenROAD behaviour (`check_antennas -report_file F` creates F and writes
#     zero bytes), and the assertion is on the DIRECTORY afterwards.
#   * `_drop_empty_antenna_reports` is the producer-side sweep.  It is driven
#     against the exact shape rbsub6 published, and the assertion is that both
#     files are gone BY NAME while every other report in the directory stays.
#   * The mutation arm is executed here, in-test: strip the cleanup call the
#     run actually exercises and the two 0-byte files come back.  Without that
#     arm the artefact assertion could be passing for a reason that has nothing
#     to do with the cleanup.
# ---------------------------------------------------------------------------



#: The three OpenROAD commands the emitted block calls outside a `catch`.
#: `check_antennas` reproduces the measured defect shape: the report file is
#: CREATED and holds zero bytes.  Everything else the block touches
#: (`ord::get_db_block` and friends) is already `catch`-guarded by the block
#: itself, which is why plain `tclsh` can run it at all.
_TOOL_STUBS = r"""
set ::VIC_SEQ {seq}
set ::VIC_I 0
set ::VIC_BODY {body}
proc check_antennas {{args}} {{
  set rf ""
  for {{set i 0}} {{$i < [llength $args]}} {{incr i}} {{
    if {{[lindex $args $i] eq "-report_file"}} {{
      set rf [lindex $args [expr {{$i+1}}]]
    }}
  }}
  if {{$rf eq ""}} {{ return 3 }}
  set fh [open $rf w]
  if {{$::VIC_BODY ne ""}} {{ puts -nonewline $fh $::VIC_BODY }}
  close $fh
  set n [lindex $::VIC_SEQ $::VIC_I]
  if {{$n eq ""}} {{ set n 0 }}
  incr ::VIC_I
  return $n
}}
proc repair_antennas {{args}} {{ return 0 }}
proc detailed_route {{args}} {{ return 0 }}
"""

#: The cleanup call the normal loop path exercises — the one the measured
#: escape would have needed.  Used as the mutation anchor.
_LOOP_CLEANUP = ("    set _ant_now [_vic_ant_nets $_ant_rf $_nv]\n"
                 "    _vic_ant_rm_empty $_ant_rf\n")














# --- the producer-side sweep -----------------------------------------------











def test_the_sweep_runs_after_every_approach_including_a_killed_one():
    """THE CHEAP SIBLING, and it is a sibling — the artefact tests above are
    the guard. Read with `ast`, not grep: the sweep must be called inside the
    PnR approach loop AHEAD of the stall/ceiling `break`, or a killed approach
    ships its leftovers."""
    import ast
    tree = ast.parse(SRC)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "step_pnr")
    loops = [n for n in ast.walk(fn) if isinstance(n, ast.For)]
    hits = []
    for loop in loops:
        for i, stmt in enumerate(loop.body):
            for sub in ast.walk(stmt):
                if (isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Name)
                        and sub.func.id == "_drop_empty_antenna_reports"):
                    hits.append((loop, i))
    assert hits, "the sweep is not called inside any PnR approach loop"
    loop, idx = hits[0]
    # the stall/ceiling handler is the first `if` naming _RC_STALLED
    stall_idx = next(
        (j for j, st in enumerate(loop.body)
         if any(isinstance(s, ast.Name) and s.id == "_RC_STALLED"
                for s in ast.walk(st))), None)
    assert stall_idx is not None, "the stall handler moved out of this loop"
    assert idx < stall_idx, (
        "the sweep must run BEFORE the stall/ceiling break, or a killed "
        f"approach keeps its empty reports (sweep at {idx}, break at "
        f"{stall_idx})")
