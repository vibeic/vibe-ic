#!/usr/bin/env python3
"""`spm` on gf180mcuD halted at `drc` with 70 violations. 60 of them were ours.

MEASURED (host 8HD-6, image `ghcr.io/vibeic/vibeic-eda@sha256:06537f7e…`, own
label 0.3.46; plugin base `ad38a76d` = v1.17.45; two PnR arms whose only
difference is the fix under test):

  arm A (base)  76 sign-off violations: DF.13_MV 41 · DF.14_MV 19 ·
                ANT.16_ii_ANT.3 6 · ANT.16_ii_ANT.5 3 · PL.8 1 ·
                M1.4/M2.4/M3.4/M4.4/M5.4/MT.3 1 each
  arm B (fix)   16: DF.13_MV 0 · DF.14_MV 0, everything else BYTE-FOR-BYTE
                the same set. Zero new violations.

  (The six metal-density rows are present in BOTH arms because the sandbox
  streams the DEF straight to GDS without the flow's metal fill; the flow's
  own run closes them. arm A's remaining 70 is exactly the run's 70.)

WHAT WAS WRONG. `_build_tapcell_prune_tcl` decides tap coverage at
`placed.def` time. CTS, the resizer repair passes and `repair_antennas` all
create DEVICE-BEARING cells AFTER that, and `tapcell` cannot be re-run once
cells are placed. Measured on the shipped `spm.def`: 14 of 651 logic/buffer
instances and 4 of 64 antenna diodes had NO well-tie within the PDK max tap
distance — worst 98.7 um — and the sign-off deck put 60 of the run's 70
violations on them. Two of them (`wire70`, `wire79`, row y=709.52 um) were
7.84 um from a tie one row below and STILL violated: gf180mcu's DF.13_MV
grows the tap INSIDE nwell, and a neighbouring row's nwell is a separate
island. So the repair is PER ROW, not by euclidean distance.

Also covered here, both found while reading the same run:
  * RB-12 flow ordering — `signoff_metrics_aggregate` ran BEFORE the three
    sign-off gates that write the reports it reads.
  * RB-13 schema — the same record's LVS reader knew one of the two spellings
    its own producers use for the verdict.
  * RB-15 — the SPICE correlation gate built its deck at the ACTIVE liberty's
    PVT and compared it against a path taken from a report produced at a
    DIFFERENT corner, then charged the difference to the design.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import signoff_metrics_aggregate as sma  # noqa: E402
import spice_correlation_check as scc  # noqa: E402




# ── the repair block itself ──────────────────────────────────────────────────




















# ── RB-12: the sign-off gates write what the metrics record reads ────────────


def test_declared_signoff_gates_run_before_the_metrics_record():
    """MEASURED: `signoff_metrics_aggregate` was produced over reports that did
    not exist yet -- 7 of 18 keys NOT_MEASURED, its own `--check` green because
    both sides were empty, and rc=1 FAIL in the SAME run's gate ledger."""
    from _phase3_main_dispatch import _main, _calls, guarded_producer_line
    main, _ = _main()
    gates = _calls(main, "step_declared_signoff_gates")[0].lineno
    record = guarded_producer_line("step_signoff_metrics_aggregate",
                                   "signoff_metrics_aggregate")
    assert gates < record, (
        "the gates that write post_route_signoff_corner.json, "
        "sta_corner_record_completeness.json and tapeout_precheck.json must "
        "be planned BEFORE the record that reads them")


def test_metrics_record_still_precedes_the_release_documents():
    """37.5ic blocks_on 37.4; the reorder must not have moved that."""
    from _phase3_main_dispatch import guarded_producer_line
    record = guarded_producer_line("step_signoff_metrics_aggregate",
                                   "signoff_metrics_aggregate")
    docs = guarded_producer_line("step_tapeout_docs_gen",
                                 "tapeout_docs_gen")
    assert record < docs


# ── RB-13: the LVS verdict has two spellings and both are the flow's own ─────
def _write_lvs(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "reports" / "phase3"
    p.mkdir(parents=True, exist_ok=True)
    (p / "lvs.json").write_text(json.dumps(payload))
    return tmp_path


LVS_KEYS = ("design__lvs_error__count", "design__lvs_unmatched_device__count",
            "design__lvs_unmatched_net__count",
            "design__lvs_unmatched_pin__count")


def test_lvs_reads_the_netgen_parser_top_level_verdict(tmp_path):
    """The shape `spm` actually shipped: verdict at the TOP level."""
    proj = _write_lvs(tmp_path, {
        "verdict": "match", "verdict_reason": "circuits match uniquely",
        "summary": {"devices": {"ckt1": 661, "ckt2": 661},
                    "unmatched_devices": {"ckt1": 0, "ckt2": 0}}})
    for key in LVS_KEYS:
        cell = sma._lvs(proj, key)
        assert cell.value == 0, key
        assert "verdict=MATCH" in cell.basis


def test_lvs_still_reads_the_audit_spelling(tmp_path):
    """`eda_report_audit:lvs` puts it under summary. Unchanged."""
    proj = _write_lvs(tmp_path, {"summary": {"terminal_verdict": "MATCH"}})
    cell = sma._lvs(proj, LVS_KEYS[0])
    assert cell.value == 0
    assert "summary.terminal_verdict=MATCH" in cell.basis


def test_lvs_a_non_match_is_still_not_a_count(tmp_path):
    """The §4.05 no-leak arm: reading a second spelling must not turn a
    MISMATCH into a zero."""
    proj = _write_lvs(tmp_path, {"verdict": "mismatch",
                                 "summary": {"unmatched_devices":
                                             {"ckt1": 3, "ckt2": 3}}})
    cell = sma._lvs(proj, LVS_KEYS[1])
    assert cell.value == "NOT_MEASURED"
    assert "'MISMATCH'" in cell.reason and "not MATCH" in cell.reason


def test_lvs_audit_spelling_mismatch_is_still_not_a_count(tmp_path):
    """The no-leak arm that is GREEN ON BOTH SIDES of this change: reading a
    second spelling must not have made the FIRST one softer."""
    proj = _write_lvs(tmp_path, {"summary": {"terminal_verdict": "MISMATCH"}})
    cell = sma._lvs(proj, LVS_KEYS[1])
    assert cell.value == "NOT_MEASURED"
    assert "not MATCH" in cell.reason


def test_lvs_no_verdict_at_all_names_both_spellings(tmp_path):
    proj = _write_lvs(tmp_path, {"summary": {"devices": {"ckt1": 1}}})
    cell = sma._lvs(proj, LVS_KEYS[0])
    assert cell.value == "NOT_MEASURED"
    assert "summary.terminal_verdict" in cell.reason
    assert "verdict" in cell.reason


def _write_lvs_verdict(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "reports" / "phase3"
    p.mkdir(parents=True, exist_ok=True)
    (p / "lvs_verdict.json").write_text(json.dumps(payload))
    return tmp_path


def test_lvs_falls_back_to_the_runners_own_verdict_file(tmp_path):
    """MEASURED: once the ties were restored, the POWER-AWARE compare became
    the accepted arm on its first attempt -- a STRONGER result -- and netgen's
    `lvs.json` sidecar (named from the plain arm's logfile stem) vanished with
    it. All four LVS keys went NOT_MEASURED on a run whose LVS is better.
    Control on the real run tree: 6 NOT_MEASURED without this, 2 with it, and
    the delta is exactly the four LVS keys."""
    proj = _write_lvs_verdict(tmp_path, {
        "status": "PASS", "result": "PASS",
        "finding": "LVS_MATCH_POWER_VERIFIED",
        "message": "circuits match uniquely with a POWER-AWARE gate netlist"})
    for key in LVS_KEYS:
        cell = sma._lvs(proj, key)
        assert cell.value == 0, key
        assert "LVS_MATCH_POWER_VERIFIED" in cell.basis


def test_lvs_verdict_file_is_only_consulted_when_the_sidecar_is_absent(
        tmp_path):
    """The sidecar stays the first authority: a MISMATCH there is not
    overridden by a PASS in the verdict file."""
    proj = _write_lvs(tmp_path, {"verdict": "mismatch"})
    _write_lvs_verdict(tmp_path, {"status": "PASS", "finding": "LVS_MATCH"})
    cell = sma._lvs(proj, LVS_KEYS[0])
    assert cell.value == "NOT_MEASURED"
    assert "not MATCH" in cell.reason


def test_lvs_verdict_file_non_pass_is_still_not_a_count(tmp_path):
    proj = _write_lvs_verdict(tmp_path, {"status": "FAIL",
                                         "finding": "LVS_MISMATCH"})
    cell = sma._lvs(proj, LVS_KEYS[2])
    assert cell.value == "NOT_MEASURED"
    assert "'FAIL'" in cell.reason and "not a match" in cell.reason


def test_lvs_neither_file_names_all_three(tmp_path):
    (tmp_path / "reports" / "phase3").mkdir(parents=True)
    cell = sma._lvs(tmp_path, LVS_KEYS[0])
    assert cell.value == "NOT_MEASURED"
    assert "three files" in cell.reason


# ── RB-15: the correlation must not cross corners ────────────────────────────
_OCV_REPORT = """\
=== SETUP corner: process=SS liberty=/pdk/lib/cell__ss_125C_4v50.lib, SPEF=x ===
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
STA_BASIS: POST_ROUTE_SPEF
STA_BASIS_LIBERTY: /pdk/lib/cell__ss_125C_4v50.lib
"""

_MULTICORNER_REPORT = """\
# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
# corner_liberty: max=/pdk/lib/cell__tt_025C_5v00.lib
"""


def test_sta_corner_basis_reads_the_report_declared_liberty():
    b = scc.parse_sta_corner_basis(_OCV_REPORT)
    assert b["liberty"] == "/pdk/lib/cell__ss_125C_4v50.lib"
    assert b["ocv_late_derate"] == 1.05


def test_sta_corner_basis_reads_the_multicorner_spelling():
    b = scc.parse_sta_corner_basis(_MULTICORNER_REPORT)
    assert b["liberty"] == "/pdk/lib/cell__tt_025C_5v00.lib"
    assert b["ocv_late_derate"] is None


def test_sta_corner_basis_is_empty_when_the_report_declares_nothing():
    """An undeclared corner must reach the caller as ABSENT, so it can decline
    rather than fall back on the active corner."""
    b = scc.parse_sta_corner_basis("Startpoint: a\nEndpoint: b\n")
    assert b["liberty"] == ""


def _stub_driver(monkeypatch, tmp_path, sta_text, calls):
    """Use the current Step-23 State/receipt; stop at native transport.

    The historical OCV report stays on disk and cannot stand in for the
    current corner. Reuse the shipped source-only binding fixture rather
    than replacing the current State reader or any scientific verdict.
    """
    import test_default_si_spice_power as fixture
    from test_spice_correlation_sta_slack_parse import _current_binding_fixture

    name = Path(scc.parse_sta_corner_basis(_OCV_REPORT)["liberty"]).name
    project, folder, lib, observations = _current_binding_fixture(
        tmp_path, monkeypatch, corner="slow", liberty_name=name)
    lib.write_text(lib.read_text().replace(
        "{", "{ nom_temperature: 125; nom_voltage: 4.50;", 1))
    fingerprint = json.loads((folder / "input_fingerprint.json").read_text())
    guest = "/pdk/neutral/" + name
    fingerprint["config_files"][guest] = fixture.LC.digest(lib)
    fingerprint["liberty_files"][guest] = fixture.LC.digest(lib)
    fixture.seal(folder, fingerprint)
    historical = project / "phase3/stage3/sta/sta_mcorner_ocv.rpt"
    historical.parent.mkdir(parents=True, exist_ok=True)
    historical.write_text(sta_text)
    model = project / "fixture_pdk/neutral/libs.tech/ngspice/model.sp"
    model.write_text(".lib ss\n.model neutral nmos level=1\n.endl ss\n"
                     ".lib tt\n.model neutral nmos level=1\n.endl tt\n")
    record_path = project / fixture.LP.STEP23_RECORD
    if not scc.parse_sta_corner_basis(sta_text)["liberty"]:
        record = json.loads(record_path.read_text())
        record["judgment"]["worst_setup"].pop("corner")
        fixture.put(record_path, record)

    stopped_transport = fixture.PST.run_step30
    calls["binding"] = observations
    calls["liberty"] = lib
    calls["model"] = model

    def observe(*args, **kwargs):
        try:
            return stopped_transport(*args, **kwargs)
        except fixture.LC.Refusal:
            if observations:
                observed = observations[-1]
                # These are the real bound inputs and the actual native Tcl,
                # not calls to the retired text-report discovery driver.
                calls["read"] += observed["inputs"]["liberties"]
                calls["models"] = fixture.PST.model_file(
                    model.parent, "/pdk/neutral/libs.tech/ngspice", "ngspice",
                    Path(observed["inputs"]["liberties"][0]).name,
                    {"neutral"}, scc.parse_liberty_header(lib.read_text())["nom_temperature"],
                    project / "SOURCE_FIXTURE_ONLY/models.sp")
            raise

    monkeypatch.setattr(fixture.PST, "run_step30", observe)
    return project


ACTIVE_TT = "/pdk/lib/cell__tt_025C_5v00.lib"


def test_driver_builds_the_deck_at_the_corner_the_report_declares(
        monkeypatch, tmp_path):
    """Current Step-23 corner wins over the caller's active-TT hint."""
    calls = {"read": [], "discover": []}
    project = _stub_driver(monkeypatch, tmp_path, _OCV_REPORT, calls)
    result = scc.run_installed_pdk_path_correlation(
        project, liberty_path=ACTIVE_TT, container="none")
    ss = "/pdk/neutral/cell__ss_125C_4v50.lib"
    assert ss in calls["read"], (
        "the corner liberty the current STA State declares was never read")
    assert calls["models"]["sections"] == [[str(calls["model"]), "ss"]], (
        "the device-model section must be selected for the same slow corner")
    assert calls["models"]["temperature"] == 125.0
    assert "read_liberty " + ss in calls["binding"][0]["script"]
    assert result["status"] == "ERROR" and result["measurement"] == "NOT_MEASURED"
    assert result["reason"].startswith("SOURCE_FIXTURE_ONLY_NATIVE_TRANSPORT_NOT_RUN:")


def test_driver_declines_when_the_report_declares_no_corner(
        monkeypatch, tmp_path):
    """An undeclared current corner refuses; active TT is never a fallback."""
    calls = {"read": [], "discover": []}
    project = _stub_driver(monkeypatch, tmp_path,
                 "STA_BASIS: POST_ROUTE_SPEF\n"
                 "Startpoint: a\nEndpoint: b\n  0.00 0.00 x\n", calls)
    out = scc.run_installed_pdk_path_correlation(
        project, liberty_path=ACTIVE_TT, container="none")
    assert out["status"] == "ERROR"
    assert "CURRENT_STEP30_CORNER_MISSING" in out["reason"]
    assert calls["binding"] == [] and calls["read"] == []


def test_driver_declines_when_the_declared_corner_cannot_be_read(
        monkeypatch, tmp_path):
    calls = {"read": [], "discover": []}
    project = _stub_driver(monkeypatch, tmp_path, _OCV_REPORT, calls)
    calls["liberty"].unlink()
    out = scc.run_installed_pdk_path_correlation(
        project, liberty_path=ACTIVE_TT, container="none")
    assert out["status"] == "ERROR"
    assert calls["liberty"].name in out["reason"]
    assert calls["binding"] == [] and calls["read"] == []


def test_driver_divides_out_the_ocv_derate_the_spice_side_does_not_carry(
        tmp_path, monkeypatch):
    """The current route measures nominal STA and SPICE in the same session.

    The retired report-based driver divided its borrowed OCV report by 1.05.
    The native owner instead emits report_checks and write_path_spice together,
    so applying that old division again would manufacture a basis mismatch.
    """
    import path_spice_tool as pst
    calls = {"read": [], "discover": []}
    project = _stub_driver(monkeypatch, tmp_path, _OCV_REPORT, calls)
    result = scc.run_installed_pdk_path_correlation(
        project, liberty_path=ACTIVE_TT, container="none")
    assert result["reason"].startswith("SOURCE_FIXTURE_ONLY_NATIVE_TRANSPORT_NOT_RUN:")
    observed = calls["binding"][0]
    script = observed["script"]
    assert script.index("report_checks ") < script.index("write_path_spice ")
    assert "set_timing_derate" not in script and "1.05" not in script
    assert "set_timing_derate" not in (project / observed["inputs"]["sdc"]).read_text()
    native = ("Startpoint: in\nEndpoint: out\n"
              " 0.02 0.00 0.00 ^ in (in)\n"
              " 0.03 13.40 13.40 ^ out (BUF)\n")
    parsed = pst.parse_path_report(native)
    assert parsed["path_delay_ns"] == pytest.approx(13.40)
    assert parsed["path_delay_ns"] != pytest.approx(13.40 / 1.05)


def test_stagewise_deck_visits_the_sta_operating_points():
    """The tolerance is derived per stage at the STA (slew, load) points, so
    the measurement has to be taken there. MEASURED on `spm`: the free-running
    chain gave -47.6 %, the same stages at those points -22.4 %."""
    stages = [
        {"cell": "buf", "toggle_pin": "I", "out_pin": "Z",
         "transition": "fall", "sta_load_pf": 0.04, "wire_cap_pf": 0.01,
         "sta_delay_ns": 0.55},
        {"cell": "buf", "toggle_pin": "I", "out_pin": "Z",
         "transition": "rise", "sta_load_pf": 0.39, "wire_cap_pf": 0.14,
         "sta_delay_ns": 1.39},
    ]
    deck = scc.build_installed_stagewise_deck(
        "/m.spice", "ss", [], "/c.spice", stages,
        {"buf": (["I", "Z", "VDD", "VNW", "VPW", "VSS"], "")},
        4.5, 125.0, 2.25, 0.05, [0.5, 2.0])
    # the STA load, not the SPEF wire cap
    assert "c0r so0r 0 40f" in deck and "c1r so1r 0 390f" in deck
    # both drive polarities for both stages
    for n in ("vsi0r", "vsi0f", "vsi1r", "vsi1f"):
        assert n in deck
    # measured to the transition the STA row declares
    assert "TARG v(so0r) VAL='2.25' FALL=1" in deck
    assert "TARG v(so1r) VAL='2.25' RISE=1" in deck


def test_stagewise_parse_takes_the_one_arc_that_can_exist():
    """Exactly one drive polarity can produce the declared output edge."""
    transcript = (
        "d0f                 =  3.94501e-10 targ=  1.03950e-08\n"
        "mx0f                =  4.50000e+00 at=  1.1e-08\n"
        "mn0f                =  0.00000e+00 at=  1.0e-08\n"
        "Error: measure  d0r  trig(TARG) : out of interval\n")
    vals, why = scc.parse_stagewise_meas(transcript, 1, 4.5)
    assert why == ""
    assert vals == pytest.approx([0.394501], rel=1e-6)


def test_stagewise_parse_refuses_when_no_polarity_survives():
    vals, why = scc.parse_stagewise_meas(
        "Error: measure  d0r  trig(TARG) : out of interval\n"
        "Error: measure  d0f  trig(TARG) : out of interval\n", 1, 4.5)
    assert vals is None
    assert "0 of 2 drive polarities" in why


def test_stagewise_parse_refuses_a_stage_that_did_not_swing():
    """A number taken off a node that never reached the rail is not a delay."""
    transcript = ("d0f = 3.9e-10 targ= 1e-08\n"
                  "mx0f = 1.00000e+00 at= 1.1e-08\n"
                  "mn0f = 0.00000e+00 at= 1.0e-08\n")
    vals, why = scc.parse_stagewise_meas(transcript, 1, 4.5)
    assert vals is None and "full swing" in why


def test_stagewise_parse_refuses_when_both_polarities_survive():
    """Two live arcs is an unresolved sensitisation, not a choice to make."""
    transcript = "".join(
        f"d0{v} = 3.9e-10 targ= 1e-08\nmx0{v} = 4.5e+00 at= 1e-08\n"
        f"mn0{v} = 0.0e+00 at= 1e-08\n" for v in ("r", "f"))
    vals, why = scc.parse_stagewise_meas(transcript, 1, 4.5)
    assert vals is None and "2 of 2 drive polarities" in why


def test_path_deck_window_clears_the_delay_it_is_measuring():
    """At tt the path is 3.87 ns inside an 8 ns half-period and nothing showed;
    at the report's own corner it is 7.15 ns, 89 % of that window."""
    src = (PROGS / "spice_correlation_check.py").read_text()
    assert "pw = max(8.0, 24.0 * tr_ns, 3.0 * float(expected_ns or 0.0))" in src


# ── the modules still parse and the new names are real ───────────────────────
@pytest.mark.parametrize("mod", ["phase3_one_shot_runner.py",
                                 "signoff_metrics_aggregate.py",
                                 "spice_correlation_check.py"])
def test_touched_modules_parse(mod):
    ast.parse((PROGS / mod).read_text())
