"""v0.3.16 — #514: ERC sub-gate FAILed on a raw floating net/pin count
even when 100% of the floats were design-for-ECO spare-cell I/O (spare
inverter/nand/mux/dff inputs+outputs, deliberately unconnected for a late
metal ECO) + optional-unused top input ports — benign by construction.
New by-owner classifier: a float is benign when its owner instance is a
spare ('spare' in the name) or it is a declared optional-unused top port;
functional==0 → 'benign-ERC' (waiver-eligible).

Validated on real subservient Step-31 ERC: 40 floating pins, 100%
spare_*/<pin> → functional == 0 → benign-ERC. chip/PDK-AGNOSTIC.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import erc_float_owner_classify as E  # noqa: E402

_VERBOSE = """[WARNING RSZ-0095] found 5 floating pins.
 spare_aoi_0/A1
 spare_dff_0/CLK
 spare_inverter_0/A
 spare_mux2_0/S
 spare_nand2_0/B
"""

_VERBOSE_WITH_FUNCTIONAL = """[WARNING RSZ-0095] found 3 floating pins.
 spare_aoi_0/A1
 _0123_/Y
 u_dut.core/data_reg/D
"""


def test_parse_floats_from_verbose():
    f = E.parse_floats(_VERBOSE)
    assert "spare_aoi_0/A1" in f and "spare_nand2_0/B" in f
    assert len(f) == 5


def test_all_spare_floats_are_benign():
    s = E.classify(E.parse_floats(_VERBOSE))
    assert s["total_floats"] == 5
    assert s["functional_count"] == 0
    assert s["classification"] == "benign-ERC"
    assert s["waiver_eligible"] is True


def test_functional_float_is_not_waiver_eligible():
    s = E.classify(E.parse_floats(_VERBOSE_WITH_FUNCTIONAL))
    assert s["functional_count"] == 2     # _0123_/Y + u_dut.core/...
    assert s["classification"] == "has-functional-floats"
    assert s["waiver_eligible"] is False
    assert any("_0123_" in f for f in s["functional_floats"])


def test_optional_port_is_benign():
    v = "[WARNING RSZ-0020] found 1 floating nets.\n i_gpio[0]\n"
    s = E.classify(E.parse_floats(v), optional_ports={"i_gpio[0]"})
    assert s["functional_count"] == 0 and s["classification"] == "benign-ERC"


def test_optional_port_without_allowlist_is_functional():
    v = "[WARNING RSZ-0020] found 1 floating nets.\n some_real_net\n"
    s = E.classify(E.parse_floats(v))
    assert s["functional_count"] == 1 and s["waiver_eligible"] is False


def test_clean_no_floats():
    s = E.classify([])
    assert s["classification"] == "clean" and s["waiver_eligible"] is True
