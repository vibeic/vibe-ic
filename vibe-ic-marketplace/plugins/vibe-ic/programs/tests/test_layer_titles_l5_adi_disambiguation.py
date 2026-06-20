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
from phase1_engine.schema import LAYER_FILE_NAMES, LAYER_TITLES  # noqa: E402


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
