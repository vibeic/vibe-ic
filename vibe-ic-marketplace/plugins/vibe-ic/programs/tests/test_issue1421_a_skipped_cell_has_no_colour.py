#!/usr/bin/env python3
"""vibe-ic#1421 — a SKIPPED cell was scored 0, so an unmeasured mutant arm read
as "the recorded mutation stopped reddening its witness".

THE DEFECT
==========
`matrix_mutation_ledger._cell_rc_from_report` turned pytest's report of the one
cell into a colour. Three outcomes are a colour — passed, failed, errored — and
four shapes already refused to be one: a missing report, an unparseable report,
a report carrying the wrong number of testcases (#1412), and a cell killed by
its bound (#1403). `skipped` was the last outcome still being given a colour,
and it was given 0 on this argument:

    "the two locks that consume this ask whether the cell went PASS -> FAIL,
    and a skip is not a fail. It is only ever a witness's BASELINE that could
    be skipped, and LOCK 2's `proved` still requires the mutant arm to go
    non-zero with the declared signal, so a skip cannot manufacture a red."

The final sentence is false. A cell test's skip conditions are properties of the
CHECKOUT, not of the mutation — dimension 3's cell skips when the published
corpus is not in this tree, which is its honest answer since the result cells
moved to `vibeic/benchmark-data` — so they hold on BOTH arms. The mutant arm
skips too, and `replay` reads baseline 0, mutant 0.

MEASURED ON CLEAN `ee849c19e`, no environment overrides, in five seconds:

    D3-UNDECLARED-ARTEFACT @ D1
        verdict        = STAYED_GREEN
        baseline_rc    = 0
        mutant_rc      = 0
        not_replayable = ''
        mutant tail    = `s   [100%]`          <- one skipped testcase

STAYED_GREEN is not a quiet outcome here. It is what LOCK 2 reports as *"the
ledger says this edit reddens the cell; re-running it says otherwise, so the
recorded proof no longer holds"* — the headline claim of vibe-ic#1421, asserted
over a cell nobody looked at. A skip cannot manufacture a red; it manufactures
the FALSE NEGATIVE, which is the expensive direction and the one this ledger
exists to refuse.

WHAT THIS FILE PINS
===================
  * :func:`test_a_skipped_cell_is_a_REASON_not_a_colour` — the reproduction,
    through a REAL pytest session that really skips.
  * :func:`test_the_skip_holds_on_the_MUTANT_arm_too` — falsifies the sentence
    the old behaviour rested on, by measuring both arms.
  * :func:`test_the_reason_carries_what_pytest_said_so_the_reader_can_restore_it`
    — a refusal that does not say what is missing cannot be acted on.
  * :func:`test_the_reason_refuses_the_two_evidence_deleting_repairs` — the same
    two #1403's reason refuses, for the same reason.
  * :func:`test_a_skipped_arm_is_NOT_REPLAYABLE_and_still_FAILS` — it must not
    pass, and it must not be folded into UNMEASURABLE (which would claim the
    witness was pre-reddened, a claim nothing here supports).
  * :func:`test_a_gate_that_REALLY_stopped_catching_is_still_STAYED_GREEN` —
    THE CONTROL. A green bought by no longer being able to see the defect is
    worse than the defect. A pair whose cell really ran and really stayed green
    keeps its own verdict and keeps failing.
  * :func:`test_a_genuinely_REDDENING_pair_is_still_REDDENED` — the other half
    of the control: real proof still banks.

Every session below is a REAL pytest process running the REAL `_run_cell`, in a
throwaway tree outside this repository. chip-AGNOSTIC: no design, PDK, vendor or
IC input anywhere.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import matrix_mutation_ledger as L

#: Bound for one synthetic pytest session. These trees hold ONE trivial test and
#: measure at well under a second; 30 s is slack for a loaded host and is under
#: the 60 s ceiling `ci_harness_timeout_ceiling_check` enforces (vibe-ic#1022).
_T = 30

#: What dimension 3's cell says today, quoted in shape rather than imported so
#: this file keeps pinning the behaviour if that particular reason is reworded.
_SKIP_REASON = "the published corpus is not in this checkout"

_PASSING = "def test_probe():\n    assert True\n"
_FAILING = ("def test_probe():\n"
            "    assert False, 'step D1 declares an output nothing produces'\n")
_SKIPPING = ("import pytest\n\n\n"
             "def test_probe():\n"
             f"    pytest.skip({_SKIP_REASON!r})\n")


def _tree(root: Path, body: str) -> Path:
    """A throwaway pytest rootdir holding exactly one test file."""
    root.mkdir(parents=True)
    (root / "test_probe.py").write_text(body, encoding="utf-8")
    (root / "conftest.py").write_text("", encoding="utf-8")
    return root


@pytest.fixture()
def cell(monkeypatch):
    """Point `cell_nodeid` at the synthetic probe instead of a matrix cell."""
    nodeid = "test_probe.py::test_probe"
    monkeypatch.setattr(L, "cell_nodeid", lambda dim, sid: nodeid)
    return nodeid


# --------------------------------------------------------------------------
# The reproduction.
# --------------------------------------------------------------------------

def test_a_skipped_cell_is_a_REASON_not_a_colour(tmp_path, cell):
    """A cell that declined to run has told us nothing about its colour."""
    root = _tree(tmp_path / "t", _SKIPPING)

    rc, out, why = L._run_cell(3, "D1", root, None, _T)

    assert "1 skipped" in out, (
        f"fixture is not faithful — the probe was supposed to skip:\n{out}")
    assert rc is None, (
        f"a cell that never ran was scored rc={rc!r}. Scored 0 on the MUTANT "
        f"arm this is vibe-ic#1421: `replay` reads baseline 0, mutant 0 and "
        f"publishes STAYED_GREEN — a recorded mutation that stopped reddening "
        f"its witness — over a cell nobody looked at:\n{out}")
    assert why, "NOT_REPLAYABLE with no reason is the silence this forbids"


def test_the_skip_holds_on_the_MUTANT_arm_too(tmp_path, cell):
    """Falsifies the sentence the old behaviour rested on.

    *"It is only ever a witness's BASELINE that could be skipped"* — measured
    here on both arms of the same tree. A cell test's skip conditions are
    properties of the CHECKOUT, and `flow_override` is the only thing that
    differs between the two arms, so whatever makes the baseline decline to run
    makes the mutant decline as well.
    """
    root = _tree(tmp_path / "t", _SKIPPING)
    mutant = tmp_path / "flow.yaml"
    mutant.write_text("steps: []\n", encoding="utf-8")

    base_rc, base_out, base_why = L._run_cell(3, "D1", root, None, _T)
    mut_rc, mut_out, mut_why = L._run_cell(3, "D1", root, mutant, _T)

    assert "1 skipped" in base_out and "1 skipped" in mut_out, (base_out, mut_out)
    assert (base_rc, mut_rc) == (None, None), (
        f"the mutant arm was given a colour it does not have: "
        f"baseline={base_rc!r} mutant={mut_rc!r} — this is the pair that used "
        f"to read (0, 0) and publish STAYED_GREEN")
    assert base_why and mut_why, (base_why, mut_why)
    # The env override really was applied, or the two arms are not two arms.
    assert L.FLOW_YAML_ENV not in os.environ, (
        "this process must not carry the flow override, or the 'baseline' arm "
        "above is not a baseline")


def test_the_reason_carries_what_pytest_said_so_the_reader_can_restore_it(
        tmp_path, cell):
    """A refusal that does not name what is missing cannot be acted on."""
    root = _tree(tmp_path / "t", _SKIPPING)
    _rc, _out, why = L._run_cell(3, "D1", root, None, _T)
    assert _SKIP_REASON in why, (
        f"the cell said WHY it declined and the reason dropped it, so the "
        f"reader cannot tell a missing corpus from a missing tool: {why!r}")
    assert "SKIPPED" in why and "NOT MEASURED" in why, (
        f"the reason does not say the arm was not measured, so a reader still "
        f"cannot tell this from a gate that stopped catching: {why!r}")


def test_the_reason_refuses_the_two_evidence_deleting_repairs(tmp_path, cell):
    """The message routes the reader, or vibe-ic#1421 happens again.

    The same two repairs the fired-bound reason refuses (#1403), refused here
    for the same reason: both restore green by deleting the evidence rather
    than by measuring anything.
    """
    root = _tree(tmp_path / "t", _SKIPPING)
    _rc, _out, why = L._run_cell(3, "D1", root, None, _T)
    assert "re-record the ledger" in why, (
        f"the reason does not refuse re-recording the ledger: {why!r}")
    assert "re-pick the witness" in why, (
        f"the reason does not refuse re-picking the witness: {why!r}")
    assert "stopped catching" in why, (
        f"the reason does not deny the lost-gate reading, which is the one a "
        f"reader arrives with: {why!r}")


def test_a_skipped_arm_is_NOT_REPLAYABLE_and_still_FAILS(tmp_path, cell):
    """It must not pass, and it must not become a claim about the witness."""
    root = _tree(tmp_path / "t", _SKIPPING)
    mut_rc, _out, mut_why = L._run_cell(3, "D1", root, None, _T)
    # `replay` builds `not_replayable` by joining the arms that returned a
    # reason, so an EMPTY reason here would make the assertions below vacuous —
    # the result would carry no reason, score STAYED_GREEN, and this test would
    # be pinning nothing. Asserted, not assumed.
    assert mut_why, (
        "the skipped arm returned no reason, so `replay` would score this pair "
        "STAYED_GREEN and every assertion below would be about a result this "
        "code never produces")

    r = L.ReplayResult("PROBE", 3, "D1", True, 0, mut_rc, False,
                       "synthetic", 0.0, "REDDENED",
                       f"mutant arm: {mut_why}", L.FLOW_YAML)
    assert r.verdict == "NOT_REPLAYABLE", r.verdict
    assert not r.proved, "a replay that never ran was banked as proof"
    assert not r.as_recorded, "a replay that never ran was banked as reproduced"
    assert not r.unmeasurable, (
        "a skipped arm was folded into UNMEASURABLE, which is the claim that "
        "the WITNESS was pre-reddened — this measurement supports no such "
        "claim, and the unmeasurable ceiling would then absorb it")


# --------------------------------------------------------------------------
# THE CONTROL. A green bought by no longer being able to see the defect is
# worse than the defect.
# --------------------------------------------------------------------------

def test_a_gate_that_REALLY_stopped_catching_is_still_STAYED_GREEN(
        tmp_path, cell):
    """PAIRED GUARD. The finding this ledger exists to publish must survive.

    A gate that genuinely lost its teeth produces baseline GREEN, mutant GREEN
    and NO reason — it was measured, twice, and it is the defect. If the fix
    above had made every non-red arm colourless, this pair would now be
    NOT_REPLAYABLE and the ledger would have stopped being able to say it.
    """
    root = _tree(tmp_path / "t", _PASSING)

    base_rc, _bo, base_why = L._run_cell(3, "D1", root, None, _T)
    mut_rc, _mo, mut_why = L._run_cell(3, "D1", root, None, _T)
    assert (base_rc, mut_rc) == (0, 0), (base_rc, mut_rc)
    assert (base_why, mut_why) == ("", ""), (
        f"a cell that RAN and passed was given a reason, so a toothless gate "
        f"is about to be reported as unmeasurable: {base_why!r} {mut_why!r}")

    r = L.ReplayResult("PROBE", 3, "D1", True, base_rc, mut_rc, False,
                       "synthetic", 0.0, "REDDENED", "", L.FLOW_YAML)
    assert r.verdict == "STAYED_GREEN", r.verdict
    assert not r.proved and not r.as_recorded, "a toothless gate bought a pass"


def test_a_genuinely_REDDENING_pair_is_still_REDDENED(tmp_path, cell):
    """The other half of the control: real proof still banks.

    Baseline green, mutant red, the declared signal present in the mutant's own
    output. Nothing about the skip refusal may stand between a measured proof
    and its verdict.
    """
    base_root = _tree(tmp_path / "base", _PASSING)
    mut_root = _tree(tmp_path / "mut", _FAILING)

    base_rc, _bo, base_why = L._run_cell(3, "D1", base_root, None, _T)
    mut_rc, mut_out, mut_why = L._run_cell(3, "D1", mut_root, None, _T)
    assert (base_rc, mut_rc) == (0, 1), (base_rc, mut_rc, mut_out)
    assert (base_why, mut_why) == ("", ""), (base_why, mut_why)

    signal = L.mutation("D3-UNDECLARED-ARTEFACT").red_signal
    r = L.ReplayResult("PROBE", 3, "D1", True, base_rc, mut_rc,
                       signal in mut_out, "synthetic", 0.0, "REDDENED", "",
                       L.FLOW_YAML)
    assert r.verdict == "REDDENED", (r.verdict, mut_out)
    assert r.proved and r.as_recorded


def test_a_skipped_report_is_read_from_the_REPORT_not_the_exit_status(tmp_path):
    """A skipping session exits 0, so the process status cannot see this at all.

    Asserted directly on the reader with a report pytest itself could have
    written, because the whole point of #1412 was that the exit status and the
    cell are different claims — and for a skip the exit status is the one that
    says "green".
    """
    p = tmp_path / "cell.xml"
    p.write_text(
        '<testsuites><testsuite><testcase name="a">'
        '<skipped type="pytest.skip" message="no corpus here"/>'
        '</testcase></testsuite></testsuites>', encoding="utf-8")

    rc, why = L._cell_rc_from_report(p, 0)
    assert rc is None, f"process rc 0 was read as a green cell: {rc!r}"
    assert "no corpus here" in why, why
