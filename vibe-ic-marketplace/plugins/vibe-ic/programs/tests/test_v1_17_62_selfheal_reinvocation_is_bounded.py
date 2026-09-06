"""CZT-18 — nothing bounded the Step-11..13 re-invocation across processes.

`phase3_one_shot_runner.run_step11_dft_after_synth` re-invokes
`design_one_shot_runner.step_dft_lec_chain` -- Steps 11, 12 AND 13 -- whenever
canonical Step 11 is unmeasured.  Two facts about that, both measured:

  * The trigger (`step11_needs_rerun`) reads STEP-11 state only: a required
    output absent, or the producer's own `dft_atpg_not_run.json` on disk.  It
    looks at nothing Step 13 produces.  So the post-layout LEC is re-run as
    COLLATERAL -- a proof that may have held a core for hours restarts from
    zero because a DIFFERENT step has no artefact.
  * Each leg is a separate PROCESS building its own `StepBudget` with
    `attempts: 1`, so no mechanism inside the producer can see that this has
    happened before.  The previous lane measured exactly that on a real run.

THE BOUND IS THE STATE, NOT A COUNT.  A counter answers "how many times have I
been here", which is wrong in both directions: it refuses a legitimate
re-measure after a genuinely NEW netlist, and it permits an identical repeat as
long as it has room.  What is recorded instead is what the trigger READ -- the
reason, the absent outputs, the not-run record's digest, and the mapped
netlist's digest.  The same reason over byte-identical inputs cannot buy a
second identical run; a changed netlist always can, however many attempts
preceded it.

AND THE COLLATERAL IS NAMED.  Nothing downstream can RESUME the stopped proof:
the proved set lives inside yosys and `equiv_induct` carries no partial-proof
serialisation to hand it back (Bucket-T / CZT-17).  What the flow can stop
doing is paying that cost in silence, so a re-invocation over a stopped LEC leg
records how far that leg had got and that it is restarting from zero.

chip-AGNOSTIC: a synthetic project tree; no chip / PDK / vendor literal.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase3_one_shot_runner as R  # noqa: E402


def _proj(tmp_path, *, netlist="module top(); endmodule\n"):
    p = tmp_path / "proj"
    (p / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (p / "phase2" / "stage2" / "synth" / "netlist.v").write_text(netlist)
    (p / "reports").mkdir(parents=True, exist_ok=True)
    return p


def _lec(p, **fields):
    doc = {"verdict": "INCONCLUSIVE", "equivalent": False,
           "compared_points": 2130, "unproven_points": 1070,
           "elapsed_sec": 7195.77}
    doc.update(fields)
    (p / "reports").mkdir(parents=True, exist_ok=True)
    (p / "reports" / "lec.json").write_text(json.dumps(doc, indent=2))


# ---------------------------------------------------------------------------
# The fingerprint — WHAT the trigger read
# ---------------------------------------------------------------------------
def test_the_fingerprint_records_the_inputs_the_trigger_read(tmp_path):
    p = _proj(tmp_path)
    fp = R._selfheal_state_fingerprint(p, "because")
    assert fp["trigger_reason"] == "because"
    assert fp["step11_required_absent"], fp
    assert fp["not_run_record"] is None          # absent, not "unreadable"
    assert str(fp["mapped_netlist"]).startswith("sha256:"), fp


def test_a_new_netlist_changes_the_fingerprint(tmp_path):
    """THE DIRECTION A COUNTER GETS WRONG. A genuinely new netlist is a new
    question and must always be allowed to re-measure."""
    a = R._selfheal_state_fingerprint(_proj(tmp_path / "a"), "r")
    b = R._selfheal_state_fingerprint(
        _proj(tmp_path / "b", netlist="module top(input c); endmodule\n"), "r")
    assert a["mapped_netlist"] != b["mapped_netlist"]
    assert a != b


def test_an_unreadable_input_is_not_reported_as_an_absent_one(tmp_path):
    """"Could not read it" is not "it is not there".

    Collapsing the two would let an unreadable file match an absent one, so a
    tree whose not-run record had become unreadable would fingerprint the same
    as one that never had it -- and a legitimate re-run would be suppressed by
    a permission problem. Asserted as a VALUE, three ways apart.
    """
    absent = R._selfheal_state_fingerprint(_proj(tmp_path / "absent"), "r")
    assert absent["not_run_record"] is None

    present = _proj(tmp_path / "present")
    nr = present / R._STEP11_NOT_RUN_REL
    nr.parent.mkdir(parents=True, exist_ok=True)
    nr.write_text('{"verdict": "SKIPPED-CONDITION"}')
    readable = R._selfheal_state_fingerprint(present, "r")
    assert str(readable["not_run_record"]).startswith("sha256:")

    nr.chmod(0o000)
    try:
        blocked = R._selfheal_state_fingerprint(present, "r")
    finally:
        nr.chmod(0o644)
    if blocked["not_run_record"] == readable["not_run_record"]:
        import pytest
        pytest.skip("this user can read a 0o000 file (root?) — the distinction "
                    "cannot be driven here")
    assert blocked["not_run_record"] == "unreadable"
    assert blocked["not_run_record"] != absent["not_run_record"]


# ---------------------------------------------------------------------------
# The LEC stop evidence
# ---------------------------------------------------------------------------
def test_a_stopped_lec_leg_is_recognised(tmp_path):
    p = _proj(tmp_path)
    _lec(p, progress_stalled=True)
    ev = R._lec_leg_stop_evidence(p)
    assert ev is not None
    assert ev["progress_stalled"] is True
    assert ev["compared_points"] == 2130
    assert ev["unproven_points"] == 1070


def test_a_finished_lec_leg_is_not_a_stop(tmp_path):
    """THE CONTROL. A proof that ran to its own end must never be reported as
    having been cut off — that would be the mirror of the defect."""
    p = _proj(tmp_path)
    _lec(p, verdict="PASS", equivalent=True, unproven_points=0,
         progress_stalled=False, budget_exhausted=False)
    assert R._lec_leg_stop_evidence(p) is None


def test_an_absent_lec_report_is_not_evidence_of_a_stop(tmp_path):
    assert R._lec_leg_stop_evidence(_proj(tmp_path)) is None


def test_an_unreadable_lec_report_is_not_evidence_of_a_stop(tmp_path):
    p = _proj(tmp_path)
    (p / "reports" / "lec.json").write_text("{not json")
    assert R._lec_leg_stop_evidence(p) is None


# ---------------------------------------------------------------------------
# The bound itself, driven end to end
# ---------------------------------------------------------------------------
def _drive(p, monkeypatch, calls):
    monkeypatch.setattr(R, "mapped_netlist_available_for_atpg",
                        lambda _p: (True, "a tech-mapped netlist is available"))

    class _FakeD2:
        @staticmethod
        def step_dft_lec_chain(project, top, container, ic_class,
                               full_chip=True):
            calls.append(project)
            return [R.StepResult("dft_insertion", "SKIP", 0.0, "stub")]

    monkeypatch.setitem(sys.modules, "design_one_shot_runner", _FakeD2)
    monkeypatch.setitem(sys.modules, "ic_class_profile",
                        type("M", (), {"detect_ic_class":
                                       staticmethod(lambda _p: {})}))
    return R.run_step11_dft_after_synth(p, "top", "eda")


def test_the_first_invocation_runs_and_the_identical_second_does_not(
        tmp_path, monkeypatch):
    """THE DEFECT, and the fix, in one test.

    Two invocations over a byte-identical tree. The first re-invokes; the
    second recognises that it would repeat exactly that work -- same trigger,
    same absent outputs, same netlist digest -- and refuses, naming the prior
    invocation. Before the fix BOTH re-invoked, and so would a third.
    """
    p = _proj(tmp_path)
    calls = []

    # THE DEFECT IS ASSERTED FIRST, deliberately. Written the other way round
    # the pre-fix arm died on a missing attribute two lines in and never
    # reached the second invocation -- a RED that named a symbol instead of the
    # behaviour. Both invocations happen before anything about the new record
    # is read, so the pre-fix failure is "re-invoked a SECOND time".
    first = _drive(p, monkeypatch, calls)
    assert len(calls) == 1, calls
    assert first[0].status == "PASS", (first[0].status, first[0].detail)

    second = _drive(p, monkeypatch, calls)
    assert len(calls) == 1, (
        "the chain was re-invoked a SECOND time on byte-identical inputs — "
        "same trigger, same absent outputs, same netlist digest. Step 13's "
        "post-layout LEC restarts its proof from zero on every one of these: "
        f"{calls}")
    assert second[0].status == "SKIP", (second[0].status, second[0].detail)
    assert "ALREADY re-invoked" in second[0].detail

    # ...and only now, the shape of the record that makes it possible.
    assert first[0].extras["bounded_by"] == "recorded state, not a count"
    ledger = json.loads((p / R._SELFHEAL_LEDGER_REL).read_text())
    assert len(ledger) == 1 and ledger[0]["outcome"] == "reinvoked"
    assert second[0].extras["prior_invocation"] == ledger[0]["when"]


def test_a_CHANGED_netlist_is_allowed_to_re_measure(tmp_path, monkeypatch):
    """THE CONTROL THAT MAKES THIS A BOUND AND NOT A CAP.

    A counter would refuse this. The state-keyed bound must not: a new netlist
    is a new question, and the answer to it has not been computed.
    """
    p = _proj(tmp_path)
    calls = []
    _drive(p, monkeypatch, calls)
    assert len(calls) == 1

    (p / "phase2" / "stage2" / "synth" / "netlist.v").write_text(
        "module top(input clk); endmodule\n")
    third = _drive(p, monkeypatch, calls)
    assert len(calls) == 2, (
        "a genuinely new netlist was refused a re-measurement — the bound has "
        "become a cap")
    assert third[0].status == "PASS", third[0].detail


def test_the_collateral_lec_restart_is_NAMED_in_the_record(
        tmp_path, monkeypatch):
    """It cannot be prevented -- the proved set lives in the engine and yosys
    `equiv_induct` has no partial-proof serialisation. It must not be silent."""
    p = _proj(tmp_path)
    _lec(p, progress_stalled=True)
    calls = []
    out = _drive(p, monkeypatch, calls)
    assert len(calls) == 1
    collateral = out[0].extras["collateral_lec_restart_from_zero"]
    assert collateral is not None, out[0].extras
    assert collateral["compared_points"] == 2130
    assert collateral["unproven_points"] == 1070
    entry = json.loads((p / R._SELFHEAL_LEDGER_REL).read_text())[0]
    assert entry["collateral_lec_restart_from_zero"] == collateral


def test_a_finished_lec_leg_records_no_collateral(tmp_path, monkeypatch):
    """THE CONTROL: a re-invocation that discards nothing must not claim to."""
    p = _proj(tmp_path)
    _lec(p, verdict="PASS", equivalent=True, unproven_points=0)
    out = _drive(p, monkeypatch, [])
    assert out[0].extras["collateral_lec_restart_from_zero"] is None
