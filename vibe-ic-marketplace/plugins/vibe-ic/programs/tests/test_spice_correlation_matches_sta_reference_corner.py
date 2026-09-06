"""test_spice_correlation_matches_sta_reference_corner.py

The Step-30 transistor-level correlation compares a Liberty+SPEF path delay
taken from a post-route STA report against an ngspice measurement of the same
stitched path.  That subtraction is a statement about the DESIGN only while
both sides sit at the same PVT corner.

Before this test existed the reference came from the STA report (timed at the
SLOW sign-off corner the flow selects for step 23) while the deck was built
from the PDK's NOMINAL Liberty — different process section, different
temperature, different supply.  The check then measured the corner-to-corner
delay ratio and reported it as a design error.

These tests are hermetic: every container call and the simulator itself are
substituted, so they assert the DECK the driver builds and the VERDICT it
reaches, never a PDK's numbers.  The stand-in simulator is corner-aware — it
reads the deck the driver just wrote and answers with the delay that corner
would really produce — which is what makes the second direction meaningful:
with the corners matched, a REAL delay error still has to FAIL.

No design, PDK, foundry or vendor name appears here; the fixture library is a
two-corner invention.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import spice_correlation_check as m  # noqa: E402


# ── fixture PDK (invented) ───────────────────────────────────────────────────
PDK_ROOT = "/toypdk"
LIB_DIR = PDK_ROOT + "/libs.ref/toycells/lib"
CELL_SPICE = PDK_ROOT + "/libs.ref/toycells/spice/toycells.spice"
MODEL_FILE = PDK_ROOT + "/libs.tech/ngspice/toymodels.spice"

LIB_NOMINAL = LIB_DIR + "/toycells__tt_025C_5v00.lib"
LIB_SIGNOFF = LIB_DIR + "/toycells__ss_125C_4v00.lib"


def _liberty(nom_voltage: str, nom_temperature: str, v00: str, v01: str,
             v10: str, v11: str) -> str:
    """A one-cell library whose ONLY corner-dependent content is the header and
    the NLDM values, so a test can tell the two apart by what the driver reads.
    """
    return f"""
library (toycells) {{
    time_unit : "1ns";
    voltage_unit : "1V";
    capacitive_load_unit (1, pf);
    slew_lower_threshold_pct_rise : 30.0;
    slew_upper_threshold_pct_rise : 70.0;
    slew_lower_threshold_pct_fall : 30.0;
    slew_upper_threshold_pct_fall : 70.0;
    input_threshold_pct_rise : 50.0;
    input_threshold_pct_fall : 50.0;
    output_threshold_pct_rise : 50.0;
    output_threshold_pct_fall : 50.0;
    slew_derate_from_library : 0.5;
    nom_process : 1;
    nom_temperature : {nom_temperature};
    nom_voltage : {nom_voltage};
    cell (BUFX1) {{
        pin (A) {{ direction : input; capacitance : 0.004; }}
        pin (Y) {{
            direction : output;
            function : "(A)";
            timing () {{
                related_pin : "A";
                cell_rise (t2x2) {{
                    index_1("0.1, 0.4");
                    index_2("0.01, 0.04");
                    values("{v00}, {v01}", \\
                      "{v10}, {v11}");
                }}
                cell_fall (t2x2) {{
                    index_1("0.1, 0.4");
                    index_2("0.01, 0.04");
                    values("{v00}, {v01}", \\
                      "{v10}, {v11}");
                }}
            }}
        }}
    }}
}}
"""


# Nominal corner: fast cells, tight grid.  Sign-off corner: ~2.5x slower.
# Both grids are deliberately tight so the DERIVED tolerance stays small and
# the verdicts below turn on WHAT was compared, not on how much slack the
# tolerance happens to allow.
LIB_TEXT = {
    LIB_NOMINAL: _liberty("5.0", "25.0", "0.190", "0.200", "0.210", "0.220"),
    LIB_SIGNOFF: _liberty("4.0", "125.0", "0.480", "0.500", "0.520", "0.540"),
}

CELL_TEXT = """
.SUBCKT BUFX1 A Y VDD VSS
MN0 Y A VSS VSS nfet w=1u l=0.28u
MP0 Y A VDD VDD pfet w=2u l=0.28u
.ENDS
"""

NETLIST = """
module toptest (a, p);
  input a;
  output p;
  BUFX1 u1 (.A(a), .Y(n1), .VDD(VDD), .VSS(VSS));
  BUFX1 u2 (.A(n1), .Y(p), .VDD(VDD), .VSS(VSS));
endmodule
"""

# expected (Liberty+SPEF) cone delay = 0.50 + 0.50 = 1.00 ns, at the SIGN-OFF
# corner — which the report names in its own stamp.
STA_RPT_HEAD = """Startpoint: a (input port clocked by clk)
Endpoint: p (output port clocked by clk)
Path Group: clk
Path Type: max

  Delay    Time   Description
---------------------------------------------------------
   0.00    0.00   clock clk (rise edge)
   0.00    0.00 v a (in)
   0.50    0.50 v u1/Y (BUFX1)
   0.50    1.00 v u2/Y (BUFX1)
           1.00   data arrival time
"""
STA_RPT = STA_RPT_HEAD + f"""
STA_BASIS: POST_ROUTE_SPEF
STA_SIGNOFF_CORNER: SS
STA_BASIS_LIBERTY: {LIB_SIGNOFF}
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
"""

#: What the stand-in simulator answers, per model section.  The sign-off
#: section reproduces the reference; the nominal section is 2.5x faster —
#: the corner ratio, not a design error.
SECTION_DELAY_NS = {"ss": 1.00, "typical": 0.40}


def _make_project(tmp_path: Path, sta_text: str) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase3/stage3/pnr").mkdir(parents=True)
    (proj / "phase3/stage3/pnr/toptest_pnr.v").write_text(NETLIST)
    m._pl.extracted_dir(proj).mkdir(parents=True)
    (m._pl.extracted_dir(proj) / "toptest.spef").write_text(
        "*SPEF \"IEEE 1481-1998\"\n")
    m._pl.sta_dir(proj).mkdir(parents=True)
    (m._pl.sta_dir(proj) / "post_route_timing.rpt").write_text(sta_text)
    return proj


def _install_fake_container(monkeypatch, delay_scale: float = 1.0):
    """Substitute every container/simulator call with a deterministic stand-in.

    The simulator reads the deck the driver actually wrote and answers for the
    model section named in it — so the deck's corner, not the test, decides the
    number.  `delay_scale` injects a REAL delay error on top of that.
    """
    def fake_stdout(container, command, timeout=120):
        if command.startswith("cat "):
            path = command.split(None, 1)[1].strip().strip("'")
            if path in LIB_TEXT:
                return LIB_TEXT[path]
            if path == CELL_SPICE:
                return CELL_TEXT
            return None
        if "-path '*/spice/*'" in command:
            return CELL_SPICE + "\n"
        if "-exec grep" in command:
            return f"{MODEL_FILE}:.lib typical\n{MODEL_FILE}:.lib ss\n"
        if command.startswith("for f in"):
            return ""
        return None

    def fake_run(container, cwd_dir, deck_path, timeout=600):
        deck = Path(deck_path).read_text()
        section = re.search(r"^\.lib\s+'[^']+'\s+(\S+)", deck,
                            re.MULTILINE).group(1)
        vdd = float(re.search(r"^vdd vdd 0 (\S+)", deck,
                              re.MULTILINE).group(1))
        delay_ns = SECTION_DELAY_NS[section] * delay_scale
        return True, (
            f"tpd_fall = {delay_ns * 1e-9:.6e} targ= trig=\n"
            f"tpd_rise = {delay_ns * 1e-9:.6e} targ= trig=\n"
            f"vpout_max = {vdd:.6e}\n"
            "vpout_min = 0.000000e+00\n")

    monkeypatch.setattr(m, "_container_stdout", fake_stdout)
    monkeypatch.setattr(m, "_resolve_ngspice", lambda c: "/usr/bin/ngspice")
    monkeypatch.setattr(m, "_run_ngspice_in", fake_run)


def _run(tmp_path, monkeypatch, sta_text=STA_RPT, delay_scale=1.0):
    proj = _make_project(tmp_path, sta_text)
    _install_fake_container(monkeypatch, delay_scale)
    res = m.run_installed_pdk_path_correlation(
        proj, liberty_path=LIB_NOMINAL, container="toy")
    assert res["status"] == "RAN", res
    deck = (m._pl.spice_dir(proj) / "correlation.spice").read_text()
    return res["report"], deck


# ── the pure stamp reader ────────────────────────────────────────────────────

def test_basis_liberty_is_read_from_the_report_stamp():
    got, why = m.sta_report_basis_liberty(STA_RPT)
    assert got == LIB_SIGNOFF, why


def test_basis_liberty_is_none_when_the_report_never_stamped_one():
    got, why = m.sta_report_basis_liberty(STA_RPT_HEAD)
    assert got is None
    assert "no STA_BASIS_LIBERTY" in why


def test_basis_liberty_refuses_to_guess_on_a_multi_corner_report():
    """A multi-corner report stamps several; one parsed path cannot be
    attributed to one of them, so the answer is None — never the first one."""
    multi = STA_RPT + f"STA_BASIS_LIBERTY: {LIB_NOMINAL}\n"
    got, why = m.sta_report_basis_liberty(multi)
    assert got is None
    assert "2 distinct" in why


def test_late_derate_is_read_and_reported():
    assert m.sta_report_late_derate(STA_RPT) == 1.05
    assert m.sta_report_late_derate(STA_RPT_HEAD) is None


# ── direction 1: the comparison is made at ONE corner ────────────────────────

def test_deck_is_built_at_the_corner_the_sta_reference_was_timed_at(
        tmp_path, monkeypatch):
    """RED before the fix: the deck carried the NOMINAL corner (`typical`,
    .temp 25, 5 V) while the reference came from the sign-off corner."""
    report, deck = _run(tmp_path, monkeypatch)
    assert f".lib '{MODEL_FILE}' ss" in deck, deck
    assert ".temp 125" in deck, deck
    assert re.search(r"^vdd vdd 0 4\b", deck, re.MULTILINE), deck
    pvt = report["pvt"]
    assert pvt["corner_matched"] is True
    assert pvt["spice_liberty"] == LIB_SIGNOFF
    assert pvt["supplied_liberty"] == LIB_NOMINAL
    assert pvt["spice_model_section"] == "ss"
    assert pvt["spice_supply_v"] == 4.0
    assert pvt["spice_temperature_c"] == 125.0
    assert report["reference"]["sta_basis_liberty"] == LIB_SIGNOFF
    # DISCLOSED, not applied.
    assert pvt["sta_late_derate_not_applied_to_spice"] == 1.05


def test_a_corner_matched_agreeing_path_correlates(tmp_path, monkeypatch):
    """RED before the fix: the same design read -60 % and CRITICAL_MISMATCH,
    which was the corner ratio and not a design error."""
    report, _deck = _run(tmp_path, monkeypatch)
    c = report["correlation"]
    assert abs(c["pct_error"]) < 1.0, c
    assert c["verdict"] == "CORRELATED", c


# ── direction 2: THE POINT — it still refuses a real error ───────────────────

@pytest.mark.parametrize("scale,expected", [
    (1.40, "CRITICAL_MISMATCH"),
    (0.60, "CRITICAL_MISMATCH"),
])
def test_a_real_delay_error_at_the_matched_corner_still_fails(
        tmp_path, monkeypatch, scale, expected):
    """Corners matched, and the simulated path is genuinely 40 % off the
    Liberty+SPEF cone.  A correlation check that stops refusing this has been
    disabled, not fixed."""
    report, deck = _run(tmp_path, monkeypatch, delay_scale=scale)
    assert f".lib '{MODEL_FILE}' ss" in deck, deck
    c = report["correlation"]
    assert c["verdict"] == expected, c
    assert abs(c["pct_error"]) > 2.0 * c["tolerance_pct"], c


# ── degrade loudly, never silently ───────────────────────────────────────────

def test_an_unstamped_report_keeps_the_supplied_liberty_and_says_so(
        tmp_path, monkeypatch):
    """No stamp -> no guess.  The pre-existing behaviour is kept EXACTLY, and
    the record says the percentage carries an unquantified corner term."""
    report, deck = _run(tmp_path, monkeypatch, sta_text=STA_RPT_HEAD)
    assert f".lib '{MODEL_FILE}' typical" in deck, deck
    assert ".temp 25" in deck, deck
    pvt = report["pvt"]
    assert pvt["corner_matched"] is False
    assert pvt["spice_liberty"] == LIB_NOMINAL
    assert "no STA_BASIS_LIBERTY" in pvt["corner_basis"]
    assert report["reference"]["sta_basis_liberty"] is None
    # and the verdict it reaches is the corner-ratio one, still reported.
    assert report["correlation"]["verdict"] == "CRITICAL_MISMATCH"


def test_a_stamp_outside_the_cell_librarys_pdk_root_is_not_a_match(
        tmp_path, monkeypatch):
    """Pairing a header with an unrelated library is a degrade, not a match."""
    foreign = "/otherpdk/libs.ref/toycells/lib/toycells__ss_125C_4v00.lib"
    sta = STA_RPT_HEAD + f"STA_BASIS_LIBERTY: {foreign}\n"
    report, deck = _run(tmp_path, monkeypatch, sta_text=sta)
    assert f".lib '{MODEL_FILE}' typical" in deck, deck
    assert report["pvt"]["corner_matched"] is False
    assert "outside the PDK root" in report["pvt"]["corner_basis"]


def test_an_unreadable_stamped_liberty_degrades_loudly(tmp_path, monkeypatch):
    absent = LIB_DIR + "/toycells__ss_125C_9v99.lib"
    sta = STA_RPT_HEAD + f"STA_BASIS_LIBERTY: {absent}\n"
    report, deck = _run(tmp_path, monkeypatch, sta_text=sta)
    assert f".lib '{MODEL_FILE}' typical" in deck, deck
    assert report["pvt"]["corner_matched"] is False
    assert "could not be read" in report["pvt"]["corner_basis"]


def test_the_emitted_json_carries_the_pvt_block(tmp_path, monkeypatch):
    proj = _make_project(tmp_path, STA_RPT)
    _install_fake_container(monkeypatch)
    res = m.run_installed_pdk_path_correlation(
        proj, liberty_path=LIB_NOMINAL, container="toy")
    on_disk = json.loads(Path(res["report_path"]).read_text())
    assert on_disk["pvt"]["corner_matched"] is True
    assert on_disk["pvt"]["spice_liberty"] == LIB_SIGNOFF
