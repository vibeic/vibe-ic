"""The LEC ladder runs ONE RUNG PER PROCESS, so its ceiling stops being the SUM.

THE MEASURED FACT THIS SUITE IS BUILT ON (vibe-ic#2194). opentitan_aes's LEC was
OOM-killed at a 48 GiB cgroup cap — `OOMKilled=true`, `HostConfig.Memory=
51539607552`, `memory.events oom_kill 1` — while the very rung that died reaches
frame 18 with the SAME 57873326 clauses and 22024817 variables at 16.3 GB and
`oom_kill 0` when it is the ONLY rung in the process. 48 GiB was therefore never
that rung's footprint; it was the LADDER'S ACCUMULATION across rungs in one
address space.

Raising the ceiling is not the repair: a bigger number buys exactly one more
rung and hits the same wall — a limit moved to fit the job it just failed, the
shape #2177 forbids. A ladder whose memory grows with the NUMBER OF RUNGS can
only be sized for a machine, and then only until the next design.

WHAT THESE TESTS PIN, each one a direction the change could go wrong in:

  * the ladder can be BOUNDED to one rung, and with no bound its text is
    BYTE-IDENTICAL to the pre-#2194 emission (so the whole-ladder path stays a
    control and not a re-implementation of one);
  * the driver launches ONE PROCESS PER RUNG, each reading the previous rung's
    checkpoint — the mutation that restores the single-process ladder is what
    this catches;
  * THE PROOF STATE CROSSES THE BOUNDARY. A restart from a checkpoint that had
    lost the proven set would redo the work and look exactly like progress, so
    the carry is MEASURED at every boundary — and the measurement is proven to
    go RED when the set is lost, not merely green when it is kept;
  * a rung that genuinely exceeds the ceiling STILL FAILS: the ladder stops at
    it, says so, re-attempts nothing, and never reports a PASS;
  * a figure that could not be read is NOT_MEASURED (None) and never a 0.
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

_ARGS = dict(gold_files=["/p/rtl/a.v"], gate_netlist="/p/synth/netlist.v",
             top="dut", liberty="/foss/pdks/x.lib")

# The rung ladder as this suite expects to find it. Spelled out on purpose: if
# a rung is ever added or reordered, these tests must be updated DELIBERATELY
# rather than silently agreeing with whatever the code now emits.
_RUNGS = ("equiv_simple_short", "equiv_induct_joint_seq16", "equiv_simple_full", "equiv_induct_seq4",
          "equiv_induct_seq16", "equiv_induct_seq64")


# ---------------------------------------------------------------------------
# The ladder can be bounded — and unbounded it does not move
# ---------------------------------------------------------------------------
def test_the_ladder_is_the_one_this_suite_was_written_against():
    assert lec_run.LEC_CHECKPOINT_RUNGS == _RUNGS


def test_an_unbounded_ladder_is_byte_identical_to_the_pre_2194_text():
    """THE CONTROL. `rungs=None` is what every caller before #2194 asked for."""
    for start in range(len(_RUNGS)):
        assert (lec_run._emit_ladder("/ck", start_index=start, rungs=None)
                == lec_run._emit_ladder("/ck", start_index=start)), (
            f"the unbounded ladder from rung {start} moved; the whole-ladder "
            "path is supposed to be a control")


def test_a_bounded_ladder_emits_exactly_one_rung_and_its_checkpoint():
    for idx, rung in enumerate(_RUNGS):
        text = lec_run._emit_ladder("/ck", start_index=idx, rungs=1)
        assert f"write_rtlil /ck/{rung}.il.part" in text
        assert f"{lec_run.LEC_CHECKPOINT_SENTINEL} ck:{rung}" in text
        # ...and NOTHING above it.
        for later in _RUNGS[idx + 1:]:
            assert later not in text, (
                f"a ladder bounded at {rung} still emitted {later} — the rung "
                "would run in the same process and the peak would accumulate")


def test_a_bound_larger_than_the_ladder_is_the_whole_ladder_not_an_error():
    assert (lec_run._emit_ladder("/ck", start_index=0, rungs=99)
            == lec_run._emit_ladder("/ck", start_index=0))


def test_the_uncheckpointed_recipe_never_gains_a_rung_directive():
    """The no-checkpoint script is the control the resume suite already pins."""
    script = lec_run.build_equiv_script(**_ARGS)
    for token in ("write_rtlil", "read_rtlil", lec_run.LEC_CHECKPOINT_SENTINEL):
        assert token not in script
    assert script.endswith("equiv_simple -short\nequiv_induct -seq 16\nequiv_simple\n"
                           "equiv_induct -seq 4\nequiv_induct -seq 16\n"
                           "equiv_induct -seq 64\nequiv_status\n")


def test_a_from_zero_script_can_be_bounded_to_the_first_rung_only():
    script = lec_run.build_equiv_script(**_ARGS, checkpoint_dir="/ck",
                                        ladder_rungs=1)
    assert "equiv_simple -short" in script
    assert "equiv_simple\n" not in script
    for later in ("equiv_simple\n", "equiv_induct -seq 4", "equiv_induct -seq 16",
                  "equiv_induct -seq 64"):
        assert later not in script
    assert f"{lec_run.LEC_CHECKPOINT_SENTINEL} ck:equiv_simple_short" in script


def test_a_resumed_script_can_be_bounded_to_the_next_rung_only():
    resume = {"rung": "equiv_induct_seq4", "rung_index": lec_run.ladder_index("equiv_induct_seq4"),
              "il_path": "/ck/equiv_induct_seq4.il"}
    script = lec_run.build_equiv_script(**_ARGS, checkpoint_dir="/ck",
                                        resume_from=resume, ladder_rungs=1)
    assert script.startswith("read_rtlil /ck/equiv_induct_seq4.il\n")
    assert "equiv_induct -seq 16" in script
    assert "equiv_induct -seq 64" not in script, (
        "the deepest rung rode along in the same process as -seq 16")


def test_a_rung_bound_is_refused_where_it_would_mean_nothing():
    """Loud refusal beats bounding the wrong ladder."""
    with pytest.raises(ValueError):
        lec_run.equiv_proof_tail(induction=False, rungs=1)
    with pytest.raises(ValueError):
        lec_run.equiv_proof_tail(seq_depths=[4, 16], rungs=1)


# ---------------------------------------------------------------------------
# The readings — and what they say when they cannot read
# ---------------------------------------------------------------------------
def test_final_status_counts_reads_the_last_status_not_the_first():
    raw = ("  Of those cells 10 are proven and 90 are unproven.\n"
           "Executing EQUIV_INDUCT pass.\n"
           "  Of those cells 70 are proven and 30 are unproven.\n")
    assert lec_run.final_status_counts(raw) == {"proved": 70, "unproven": 30}


def test_final_status_counts_says_nothing_rather_than_zero():
    assert lec_run.final_status_counts("Executing EQUIV_INDUCT pass.\n") is None
    assert lec_run.final_status_counts("") is None


def test_leg_peak_rss_is_the_max_of_that_legs_own_samples():
    side = Path(tempfile.mkdtemp()) / "t.json"
    side.write_text(json.dumps({"samples": [
        {"attempt": 1, "rss_kib": 100}, {"attempt": 1, "rss_kib": 900},
        {"attempt": 2, "rss_kib": 300}, {"attempt": 2, "rss_kib": 50},
    ]}), encoding="utf-8")
    assert lec_run.leg_peak_rss_kib(side, 1) == 900
    assert lec_run.leg_peak_rss_kib(side, 2) == 300


def test_an_unreadable_peak_is_not_measured_never_zero():
    side = Path(tempfile.mkdtemp()) / "t.json"
    side.write_text(json.dumps({"samples": [
        {"attempt": 1, "rss_kib": None, "resource_probe_degraded": True}]}),
        encoding="utf-8")
    assert lec_run.leg_peak_rss_kib(side, 1) is None, (
        "a degraded probe must read NOT_MEASURED; a 0 would be taken for "
        "'measured, and it was empty'")
    assert lec_run.leg_peak_rss_kib(side, 7) is None
    assert lec_run.leg_peak_rss_kib(None, 1) is None


# ---------------------------------------------------------------------------
# The proof-state carry — proven in BOTH directions
# ---------------------------------------------------------------------------
def _legs(*pairs):
    return [{"rung": f"r{i}", "proved_at_entry": e, "proved_at_exit": x}
            for i, (e, x) in enumerate(pairs)]


def test_a_carried_proof_state_reads_carried():
    out = lec_run.proof_state_carry(_legs((None, 20), (20, 40), (40, 60)))
    assert out["carried"] is True
    assert out["boundaries_measured"] == out["boundaries_total"] == 2


def test_a_LOST_proof_state_reads_NOT_carried():
    """THE OTHER DIRECTION. A restart that re-proves from zero would show a
    smaller entry than the previous exit — and would otherwise look exactly
    like progress."""
    out = lec_run.proof_state_carry(_legs((None, 20), (0, 40)))
    assert out["carried"] is False
    assert out["boundaries"][0]["proved_at_exit"] == 20
    assert out["boundaries"][0]["proved_at_entry"] == 0


def test_an_unmeasured_boundary_is_not_reported_as_carried():
    out = lec_run.proof_state_carry(_legs((None, 20), (None, 40)))
    assert out["carried"] is None, (
        "a boundary that could not be read must not be counted as kept")
    assert out["boundaries_measured"] == 0


def test_a_single_leg_ladder_has_no_boundary_to_carry():
    out = lec_run.proof_state_carry(_legs((None, 20)))
    assert out["carried"] is None and out["boundaries_total"] == 0


# ---------------------------------------------------------------------------
# THE DRIVER: one PROCESS per rung. This is what the mutation breaks.
# ---------------------------------------------------------------------------
class _FakeYosys:
    """Stands in for the container on the two behaviours that matter here: it
    WRITES the RTLIL a `write_rtlil` line names, and it PRINTS the sentinel
    that attests the write finished. Everything else is the log shape the
    parser already reads. It is a stand-in for the TOOL, not for the ladder —
    the ladder under test is the real one.

    `die_at_rung` reproduces a rung that genuinely exceeds the ceiling: the
    pass runs, and then the process ends with no checkpoint written, exactly as
    an OOM kill leaves it (rc 137 does not distinguish the two, which is why
    the marker says so).
    """

    def __init__(self, total=100, die_at_rung=None, silent=False):
        self.scripts = []
        self.total = total
        self.proved = 0
        self.die_at_rung = die_at_rung
        # `silent` is the OTHER exhaustion shape: the process simply ends —
        # no stop marker, no checkpoint. An OOM kill of the container's yosys
        # can arrive either way, so both roads have to lead to an honest stop.
        self.silent = silent

    def __call__(self, container, ys_path, timeout=0, workdir=None, *,
                 live_log_path=None, telemetry_path=None,
                 telemetry_context=None, **kw):
        # `**kw` absorbs keywords the real `run_yosys_equiv` grows (it gained
        # `kill_cause` on main). A stub that pins today's exact signature turns
        # every future producer keyword into a red in THIS suite, which says
        # nothing about the ladder.
        script = Path(ys_path).read_text(encoding="utf-8")
        self.scripts.append(script)
        lines = script.splitlines()
        out = ["", " /----- Yosys 0.68+ (fake) -----\\", ""]
        if lines and lines[0].startswith("read_rtlil"):
            # A resumed leg STATES the position it read back, first.
            out += [f"Found {self.total} $equiv cells in equiv:",
                    f"  Of those cells {self.proved} are proven and "
                    f"{self.total - self.proved} are unproven."]
        died = False
        for ln in lines:
            if ln.startswith("equiv_simple"):
                out.append("Executing EQUIV_SIMPLE pass.")
                self.proved = min(self.total, self.proved + 10)
            elif ln.startswith("equiv_induct"):
                out.append("Executing EQUIV_INDUCT pass.")
                self.proved = min(self.total, self.proved + 20)
            elif ln.startswith("write_rtlil "):
                target = Path(shlex.split(ln)[1])
                rung = target.name[:-len(".il.part")]
                if rung == self.die_at_rung:
                    if not self.silent:
                        out.append(
                            lec_run._TIMEOUT_MARKER +
                            " (rc=137: the container-side backstop, or an "
                            "OOM kill -- rc 137 does not distinguish them).")
                    died = True
                    break
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"# fake RTLIL proved={self.proved}\n",
                                  encoding="utf-8")
            elif ln.startswith("log "):
                out.append(ln[len("log "):])
        if not died:
            out += [f"Found {self.total} $equiv cells in equiv:",
                    f"  Of those cells {self.proved} are proven and "
                    f"{self.total - self.proved} are unproven."]
        raw = "\n".join(out) + "\n"
        if live_log_path is not None:
            with open(live_log_path, "a", encoding="utf-8") as fh:
                fh.write(raw)
        return True, raw


def _make_project() -> Path:
    # mkdtemp, NOT tmp_path: a tmp_path under this image carries a newline, and
    # these paths are written into a yosys script.
    root = Path(tempfile.mkdtemp(prefix="lec2194_"))
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


def test_every_rung_gets_its_own_process(monkeypatch):
    """THE REPAIR ITSELF. Four rungs, four yosys invocations, and each script
    carries exactly ONE rung — so the peak bounds by the worst rung instead of
    accumulating all four in one address space."""
    fake = _FakeYosys()
    _rc, report = _drive(monkeypatch, fake)
    ladder = report["lec_ladder"]
    assert ladder["per_rung_processes"] is True
    assert [lg["rung"] for lg in ladder["legs"]] == list(_RUNGS), (
        "the ladder did not climb one rung per leg")
    assert len(fake.scripts) == len(_RUNGS), (
        f"{len(fake.scripts)} yosys process(es) ran the {len(_RUNGS)}-rung "
        "ladder — a single process is the defect this closed")
    for script in fake.scripts:
        induct = script.count("equiv_induct -seq")
        assert induct <= 1, (
            "one process carried more than one induction rung:\n" + script)
    for leg in ladder["legs"]:
        assert leg["rungs_in_this_process"] == 1


def test_each_rung_after_the_first_reads_the_previous_rungs_checkpoint(
        monkeypatch):
    fake = _FakeYosys()
    _rc, report = _drive(monkeypatch, fake)
    # GUARD THE DENOMINATOR FIRST. With the single-process ladder restored
    # there is exactly ONE script, `fake.scripts[1:]` is empty, and the loop
    # below would iterate zero times and PASS having observed nothing. An
    # empty scan is NOT_OBSERVED, not a pass.
    assert len(fake.scripts) == len(_RUNGS), (
        f"{len(fake.scripts)} process(es) ran the {len(_RUNGS)}-rung ladder — "
        "there is no process boundary here to check")
    assert not fake.scripts[0].startswith("read_rtlil"), (
        "the first leg must BUILD the miter, not read one back")
    for prev_rung, script in zip(_RUNGS, fake.scripts[1:]):
        assert script.startswith(f"read_rtlil "), script[:120]
        assert f"{prev_rung}.il" in script.splitlines()[0], (
            f"a leg did not resume from {prev_rung}: {script.splitlines()[0]}")
    for leg, prev in zip(report["lec_ladder"]["legs"][1:], _RUNGS):
        assert leg["resumed_from_rung"] == prev


def test_the_proved_set_crosses_every_process_boundary(monkeypatch):
    """ACCEPTANCE 2, measured rather than assumed: a checkpoint that had lost
    the proof state would silently redo the work and look like progress."""
    fake = _FakeYosys()
    _rc, report = _drive(monkeypatch, fake)
    carry = report["lec_ladder"]["proof_state_carry"]
    assert carry["boundaries_total"] == len(_RUNGS) - 1
    assert carry["boundaries_measured"] == carry["boundaries_total"], (
        "a boundary went unmeasured; NOT_MEASURED is not evidence of carrying")
    assert carry["carried"] is True, carry["boundaries"]
    # ...and the proved count only ever goes UP across the ladder.
    proved = [lg["proved_at_exit"] for lg in report["lec_ladder"]["legs"]]
    assert proved == sorted(proved) and proved[0] < proved[-1], proved


def test_a_from_zero_run_does_not_claim_it_resumed(monkeypatch):
    """`resumed` has always meant 'a PREVIOUS INVOCATION left this'. It must not
    flip merely because a run's own rung 2 reads its own rung 1."""
    _rc, report = _drive(monkeypatch, _FakeYosys())
    assert report["lec_resume"]["resumed"] is False
    assert report["proof_execution"]["path"] == "from-zero"


@pytest.mark.parametrize("silent, expect_in_reason",
                         [(False, "CUT OFF"), (True, "no checkpoint")])
def test_a_rung_that_exceeds_the_ceiling_still_fails_honestly(
        monkeypatch, silent, expect_in_reason):
    """ACCEPTANCE 3, on BOTH exhaustion shapes — a leg that leaves this
    producer's stop marker, and a leg that simply ends. The restart must not be
    able to hide a real exhaustion: the ladder stops AT the rung, names it,
    re-attempts nothing, and the run is not a PASS."""
    fake = _FakeYosys(die_at_rung="equiv_induct_seq16", silent=silent)
    _rc, report = _drive(monkeypatch, fake)
    ladder = report["lec_ladder"]
    climbed = [lg["rung"] for lg in ladder["legs"]]
    assert climbed == ["equiv_simple_short", "equiv_induct_joint_seq16", "equiv_simple_full", "equiv_induct_seq4",
                       "equiv_induct_seq16"], climbed
    assert "equiv_induct_seq16" in (ladder["stopped_because"] or "")
    assert expect_in_reason in (ladder["stopped_because"] or ""), \
        ladder["stopped_because"]
    assert ladder["complete"] is False
    # It was attempted ONCE. A driver that retried the failing rung would spin
    # on it forever and call the spinning progress.
    assert climbed.count("equiv_induct_seq16") == 1
    assert len(fake.scripts) == 5
    assert report.get("equivalent") is not True
    assert report["verdict"] != "PASS", (
        "a rung that ran out of memory was reported as a proof")


def test_a_ladder_cut_off_mid_rung_is_not_reported_as_a_MISMATCH(monkeypatch):
    """THE OTHER HALF OF ACCEPTANCE 3, and the #2182 mislabel arriving by a new
    road. Splitting the ladder gives every leg its own `equiv_status`, so a
    completed EARLIER leg's count sits in the log when a LATER rung is killed.
    Read as "attempted and left unproven" it would publish a design that "may
    genuinely differ" over points the rung that died was still going to
    discharge. A cut-off ladder is NOT_MEASURED, never a non-equivalence."""
    fake = _FakeYosys(die_at_rung="equiv_induct_seq16")
    _rc, report = _drive(monkeypatch, fake)
    # THE DENOMINATOR FIRST. The precondition for the mislabel is that an
    # earlier leg left a COMPLETED count in the log while the ladder did not
    # finish. If either half is absent this test proves nothing.
    assert report["lec_ladder"]["complete"] is False
    assert report["lec_ladder"]["legs"][1]["unproven_at_exit"] > 0
    # THE FIELDS THAT CARRY THE DECISION. MEASURED, by dropping the
    # `ladder_complete` conjunct in `parse_equiv_output` and re-running this
    # exact driver: each of these four flips, and the explanation becomes
    # "the RTL and gate netlist may genuinely differ at these points" — the
    # #2182 mislabel, verbatim, about a rung that never ran.
    assert report["verdict"] == "INCONCLUSIVE", report["verdict"]
    assert report["inconclusive"] is True
    assert report["non_convergence"] is True
    _why = report.get("verdict_explanation") or ""
    assert "may genuinely differ" not in _why, _why
    assert "STOPPED before it could finish" in _why, _why
    # THE OTHER DIRECTION, kept deliberately and labelled for what it is. These
    # two are INSENSITIVE to `ladder_complete` — MEASURED unchanged in both
    # arms, because the flag can only move a verdict toward NOT MEASURED and
    # never toward a PASS. They guard a DIFFERENT failure (a cut-off ladder
    # becoming a proof, or booking a mismatch it never found), so they are
    # evidence about that, not about this flag.
    assert report["equivalent"] is not True
    assert report["non_equivalent_points"] in (0, None), (
        "unproven points from an unfinished ladder were booked as mismatches")
