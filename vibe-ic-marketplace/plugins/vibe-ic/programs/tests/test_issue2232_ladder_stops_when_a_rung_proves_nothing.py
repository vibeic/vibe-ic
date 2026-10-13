"""A fallback induction rung that proves NOTHING NEW ends the ladder.

THE MEASURED FACT THIS SUITE IS BUILT ON (vibe-ic#2232, `ic/sha256`, 8HD-9).
The rung that did the work took **700.6 s** and left `1611 proven / 2 unproven`.
The ladder then started the NEXT rung anyway, which printed

    Proved 0 previously unproven $equiv cells.
      Of those cells 1611 are proven and 2 are unproven.

and the ladder started a THIRD rung on top of that — `attempt 4`,
`current_pass equiv_induct_seq64`, `elapsed 8.21 h`, `rss 10.1 GiB`, every
attempt carrying `budget_sec 86400`. 700 s of proof followed by 7.5 h that
moved nothing, with 24 h per attempt authorised to keep moving nothing.

The driver already MEASURES the thing that decides this: every leg records
`proved_at_entry` (its own read-back `equiv_status`) and `proved_at_exit` (its
closing one), because #2194 needed the proof state's survival across the
process boundary to be measured rather than assumed. Nothing compared the two
in the direction "did this rung earn the next one".

WHAT THESE TESTS PIN, each one a direction the change could go wrong in:

  * a fallback induction rung that proves nothing NEW, with a residual still
    standing, ENDS the ladder — the rung above it is never launched, and the
    record says which rung stopped it and why;
  * a plateau in short simple, early joint or full simple still reaches the
    later strategies while the same total admission budget permits it;
  * A LADDER THAT IS STILL PROVING IS NEVER TRUNCATED. The control: every rung
    proves something, and all six still run. A guard that stopped a
    progressing ladder would buy the wall clock back by throwing proofs away;
  * A FINISHED PROOF IS NOT A FLAT WALL. When the residual is ZERO the deeper
    rungs necessarily print `Proved 0` too — that is a proof, not a wall, and
    it must still reach PASS over the whole ladder;
  * the stop is HONEST about which resource ran out: the closing
    `equiv_status` is the LADDER's, the residual is NAMED, and the report must
    not claim a budget was spent when none was.
"""
import json
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "lec_run.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import lec_run  # noqa: E402

# The rung ladder as this suite expects to find it. Spelled out on purpose: a
# rung added or reordered must update these tests DELIBERATELY rather than let
# them silently agree with whatever the code now emits.
# The early joint induction preserves relations before the full simple pass
# rewires cutpoints. The two simple rungs AND this joint attempt are exempt
# from the no-progress stop: each has a different strategy still ahead of it.
# The three later induction rungs retain the original plateau contract.
_RUNGS = ("equiv_simple_short", "equiv_induct_joint_seq16",
          "equiv_simple_full", "equiv_induct_seq4", "equiv_induct_seq16",
          "equiv_induct_seq64")


def test_the_ladder_is_the_one_this_suite_was_written_against():
    assert lec_run.LEC_CHECKPOINT_RUNGS == _RUNGS


# ---------------------------------------------------------------------------
# THE FAKE TOOL. It stands in for the CONTAINER, never for the ladder: the
# ladder under test is the real one.
# ---------------------------------------------------------------------------
class _FakeYosys:
    """Yosys as far as this ladder can see it — it writes the RTLIL a
    `write_rtlil` line names, prints the sentinel that attests the write, and
    prints the count lines the parser reads.

    `gains` — how many previously-unproven points each rung proves, by rung
    name. A 0 reproduces #2232's measured rung: the pass RUNS, completes, and
    prints `Proved 0 previously unproven $equiv cells.` with the residual
    unchanged. Rungs absent from the map prove `default_gain` (zero unless
    explicitly requested), so an unlisted rung cannot silently finish a proof.
    """

    def __init__(self, total=100, gains=None, default_gain=0, die_at=None):
        self.scripts = []
        self.rungs_run = []
        self.total = total
        self.proved = 0
        self.gains = dict(gains or {})
        self.default_gain = default_gain
        # `die_at` — the SILENT exhaustion shape: the pass runs and the process
        # simply ends. No checkpoint, no stop marker, and NO CLOSING
        # `equiv_status`, so the leg's only status line is the read-back it
        # opened with. That is the shape this suite's own change had to be kept
        # from stealing (see the ordering test below).
        self.die_at = die_at

    def _rung_of(self, lines):
        for ln in lines:
            if ln.startswith("write_rtlil "):
                return Path(shlex.split(ln)[1]).name[:-len(".il.part")]
        return None

    def _status_block(self, out):
        unproven = self.total - self.proved
        out.append(f"Found {self.total} $equiv cells in equiv:")
        out.append(f"  Of those cells {self.proved} are proven and "
                   f"{unproven} are unproven.")
        if unproven:
            # equiv_status NAMES the residual. Two bit-31 points, the shape
            # #2232 measured on a carry-save datapath whose carry out of the
            # MSB is discarded by mod-2^32 arithmetic.
            out.append("Unproven $equiv "
                       + " ".join(f"\\resid[{i}]_gold" for i in range(unproven)))

    def __call__(self, container, ys_path, timeout=0, workdir=None, *,
                 live_log_path=None, telemetry_path=None,
                 telemetry_context=None, **kw):
        # `**kw` absorbs keywords the real `run_yosys_equiv` grows; pinning
        # today's exact signature would turn every future producer keyword into
        # a red here, which would say nothing about the ladder.
        script = Path(ys_path).read_text(encoding="utf-8")
        self.scripts.append(script)
        lines = script.splitlines()
        rung = self._rung_of(lines)
        self.rungs_run.append(rung)
        out = ["", " /----- Yosys 0.68+ (fake) -----\\", ""]
        if lines and lines[0].startswith("read_rtlil"):
            # A resumed leg STATES the position it read back, FIRST.
            self._status_block(out)
        # ONE gain per RUNG, not per command line. Before 6dc565435 rung
        # `equiv_simple_full` was TWO yosys commands (`equiv_simple -short`
        # then `equiv_simple`) and charging the gain twice would have let a
        # 60-point rung prove 120; the rule is kept so a rung that grows a
        # second command line cannot double its gain silently.
        gain = min(self.gains.get(rung, self.default_gain),
                   self.total - self.proved)
        for ln in lines:
            if ln.startswith("equiv_simple") or ln.startswith("equiv_induct"):
                out.append("Executing EQUIV_INDUCT pass."
                           if ln.startswith("equiv_induct")
                           else "Executing EQUIV_SIMPLE pass.")
            elif ln.startswith("write_rtlil "):
                if rung == self.die_at:
                    return True, "\n".join(out) + "\n"
                target = Path(shlex.split(ln)[1])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"# fake RTLIL proved={self.proved}\n",
                                  encoding="utf-8")
            elif ln.startswith("log "):
                out.append(ln[len("log "):])
        self.proved += gain
        out.append(f"Proved {gain} previously unproven $equiv cells.")
        if gain == 0 and self.proved < self.total:
            out.append("Proof for induction step failed. Trying to prove "
                       "individual $equiv from workset.")
            for i in range(self.total - self.proved):
                out.append(f"  Trying to prove $equiv for "
                           f"\\resid[{i}]_gold: failed.")
        if self.proved >= self.total:
            out.append("Equivalence successfully proven!")
        self._status_block(out)
        raw = "\n".join(out) + "\n"
        if live_log_path is not None:
            with open(live_log_path, "a", encoding="utf-8") as fh:
                fh.write(raw)
        return True, raw


def _make_project() -> Path:
    # mkdtemp, NOT tmp_path: a tmp_path under this image carries a newline, and
    # these paths are written into a yosys script.
    root = Path(tempfile.mkdtemp(prefix="lec2232_"))
    (root / "phase2/stage1/rtl").mkdir(parents=True)
    (root / "phase2/stage2/synth").mkdir(parents=True)
    (root / "phase2/stage1/rtl/dut.v").write_text(
        "module dut(input clk, input a, output reg y);\n"
        "  always @(posedge clk) y <= a;\n"
        "endmodule\n", encoding="utf-8")
    (root / "phase2/stage2/synth/netlist.v").write_text(
        "module dut(clk, a, y);\n"
        "  input clk;\n  input a;\n  output y;\n"
        "  sky130_fd_sc_hd__dfxtp_1 _0_ (.CLK(clk), .D(a), .Q(y));\n"
        "endmodule\n", encoding="utf-8")
    return root


def _drive(monkeypatch, fake) -> tuple:
    root = _make_project()
    monkeypatch.setattr(lec_run, "_container_available", lambda c: True)
    monkeypatch.setattr(lec_run, "_container_file_exists", lambda c, p: True)
    monkeypatch.setattr(lec_run, "_container_dir_writable",
                        lambda c, p: (True, ""))
    monkeypatch.setattr(lec_run, "_container_file_sha256", lambda c, p: "0" * 64)
    monkeypatch.setattr(lec_run, "_yosys_version", lambda c: "Yosys 0.68+ fake")
    monkeypatch.setattr(lec_run, "_container_image_digest",
                        lambda c: "sha256:" + "1" * 64)
    monkeypatch.setattr(lec_run, "run_yosys_equiv", fake)
    rc = lec_run.main([str(root), "--top", "dut", "--container", "fake",
                       "--liberty", "/foss/pdks/x.lib"])
    report = json.loads((root / "reports/lec.json").read_text(encoding="utf-8"))
    shutil.rmtree(root, ignore_errors=True)
    return rc, report


# The measured shape: equiv_simple carries most of it, -seq 4 finishes the
# work it can, and -seq 16 runs to completion having proved NOTHING NEW with a
# residual still standing.
_FLAT_AT_SEQ16 = {"equiv_simple_short": 20, "equiv_induct_joint_seq16": 0,
                  "equiv_simple_full": 40,
                  "equiv_induct_seq4": 38,
                  "equiv_induct_seq16": 0, "equiv_induct_seq64": 0}

# What a stop OWES its reader: which rung stopped it, and the two counts it was
# decided from. A ladder that ends without saying these three things reads
# downstream exactly like one that finished.
_STOP_OWES = ("equiv_induct_seq16", "98 proven at entry", "2 still unproven")


# ---------------------------------------------------------------------------
# THE REPAIR ITSELF
# ---------------------------------------------------------------------------
def test_a_rung_that_proved_nothing_new_does_not_earn_the_next_one(monkeypatch):
    """#2232's own sequence: a rung completes, proves 0, and the ladder stops
    there instead of spending the next rung's budget on the same residual."""
    fake = _FakeYosys(gains=_FLAT_AT_SEQ16)
    _rc, report = _drive(monkeypatch, fake)
    ladder = report["lec_ladder"]
    climbed = [lg["rung"] for lg in ladder["legs"]]
    assert climbed == ["equiv_simple_short", "equiv_induct_joint_seq16",
                       "equiv_simple_full",
                       "equiv_induct_seq4", "equiv_induct_seq16"], climbed
    assert "equiv_induct_seq64" not in fake.rungs_run, (
        "the deepest rung was launched after the rung below it proved 0 — "
        "that is #2232's 7.5 h, exactly")
    assert len(fake.scripts) == 5, (
        f"{len(fake.scripts)} yosys process(es) ran; the ladder was supposed "
        "to stop at the rung that proved nothing")


def test_the_stop_names_the_rung_and_says_it_proved_nothing_new(monkeypatch):
    """DEGRADE LOUDLY. A ladder that stops silently is indistinguishable from
    one that finished, and the residual would look like an exhausted engine."""
    _rc, report = _drive(monkeypatch, _FakeYosys(gains=_FLAT_AT_SEQ16))
    ladder = report["lec_ladder"]
    # ONE observed tuple against ONE expected tuple, and `.get` rather than
    # `[...]`: a control that raises KeyError, or that puts a bare `is True`
    # against a field the fix introduces, has OBSERVED NOTHING — it noticed an
    # absence. The pre-fix tree answers every element of this tuple, and
    # answers it wrongly.
    why = ladder.get("stopped_because") or ""
    observed = (
        report.get("unproven_points"),
        sorted(report.get("unproven_cells") or []),
        # WHICH of the sentences the stop owes are actually in it — a LIST of
        # what was read, not a truthiness test, so a pre-fix arm reports the
        # empty list it really has rather than merely "not True".
        [phrase for phrase in _STOP_OWES if phrase in why],
    )
    assert observed == (2, ["\\resid[0]_gold", "\\resid[1]_gold"],
                        list(_STOP_OWES)), (
        "stopped_because=" + repr(ladder.get("stopped_because")))
    assert ladder.get("stopped_on_no_progress") is True


def test_the_closing_equiv_status_is_the_ladders_own(monkeypatch):
    """A no-progress stop is a TERMINAL state, not a cut-off leg.

    `complete is False` means "a count from an unfinished ladder is a POSITION,
    not a verdict" — it exists so a ladder killed at -seq 16 is not booked as a
    design that "may genuinely differ" over points -seq 64 was still going to
    discharge. Here the rung RAN, to its own closing `equiv_status`, and
    reported that it moved nothing. That count IS the ladder's verdict-grade
    state, so the flag must not say otherwise — and `_decided and
    ladder_complete is False` would otherwise append "the admission budget was
    spent", which on this run is simply untrue."""
    _rc, report = _drive(monkeypatch, _FakeYosys(gains=_FLAT_AT_SEQ16))
    assert report["lec_ladder"]["complete"] is True
    why = report.get("verdict_explanation") or ""
    assert "admission budget was spent" not in why, why
    assert "did not finish" not in why, why


def test_a_flat_wall_stop_is_INCONCLUSIVE_and_never_a_PASS(monkeypatch):
    """§4.05 NO-LEAK, and DELIBERATELY INSENSITIVE — it holds on both arms.

    Stopping EARLIER can only leave MORE points unproven, never fewer, so this
    road must not reach a proof, nor book a mismatch it never found. It guards
    the direction the change must not go, so a red here would mean the stop had
    moved a verdict rather than saved a rung."""
    _rc, report = _drive(monkeypatch, _FakeYosys(gains=_FLAT_AT_SEQ16))
    assert report["verdict"] == "INCONCLUSIVE", report["verdict"]
    assert report["equivalent"] is not True
    assert report["non_equivalent_points"] in (0, None)
    assert report["unproven_points"] == 2


# ---------------------------------------------------------------------------
# THE TWO CONTROLS — what this change must NOT move
# ---------------------------------------------------------------------------
def test_a_ladder_that_is_still_proving_climbs_every_rung(monkeypatch):
    """THE CONTROL. Every rung proves something, so every rung is earned. A
    guard that truncated a progressing ladder would buy the wall clock back by
    throwing away proofs — it is the opposite defect and it is worse."""
    fake = _FakeYosys(total=200, gains={"equiv_simple_short": 30,
                                        "equiv_induct_joint_seq16": 20,
                                        "equiv_simple_full": 30,
                                        "equiv_induct_seq4": 30,
                                        "equiv_induct_seq16": 20,
                                        "equiv_induct_seq64": 10})
    _rc, report = _drive(monkeypatch, fake)
    ladder = report["lec_ladder"]
    assert [lg["rung"] for lg in ladder["legs"]] == list(_RUNGS), (
        "a ladder that proved something on every rung was cut short")
    # `.get`, not `[...]`: this is a CONTROL, and it has to be answerable by
    # the tree that does not have the field yet — otherwise the pre-fix arm
    # raises KeyError and observes nothing about the behaviour it guards.
    assert ladder.get("stopped_on_no_progress") is not True
    assert ladder["complete"] is True
    assert len(fake.scripts) == len(_RUNGS)
    assert [lg["proved_at_exit"] for lg in ladder["legs"]] == [
        30, 50, 80, 110, 130, 140]
    assert [lg["unproven_at_exit"] for lg in ladder["legs"]] == [
        170, 150, 120, 90, 70, 60]
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["equivalent"] is False
    assert report["unproven_points"] == 60


def test_a_fully_proven_ladder_is_not_a_flat_wall(monkeypatch):
    """THE OTHER CONTROL, and the one direction that could cost a PASS. Once
    the residual is ZERO every deeper rung necessarily prints `Proved 0` — the
    guard's own signature — because there is nothing left to prove. That is a
    finished proof, not a wall, and the run must still reach PASS."""
    fake = _FakeYosys(gains={"equiv_simple_short": 40,
                             "equiv_induct_joint_seq16": 0,
                             "equiv_simple_full": 60,
                             "equiv_induct_seq4": 0,
                             "equiv_induct_seq16": 0, "equiv_induct_seq64": 0})
    rc, report = _drive(monkeypatch, fake)
    ladder = report["lec_ladder"]
    assert [lg["rung"] for lg in ladder["legs"]] == list(_RUNGS), (
        "a ladder with nothing left to prove was reported as having hit a "
        "wall: " + str(ladder["stopped_because"]))
    assert ladder.get("stopped_on_no_progress") is not True
    assert report["verdict"] == "PASS", report["verdict"]
    assert report["equivalent"] is True
    assert report["unproven_points"] == 0
    assert rc == 0
    assert [lg["proved_at_exit"] for lg in ladder["legs"]] == [
        40, 40, 100, 100, 100, 100]
    assert [lg["unproven_at_exit"] for lg in ladder["legs"]] == [
        60, 60, 0, 0, 0, 0]


@pytest.mark.parametrize("gains, proved, residual", [
    ((0, 10, 20, 30, 40, 50), [0, 10, 30, 60, 100, 150], 50),
    ((10, 0, 20, 30, 40, 50), [10, 10, 30, 60, 100, 150], 50),
    ((10, 20, 0, 30, 40, 50), [10, 30, 30, 60, 100, 150], 50),
    ((0, 0, 0, 30, 40, 50), [0, 0, 0, 30, 70, 120], 80),
], ids=["short-zero", "joint-zero", "full-zero", "all-three-zero"])
def test_initial_strategy_plateaus_still_run_the_whole_fallback(
        monkeypatch, gains, proved, residual):
    """A completed initial strategy cannot speak for the later strategies.

    The tool is synthetic; the real driver must launch all six processes and
    report their exact carried counts, including every zero-gain boundary.
    """
    fake = _FakeYosys(total=200, gains=dict(zip(_RUNGS, gains)))
    rc, report = _drive(monkeypatch, fake)
    ladder = report["lec_ladder"]
    assert [lg["rung"] for lg in ladder["legs"]] == list(_RUNGS)
    assert fake.rungs_run == list(_RUNGS)
    assert len(fake.scripts) == 6
    assert [lg["proved_at_entry"] for lg in ladder["legs"]] == [
        None, *proved[:-1]]
    assert [lg["proved_at_exit"] for lg in ladder["legs"]] == proved
    assert [lg["unproven_at_exit"] for lg in ladder["legs"]] == [
        200 - n for n in proved]
    assert ladder["proof_state_carry"]["boundaries_measured"] == 5
    assert ladder["proof_state_carry"]["carried"] is True
    assert ladder["stopped_on_no_progress"] is False
    assert ladder["complete"] is True
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["equivalent"] is False
    assert report["unproven_points"] == residual
    assert rc == 0


def test_a_joint_plateau_does_not_rearm_a_spent_total_budget(monkeypatch):
    """The joint exception permits fallback only when admission remains.

    Spending the total budget is not a completed no-progress decision and
    must retain the joint checkpoint without claiming an engine resource kill.
    """
    now = [0.0]
    budget_cls = lec_run.StepBudget
    monkeypatch.setattr(lec_run, "DEFAULT_YOSYS_TIMEOUT_S", 100)
    monkeypatch.setattr(lec_run, "StepBudget", lambda total_s: budget_cls(
        total_s, clock=lambda: now[0]))
    fake = _FakeYosys(total=200, gains={
        "equiv_simple_short": 10, "equiv_induct_joint_seq16": 0,
        "equiv_simple_full": 20, "equiv_induct_seq4": 30,
        "equiv_induct_seq16": 40, "equiv_induct_seq64": 50})
    timeouts = []

    def run(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        result = fake(*args, **kwargs)
        now[0] = 30.0 if len(fake.scripts) == 1 else 101.0
        return result

    rc, report = _drive(monkeypatch, run)
    ladder = report["lec_ladder"]
    assert fake.rungs_run == ["equiv_simple_short", "equiv_induct_joint_seq16"]
    assert [lg["rung"] for lg in ladder["legs"]] == fake.rungs_run
    assert timeouts == [100, 70]
    assert [lg["proved_at_exit"] for lg in ladder["legs"]] == [10, 10]
    assert report["unproven_points"] == 190
    assert ladder["stopped_on_no_progress"] is False
    assert ladder["complete"] is False
    assert ladder["stopped_because"] == (
        "the step budget was spent before rung equiv_simple_full could be launched")
    assert report["lec_attempts_detail"][-1]["launched"] is False
    assert report["lec_attempts_detail"][-1]["budget_sec"] == 0
    assert report["step_budget_exhausted"] is True
    assert report["step_budget_stopped_this_proof"] is False
    assert report["exhausted_resource"] is None
    assert report["lec_resume"]["state"] == "RESUMABLE"
    assert report["lec_resume"]["resumable_from_rung"] == "equiv_induct_joint_seq16"
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["equivalent"] is False
    assert rc == 0


# ---------------------------------------------------------------------------
# THE PREDICATE, on its own — it is PURE, so it is tested as one
# ---------------------------------------------------------------------------
# THE ONE ASSERTION FROM THE ORIGINATING BRANCH THAT IS NOT ADOPTED, AND WHY.
# `next/cl-2232` exposed a pure `rung_proved_nothing_new(leg)` reading THREE
# measured fields — proved at entry, proved at exit, unproven at exit — and a
# table-driven test for it. The stop that LANDED on main (8461b53e7, v1.20.69)
# reads FOUR: it also requires the unproven count to be unchanged. That fourth
# conjunct is not ceremony. A rung that leaves `proved` alone while `unproven`
# falls from 2 to 1 HAS moved something — a point was discharged or removed —
# and the three-field predicate would stop a ladder that is still making
# progress, which is the opposite of this issue.
#
# So the predicate test is deliberately NOT ported: adopting it would mean
# loosening the guard main already carries. Nothing here is weakened; one
# proposed weakening is declined, and said out loud rather than dropped
# silently. The property that test was reaching for — "silence is never a
# stop", i.e. an unmeasured count never reads as no-progress — is pinned by
# `test_counts_that_were_not_measured_never_read_as_no_progress` in this
# file's landed sibling and by the `None not in (...)` guard at the call site.

@pytest.mark.parametrize("flat_at, climbed, proved, residual", [
    ("equiv_induct_seq4", ["equiv_simple_short", "equiv_induct_joint_seq16",
                           "equiv_simple_full", "equiv_induct_seq4"],
     [20, 20, 60, 60], 40),
    ("equiv_induct_seq16", ["equiv_simple_short", "equiv_induct_joint_seq16",
                            "equiv_simple_full", "equiv_induct_seq4",
                            "equiv_induct_seq16"], [20, 20, 60, 70, 70], 30),
], ids=["equiv_induct_seq4-climbed0", "equiv_induct_seq16-climbed1"])
def test_the_ladder_stops_at_the_FIRST_rung_that_proves_nothing(
        monkeypatch, flat_at, climbed, proved, residual):
    """WHICH rung stops it is decided by the evidence, not by a position in the
    list. A zero-gain early joint attempt must reach the full fallback before
    a later induction plateau can decide the stop."""
    gains = {"equiv_simple_short": 20, "equiv_induct_joint_seq16": 0,
             "equiv_simple_full": 40}
    seen_flat = False
    for rung in _RUNGS[3:]:
        if rung == flat_at:
            seen_flat = True
        gains[rung] = 0 if seen_flat else 10
    fake = _FakeYosys(gains=gains)
    _rc, report = _drive(monkeypatch, fake)
    assert [lg["rung"] for lg in report["lec_ladder"]["legs"]] == climbed
    assert fake.rungs_run == climbed
    assert [lg["proved_at_exit"] for lg in report["lec_ladder"]["legs"]] == proved
    assert report["lec_ladder"]["stopped_on_no_progress"] is True
    assert report["lec_ladder"]["complete"] is True
    why = report["lec_ladder"]["stopped_because"]
    assert flat_at in why
    assert f"{proved[-1]} proven at entry" in why
    assert f"{residual} still unproven at exit" in why
    assert report["unproven_points"] == residual
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["equivalent"] is False


def test_a_leg_KILLED_mid_rung_is_not_re_labelled_a_flat_wall(monkeypatch):
    """THE TRAP THIS CHANGE HAD TO BE KEPT OUT OF, and it was MEASURED, not
    foreseen: with the no-progress stop placed ABOVE the checkpoint check,
    `test_issue2194 ...test_a_rung_that_exceeds_the_ceiling_still_fails_
    honestly[True-no checkpoint]` went RED.

    A leg killed inside its pass prints no closing `equiv_status`, so its only
    status line is the read-back it opened with — entry and exit are the same
    number for a rung that NEVER FINISHED, which is arithmetically identical to
    a rung that finished and proved nothing. Booking that as a flat wall would
    trade a real, honest exhaustion for a capability-gap sentence. The
    checkpoint separates them: `write_rtlil` and its sentinel run only after
    the pass returns."""
    fake = _FakeYosys(gains={"equiv_simple_short": 20,
                             "equiv_induct_joint_seq16": 0,
                             "equiv_simple_full": 40,
                             "equiv_induct_seq4": 20},
                      die_at="equiv_induct_seq16")
    _rc, report = _drive(monkeypatch, fake)
    ladder = report["lec_ladder"]
    why = ladder.get("stopped_because") or ""
    # `.get(...) is not True`, so the pre-fix tree can answer this too: it is a
    # guard on what must NOT move, and it holds on both arms.
    observed = [w for w in ("no checkpoint", "proved 0 previously-unproven")
                if w in why]
    assert observed == ["no checkpoint"], why
    assert ladder.get("stopped_on_no_progress") is not True
    assert ladder["complete"] is False, (
        "a leg that was cut off left the ladder reported as finished")
