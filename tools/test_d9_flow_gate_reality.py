#!/usr/bin/env python3
"""Tests for the D9 flow-gate reality instrument and its page block.

THE DECISION UNDER TEST is the one the published headline turns on: a cell may
be called MOVES only when the step's blocking gate BOTH read something AND
changed its verdict once the step's own declared output was deleted.

Why that conjunction and not the cheaper half: measured on this tree, 59 of 63
steps name a blocking program that calls ``open``/``glob`` somewhere. A
"reads content" test therefore reports 59/63 and means nothing -- it proves the
program is written in Python. The two-arm form reports 31/63. The gap between
those two numbers is the entire deliverable, so it is guarded here rather than
left inline where relaxing it would look like a tidy-up.

Every stdout shape below was HARVESTED from the real sweep published under
``benchmark-data/evaluation/d9_flow_gate_reality/``; none is invented. Where a
test names a step, the docstring names the run that produced the shape so a
reviewer can re-derive it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import d9_flow_gate_reality as d9  # noqa: E402
import gen_flow_gate_d9_section as gen  # noqa: E402

CLEAN, FINDING, NO_INPUT, ERROR = d9.CLEAN, d9.FINDING, d9.NO_INPUT, d9.ERROR


def cell(bucket, rc):
    return {"bucket": bucket, "rc": rc}


class TestAGreenThatSurvivesDeletionIsNotAMeasurement:
    """The RULER-BLIND case, which is the reason this instrument exists.

    Measured on step 14 (``yosys_hilomap_required_check``) against
    ``benchmark-data/evaluation/run_v0153_runner/fixed_priority_arbiter``: arm A
    CLEAN, arm B CLEAN after the step's declared output was removed. The gate
    passes whether or not the artefact it claims to judge is there.
    """

    def test_identical_clean_in_both_arms_does_not_move(self):
        assert d9.verdict_moved(cell(CLEAN, 0), cell(CLEAN, 0)) is False

    def test_identical_finding_in_both_arms_does_not_move(self):
        """Step 36 / step 38: already red for another reason.

        The gate may well be reading something, but nothing here PROVES it
        reads this step's output, and a measurement may not claim what it did
        not show.
        """
        assert d9.verdict_moved(cell(FINDING, 1), cell(FINDING, 1)) is False

    def test_clean_then_absent_does_move(self):
        """The healthy shape: step 3 ``cdc_crossing_check``, 25/25 runs."""
        assert d9.verdict_moved(cell(CLEAN, 0), cell(NO_INPUT, 2)) is True

    def test_clean_then_failing_does_move(self):
        assert d9.verdict_moved(cell(CLEAN, 0), cell(FINDING, 1)) is True

    def test_a_ruler_that_never_read_cannot_move_however_arm_b_lands(self):
        """Step 9: arm A NO-INPUT / ERROR on every run in the denominator set.

        Without this clause a gate that errors in arm A and is absent in arm B
        would score as a mover on the strength of two different failures.
        """
        assert d9.verdict_moved(cell(NO_INPUT, 2), cell(ERROR, None)) is False
        assert d9.verdict_moved(cell(ERROR, None), cell(NO_INPUT, 2)) is False


class TestZeroDenominatorRefusesRatherThanPasses:
    """The house rule (``gate_zero_denominator_refuses_check``): a verdict over
    an empty population is a refusal, never a pass.

    22 of 63 steps have a zero denominator on the published corpus. If those
    scored as MOVES for want of a contradicting observation, the headline would
    read 53/63 and every one of the extra 22 would be a cell that never ran.
    """

    # CAMPAIGN TIER, and here it is also a repair. Both items in this class read
    # `benchmark-data/evaluation/d9_flow_gate_reality/d9_reality.json`, which
    # left this repository in c5d7f2d00. `tools/gatekeeper-land.sh`'s repo-tools
    # arm discovers this file by an UNCONDITIONAL `find tools/`, so on a clean
    # checkout the whole arm was rc=1 and no landing could be stamped. Declared,
    # with subject and owner, in `programs/landing_excluded_corpus.py`.
    @pytest.mark.campaign_tier
    def test_zero_denominator_steps_are_dark_with_that_cause(self):
        report = json.loads(
            (REPO / "benchmark-data" / "evaluation" / "d9_flow_gate_reality"
             / "d9_reality.json").read_text())
        zero = [r for r in report["rows"] if r["denominator"] == 0]
        assert zero, "no zero-denominator step found; corpus shape changed"
        for row in zero:
            assert row["moves_today"] is False, (
                f'{row["step"]}: zero denominator scored as MOVES')
            assert row["cause"] == "DENOMINATOR", (
                f'{row["step"]}: zero denominator blamed on {row["cause"]}')

    @pytest.mark.campaign_tier
    def test_no_cell_claims_to_have_moved_on_more_runs_than_it_probed(self):
        report = json.loads(
            (REPO / "benchmark-data" / "evaluation" / "d9_flow_gate_reality"
             / "d9_reality.json").read_text())
        for row in report["rows"]:
            assert row["runs_moved"] <= row["runs_probed"], row["step"]
            assert row["runs_probed"] <= row["denominator"], row["step"]


class TestThePageMayNotSoftenTheSentence:
    """The block's whole purpose is one sentence. A generator that reflows or
    trims it would leave the page looking finished and saying less.
    """

    def test_the_certification_sentence_is_verbatim(self):
        assert gen.CERTIFIES == (
            "This gate certifies CONSISTENCY AND ATTRIBUTION, "
            "never CORRECTNESS.")

    # NOTE the split inside this class: `test_the_certification_sentence_is_verbatim`
    # above reads ONE module constant and is a genuine landing regression — it
    # stays. The three below render the published block from the absent report.
    @pytest.mark.campaign_tier
    def test_the_rendered_block_carries_it_and_both_belief_lists(self):
        report = json.loads(
            (REPO / "benchmark-data" / "evaluation" / "d9_flow_gate_reality"
             / "d9_reality.json").read_text())
        block = gen.render(report)
        assert gen.CERTIFIES in block
        assert "MAY believe" in block and "MAY NOT believe" in block
        assert "foundry deck would sign it off" in block
        assert "silicon works" in block

    @pytest.mark.campaign_tier
    def test_every_dark_cell_is_rendered_as_dark_with_a_named_cause(self):
        report = json.loads(
            (REPO / "benchmark-data" / "evaluation" / "d9_flow_gate_reality"
             / "d9_reality.json").read_text())
        block = gen.render(report)
        assert block.count('class="d9-dark"') == report["dark"], (
            "the number of rows drawn dark must equal the number measured dark")
        for row in report["rows"]:
            if not row["moves_today"]:
                assert row["cause"] in gen.CAUSES, (
                    f'{row["step"]}: cause {row["cause"]} has no rendering, so '
                    "the page would show a dark cell with no reason")

    @pytest.mark.campaign_tier
    def test_the_block_does_not_claim_d9_is_shipped(self):
        report = json.loads(
            (REPO / "benchmark-data" / "evaluation" / "d9_flow_gate_reality"
             / "d9_reality.json").read_text())
        block = gen.render(report)
        assert "D9 不是一個已經出貨的維度" in block
        assert "PLANNED" in block


class TestNoMeasuredNumberInTheBlockIsHandTyped:
    """A literal typed into the prose beside a derived cell is this page's own
    defect, committed inside the section that exists to name it.

    It cannot fail on the day it is written -- the two copies agree -- and it
    fails silently on every day after.  MEASURED here: the generator printed
    the derived ``all_py_in_programs`` in the comparison table and a hand-typed
    copy of the same number in the sentence beside it.  Rebasing this branch
    onto main moved the tree from 1133 tracked ``.py`` files to 1134; the
    derived cell followed and the sentence did not.

    ``--check`` cannot catch this: it compares the page against the block the
    generator renders, and both sides carry the same stale literal.
    """

    def _report(self):
        return json.loads(
            (REPO / "benchmark-data" / "evaluation" / "d9_flow_gate_reality"
             / "d9_reality.json").read_text())

    @pytest.mark.campaign_tier
    @pytest.mark.parametrize(
        "field", ["on_disk", "all_py_in_programs", "referenced_by_flow"])
    def test_moving_the_measurement_moves_every_copy_in_the_block(self, field):
        report = self._report()
        stale = str(report["programs"][field])
        assert stale in gen.render(report), (
            f"{field} is not printed at all; this test would pass vacuously")

        moved = json.loads(json.dumps(report))
        moved["programs"][field] += 1
        after = gen.render(moved)

        assert str(moved["programs"][field]) in after
        assert stale not in after, (
            f"programs.{field}: the block still prints {stale} after the "
            f"measurement moved to {moved['programs'][field]} -- that copy is "
            "hand-typed, not derived, and will drift with the next commit")


class TestDriftIsDetected:
    """``--check`` is the only thing standing between this block and the
    hand-typed total the page's masthead warns about.
    """

    @pytest.mark.campaign_tier
    def test_check_fails_when_the_page_block_no_longer_matches(self, tmp_path):
        reality = (REPO / "benchmark-data" / "evaluation"
                   / "d9_flow_gate_reality" / "d9_reality.json")
        report = json.loads(reality.read_text())
        page = tmp_path / "p.html"
        page.write_text("<style>\n</style>\n"
                        "<!-- END GENERATED SCORE -->\n</div>\n")
        page.write_text(gen.install(page.read_text()))
        page.write_text(gen.splice(page.read_text(), gen.render(report)))

        ok = subprocess.run(
            [sys.executable, str(TOOLS / "gen_flow_gate_d9_section.py"),
             "--reality", str(reality), "--page", str(page), "--check"],
            capture_output=True, text=True)
        assert ok.returncode == 0, ok.stderr

        page.write_text(page.read_text().replace(
            '<div class="n">31</div>', '<div class="n">63</div>'))
        drifted = subprocess.run(
            [sys.executable, str(TOOLS / "gen_flow_gate_d9_section.py"),
             "--reality", str(reality), "--page", str(page), "--check"],
            capture_output=True, text=True)
        assert drifted.returncode == 1, (
            "a page edited to flatter the headline passed --check")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
