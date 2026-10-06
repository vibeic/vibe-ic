"""Step 32: the canonical decision record is bound to the report it decided
from, so the no-repair certificate survives the status generator that
verifies it; and the derived generators' outcomes are no longer discarded.

MEASURED (IC-path gf180mcuD run, 2026-09-28, evidence copy replayed): the
canonical `postroute_timing_repair_decision.json` said `repair_needed=false`
(multi-corner OCV, setup +2.68 ns, hold +0.44 ns, action
`no_repair_needed_flag`) and canonicalize wrote `no_repair_needed.flag`. The
Step-32 status generator dispatched after it accepts a decision receipt only
when `source_report` resolves inside the project to a file whose sha256 is
`source_report_sha256` -- the receipt shape the Step-32 LibreLane producer
publishes. The canonical record carried neither field, so the generator
answered "NOT_MEASURED: Step-32 decision invalid: measured source or sha256
absent", unlinked the flag and exited 2. The runner discarded that exit and
its message; Step 32 failed with the flag "absent" while the runner's output
list still named it.

Real code paths: `step_canonicalize_artefacts` (docker faked: only the EDA
tool's report write), the shipped status generator, the shipped
`postroute_timing_repair_audit`, and `_run_derived_artefact_generators`.
chip-agnostic: synthetic project, no design names in any assertion.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

REPAIR = "phase3/stage3/postroute_timing_repair"
DECISION = f"{REPAIR}/postroute_timing_repair_decision.json"
FLAG = f"{REPAIR}/no_repair_needed.flag"
LOG = f"{REPAIR}/repair_log.json"
CANONICAL = f"{REPAIR}/postroute_timing_repair_decision.canonical.json"
STATUS_GEN = "postroute_timing_repair_status_gen.py"

PATH_MET = """\
Startpoint: a (rising edge-triggered)
Endpoint: b (rising edge-triggered)
Path Type: max
           0.47   slack (MET)
"""
EST_MET = PATH_MET + "\ntns 0.00\n"
SPEF_MET = PATH_MET + "\ntns max 0.00\nworst slack max 0.47\n"
SPEF_VIOLATED = """\
Startpoint: a (rising edge-triggered)
Endpoint: b (rising edge-triggered)
Path Type: max
         -12.27   slack (VIOLATED)

tns max -60088.21
wns max -12.27
worst slack max -12.27
"""


def _pdk():
    return R.PdkConfig(
        name="sky130A", liberty="/foss/pdks/x.lib", tech_lef="/t.tlef",
        cell_lef="/c.lef", cell_gds=None, site="s", drc_deck=None)


def _proj(root: Path) -> Path:
    pnr = root / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "chip_top.def").write_text("VERSION 5.8 ;\nDESIGN chip_top ;\n"
                                      "END DESIGN\n")
    (pnr / "sta.rpt").write_text(EST_MET)
    (pnr / "chip_top_pnr.v").write_text("module chip_top();\nendmodule\n")
    (pnr / "constraint.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    synth = root / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "chip_top_synth.v").write_text("module chip_top();\nendmodule\n")
    ext = root / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True)
    (ext / "chip_top.spef").write_text(
        "*SPEF \"IEEE 1481-1998\"\n*DESIGN \"chip_top\"\n" + "x" * 200)
    return root


def _fake_docker(spef_sta_text):
    """Every container call succeeds; the `sta -no_init` call writes the
    SPEF-based report where the deck's `report_checks > <rpt>` names it --
    the only EDA tool write this path needs."""
    def fake(container, cmd, timeout=0, **_):
        if "sta -no_init" in cmd:
            m = re.search(r"-exit\s+(\S+\.tcl)", cmd)
            if m and Path(m.group(1)).is_file():
                rm = re.search(r"report_checks > (\S+)",
                               Path(m.group(1)).read_text())
                if rm:
                    Path(rm.group(1)).write_text(spef_sta_text)
        return (0, "", "")
    return fake


def _canonicalize(p: Path, monkeypatch, spef_text: str) -> None:
    # This control supplies the direct OpenSTA report at its tool boundary.
    switch = p / "phase3/librelane_switch.json"
    switch.write_text(json.dumps({"steps": {
        step: "direct" for step in ("22", "23", "32", "34", "37")}}))
    monkeypatch.setattr(R, "_docker_exec", _fake_docker(spef_text))
    monkeypatch.setattr(R, "_to_container_path", lambda s, c: s)
    R.step_canonicalize_artefacts(p, "chip_top", _pdk(), "x")


def test_missing_native_power_state_retires_previous_measurement(tmp_path):
    from _ppa import power

    report = tmp_path / "reports/phase3/power.rpt"
    report.parent.mkdir(parents=True)
    report.write_text("previous tool measurement\n")
    report.with_suffix(".current.json").write_text("{}")
    report.with_suffix(".json").write_text(json.dumps({
        "verdict": "PASS", "power_measurement": "MEASURED",
        "total_power_w": 0.01}))
    notes = []
    assert power.adopt_current_power_report(tmp_path, "chip_top", report, notes) is False
    assert not report.exists()
    assert not report.with_suffix(".current.json").exists()
    retired = json.loads(report.with_suffix(".json").read_text())
    assert retired["power_measurement"] == "NOT_MEASURED"
    assert retired.get("total_power_w") is None
    assert any("LL_STAPOSTPNR_STATE_ABSENT" in note for note in notes)


def _bound_basis(p: Path, record: dict) -> Path:
    """The SHIPPED receipt check (`postroute_timing_repair_decision.
    verify_receipt`, the one the status generator applies), then the primary
    basis it names."""
    assert isinstance(record.get("source_report"), str), (
        "the Step-32 decision record names no measured basis "
        f"(source_report={record.get('source_report')!r})")
    R._repair_dec.verify_receipt(p, record)
    return (p / record["source_report"]).resolve()


def _status_gen(p: Path) -> subprocess.CompletedProcess:
    """The generator exactly as the runner dispatches it."""
    return subprocess.run([sys.executable, str(PROGRAMS / STATUS_GEN), str(p)],
                          capture_output=True, text=True, timeout=120)


def test_no_repair_record_is_bound_and_the_flag_survives_the_generator(
        tmp_path, monkeypatch):
    p = _proj(tmp_path)
    _canonicalize(p, monkeypatch, SPEF_MET)
    record = json.loads((p / DECISION).read_text())
    assert record["repair_needed"] is False
    assert record["action"] == "no_repair_needed_flag"
    assert (p / FLAG).is_file()
    basis = _bound_basis(p, record)
    # Single-corner basis here: the report canonicalize parsed for timing.
    assert basis.name == "sta_spef_based.rpt"

    cp = _status_gen(p)
    assert cp.returncode == 0, cp.stderr
    assert json.loads(cp.stdout)["artefact"] == FLAG
    assert (p / FLAG).is_file() and not (p / LOG).exists()

    # The binding is to BYTES: a changed basis no longer verifies, and the
    # shipped generator then withdraws the flag (NOT_MEASURED, rc 2).
    basis.write_text(basis.read_text() + "\n")
    assert hashlib.sha256(basis.read_bytes()).hexdigest() \
        != record["source_report_sha256"]
    cp = _status_gen(p)
    assert cp.returncode == 2 and "sha256 changed" in cp.stderr, cp.stderr
    assert not (p / FLAG).exists()


def test_multi_corner_basis_binds_the_stance_the_decision_read(
        tmp_path, monkeypatch):
    p = _proj(tmp_path)
    stance = p / "reports/phase3/mcorner_ocv_stance.json"
    stance.parent.mkdir(parents=True, exist_ok=True)
    stance.write_text(json.dumps({
        "signoff_dimension": "multi_corner_ocv_process",
        "setup_process_corner": "SS", "hold_process_corner": "FF",
        "multi_process_corner": True,
        "report": "phase3/stage3/sta/sta_mcorner_ocv.rpt",
        "setup_worst_slack_ns": 2.5, "hold_worst_slack_ns": 0.4,
        "violated_corners": []}))
    # Newer than every layout input, so canonicalize reuses it as measured.
    future = time.time() + 3600
    os.utime(stance, (future, future))
    _canonicalize(p, monkeypatch, SPEF_MET)
    record = json.loads((p / DECISION).read_text())
    assert record["basis"] == "multi_corner_ocv"
    assert record["repair_needed"] is False
    assert _bound_basis(p, record) == stance.resolve()
    assert (p / FLAG).is_file()


def test_genuine_repair_needed_still_requires_a_repair_log(tmp_path, monkeypatch):
    p = _proj(tmp_path)
    _canonicalize(p, monkeypatch, SPEF_VIOLATED)
    record = json.loads((p / DECISION).read_text())
    assert record["repair_needed"] is True
    _bound_basis(p, record)
    assert not (p / FLAG).exists()

    cp = _status_gen(p)
    assert cp.returncode == 0, cp.stderr
    assert not (p / FLAG).exists()
    log = json.loads((p / LOG).read_text())
    assert log["verdict"] == "REPAIR_REQUIRED"
    # A demand, not a certificate: the audit refuses a log with no repair.
    audit = subprocess.run(
        [sys.executable, str(PROGRAMS / "postroute_timing_repair_audit.py"),
         str(p)], capture_output=True, text=True, timeout=120)
    assert audit.returncode != 0, audit.stdout


def test_no_measured_basis_binds_nothing(tmp_path):
    decision = {"repair_needed": True, "mc_ocv_available": False}
    record = R._step32_decision_record(
        tmp_path, decision, tmp_path / "reports/phase3/mcorner_ocv_stance.json",
        tmp_path / "phase3/stage3/sta/absent.rpt")
    assert record["source_report"] is None
    assert record["source_report_sha256"] is None
    assert record["repair_needed"] is True


def test_a_derived_generator_refusal_is_reported_not_discarded(
        tmp_path, monkeypatch, capsys):
    # No STA report on disk: the shipped status generator refuses (rc 2).
    monkeypatch.setattr(R, "_DERIVED_ARTEFACT_GENERATORS",
                        ((STATUS_GEN, "post-route repair no-op flag"),))
    outcomes = R._run_derived_artefact_generators(tmp_path, None)
    assert [o["program"] for o in outcomes] == [STATUS_GEN]
    assert outcomes[0]["rc"] == 2
    assert "No candidate post-route STA report" in outcomes[0]["message"]
    err = capsys.readouterr().err
    assert f"{STATUS_GEN} exited rc=2" in err
    assert "No candidate post-route STA report" in err


# ---------------------------------------------------------------------------
# Review wave 57 (STEP32FLAG adversarial) + R-0929-STEP32-RECORD
# ---------------------------------------------------------------------------

LL_REPORT = "reports/phase3/librelane_postroute_repair.json"


def _audit(p: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "postroute_timing_repair_audit.py"), str(p)],
        capture_output=True, text=True, timeout=120)


def _ll_report(p: Path, *, adopted, before_drv, after_drv, setup=0.5, hold=0.2):
    """The Step-32 LibreLane producer's own report, as `run` writes it: the
    census baseline, the adopted candidate, and the adopted route's
    STAPostPNR measurement bound by its state's sha256."""
    state = p / "phase3/librelane/32-cand01/03-openroad-stapostpnr/state_out.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"metrics": {"x": 1}}))
    digest = hashlib.sha256(state.read_bytes()).hexdigest()
    report = p / LL_REPORT
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "step": "32", "mode": "librelane", "verdict": "PASS", "adopted": adopted,
        "baseline": {"drv_count": before_drv, "setup_ws_min": setup,
                     "hold_ws_min": hold},
        "final": {"drv_count": after_drv, "setup_ws_min": setup, "hold_ws_min": hold,
                  "sta_state": str(state), "sta_state_sha256": digest}}))
    return report, state


def test_an_adopted_candidate_is_recorded_as_a_repair_not_a_flag(tmp_path, monkeypatch):
    """R-0929-STEP32-RECORD: Step 32 adopted a candidate (DRV 9 -> 0) on a
    timing-clean route. The run records a repair: repair_log.json with the
    candidate, before/after and the sha-bound re-verification; no flag."""
    p = _proj(tmp_path)
    _ll_report(p, adopted="32-cand01", before_drv=9, after_drv=0)
    _canonicalize(p, monkeypatch, SPEF_MET)
    record = json.loads((p / DECISION).read_text())
    assert record["repair_needed"] is True
    assert record["action"] == "candidate_adopted"
    assert not (p / FLAG).exists()
    _bound_basis(p, record)
    assert LL_REPORT in [row["path"] for row in record["inputs"]]
    log = json.loads((p / LOG).read_text())
    assert log["candidate"] == "32-cand01"
    assert log["before"]["drv_count"] == 9 and log["after"]["drv_count"] == 0
    assert log["re_verification"]["sta_state_sha256_verified"] is True
    assert log["re_verification"]["no_further_repair_needed"] is True
    assert log["re_verified"] is True and log["changes"]
    cp = _status_gen(p)
    assert cp.returncode == 0, cp.stderr
    assert not (p / FLAG).exists()
    assert json.loads((p / LOG).read_text())["candidate"] == "32-cand01"
    assert _audit(p).returncode == 0


def test_a_residual_drv_after_adoption_stays_a_failure(tmp_path, monkeypatch):
    """R-0929-STEP32-ADOPT: the improving candidate is adopted and recorded,
    and its residual DRV keeps Step 32 FAIL (never a flag, never a waiver)."""
    p = _proj(tmp_path)
    _ll_report(p, adopted="32-cand01", before_drv=9, after_drv=3)
    _canonicalize(p, monkeypatch, SPEF_MET)
    record = json.loads((p / DECISION).read_text())
    assert record["repair_needed"] is True
    assert [r["domain"] for r in record["nontiming_failures"]] == ["drv"]
    log = json.loads((p / LOG).read_text())
    assert log["residual_violation"] is True
    assert log["re_verified"] is False
    assert log["re_verification"]["no_further_repair_needed"] is False
    assert not (p / FLAG).exists()
    assert _status_gen(p).returncode == 0 and not (p / FLAG).exists()
    audit = _audit(p)
    assert audit.returncode != 0 and "REPAIR_BLOCKED_ON_NONTIMING_SIGNOFF" in audit.stdout


def test_decide_sees_the_step32_drv(tmp_path):
    """decide() reads the DRV Step 32 measured on the route it kept: a
    residual is a failed domain, an absent count is not a zero."""
    p = tmp_path
    _ll_report(p, adopted=None, before_drv=3, after_drv=3)
    d = R._repair_dec.decide(None, True, project=p)
    assert d["repair_needed"] is True and d["timing_repair_needed"] is False
    assert d["nontiming_failures"][0]["signal"] == "drv_count=3"
    _ll_report(p, adopted=None, before_drv=3, after_drv=None)
    d = R._repair_dec.decide(None, True, project=p)
    assert d["repair_needed"] is True
    assert d["nontiming_not_determined"][0]["domain"] == "drv"
    _ll_report(p, adopted=None, before_drv=0, after_drv=0)
    assert R._repair_dec.decide(None, True, project=p)["repair_needed"] is False


def test_a_bound_producer_receipt_is_never_overwritten(tmp_path, monkeypatch):
    """Adversarial wave 57 MAJOR: a bound Step-32 PRODUCER receipt says
    repair_needed=true (DRV 9 -> residual 3, not re-verified) on a
    timing-clean route. Canonicalize must not flip it to false, must not
    write the flag, and must leave the receipt and its repair_log as written;
    the shipped generator keeps it true and the audit refuses."""
    p = _proj(tmp_path)
    report, _ = _ll_report(p, adopted=None, before_drv=9, after_drv=3)
    receipt = {"repair_needed": True, "action": "input_route_kept",
               "baseline": {"drv_count": 9}, "final": {"drv_count": 3},
               "residual": {"drv_count": 3},
               "source_report": LL_REPORT,
               "source_report_sha256": hashlib.sha256(report.read_bytes()).hexdigest()}
    (p / REPAIR).mkdir(parents=True, exist_ok=True)
    (p / DECISION).write_text(json.dumps(receipt))
    (p / LOG).write_text(json.dumps({"changes": [], "re_verified": False}))
    before = (p / DECISION).read_bytes(), (p / LOG).read_bytes()
    _canonicalize(p, monkeypatch, SPEF_MET)
    assert (p / DECISION).read_bytes() == before[0], "the producer receipt was rewritten"
    assert (p / LOG).read_bytes() == before[1]
    assert not (p / FLAG).exists()
    canonical = json.loads((p / REPAIR / "postroute_timing_repair_decision.canonical.json")
                           .read_text())
    assert canonical["repair_needed"] is True
    cp = _status_gen(p)
    assert cp.returncode == 0, cp.stderr
    assert json.loads(cp.stdout).get("measured_step32_repair_needed") is True
    assert not (p / FLAG).exists()
    assert _audit(p).returncode != 0


def test_the_record_binds_every_decision_input(tmp_path, monkeypatch):
    """Adversarial wave 57 minor: the record binds the report the stance
    summarises, the tt report, the hold inputs and the non-timing reports --
    not only the stance summary. Any of them changing voids the receipt."""
    p = _proj(tmp_path)
    stance = p / "reports/phase3/mcorner_ocv_stance.json"
    stance.parent.mkdir(parents=True, exist_ok=True)
    mc = p / "phase3/stage3/sta/sta_mcorner_ocv.rpt"
    mc.parent.mkdir(parents=True, exist_ok=True)
    mc.write_text("worst slack max 2.5\n")
    stance.write_text(json.dumps({
        "multi_process_corner": True, "report": "phase3/stage3/sta/sta_mcorner_ocv.rpt",
        "setup_worst_slack_ns": 2.5, "hold_worst_slack_ns": 0.4,
        "violated_corners": []}))
    ir = p / "reports/phase3/ir_drop.json"
    ir.write_text(json.dumps({"verdict": "PASS"}))
    future = time.time() + 3600
    os.utime(stance, (future, future))
    _canonicalize(p, monkeypatch, SPEF_MET)
    record = json.loads((p / DECISION).read_text())
    bound = {row["path"] for row in record["inputs"]}
    assert {"phase3/stage3/sta/sta_mcorner_ocv.rpt", "reports/phase3/ir_drop.json",
            "reports/phase3/mcorner_ocv_stance.json"} <= bound
    assert any(path.endswith("sta_spef_based.rpt") for path in bound)
    R._repair_dec.verify_receipt(p, record)
    for changed in (mc, ir):
        original = changed.read_bytes()
        changed.write_bytes(original + b"\n")
        try:
            R._repair_dec.verify_receipt(p, record)
            raise AssertionError(f"{changed.name} changed and the receipt still verified")
        except ValueError as exc:
            assert "sha256 changed" in str(exc)
        changed.write_bytes(original)


def test_a_generator_refusal_is_in_the_run_record(tmp_path, monkeypatch):
    """Adversarial wave 57 minor: the refusal reaches a durable record and
    the run's step list, not only stderr."""
    monkeypatch.setattr(R, "_DERIVED_ARTEFACT_GENERATORS",
                        ((STATUS_GEN, "post-route repair no-op flag"),))
    outcomes = R._run_derived_artefact_generators(tmp_path, None)
    record = json.loads((tmp_path / "reports/phase3" / R.DERIVED_GENERATORS_RECORD)
                        .read_text())
    assert record["outcomes"] == outcomes and outcomes[0]["rc"] == 2
    steps = R._derived_generator_refusals(outcomes)
    assert [s.status for s in steps] == ["NOT_MEASURED"]
    assert STATUS_GEN in steps[0].name and "No candidate post-route STA report" in steps[0].detail


# ---------------------------------------------------------------------------
# Review wave 58 (STEP32FLAG final): behind a bound producer receipt the
# canonical decision's demands must still reach the Step-32 audit.
# ---------------------------------------------------------------------------

def _adopted_producer_receipt(p: Path) -> None:
    """The real spm path: LibreLane Step 32 adopted 32-cand01 (DRV 9 -> 0)
    and published its bound receipt and a re-verified repair_log."""
    report, state = _ll_report(p, adopted="32-cand01", before_drv=9, after_drv=0)
    (p / REPAIR).mkdir(parents=True, exist_ok=True)
    (p / DECISION).write_text(json.dumps({
        "repair_needed": True, "action": "candidate_adopted",
        "baseline": {"drv_count": 9}, "final": {"drv_count": 0},
        "residual": {"drv_count": 0},
        "source_report": LL_REPORT,
        "source_report_sha256": hashlib.sha256(report.read_bytes()).hexdigest()}))
    (p / LOG).write_text(json.dumps({
        "changes": [{"candidate": "32-cand01"}], "re_verified": True,
        "affected_steps": []}))


def test_a_nontiming_failure_behind_a_producer_receipt_reaches_the_audit(
        tmp_path, monkeypatch):
    """Wave 58 (a): adopted candidate, IR-drop sign-off FAIL, timing met. The
    canonical record names ir_drop; the audit must refuse, as main does."""
    p = _proj(tmp_path)
    _adopted_producer_receipt(p)
    ir = p / "reports/phase3/ir_drop.json"
    ir.write_text(json.dumps({"verdict": "FAIL"}))
    before = (p / DECISION).read_bytes(), (p / LOG).read_bytes()
    _canonicalize(p, monkeypatch, SPEF_MET)
    assert (p / DECISION).read_bytes() == before[0]
    assert (p / LOG).read_bytes() == before[1]
    canonical = json.loads((p / CANONICAL).read_text())
    assert [r["domain"] for r in canonical["nontiming_failures"]] == ["ir_drop"]
    _status_gen(p)
    audit = _audit(p)
    assert audit.returncode != 0, audit.stdout
    assert "REPAIR_BLOCKED_ON_NONTIMING_SIGNOFF" in audit.stdout


def test_a_timing_violation_behind_a_producer_receipt_reaches_the_audit(
        tmp_path, monkeypatch):
    """Wave 58 (b): the same receipt, single-corner SPEF VIOLATED -12.27 ns,
    no multi-corner OCV, so no actuator fires. The producer's re-verified log
    does not describe this violation; the audit must refuse."""
    p = _proj(tmp_path)
    _adopted_producer_receipt(p)
    _canonicalize(p, monkeypatch, SPEF_VIOLATED)
    canonical = json.loads((p / CANONICAL).read_text())
    assert canonical["timing_repair_needed"] is True
    assert not (p / FLAG).exists()
    _status_gen(p)
    audit = _audit(p)
    assert audit.returncode != 0, audit.stdout
    assert "TIMING_REPAIR_REQUIRED_UNAPPLIED" in audit.stdout


def test_the_canonical_record_is_written_on_every_run(tmp_path, monkeypatch):
    """`.canonical.json` is a declared Step-32 output, so it exists with and
    without a producer receipt."""
    p = _proj(tmp_path)
    _canonicalize(p, monkeypatch, SPEF_MET)
    assert json.loads((p / CANONICAL).read_text()) == json.loads((p / DECISION).read_text())
