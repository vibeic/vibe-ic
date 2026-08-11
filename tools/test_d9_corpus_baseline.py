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

import sys
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

    def test_crash_and_timeout_are_error(self):
        assert d9.classify(1, "", "Traceback (most recent call last):\n"
                                  "ValueError: x")[0] == d9.ERROR
        assert d9.classify("TIMEOUT", "", "")[0] == d9.ERROR


class TestZeroDenominatorRefuses:
    """The house rule applies to THIS instrument too, not only to what it
    measures: a baseline over nothing must refuse rather than pass."""

    def test_empty_corpus_refuses(self, tmp_path, monkeypatch):
        monkeypatch.setattr(d9, "discover_runs", lambda repo: ([], "stub"))
        monkeypatch.setattr(d9, "discover_checkers", lambda p, y: [])
        rc = d9.main(["--out", str(tmp_path / "o")])
        assert rc == d9.RC_VACUOUS, "a baseline over 0 runs must REFUSE"


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
