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
from _tool_probes import skip_not_verified  # noqa: E402

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

import shutil                                                   # noqa: E402
import subprocess                                               # noqa: E402
import types                                                    # noqa: E402

import pytest                                                   # noqa: E402

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


def _tclsh():
    exe = shutil.which("tclsh") or shutil.which("tclsh8.6")
    if not exe:
        # DECLARED, not merely skipped (vibe-ic#1128). Without the stamp this
        # reads to the roll-up as a question that was ASKED and passed, and the
        # failure mode the tier exists for is exactly a host that quietly has
        # no tclsh: the antenna block is then never driven and nothing says so.
        skip_not_verified(
            "no tclsh on PATH — the emitted antenna block cannot be driven "
            "here",
            "run this inside the pinned EDA image, which ships tclsh 8.6, or "
            "install tclsh8.6 on this host")
    return exe


def _drive(tmp_path, *, seq="3 0", body="", mutate=False):
    """Run the REAL emitted antenna block against stubbed tool commands.

    Returns the run directory the block was told to write its reports into.
    """
    run_dir = tmp_path / "pnr"
    run_dir.mkdir(exist_ok=True)
    pdk = types.SimpleNamespace(antenna_diode_cell="ANTENNA_DIODE")
    block = R._antenna_repair_tcl(pdk, str(run_dir))
    assert "check_antennas" in block, "the emitted block drives no tool"
    if mutate:
        assert _LOOP_CLEANUP in block, "mutation anchor moved"
        block = block.replace(
            _LOOP_CLEANUP,
            "    set _ant_now [_vic_ant_nets $_ant_rf $_nv]\n", 1)
    script = tmp_path / "drive.tcl"
    script.write_text(_TOOL_STUBS.format(seq="{%s}" % seq,
                                         body='{%s}' % body) + block)
    cp = subprocess.run([_tclsh(), str(script)], capture_output=True,
                        text=True, timeout=300)
    # The block ends on its own sentinel; anything else means the drive
    # itself failed and the artefact assertion below would be vacuous.
    assert "ANTENNA_POSTROUTE_DONE" in cp.stdout, (cp.returncode, cp.stdout,
                                                   cp.stderr)
    return run_dir


def _iter_reports(run_dir):
    return sorted(p.name for p in run_dir.glob("antenna_iter_*.rpt"))


def test_a_driven_run_that_would_emit_an_empty_report_leaves_no_such_file(
        tmp_path):
    """THE ARTEFACT ASSERTION. Two iterations, both writing a 0-byte report —
    the exact `[3, 0]` shape that published `antenna_iter_{0,1}.rpt` — end with
    NO antenna iteration report on disk."""
    run_dir = _drive(tmp_path, seq="3 0", body="")
    assert _iter_reports(run_dir) == [], (
        "the emitted block left an empty antenna report behind: "
        f"{_iter_reports(run_dir)}")


def test_the_same_run_with_the_cleanup_removed_leaves_the_two_empty_reports(
        tmp_path):
    """THE MUTATION ARM, EXECUTED. Strip the cleanup call the loop's normal
    path exercises and the defect comes back byte-for-byte: two 0-byte
    `antenna_iter_{0,1}.rpt`, which is exactly what vibe-ic#2157 published. An
    assertion that cannot be made to fail is not an assertion."""
    run_dir = _drive(tmp_path, seq="3 0", body="", mutate=True)
    left = _iter_reports(run_dir)
    assert left == ["antenna_iter_0.rpt", "antenna_iter_1.rpt"], left
    assert all((run_dir / n).stat().st_size == 0 for n in left)


def test_a_driven_run_whose_report_has_content_keeps_it(tmp_path):
    """THE CONTROL. A run WITH antenna violations writes a real report and must
    still have it afterwards — the sweep is on SIZE, never on the name."""
    run_dir = _drive(tmp_path, seq="3 0", body="Net: n1\nNet: n2\nNet: n3\n")
    left = _iter_reports(run_dir)
    assert left == ["antenna_iter_0.rpt", "antenna_iter_1.rpt"], left
    assert all((run_dir / n).stat().st_size > 0 for n in left)


# --- the producer-side sweep -----------------------------------------------

def _rbsub6_shape(tmp_path):
    """The published shape of vibe-ic#2157, including the SIX other reports
    that sit in the same directory and are legitimately empty."""
    d = tmp_path / "pnr"
    d.mkdir()
    for n in ("antenna_iter_0.rpt", "antenna_iter_1.rpt"):
        (d / n).write_bytes(b"")
    for n in ("pnr_fanout_root_candidates.rpt", "routed_router.drc.rpt",
              "routed_router.drc.iter1.rpt", "sdr_drv.rpt",
              "sdr_fanout_root_candidates.rpt",
              "signoff_repair_fanout_candidates.rpt"):
        (d / n).write_bytes(b"")
    (d / "antenna_iter_final.rpt").write_text(
        "openroad\nNet: n1\n" + "x" * 400)
    return d


def test_a_planted_zero_byte_antenna_report_is_removed_by_name(tmp_path):
    """The escape vibe-ic#2157 measured was a PREVIOUS `step_pnr` invocation's
    leftover: the run's own PDN EM resize re-ran PnR, and the second invocation
    printed `ANTENNA_ALREADY_CLEAN` at both antenna stages, so it never
    re-entered the loop that owns the in-session cleanup. The producer sweeps
    the directory instead, and names what it removed."""
    d = _rbsub6_shape(tmp_path)
    dropped = R._drop_empty_antenna_reports(d)
    assert dropped == ["antenna_iter_0.rpt", "antenna_iter_1.rpt"], dropped
    assert not (d / "antenna_iter_0.rpt").exists()
    assert not (d / "antenna_iter_1.rpt").exists()


def test_the_sweep_touches_nothing_else_in_the_directory(tmp_path):
    """THE POPULATION CONTROL. Six other reports in that same directory are
    0 bytes and MUST stay: for them, empty IS the answer. And an antenna report
    WITH content is never removed."""
    d = _rbsub6_shape(tmp_path)
    before = sorted(p.name for p in d.iterdir())
    R._drop_empty_antenna_reports(d)
    after = sorted(p.name for p in d.iterdir())
    assert set(before) - set(after) == {"antenna_iter_0.rpt",
                                        "antenna_iter_1.rpt"}, (before, after)
    assert (d / "antenna_iter_final.rpt").read_text().startswith("openroad")


def test_the_sweep_is_a_no_op_on_a_clean_directory(tmp_path):
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "antenna_iter_0.rpt").write_text("openroad\nNet: n1\n")
    assert R._drop_empty_antenna_reports(d) == []
    assert (d / "antenna_iter_0.rpt").exists()


def test_the_sweep_says_out_loud_what_it_removed(tmp_path, capsys):
    """DEGRADE LOUDLY. A file that vanishes with nobody told is the same class
    of defect as a file that survives with nobody told."""
    d = _rbsub6_shape(tmp_path)
    R._drop_empty_antenna_reports(d)
    out = capsys.readouterr().out
    assert "ANTENNA_EMPTY_REPORT_DROPPED" in out
    assert "antenna_iter_0.rpt" in out and "antenna_iter_1.rpt" in out


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
