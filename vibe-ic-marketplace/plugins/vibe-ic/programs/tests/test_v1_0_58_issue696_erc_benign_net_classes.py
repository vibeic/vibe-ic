"""ORGANIC #696 [HIGH] — ERC floating-net screen had no allow-list for the
three universally-benign BARE-NET classes, so a DRC-clean + LVS-unique +
GDSII-PASS layout false-FAILed Step-31 ERC (ERC_DIRTY) purely on the raw
floating-net COUNT.

Surfaced on caravel (7th IC) round-9: the OpenROAD ERC screen
(report_floating_nets) reports 3 "floating nets" = VGND + VPWR (power/ground
SPECIALNETS) + zero_ (the yosys hilomap constant-tie net, CLAUDE.md rule #4),
plus 15 spare_* design-for-ECO pool pins (already handled by #514). The
erc_float_owner_classify benign set covered spare-cell I/O + optional ports
but NOT power/ground rails or the hilomap tie net, so those 3 were counted
as FUNCTIONAL and erc_density_check hard-FAILed ERC_DIRTY. It was masked in
round-8 behind the #693 provenance failure (Step-31 hit that first).

chip/PDK-AGNOSTIC: the benign classes are matched STRUCTURALLY by net-class
shape (canonical power/ground rail spellings + hilomap tie net), never by a
chip / SKU literal. WHOLE-NAME anchoring so a real signal that merely
contains 'vdd'/'zero' as a substring is NOT swallowed.

§4.05 NO-LEAK:
  * a genuine floating SIGNAL net (not spare-owned, not a power/ground rail,
    not a tie net) is STILL functional → ERC_DIRTY FAIL;
  * substring traps (vdd_ok, data_zero_flag, pll_vss_sel) are functional;
  * an "ERC clean: NO" report with NO verbose float list (unclassifiable)
    still FAILs — we do not waive on faith.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import erc_float_owner_classify as EFC  # noqa: E402
import erc_density_check as EDC          # noqa: E402

_CLS_SRC = (PLUGIN / "programs" / "erc_float_owner_classify.py").read_text()
_EDC_SRC = (PLUGIN / "programs" / "erc_density_check.py").read_text()


# --------------------------------------------------------------------------
# erc_float_owner_classify — benign net-class predicate
# --------------------------------------------------------------------------
def test_power_ground_rails_are_benign():
    for n in ("VPWR", "VGND", "vdd", "vss", "vccd", "vssd", "vccd1", "vssd1",
              "vdda", "vssa", "vddio", "vssio", "gnd", "VPB", "VNB"):
        assert EFC._is_benign_net_class(n), f"{n} should be benign"


def test_hilomap_tie_net_is_benign():
    for n in ("zero_", "one_", "zero_0", "tie_lo", "tiehi", "tielo",
              "logic0", "logic1"):
        assert EFC._is_benign_net_class(n), f"{n} should be benign"


def test_substring_traps_are_functional():
    """§4.05: a real signal that merely CONTAINS a rail/tie token is NOT
    benign (whole-name anchoring)."""
    for n in ("vdd_ok", "data_zero_flag", "pll_vss_sel", "vddtest_status",
              "my_one_hot", "gnd_detect_n", "spare_data"):  # 'spare_data' bare
        # 'spare_data' is a bare net (no /) NOT owned by a spare INSTANCE here
        # — only the structural rail/tie predicate is tested, owner-spare is
        # a separate path. The rail/tie predicate must reject it.
        if n == "spare_data":
            assert EFC._is_benign_net_class(n) is False
        else:
            assert EFC._is_benign_net_class(n) is False, f"{n} not a rail/tie"


def test_pin_floats_never_match_bare_net_class():
    """A pin float (inst/pin) is handled by the spare-owner path, never by
    the bare-net rail/tie predicate."""
    assert EFC._is_benign_net_class("VPWR/A") is False
    assert EFC._is_benign_net_class("spare_dff_0/CLK") is False


def test_classify_real_r9_float_set_all_benign():
    """The exact round-9 caravel float set: 3 bare power/tie + 15 spare pins
    → 0 functional."""
    floats = [
        "VGND", "VPWR", "zero_",
        "spare_aoi_0/A1", "spare_aoi_0/A2", "spare_aoi_0/B1",
        "spare_dff_0/CLK", "spare_dff_0/D", "spare_dff_0/RESET_B",
        "spare_inverter_0/A", "spare_inverter_1/A",
        "spare_mux2_0/A0", "spare_mux2_0/A1", "spare_mux2_0/S",
        "spare_nand2_0/A", "spare_nand2_0/B",
        "spare_nor2_0/A", "spare_nor2_0/B",
    ]
    rep = EFC.classify(floats)
    assert rep["total_floats"] == 18
    assert rep["functional_count"] == 0
    assert rep["benign_count"] == 18
    assert rep["classification"] == "benign-ERC"
    assert rep["waiver_eligible"] is True


def test_classify_real_signal_float_still_functional():
    """§4.05: a genuine floating signal net among benign ones is functional."""
    rep = EFC.classify(["VPWR", "VGND", "zero_", "alu_carry_unconnected"])
    assert rep["functional_count"] == 1
    assert rep["functional_floats"] == ["alu_carry_unconnected"]
    assert rep["waiver_eligible"] is False


# --------------------------------------------------------------------------
# erc_density_check — Step-31 gate consumes the classification
# --------------------------------------------------------------------------
def _erc_rpt(tmp_path, body):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "erc.rpt").write_text(body)
    return tmp_path


_R9_BODY = (
    "ERC floating nets: 3\n"
    "ERC clean: NO (review floating nets)\n"
    "=== ERC: floating nets ===\n"
    "[WARNING RSZ-0020] found 3 floating nets.\n"
    " VGND\n VPWR\n zero_\n"
    "[WARNING RSZ-0095] found 15 floating pins.\n"
    " spare_aoi_0/A1\n spare_dff_0/CLK\n spare_mux2_0/S\n"
    " spare_nand2_0/A\n spare_nor2_0/B\n spare_inverter_0/A\n"
)


def _run_erc(tmp_path):
    findings = []
    stats = {}
    EDC._check_erc(tmp_path, findings, stats)
    return findings, stats


def test_gate_passes_on_all_benign_floats(tmp_path):
    """POSITIVE: 3 benign bare nets + spare pins → ERC_BENIGN_FLOATS INFO,
    no ERC_DIRTY error → erc_clean True."""
    _erc_rpt(tmp_path, _R9_BODY)
    findings, stats = _run_erc(tmp_path)
    cats = {f.category for f in findings}
    assert "ERC_BENIGN_FLOATS" in cats
    assert "ERC_DIRTY" not in cats
    assert stats.get("erc_clean") is True
    assert not any(f.severity == "ERROR" for f in findings)


def test_gate_fails_on_functional_float(tmp_path):
    """§4.05: a genuine floating signal net → ERC_DIRTY ERROR."""
    body = (
        "ERC floating nets: 2\n"
        "ERC clean: NO\n"
        "[WARNING RSZ-0020] found 2 floating nets.\n"
        " VGND\n data_valid_unconnected\n"
    )
    _erc_rpt(tmp_path, body)
    findings, stats = _run_erc(tmp_path)
    cats = {f.category for f in findings}
    assert "ERC_DIRTY" in cats
    assert "ERC_BENIGN_FLOATS" not in cats
    assert any(f.severity == "ERROR" for f in findings)


def test_gate_fails_on_unclassifiable_clean_no(tmp_path):
    """§4.05: clean=NO with no verbose float list (cannot prove benign) →
    still FAIL, no waive-on-faith."""
    _erc_rpt(tmp_path, "ERC floating nets: 4\nERC clean: NO\n")
    findings, stats = _run_erc(tmp_path)
    cats = {f.category for f in findings}
    assert "ERC_DIRTY" in cats
    assert "ERC_BENIGN_FLOATS" not in cats


def test_gate_clean_report_unchanged(tmp_path):
    """A genuinely clean report (0 floats) is unchanged → ERC_CLEAN."""
    _erc_rpt(tmp_path, "ERC floating nets: 0\nERC clean: YES\n")
    findings, stats = _run_erc(tmp_path)
    cats = {f.category for f in findings}
    assert "ERC_CLEAN" in cats
    assert stats.get("erc_clean") is True


def test_source_pins_696():
    assert "#696" in _CLS_SRC
    assert "_is_benign_net_class" in _CLS_SRC
    assert "#696" in _EDC_SRC
    assert "ERC_BENIGN_FLOATS" in _EDC_SRC
