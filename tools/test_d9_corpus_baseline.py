#!/usr/bin/env python3
"""Tests for the D9 corpus-baseline instrument.

THE DECISION UNDER TEST is the one the deliverable turns on: an ``rc 0``
because the artefact was absent must NOT be recorded as the same fact as an
``rc 0`` because the content was read and found clean.

Every stdout shape asserted below was HARVESTED FROM REAL CORPUS OUTPUT during
the sweep this instrument published -- none is invented.  The provenance is
named per test so a reviewer can re-derive it by running the gate named in the
docstring against a published run.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d9_corpus_baseline as d9  # noqa: E402


class TestSelfDisclosedSkipOutranksExitCode:
    """rc 0 + "I read nothing" must land in NO-INPUT, not CLEAN.

    Without this, a gate that examined nothing across the whole corpus reads as
    quiet-and-safe, and gets promoted to BLOCKING on a denominator of zero.
    """

    @pytest.mark.parametrize("out,src", [
        # crc_residue_settle_state_required_check on any published run
        ("[SKIP] crc_residue_settle_state_required_check\n"
         "  files scanned: 0\n  [INFO] NO_FSM_FILE: no FSM RTL file",
         "bracket-SKIP line"),
        # phy_counter_audit on a run with no rtl/
        ('{"verdict": "SKIP", "reason": "no RTL files", "pass": true}',
         "JSON SKIP verdict"),
        # send_test_active_drive_check on a non-protocol design
        ("PASS_SKIP — no SEND_TEST-class opcode found in L3", "PASS_SKIP line"),
        # tx_bit_width_min_resolution_check
        ("PASS — chip TX clock period not declared (gate skipped).",
         "prose 'gate skipped'"),
        # the house contract in programs/_gate_denominator.py
        ('{"denominator": {"examined": 0, "unit": "file", '
         '"not_applicable_reason": "no rtl/"}}', "house denominator block"),
    ])
    def test_rc_zero_that_examined_nothing_is_no_input(self, out, src):
        bucket, why = d9.classify(0, out, "")
        assert bucket == d9.NO_INPUT, f"{src}: got {bucket} -- {why}"

    @pytest.mark.parametrize("rc,out", [
        # em_current_density_check with no Jmax reference
        (3, '{"findings": [{"severity": "SKIPPED", '
            '"rule": "JMAX_REFERENCE_ABSENT"}]}'),
        # spec_declaration_emit on a project with no field table
        (3, "spec_declaration_emit: NO_CONTRACT — nothing was written."),
    ])
    def test_rc_three_skipped_tier_is_no_input_not_error(self, rc, out):
        """rc 3 carrying a SKIPPED disclosure is 'no input', not a crash.

        Counting it as ERROR would inflate could-not-measure and hide that the
        gate behaved correctly -- it declined to fabricate a verdict.
        """
        assert d9.classify(rc, out, "")[0] == d9.NO_INPUT


class TestCleanStillMeansClean:
    """The skip rule must not swallow real results -- both directions matter."""

    def test_rc_zero_with_a_stated_denominator_is_clean(self):
        assert d9.classify(0, "examined 66 file(s) under 'rtl/'", "")[0] == d9.CLEAN

    def test_a_gate_that_fired_is_a_finding_even_with_a_skipped_subitem(self):
        """rc 1 is NOT skip-overridable.

        A report can skip one sub-item and still FAIL on another.  Letting a
        stray "[SKIP]" downgrade the whole cell would erase real findings --
        the same conflation as the headline defect, pointed the other way.
        """
        out = ("FAIL: 2 unacknowledged step-internal FAIL(s):\n"
               "  [SKIP] one sub-probe had no input")
        assert d9.classify(1, out, "")[0] == d9.FINDING


class TestCouldNotMeasureIsReportedNotDropped:
    """"Could not run" is a RESULT and must stay in the denominator."""

    def test_argparse_refusal_is_error_with_its_reason(self):
        err = ("usage: analog_mc_yield_run.py [-h] --block BLOCK\n"
               "analog_mc_yield_run.py: error: the following arguments are "
               "required: --block")
        bucket, why = d9.classify(2, "", err)
        assert bucket == d9.ERROR
        assert "could not measure" in why and "--block" in why

    def test_crash_and_a_cell_that_stopped_moving_are_error(self):
        assert d9.classify(1, "", "Traceback (most recent call last):\n"
                                  "ValueError: x")[0] == d9.ERROR
        assert d9.classify("STALLED", "", "")[0] == d9.ERROR
        # The pre-#2051 marker is still READ, so a row in a published baseline
        # measured under the old wall clock re-classifies to the bucket it had.
        assert d9.classify("TIMEOUT", "", "")[0] == d9.ERROR


class TestZeroDenominatorRefuses:
    """The house rule applies to THIS instrument too, not only to what it
    measures: a baseline over nothing must refuse rather than pass."""

    def test_empty_corpus_refuses(self, tmp_path, monkeypatch):
        monkeypatch.setattr(d9, "discover_runs", lambda repo: ([], "stub"))
        monkeypatch.setattr(d9, "discover_checkers", lambda p, y: [])
        rc = d9.main(["--out", str(tmp_path / "o")])
        assert rc == d9.RC_VACUOUS, "a baseline over 0 runs must REFUSE"


FIXTURE_FLOW = (Path(__file__).resolve().parent
                / "fixtures" / "d9_wiring" / "flow_wiring_shapes.yaml")


class TestWiringIsStructuralNotTextual:
    """vibe-ic#1012 — "the flow drives it" is a gate clause, not a mention.

    `discover_checkers` defines the DENOMINATOR of the published D9 baseline, so
    a name that merely APPEARS in the YAML text silently removes a checker from
    the population.  The reported instance: a step-36 comment naming
    `l20_dft_scan_topology_actionable_check`, written to explain why that
    checker was NOT wired, made the instrument call it wired — documenting a
    hold made the held checker invisible to the tool that measures holds.

    Both directions are asserted.  A test that only proves comments stop
    counting would also pass against a predicate that counts NOTHING as wired,
    which would inflate the denominator by the whole program directory.
    """

    def test_a_gate_clause_command_is_wiring(self):
        """The WIRED half of the fixture — all four gate-clause shapes."""
        driven = d9.flow_driven_programs(FIXTURE_FLOW)
        for name in ("fx_wired_bare_check", "fx_wired_dict_check",
                     "fx_wired_advisory_check", "fx_wired_nested_check",
                     "fx_final_gate_check"):
            assert name in driven, f"{name} is invoked by a gate clause"

    @pytest.mark.parametrize("name,shape", [
        ("fx_comment_only_check", "named ONLY in a comment (#1012 verbatim)"),
        ("fx_description_field_check", "named in a description: field"),
        ("fx_notes_field_check", "named in a notes: string"),
        ("fx_roster_only_check", "step-level programs: roster, no gate clause"),
        ("fx_path_arg_check", "a PATH ARGUMENT inside a wired command string"),
        ("fx_wired_bare", "a strict PREFIX of a wired program's name"),
    ])
    def test_a_mention_is_not_wiring(self, name, shape):
        """The UNWIRED half — every shape that a substring test would swallow."""
        assert name in FIXTURE_FLOW.read_text(), (
            f"fixture must actually contain {name!r} in text, else this "
            f"asserts nothing")
        assert name not in d9.flow_driven_programs(FIXTURE_FLOW), shape

    def test_held_checker_documented_in_a_comment_stays_in_the_population(self):
        """The reported defect, against the REAL flow YAML.

        `l20_dft_scan_topology_actionable_check` is named by a step-36 comment
        and by no gate clause, so it is a candidate and must be measurable.
        """
        held = "l20_dft_scan_topology_actionable_check"
        assert held in d9.FLOW_YAML.read_text(), (
            "premise gone: the comment naming the held checker was removed; "
            "re-point this test at whichever checker is held-and-documented "
            "today, or delete it")
        assert held not in d9.flow_driven_programs(d9.FLOW_YAML)
        names = {c["name"] for c in
                 d9.discover_checkers(d9.PROGRAMS, d9.FLOW_YAML)}
        assert held in names, "a documented hold must stay measurable"

    @pytest.mark.parametrize("name", [
        "l6_fsm_scaffold_actionable_check",
        "l9_submodule_conformance_check",
    ])
    def test_genuinely_wired_neighbours_stay_wired(self, name):
        """THE PAIRED GUARD.

        The same comment block that names the held checker also names these
        two.  Under the defect they were excluded for the WRONG reason (their
        name appeared in text) and the outcome happened to be right, because
        they are also genuinely wired.  After the fix they must still be
        excluded — now for the right reason, an `advisory_program_exit_zero`
        clause each.  Without this pair, "stop counting comments" could be
        satisfied by a predicate that stopped counting the real clause too.
        """
        driven = d9.flow_driven_programs(d9.FLOW_YAML)
        assert name in driven, f"{name} is wired by a real gate clause"
        names = {c["name"] for c in
                 d9.discover_checkers(d9.PROGRAMS, d9.FLOW_YAML)}
        # MEASURED, by this fix's own mutation control: an "always wired"
        # mutant EMPTIES the population, and `name not in names` below is then
        # satisfied VACUOUSLY -- right answer, wrong reason, which is the exact
        # failure this class exists to rule out, one level up. So the exclusion
        # only counts as evidence against a population that still has members.
        assert len(names) > 1, (
            "population collapsed -- the assertion below would pass vacuously, "
            "which is not evidence that a gate clause was read")
        assert name not in names, f"{name} is driven, so it is not a candidate"

    def test_the_predicate_is_the_house_one_not_a_private_copy(self):
        """Imported from `flow_compliance_check`, so the instrument and the
        flow runner cannot drift into two dialects of "wired"."""
        from flow_compliance_check import _declared_gate_commands as house
        assert d9._declared_gate_commands is house


class TestATimedOutCellLeavesNoOrphanWriting:
    """A cell that STOPPED MOVING must take its GRANDCHILDREN with it.

    Not hypothetical, and not found by review: it is what happened the first
    time the corrected population (#1012) was swept. `subprocess.run(timeout=)`
    kills the direct child only, and the corrected wiring test admitted the
    runner-class programs — every one of which the substring hit had excluded,
    and every one of which spawns children. A timed-out runner left
    grandchildren writing into the throwaway copy; the copy's cleanup then
    raised `OSError: [Errno 39] Directory not empty: 'reports'`, which
    propagated out of the worker and killed the sweep at cell 8500 of 9202.
    """

    #: A program that spawns a child which writes a BURST and then goes quiet,
    #: and itself blocks forever. The child is deliberately NOT waited on —
    #: that is the shape under test. The burst is what makes the assertion
    #: non-vacuous (a spawner that never wrote would prove nothing); the quiet
    #: afterwards is what lets the whole tree become motionless, which is the
    #: only thing that may now stop a cell.
    SPAWNS_AN_ORPHAN = """
import subprocess, sys, time, pathlib
out = sys.argv[1]
child = subprocess.Popen([sys.executable, "-u", "-c",
                  "import sys,time,pathlib\\n"
                  "d=pathlib.Path(sys.argv[1])\\n"
                  "for i in range(5):\\n"
                  "    (d/('f%d.txt' % i)).write_text('x')\\n"
                  "    time.sleep(0.05)\\n"
                  "time.sleep(600)\\n", out])
(pathlib.Path(out) / "orphan.pid").write_text(str(child.pid))
time.sleep(600)
"""

    #: A cell that KEEPS MOVING for a while and then exits on its own. Under
    #: the wall clock this was killed at `timeout` and recorded ERROR; under
    #: the supervisor it is never stopped, because something advanced at every
    #: look.
    KEEPS_MOVING = """
import sys, time
for i in range(12):
    print("tick", i, flush=True)
    time.sleep(0.1)
sys.exit(0)
"""

    @staticmethod
    def _tight(monkeypatch, looks=4, poll_s=0.25):
        """Only the SPACING moves. The predicate is still "every readable
        signal sat still for `looks` consecutive looks"."""
        monkeypatch.setattr(d9, "CELL_STALL_LOOKS", looks)
        monkeypatch.setattr(d9, "CELL_POLL_S", poll_s)

    def test_a_cell_that_stopped_moving_takes_its_whole_group(
            self, tmp_path, monkeypatch):
        prog = tmp_path / "spawner.py"
        prog.write_text(self.SPAWNS_AN_ORPHAN)
        work = tmp_path / "work"
        work.mkdir()
        self._tight(monkeypatch)

        cell = d9.run_cell(prog, [str(work)], timeout=3600)
        assert cell["rc"] == "STALLED"
        assert cell["bucket"] == d9.ERROR, (
            "a cell that stopped moving is a could-not-measure")

        # The orphan wrote its burst while the parent ran; if the group died
        # with the parent, the count is FROZEN from here on — and if it did
        # not, the orphan is a live process holding the throwaway copy open,
        # which is the failure that killed the sweep at cell 8500 of 9202.
        wrote = [f for f in work.iterdir() if f.name.startswith("f")]
        assert wrote, ("the orphan never wrote at all -- this test would "
                       "pass vacuously against a broken spawner")
        orphan = int((work / "orphan.pid").read_text().strip())
        # LOOKS, NOT A CLOCK, and the distinction is this repo's own: a
        # deadline here would be a wall clock deciding a verdict inside the
        # test that exists to remove one — and `watchdog_ceiling_semantics_check`
        # says so by refusing it (MEASURED: this loop, written with
        # `while time.time() < deadline`, came back OFFENDER 1
        # `clock_guarded_kill` on this very file).
        for _ in range(50):
            try:
                os.kill(orphan, 0)
            except ProcessLookupError:
                break
            time.sleep(0.2)
        else:                                      # pragma: no cover - failure
            raise AssertionError(
                f"orphan {orphan} still alive across 50 looks after the cell "
                f"was stopped; the process group survived")

    def test_a_cell_that_keeps_moving_is_never_stopped(
            self, tmp_path, monkeypatch):
        """THE OTHER DIRECTION, and the reason the clock had to go.

        Same cadence, same file, ONE difference: this cell keeps producing.
        Its RECORDED BUDGET is 1 s and it runs for about 1.2 s — under the wall
        clock that was ERROR "timed out", a property of the machine written
        into the corpus as a property of the checker.
        """
        prog = tmp_path / "worker.py"
        prog.write_text(self.KEEPS_MOVING)
        self._tight(monkeypatch)
        cell = d9.run_cell(prog, [], timeout=1)
        assert cell["rc"] == 0, cell
        assert cell["bucket"] != d9.ERROR, cell

    def test_a_copy_an_orphan_holds_open_is_reported_not_raised(self, tmp_path):
        """`_rmtree_stubborn` returns a REASON; it never raises.

        A leaked scratch dir costs disk and says an orphan outlived its cell.
        It cannot touch the corpus — `assert_corpus_pristine` proves that
        separately — so withdrawing thousands of measured cells over it would
        be the wrong trade, and crashing the sweep over it is worse.
        """
        assert d9._rmtree_stubborn(tmp_path / "never-existed", tries=1) is not None
        real = tmp_path / "real"
        (real / "reports").mkdir(parents=True)
        (real / "reports" / "r.json").write_text("{}")
        assert d9._rmtree_stubborn(real) is None
        assert not real.exists()


class TestGeneratedRtlIsNeverTheInputRtl:
    """§4.05-adjacent: pair the generated spec with the run's OWN RTL.

    MEASURED: plain alphabetical rglob returns `input/design_src/verilog/rtl`
    before `phase2/stage1/rtl`, which made a checker fail a comparison nobody
    asked for -- a wrong ruler introduced by the instrument itself.
    """

    def test_phase2_rtl_wins_over_input_rtl(self, tmp_path):
        for rel in ("input/design_src/verilog/rtl", "phase2/stage1/rtl"):
            d = tmp_path / rel
            d.mkdir(parents=True)
            (d / "m.v").write_text("module m(); endmodule\n")
        got = d9.locate_rtl_dir(tmp_path)
        assert got == tmp_path / "phase2/stage1/rtl", got

    def test_input_only_rtl_is_not_offered_at_all(self, tmp_path):
        d = tmp_path / "input/design_src/verilog/rtl"
        d.mkdir(parents=True)
        (d / "m.v").write_text("module m(); endmodule\n")
        assert d9.locate_rtl_dir(tmp_path) is None
