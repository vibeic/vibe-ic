#!/usr/bin/env python3
"""A4 must not report a block as clean when the block's own record says the
simulation FAILED against a concrete numeric target.

THE DEFECT (chip-AGNOSTIC, reproduced here on synthetic artefacts only).
`analog_a4_corner_sweep_check` accepts `status: PASS_INFORMATIONAL`. Its own
rationale (v1.6.223 / #96) states why:

    "the block has no fixed numeric target by design … semantically 'sim ran,
     no target to compare against'"

That premise is false about the artefacts its own producer writes.
`analog_real_corner_sweep` computes a three-valued verdict and then flattens it
to two before writing:

    spec_status = verdict if verdict in ("PASS","PASS_INFORMATIONAL") \\
                            else "PASS_INFORMATIONAL"

so `PASS_INFORMATIONAL` on disk means EITHER "no target" (the intended case)
OR "missed a real target" (a rewritten FAIL). The real verdict survives only in
`raw_sim_verdict`, which no consumer read — making the gate's `status == "FAIL"`
branch unreachable against any artefact the producer emits.

THE FIX discriminates on the property the premise actually names — is there a
concrete numeric target? — rather than on the label.

DIRECTION OF RISK. This is a guard TIGHTENING, so the mirror image of the §4.05
no-leak proof applies: the danger is OVER-firing, i.e. newly failing a record
that is legitimately informational. The negative set below is therefore built
from records that sit just inside the exemption and MUST still pass.

Every fixture is SYNTHETIC — invented block names, invented metric names,
invented numbers. No design, PDK SKU, vendor or part number appears.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
GATE = PROGRAMS / "analog_a4_corner_sweep_check.py"


def _corner(name, value, sim_run=True):
    return {"name": name, "process": name.split("_")[0],
            "temp_c": 27, "simulator_run": sim_run,
            "value": value, "margin": 0.1,
            "_provenance": "real_ngspice"}


# A4's declared upstream input: A3's per-block netlist. A project that has A4
# results also has this file — the sweep cannot have measured a design whose
# netlist was never produced, and the gate's A4_NETLIST_ABSENT rule says so.
# These fixtures are about the raw_sim_verdict rule, so they carry the netlist
# a complete run would have and let that rule be the one under test.
_A3_NETLIST = (
    "* {block} — synthetic block netlist (A4's declared upstream input)\n"
    ".subckt {block} vdd vss vin vout\n"
    "xm1 vout vin vss vss nch w=8 l=1\n"
    "r1 vout vss 100k\n"
    ".ends {block}\n")


def _write_project(tmp, blocks):
    """Build a minimal synthetic project the gate can read."""
    proj = Path(tmp)
    adir = proj / "phase3" / "analog"
    adir.mkdir(parents=True)
    (adir / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": b, "type": b} for b in blocks]}), encoding="utf-8")
    for name, payload in blocks.items():
        d = adir / name
        d.mkdir()
        (d / "corner_results.json").write_text(json.dumps(payload),
                                               encoding="utf-8")
        (d / f"{name}.sp").write_text(_A3_NETLIST.format(block=name),
                                      encoding="utf-8")
    return proj


def _base(block, spec, corners=None):
    return {
        "block": block, "block_type": block,
        "_provenance": "real_ngspice",
        # The four NEGATIVE controls below assert that a record just inside the
        # raw_sim_verdict exemption is NOT newly failed. Without this field
        # they were passing for a second reason as well — an artefact that
        # declares simulated corners and will not say what circuit produced
        # them does not certify — and a negative control that would hold for a
        # reason other than the one it names is not a control. The record says
        # what it contains so the raw_sim_verdict rule is the only thing under
        # test; `test_disclosure_is_what_makes_these_negative_controls_negative`
        # pins that the field is doing that job and not papering over one.
        "design_content": "structure_and_geometry",
        "total_corners": 3, "results_found": 3,
        "corners": corners or [_corner("tt_27c", 1.0),
                               _corner("ss_27c", 1.0),
                               _corner("ff_27c", 1.0)],
        "spec_results": [spec],
    }


def _run_gate(proj):
    r = subprocess.run([sys.executable, str(GATE), str(proj)],
                       capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)


class TestRawSimFailNotMasked(unittest.TestCase):

    # ── POSITIVE: the defect ──────────────────────────────────────────────

    def test_masked_raw_fail_against_concrete_target_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _write_project(tmp, {"synth_alpha": _base(
                "synth_alpha",
                {"name": "metric_a", "status": "PASS_INFORMATIONAL",
                 "raw_sim_verdict": "FAIL", "value": 0.5, "target": 2.0,
                 "target_source": "static_default", "tolerance_pct": 0.1})})
            rc, out = _run_gate(proj)
            self.assertEqual(rc, 1,
                             "a rewritten FAIL against a real target was "
                             "reported clean\n---\n%s" % out)
            self.assertIn("A4_RAW_SIM_FAIL_MASKED", out)

    def test_masked_raw_fail_with_a_spec_backed_target_is_also_caught(self):
        """A target that came from the design's own layer is not an excuse."""
        with tempfile.TemporaryDirectory() as tmp:
            proj = _write_project(tmp, {"synth_beta": _base(
                "synth_beta",
                {"name": "metric_b", "status": "PASS_INFORMATIONAL",
                 "raw_sim_verdict": "FAIL", "value": 9.0, "target": 1.0,
                 "target_source": "L5", "tolerance_pct": 0.05})})
            rc, out = _run_gate(proj)
            self.assertEqual(rc, 1, out)
            self.assertIn("A4_RAW_SIM_FAIL_MASKED", out)

    def test_the_report_names_the_measurement_and_the_target(self):
        """A verdict a reader cannot act on is only half a verdict."""
        with tempfile.TemporaryDirectory() as tmp:
            proj = _write_project(tmp, {"synth_gamma": _base(
                "synth_gamma",
                {"name": "metric_c", "status": "PASS_INFORMATIONAL",
                 "raw_sim_verdict": "FAIL", "value": 0.25, "target": 4.0,
                 "target_source": "static_default", "tolerance_pct": 0.2})})
            rc, out = _run_gate(proj)
            self.assertEqual(rc, 1, out)
            self.assertIn("0.25", out)
            self.assertIn("4.0", out)

    # ── NEGATIVE / no-over-fire: these MUST still pass ────────────────────
    # Boundary-outside cases: structurally near what the new rule catches,
    # differing only in the property that must keep them exempt.

    def test_no_target_informational_still_passes(self):
        """The case v1.6.223 exists for: nothing to compare against."""
        with tempfile.TemporaryDirectory() as tmp:
            proj = _write_project(tmp, {"synth_delta": _base(
                "synth_delta",
                {"name": "metric_d", "status": "PASS_INFORMATIONAL",
                 "raw_sim_verdict": "PASS_INFORMATIONAL", "value": 0.03,
                 "target": None, "target_source": "static_default",
                 "tolerance_pct": None})})
            rc, out = _run_gate(proj)
            self.assertEqual(rc, 0,
                             "a genuinely no-target block was newly failed — "
                             "the tightening over-fired\n---\n%s" % out)

    def test_a_null_target_with_a_raw_fail_label_still_passes(self):
        """Boundary: the raw label says FAIL but there is no target.

        Without a target there is nothing the miss could be a miss OF, so the
        record cannot support a failure verdict and must not manufacture one.
        """
        with tempfile.TemporaryDirectory() as tmp:
            proj = _write_project(tmp, {"synth_eps": _base(
                "synth_eps",
                {"name": "metric_e", "status": "PASS_INFORMATIONAL",
                 "raw_sim_verdict": "FAIL", "value": 0.03,
                 "target": None, "target_source": "static_default",
                 "tolerance_pct": None})})
            rc, out = _run_gate(proj)
            self.assertEqual(rc, 0, out)

    def test_a_real_pass_against_a_real_target_still_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _write_project(tmp, {"synth_zeta": _base(
                "synth_zeta",
                {"name": "metric_f", "status": "PASS",
                 "raw_sim_verdict": "PASS", "value": 1.01, "target": 1.0,
                 "target_source": "L5", "tolerance_pct": 0.05})})
            rc, out = _run_gate(proj)
            self.assertEqual(rc, 0, out)

    def test_a_legacy_record_without_raw_sim_verdict_still_passes(self):
        """An older artefact carries no preserved verdict.

        Absence of evidence is not evidence of failure — the gate must not
        invent one for a record shape that predates the field.
        """
        with tempfile.TemporaryDirectory() as tmp:
            proj = _write_project(tmp, {"synth_eta": _base(
                "synth_eta",
                {"name": "metric_g", "status": "PASS_INFORMATIONAL",
                 "value": 0.5, "target": 2.0,
                 "target_source": "static_default", "tolerance_pct": 0.1})})
            rc, out = _run_gate(proj)
            self.assertEqual(rc, 0, out)

    def test_disclosure_is_what_makes_these_negative_controls_negative(self):
        """The control ON the controls.

        Take the negative control that is furthest inside the exemption, remove
        the ONE field `_base` gained and change nothing else. If it still
        certified, that field would be decoration and the four controls above
        would be passing partly by accident.
        """
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base(
                "synth_iota",
                {"name": "metric_i", "status": "PASS_INFORMATIONAL",
                 "raw_sim_verdict": "PASS_INFORMATIONAL", "value": 0.03,
                 "target": None, "target_source": "static_default",
                 "tolerance_pct": None})
            self.assertEqual(payload.pop("design_content"),
                             "structure_and_geometry")
            proj = _write_project(tmp, {"synth_iota": payload})
            rc, out = _run_gate(proj)
            self.assertEqual(
                rc, 1,
                "an artefact declaring simulated corners, whose netlist is on "
                "disk, that will not say what circuit produced the numbers, "
                "was certified\n---\n%s" % out)
            self.assertIn("A4_DESIGN_CONTENT_UNDECLARED", out)

    def test_an_already_explicit_fail_is_left_to_the_existing_rule(self):
        """A record that already says FAIL is the pre-existing branch's job.

        The new rule must not double-report it under a different rule name, or
        the two rules would disagree about who owns the finding.
        """
        with tempfile.TemporaryDirectory() as tmp:
            proj = _write_project(tmp, {"synth_theta": _base(
                "synth_theta",
                {"name": "metric_h", "status": "FAIL",
                 "raw_sim_verdict": "FAIL", "value": 0.5, "target": 2.0,
                 "target_source": "L5", "tolerance_pct": 0.1})})
            rc, out = _run_gate(proj)
            self.assertEqual(rc, 1, out)
            self.assertIn("A4_NO_PASS_SPEC", out)
            self.assertNotIn("A4_RAW_SIM_FAIL_MASKED", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
