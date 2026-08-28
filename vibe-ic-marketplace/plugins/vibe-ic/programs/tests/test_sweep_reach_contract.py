"""A sweep must report how much of the guard it REACHED, not only its verdict.

THE FINDING THIS PINS
=====================
A corpus sweep published as the acceptance evidence for a guard reported
``exit 0, clean`` over 756 ordered pairs. Every one of the 756 had returned
rc 2 / NOT_COMPARABLE, because no pre-existing artefact carried the digest the
guard compares, so the guard's decision point was never entered once. In its
output, in its exit code and in the PR body that quoted it, that sweep was
indistinguishable from one that ran the guard 756 times and found nothing.

The per-item disclosure existed — each child returned rc 2, the shipped
``_vacuous_exit`` "I examined nothing" code. It was discarded at the layer that
aggregated and published the number. ``_sweep_reach`` is that missing layer.

WHAT EACH TEST BELOW IS FOR
===========================
* ``TestBidirectionalControl`` — the guard fires on a zero-reach sweep AND
  stays silent on a sweep that reached something. A one-directional control
  proves only that a check can say one word.
* ``TestReverseCaseMustStillPass`` — the over-correction control. A PARTIAL
  sweep (1 target of many reached; a declared decision point never hit) is
  legitimate and must pass. A rule demanding total coverage would fire on
  nearly every honest sweep in this tree and would be worse than the silence.
* ``TestLoadBearing`` — mutation controls. If the reach accounting is removed
  from the firing path, or the sentinel gate is loosened, a test here must
  fail. A control that passes against a disabled check is not a control.
* ``TestCorpusSweepOfTheAdopters`` — this file's own corpus sweep, over the
  real programs that adopt the contract, running their real CLIs. It accounts
  for and asserts its OWN reach, because a sweep shipped as the evidence for
  "a sweep must prove it fired" that could not prove it fired would be the
  finding rather than the fix.

Fixtures are PUBLIC (sky130 cell names) or invented grammar. No PDK under NDA.
"""
import json
import sys
from pathlib import Path

import pytest

import _gate_denominator as gd
import _sweep_reach as sr
import _vacuous_exit as vx
import perc_corpus_sweep as perc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(perc.__file__).resolve().parent
CHECK = PROGRAMS / "sweep_reach_check.py"

# A minimal routed DEF built from PUBLIC sky130 standard-cell names — the same
# shape test_perc_corpus_sweep.py already uses.
_ROUTED_DEF = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 100000 100000 ) ;
COMPONENTS 3 ;
- _1_ sky130_fd_sc_hd__nor3_1 + PLACED ( 0 0 ) N ;
- _2_ sky130_fd_sc_hd__and3_1 + PLACED ( 100 0 ) N ;
- _3_ sky130_fd_sc_hd__dfxtp_1 + PLACED ( 200 0 ) N ;
END COMPONENTS
SPECIALNETS 2 ;
    - VPWR ( _1_ VPB ) + USE POWER ;
    - VGND ( _1_ VNB ) + USE GROUND ;
END SPECIALNETS
END DESIGN
"""


def _live_dir(root: Path, name: str) -> Path:
    """A design directory the PERC chain CAN reach (carries a routed DEF)."""
    d = root / name / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "routed.def").write_text(_ROUTED_DEF)
    return root / name


def _dead_dir(root: Path, name: str) -> Path:
    """A design directory the PERC chain CANNOT reach — present, readable, no DEF.

    Deliberately NOT an empty/absent directory: the populated-but-unreachable
    corpus is the shape the finding is about, and the shape the pre-existing
    ``_gate_denominator`` / ``_vacuous_exit`` work does not cover.
    """
    d = root / name / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "NOTES.txt").write_text("routing has not run for this block yet\n")
    return root / name


def _run(args, cwd=PROGRAMS):
    # 60s is the per-call ceiling `ci_harness_timeout_ceiling_check` derives
    # from the 180s CI harness bound. A child allowed to outlive the harness
    # kills the SESSION instead of the test, and every child driven here is a
    # sub-second CLI over a three-module corpus.
    return _pr.run([sys.executable] + [str(a) for a in args],
                          cwd=str(cwd), capture_output=True, text=True)


def _sentinel_lines(proc) -> int:
    return sum(1 for ln in (proc.stdout + "\n" + proc.stderr).splitlines()
               if ln.lstrip().startswith(vx.VACUOUS_STDOUT_SENTINEL))


# =====================================================================
class TestBidirectionalControl:
    """The guard must fire on the defect AND stay silent on the healthy case."""

    def test_zero_reach_sweep_does_not_exit_zero(self, tmp_path):
        """Direction 1 — POSITIVE control. A corpus it read and never judged."""
        dirs = [_dead_dir(tmp_path, "blk_a"), _dead_dir(tmp_path, "blk_b")]
        r = _run([PROGRAMS / "perc_corpus_sweep.py"] + dirs)
        assert r.returncode == vx.RC_VACUOUS, (
            "a sweep that entered the PERC chain on nothing must not report the "
            f"exit code of a clean corpus run; got rc {r.returncode}\n{r.stderr}")
        assert _sentinel_lines(r) == 1, (
            "rc 2 and the VACUOUS_PASS sentinel are the only two signals "
            "flow_compliance_check consumes; a sweep owes BOTH\n" + r.stderr)
        assert "0 of 2 design directory" in r.stderr

    def test_reached_sweep_is_clean_and_says_so(self, tmp_path):
        """Direction 2 — NEGATIVE control. Same code path, nothing to report."""
        dirs = [_live_dir(tmp_path, "blk_a"), _live_dir(tmp_path, "blk_b")]
        r = _run([PROGRAMS / "perc_corpus_sweep.py"] + dirs)
        assert r.returncode == vx.RC_PASS, r.stderr
        assert _sentinel_lines(r) == 0, (
            "a sweep that reached its guard must not print the vacuous "
            "sentinel\n" + r.stderr)
        assert "reached the decision point on 2 of 2 design directory" in r.stderr

    def test_the_two_directions_are_actually_distinguishable(self, tmp_path):
        """The property the finding names, asserted directly.

        Not "the guard fires" but "the two runs differ" — the 756-pair sweep
        failed precisely because its two possible worlds produced identical
        observations.
        """
        dead = [_dead_dir(tmp_path, "d1"), _dead_dir(tmp_path, "d2")]
        live = [_live_dir(tmp_path, "l1"), _live_dir(tmp_path, "l2")]
        a = _run([PROGRAMS / "perc_corpus_sweep.py"] + dead)
        b = _run([PROGRAMS / "perc_corpus_sweep.py"] + live)
        assert a.returncode != b.returncode, (
            "zero-reach and full-reach runs returned the same exit code — this "
            "is the defect, not the fix")
        assert _sentinel_lines(a) != _sentinel_lines(b)

    def test_checker_fires_on_a_vacuous_report_and_passes_a_reached_one(self, tmp_path):
        """The same bidirectional pair through the consumer-facing gate."""
        vac, live = tmp_path / "vac.json", tmp_path / "live.json"
        _run([PROGRAMS / "perc_corpus_sweep.py", _dead_dir(tmp_path, "x"),
              "--report", vac])
        _run([PROGRAMS / "perc_corpus_sweep.py", _live_dir(tmp_path, "y"),
              "--report", live])
        bad = _run([CHECK, "--report", vac])
        good = _run([CHECK, "--report", live])
        assert bad.returncode == vx.RC_FAIL, bad.stdout + bad.stderr
        assert good.returncode == vx.RC_PASS, good.stdout + good.stderr


# =====================================================================
class TestReverseCaseMustStillPass:
    """The over-correction control: partial sweeps are legitimate."""

    def test_one_reached_of_many_is_a_pass(self, tmp_path):
        """1 of 3. Thin, disclosed as thin, and NOT a failure.

        This is the case a naive "prove you covered the corpus" rule would
        break, and most real corpora look like this.
        """
        dirs = [_live_dir(tmp_path, "ok"), _dead_dir(tmp_path, "d1"),
                _dead_dir(tmp_path, "d2")]
        r = _run([PROGRAMS / "perc_corpus_sweep.py"] + dirs)
        assert r.returncode == vx.RC_PASS, r.stderr
        assert _sentinel_lines(r) == 0
        assert "reached the decision point on 1 of 3 design directory" in r.stderr

    def test_checker_passes_a_partial_sweep(self, tmp_path):
        rep = tmp_path / "partial.json"
        _run([PROGRAMS / "perc_corpus_sweep.py", _live_dir(tmp_path, "ok"),
              _dead_dir(tmp_path, "no"), "--report", rep])
        block = json.loads(rep.read_text())[sr.REACH_KEY]
        assert block["reached"] == 1 and block["targets"] == 2
        assert block["is_vacuous"] is False
        r = _run([CHECK, "--report", rep])
        assert r.returncode == vx.RC_PASS, r.stdout + r.stderr

    def test_an_unreached_declared_decision_point_is_reported_not_failed(self):
        """Declaring three decision points and hitting one is a PASS.

        The report says which point was never entered — that is the coverage
        signal — but an unhit point is not on its own a defect, because a rule
        with branches for cases this corpus does not contain is a normal rule.
        """
        reach = sr.SweepReach(unit="pair", decision_points=("cmp", "classify", "ratio"))
        reach.reached("p1", point="cmp")
        reach.not_reached("p2", reason="NOT_COMPARABLE")
        rep = reach.report()
        assert rep["decision_points"] == {"classify": 0, "cmp": 1, "ratio": 0}
        assert rep["is_vacuous"] is False
        assert reach.exit_code(passed=True) == vx.RC_PASS
        assert sr.reach_violations({sr.REACH_KEY: rep}) == []

    def test_an_empty_corpus_must_be_explained_but_a_partial_one_need_not(self):
        empty = sr.SweepReach(unit="pair")
        with pytest.raises(ValueError, match="why the corpus was empty"):
            empty.report()
        empty.declare_empty_corpus("the project filter matched no design")
        assert empty.report()["targets"] == 0
        partial = sr.SweepReach(unit="pair")
        partial.reached("a")
        partial.not_reached("b", reason="no artefact")
        partial.report()          # no empty-corpus declaration needed


# =====================================================================
class TestLoadBearing:
    """Mutation controls. Each asserts a test above would FAIL if the check were
    removed — a control that survives a disabled check is not a control."""

    def test_the_positive_control_depends_on_the_reach_accounting(self, tmp_path):
        """Simulate deleting the reach accounting from perc_corpus_sweep.

        With `perc_chain_ran` stripped from the rows the sweep still produces
        the same table; what changes is that the reach block can no longer say
        anything, which is the pre-fix state and must not read as clean.
        """
        rows = [{"name": "a", "def": None, "error": "no routed DEF",
                 "perc_chain_ran": False}]
        assert perc.reach_of(rows).exit_code(passed=True) == vx.RC_VACUOUS
        mutated = [{k: v for k, v in r.items() if k != "perc_chain_ran"}
                   for r in rows]
        # Absent flag == not reached: the accounting fails CLOSED, never open.
        assert perc.reach_of(mutated).exit_code(passed=True) == vx.RC_VACUOUS

    def test_a_reached_row_is_what_makes_it_pass(self):
        """The inverse mutation: flipping ONE row's flag flips the verdict."""
        rows = [{"name": "a", "def": "/x/routed.def", "perc_chain_ran": False}]
        assert perc.reach_of(rows).is_vacuous is True
        rows[0]["perc_chain_ran"] = True
        assert perc.reach_of(rows).is_vacuous is False

    def test_fail_beats_vacuous_on_the_rc_AND_on_the_sentinel(self, capsys):
        """A zero-reach sweep that also found a violation must not print
        "examined nothing" — a consumer reading the sentinel would promote the
        run into the vacuous tier and silence the finding."""
        reach = sr.SweepReach(unit="pair")
        reach.not_reached("p", reason="NOT_COMPARABLE")
        assert reach.is_vacuous is True
        assert reach.exit_code(passed=False) == vx.RC_FAIL
        reach.announce("s", passed=False, stream=sys.stdout)
        assert vx.VACUOUS_STDOUT_SENTINEL not in capsys.readouterr().out
        reach.announce("s", passed=True, stream=sys.stdout)
        assert vx.VACUOUS_STDOUT_SENTINEL in capsys.readouterr().out

    def test_an_unexplained_non_reach_cannot_be_recorded(self):
        reach = sr.SweepReach(unit="pair")
        for bad in ("", "   "):
            with pytest.raises(ValueError, match="needs a reason"):
                reach.not_reached("p", reason=bad)

    def test_an_undeclared_decision_point_is_rejected(self):
        reach = sr.SweepReach(unit="pair", decision_points=("cmp",))
        with pytest.raises(ValueError, match="was not declared"):
            reach.reached("p", point="cpm")          # typo
        with pytest.raises(ValueError, match="must name the one"):
            reach.reached("p")

    def test_not_stated_and_stated_zero_do_not_collapse(self):
        """`None` vs `True` — the distinction a consumer must not lose."""
        assert sr.is_vacuous_report({}) is None
        assert sr.is_vacuous_report({sr.REACH_KEY: {"reached": 0}}) is True
        assert sr.is_vacuous_report({sr.REACH_KEY: {"reached": 3}}) is False
        assert "NOT STATED" in sr.line_of({})

    def test_reach_violations_catches_a_report_that_does_not_add_up(self):
        assert sr.reach_violations({sr.REACH_KEY: {
            "unit": "pair", "targets": 10, "reached": 2, "not_reached": 3,
            "is_vacuous": False, "not_reached_reasons": {"x": 3},
            "decision_points": {}}})
        assert sr.reach_violations({sr.REACH_KEY: {
            "unit": "pair", "targets": 5, "reached": 0, "not_reached": 5,
            "is_vacuous": False, "not_reached_reasons": {"x": 5},
            "decision_points": {}}})
        assert sr.reach_violations({sr.REACH_KEY: {
            "unit": "pair", "targets": 5, "reached": 0, "not_reached": 5,
            "is_vacuous": True, "not_reached_reasons": {},
            "decision_points": {}}})


# =====================================================================
class TestReusesTheExistingConventions:
    """Built ON _gate_denominator / _vacuous_exit, not beside them."""

    def test_as_denominator_is_a_real_denominator_consumers_already_parse(self):
        reach = sr.SweepReach(unit="design directory", decision_points=("perc_chain",))
        reach.reached("a", point="perc_chain")
        reach.not_reached("b", reason="no routed DEF")
        d = reach.as_denominator()
        assert isinstance(d, gd.Denominator)
        assert (d.examined, d.considered) == (1, 2)
        assert gd.disclosure_violations(gd.attach({}, d)) == []

    def test_a_vacuous_sweep_denominator_carries_the_required_reason(self):
        reach = sr.SweepReach(unit="pair")
        reach.not_reached("a", reason="NOT_COMPARABLE")
        d = reach.as_denominator()          # would RAISE if the reason were empty
        assert d.is_vacuous and "NOT_COMPARABLE" in d.not_applicable_reason
        assert gd.disclosure_violations(gd.attach({}, d)) == []

    def test_rc_routing_is_vacuous_exits_routing(self):
        for reached, passed, want in ((0, True, vx.RC_VACUOUS),
                                      (0, False, vx.RC_FAIL),
                                      (1, True, vx.RC_PASS),
                                      (1, False, vx.RC_FAIL)):
            reach = sr.SweepReach(unit="pair")
            if reached:
                reach.reached("a")
            else:
                reach.not_reached("a", reason="r")
            assert reach.exit_code(passed) == want

    def test_absorb_child_rc_is_the_bridge_the_756_sweep_lacked(self):
        """756 children each returned rc 2; the wrapper reported clean."""
        reach = sr.SweepReach(unit="ordered audit pair")
        for i in range(756):
            reach.absorb_child_rc(f"pair-{i}", vx.RC_VACUOUS)
        assert reach.is_vacuous is True
        assert reach.exit_code(passed=True) == vx.RC_VACUOUS
        assert reach.report()["coverage"] == "0/756"
        reach.absorb_child_rc("pair-756", vx.RC_PASS)
        assert reach.exit_code(passed=True) == vx.RC_PASS


# =====================================================================
class TestSelfApplication:
    """The checker is itself a sweep and is held to its own rule."""

    def test_checker_over_reports_that_state_nothing_returns_rc2_not_rc0(self, tmp_path):
        silent = tmp_path / "legacy.json"
        silent.write_text(json.dumps({"sweep": "legacy", "rows": []}))
        r = _run([CHECK, "--report", silent])
        assert r.returncode == vx.RC_VACUOUS, (
            "a gate that examined no claim must not exit 0 — that is the very "
            "defect it exists to catch\n" + r.stdout + r.stderr)
        assert _sentinel_lines(r) == 1

    def test_checker_publishes_its_own_reach_block(self, tmp_path):
        rep, out = tmp_path / "r.json", tmp_path / "out.json"
        _run([PROGRAMS / "perc_corpus_sweep.py", _live_dir(tmp_path, "z"),
              "--report", rep])
        r = _run([CHECK, "--report", rep, "--json", out])
        assert r.returncode == vx.RC_PASS, r.stdout + r.stderr
        own = json.loads(out.read_text())
        assert sr.reach_violations(own) == []
        assert own[sr.REACH_KEY]["reached"] == 1

    def test_require_reach_makes_a_silent_report_a_failure(self, tmp_path):
        silent = tmp_path / "legacy.json"
        silent.write_text(json.dumps({"rows": []}))
        r = _run([CHECK, "--report", silent, "--require-reach"])
        assert r.returncode == vx.RC_FAIL
        assert _sentinel_lines(r) == 0, (
            "FAIL beats VACUOUS on the sentinel channel too")


# =====================================================================
class TestCorpusSweepOfTheAdopters:
    """This file's own corpus sweep — and it must demonstrably FIRE.

    It runs every adopting program's REAL CLI over a real corpus, in both
    directions, and asserts the contract against the output each one actually
    produces rather than against a restatement of it here.
    """

    #: Programs that have adopted the aggregate reach contract. A ratchet: this
    #: set may grow, and the sweep below fails if it is ever empty — a sweep
    #: over an empty adopter set would pass by examining nothing, which is the
    #: finding this whole file is about.
    ADOPTERS = ("perc_corpus_sweep.py", "sweep_reach_check.py",
                "sweep_reach_survey.py")

    def test_every_adopter_imports_the_shared_contract(self):
        for name in self.ADOPTERS:
            src = (PROGRAMS / name).read_text()
            assert "_sweep_reach" in src, f"{name} does not use the shared contract"

    def test_corpus_sweep_over_the_adopters_fires_in_both_directions(self, tmp_path):
        """The sweep, with its own reach accounted for and asserted non-zero."""
        own = sr.SweepReach(unit="adopting sweep program",
                            decision_points=("zero_reach_run", "reached_run"))
        vac_corpus = [_dead_dir(tmp_path, "c_dead1"), _dead_dir(tmp_path, "c_dead2")]
        live_corpus = [_live_dir(tmp_path, "c_live1")]
        silent_report = tmp_path / "silent.json"
        silent_report.write_text(json.dumps({"rows": []}))
        good_report = tmp_path / "good.json"
        _run([PROGRAMS / "perc_corpus_sweep.py", live_corpus[0],
              "--report", good_report])

        empty_dir = tmp_path / "no_programs_here"
        empty_dir.mkdir()

        # (program, zero-reach argv, reached argv)
        plan = {
            "perc_corpus_sweep.py": (vac_corpus, live_corpus),
            "sweep_reach_check.py": (["--report", silent_report],
                                     ["--report", good_report]),
            # The survey reaches nothing when there is no sweep to discover,
            # and reaches something when pointed at a real one.
            "sweep_reach_survey.py": (["--programs-dir", empty_dir],
                                      ["--only", "rom_init_lint.py"]),
        }
        observed = {}
        for name in self.ADOPTERS:
            if name not in plan:
                own.not_reached(name, "no corpus recipe for this adopter")
                continue
            zero_argv, reached_argv = plan[name]
            z = _run([PROGRAMS / name] + list(zero_argv))
            own.reached(name, point="zero_reach_run")
            k = _run([PROGRAMS / name] + list(reached_argv))
            own.reached(name, point="reached_run")
            observed[name] = (z, k)

        # ---- this sweep's OWN reach, asserted before its findings are read.
        rep = own.report()
        assert sr.reach_violations({sr.REACH_KEY: rep}) == []
        assert rep["reached"] > 0, (
            "this corpus sweep reached no adopter — it would have reported "
            "'clean' having exercised nothing, which is exactly the defect "
            f"under test. reach={rep}")
        assert rep["decision_points"]["zero_reach_run"] > 0
        assert rep["decision_points"]["reached_run"] > 0

        # ---- and only now, the findings.
        for name, (z, k) in observed.items():
            assert z.returncode != vx.RC_PASS, (
                f"{name}: zero-reach run exited 0\n{z.stdout}{z.stderr}")
            assert _sentinel_lines(z) == 1, (
                f"{name}: zero-reach run printed no VACUOUS_PASS sentinel\n"
                f"{z.stdout}{z.stderr}")
            assert k.returncode == vx.RC_PASS, (
                f"{name}: reached run did not pass\n{k.stdout}{k.stderr}")
            assert _sentinel_lines(k) == 0, (
                f"{name}: reached run printed the vacuous sentinel\n"
                f"{k.stdout}{k.stderr}")

    def test_the_adopter_set_is_not_empty(self):
        """The ratchet's own floor. Without it the sweep above passes vacuously."""
        assert len(self.ADOPTERS) >= 2
        for name in self.ADOPTERS:
            assert (PROGRAMS / name).is_file(), name


# =====================================================================
class TestSurveyIsHonestAboutItsOwnDenominator:
    """The instrument that produces the ratio is held to the same rule."""

    def test_no_ratio_is_printed_over_an_empty_denominator(self, tmp_path):
        """A survey that drove nothing must not print a number.

        `0/0` and `8/35` must not be produced by the same code path — a ratio
        over an empty denominator is the survey committing, in its headline,
        the defect it exists to measure.
        """
        empty = tmp_path / "none"
        empty.mkdir()
        out = tmp_path / "r.json"
        r = _run([PROGRAMS / "sweep_reach_survey.py", "--programs-dir", empty,
                  "--json", out])
        assert r.returncode == vx.RC_VACUOUS, r.stdout + r.stderr
        assert _sentinel_lines(r) == 1
        doc = json.loads(out.read_text())
        assert doc["ratio"].startswith("UNDEFINED")
        assert sr.reach_violations(doc) == []
        assert doc[sr.REACH_KEY]["reached"] == 0

    def test_a_real_sweep_is_driven_and_the_denominator_is_published(self, tmp_path):
        out = tmp_path / "r.json"
        r = _run([PROGRAMS / "sweep_reach_survey.py",
                  "--only", "rom_init_lint.py", "--json", out])
        assert r.returncode == vx.RC_PASS, r.stdout + r.stderr
        doc = json.loads(out.read_text())
        assert doc["discovered"] == 1 and doc["driven"] == 1
        assert doc["ratio"] == f"{doc['discloses']}/{doc['driven']}"
        assert doc[sr.REACH_KEY]["reached"] == 1
        assert sr.reach_violations(doc) == []

    def test_not_drivable_is_published_rather_than_dropped(self, tmp_path):
        """Sweeps the probe corpus cannot drive must be COUNTED, not hidden.

        Reporting the ratio over what was reached while silently discarding
        what was not is the same defect one level up.
        """
        out = tmp_path / "r.json"
        _run([PROGRAMS / "sweep_reach_survey.py", "--only", "rom_init_lint.py",
              "--only", "spec_conformance_check.py", "--json", out])
        doc = json.loads(out.read_text())
        assert doc["discovered"] == doc["driven"] + doc["not_drivable"]
        assert doc["not_drivable"] >= 1, (
            "spec_conformance_check requires --spec, so the generic corpus "
            "cannot drive it; that must show up in the denominator")

    def test_one_silent_witness_decides_a_program(self):
        """Conservative aggregation across arg shapes, asserted on the classifier.

        A program that discloses under one invocation and is silent under
        another CAN report clean having judged nothing, so it is SILENT.
        """
        import sweep_reach_survey as srv
        assert srv.classify_run(0, "PASS", "")[0] == "SILENT"
        assert srv.classify_run(2, "", "")[0] == "DISCLOSES"
        assert srv.classify_run(0, f"{vx.VACUOUS_STDOUT_SENTINEL} x", "")[0] == "DISCLOSES"
        assert srv.classify_run(1, "found a violation", "")[0] == "NOT_DRIVABLE"
        assert srv.classify_run(2, "", "usage: x\nerror: bad")[0] == "NOT_DRIVABLE"
        assert srv.classify_run(2, "", "[Errno 21] Is a directory")[0] == "NOT_DRIVABLE"

    def test_the_probe_corpus_is_readable_and_carries_no_pdk_identity(self, tmp_path):
        """The corpus must be REAL RTL — an unreadable corpus would measure
        the wrong thing (V1 'given nothing' instead of V2 'judged nothing')."""
        import sweep_reach_survey as srv
        files, dirs = srv.make_corpus(tmp_path)
        assert len(files) == 3 and len(dirs) == 3
        for f in files:
            body = Path(f).read_text()
            assert "module" in body and "endmodule" in body
            assert "sky130" not in body and "gf180" not in body


# =====================================================================
class TestPercBackCompat:
    """Adopting the contract must not move an existing consumer's ground."""

    def test_json_mode_still_emits_the_row_array(self, tmp_path):
        r = _run([PROGRAMS / "perc_corpus_sweep.py", "--json",
                  _live_dir(tmp_path, "a")])
        assert r.returncode == vx.RC_PASS
        data = json.loads(r.stdout)
        assert isinstance(data, list) and data[0]["welltap"]["status"]

    def test_vintage_only_mode_is_untouched(self, tmp_path):
        d = _live_dir(tmp_path, "v")
        r = _run([PROGRAMS / "perc_corpus_sweep.py", "--vintage",
                  d / "phase3" / "stage3" / "pnr" / "routed.def"])
        assert r.returncode == vx.RC_PASS
        assert json.loads(r.stdout)["verdict"]
