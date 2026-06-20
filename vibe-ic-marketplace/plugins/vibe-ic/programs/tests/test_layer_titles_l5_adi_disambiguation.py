"""L5 "ADI" must be disambiguated as Analog-Digital Interface, never read as the
vendor Analog Devices Inc.

The phase1 layer file name `L5_ADI_SPEC.json` uses the acronym "ADI", which
collides with the well-known vendor. This guards the authoritative
disambiguation: schema.LAYER_TITLES exists, covers every layer-file code, and
its L5 title states the analog-digital-interface expansion explicitly while
disclaiming the vendor — and the taxonomy carries no vendor-named layer.
"""
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
from phase1_engine.schema import (  # noqa: E402
    LAYER_FILE_NAMES, LAYER_TITLES, ALL_LAYER_CODES, ADVANCED_LAYER_CODES,
    GENERATABLE_LAYER_CODES, FactGraph)
from phase1_engine import render as _render  # noqa: E402
import tempfile  # noqa: E402


def test_layer_titles_cover_every_file_code():
    # every layer that has a file name has a human-readable title
    for code in LAYER_FILE_NAMES:
        assert code in LAYER_TITLES, f"{code} missing a LAYER_TITLES entry"
        assert LAYER_TITLES[code].strip(), f"{code} title is empty"


def test_l5_title_is_analog_digital_interface_not_vendor():
    t = LAYER_TITLES["L5"]
    assert "Analog-Digital Interface" in t
    # explicitly disclaims the vendor collision
    assert "Analog Devices" in t and "NOT" in t.upper()


def test_no_layer_title_is_a_vendor_name():
    # chip-AGNOSTIC: no functional layer is named after a vendor/SKU
    vendors = ("intel", "amd", "nvidia", "qualcomm", "broadcom", "tsmc",
               "samsung", "micron", "maxim", "texas instruments")
    for code, title in LAYER_TITLES.items():
        low = title.lower()
        for v in vendors:
            # the L5 disclaimer legitimately NAMES the vendor to disclaim it
            if code == "L5" and v in ("analog devices",):
                continue
            assert v not in low, f"{code} title names a vendor: {v!r}"


def test_advanced_layers_l14_l24_formalized():
    # the advanced/protocol layers are documented (not only scattered in the
    # protocol_synth producers)
    for code in [f"L{n}" for n in range(14, 25)]:
        assert code in LAYER_TITLES and LAYER_TITLES[code].strip()
    # L21 power intent is the UPF/IEEE-1801 dimension (research-verified mapping)
    assert "UPF" in LAYER_TITLES["L21"] or "1801" in LAYER_TITLES["L21"]


def test_coverage_completeness_layers_l25_l27_added():
    """Per the L1-L24 all-chip-classes survey: three spec dimensions were absent
    from L1-L24 and are added so the taxonomy can claim ALL chip classes."""
    rel = LAYER_TITLES["L25"].lower()
    assert "reliability" in rel and ("jesd47" in rel or "aec" in rel
                                     or "mission" in rel)
    mech = LAYER_TITLES["L26"].lower()
    assert "mems" in mech or "transduction" in mech or "mechanical" in mech
    mem = LAYER_TITLES["L27"].lower()
    assert "spd" in mem or "self-describing" in mem


def test_advanced_layers_are_optin_not_required():
    """The new layers are GENERATABLE but NOT in the REQUIRED ALL_LAYER_CODES, so a
    simple digital block is never forced to carry them and the all-L-docs-present
    gates (which key on ALL_LAYER_CODES) are unaffected."""
    for code in ["L14", "L21", "L25", "L26", "L27"]:
        assert code not in ALL_LAYER_CODES, f"{code} must NOT be required"
        assert code in ADVANCED_LAYER_CODES and code in GENERATABLE_LAYER_CODES
        assert code in LAYER_FILE_NAMES, f"{code} needs a generatable file name"


def test_new_layers_actually_render():
    """L25-L27 are first-class generatable: render_layers emits them from facts
    with the matching `L<N>.` path prefix when the caller opts in."""
    fg = FactGraph(ic_name="ddr5_dimm", class_path="memory/dram")
    fg.add_fact("L25.mission_profile.temp_max_c", 125, ["L25"], "user_stated")
    fg.add_fact("L27.spd.module_capacity_gb", 16, ["L27"], "user_stated")
    d = Path(tempfile.mkdtemp())
    _render.render_layers(fg, d, layers=GENERATABLE_LAYER_CODES)
    assert (d / LAYER_FILE_NAMES["L25"]).is_file()
    assert (d / LAYER_FILE_NAMES["L27"]).is_file()
