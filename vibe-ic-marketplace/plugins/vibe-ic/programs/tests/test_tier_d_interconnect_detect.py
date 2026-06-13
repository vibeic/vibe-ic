"""Regression tests for the v0.1.90 Tier-D interconnect detectors.

These pin the sibling-MUTEX behaviour so a future edit cannot reintroduce the masking
risk from the v0.1.89 KEY LESSON: NVLink/UCIe ride the PCIe/CXL family and 800G extends
base Ethernet, each Tier-D synth runs last and force-overrides the L-docs, so a detector
that over-fires on a sibling doc would silently overwrite the sibling's output.

Two layers:
  * unit  — synthetic minimal strings exercising each token + each mutex branch;
  * fixture — the real benchmark input_doc specs (the original 9-case adversarial smoke),
              skipped gracefully if a benchmark dir is absent.
"""
import glob
import os
from pathlib import Path

import pytest

from tier_d_interconnect_detect import is_ethernet_800g, is_nvlink, is_ucie

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent.parent
BP = REPO_ROOT / "benchmark-data" / "evaluation" / "phase1_parity"


# --------------------------------------------------------------------------- unit
def test_empty_blob_never_fires():
    for det in (is_ethernet_800g, is_nvlink, is_ucie):
        assert det("") is False
        assert det(None) is False  # type: ignore[arg-type]


@pytest.mark.parametrize("blob", [
    "800GBASE-DR8 lane",
    "per IEEE 802.3df clause 120",
    "800G link using PAM4 modulation",
    "an 800 Gigabit Ethernet MAC",
])
def test_ethernet_800g_fires_on_signature(blob):
    assert is_ethernet_800g(blob) is True


@pytest.mark.parametrize("blob", [
    "10/100/1000 Ethernet MII/GMII PHY",          # base ethernet, no 800G tokens
    "Gigabit Ethernet 1000BASE-T",
    "",
])
def test_ethernet_800g_silent_on_base_ethernet(blob):
    assert is_ethernet_800g(blob) is False


def test_nvlink_fires_on_name_tokens():
    assert is_nvlink("NVLink 4.0 GPU interconnect") is True
    assert is_nvlink("NVHS differential signalling") is True
    assert is_nvlink("connected through an NVSwitch fabric") is True


def test_nvlink_defers_to_pcie5_phy():
    # PCIe-Gen5-primary doc that merely name-drops NVLink must NOT fire NVLink.
    for phy in ("retimer", "lane margining", "equalization"):
        blob = f"PCIe Gen5 PHY {phy}; compared against NVLink"
        assert is_nvlink(blob) is False


def test_nvlink_defers_to_cxl_primary():
    blob = "CXL.io and CXL.mem coherent protocol, mentions NVLink in passing"
    assert is_nvlink(blob) is False


def test_ucie_fires_on_signature():
    assert is_ucie("UCIe 1.1 chiplet link") is True
    assert is_ucie("a chiplet die-to-die adapter") is True


def test_ucie_silent_when_nvlink_present():
    # NVLink-absent is a hard precondition; an NVLink doc must not dual-fire UCIe.
    assert is_ucie("NVLink GPU mesh with UCIe-like framing") is False
    assert is_ucie("NVHS lanes") is False


def test_ucie_silent_on_plain_pcie():
    assert is_ucie("PCIe Gen5 root complex, 16 lanes") is False


# --------------------------------------------------------- fixture (real specs)
def _spec_blob(proto: str) -> str:
    cands = (
        glob.glob(str(BP / proto / "phase1" / "input_doc" / "*"))
        + glob.glob(str(BP / proto / "input_doc" / "*"))
        + glob.glob(str(BP / proto / "input" / "docs" / "*"))
    )
    txt = ""
    for c in cands:
        if os.path.isfile(c) and c.endswith((".txt", ".md")):
            try:
                txt += Path(c).read_text(errors="ignore") + "\n"
            except OSError:
                pass
    return txt


# (label, benchmark proto dir, detector, expected) — the 9-case adversarial smoke.
_SMOKE = [
    ("e800 fires on 800G",        "ethernet_800g", is_ethernet_800g, True),
    ("e800 silent on ethernet",   "ethernet",      is_ethernet_800g, False),
    ("e800 silent on pcie_gen5",  "pcie_gen5",     is_ethernet_800g, False),
    ("nvlink fires on nvlink",    "nvlink",        is_nvlink,        True),
    ("nvlink silent on pcie_gen5","pcie_gen5",     is_nvlink,        False),
    ("nvlink silent on cxl",      "cxl",           is_nvlink,        False),
    ("ucie fires on ucie",        "ucie",          is_ucie,          True),
    ("ucie silent on nvlink",     "nvlink",        is_ucie,          False),
    ("ucie silent on pcie_gen5",  "pcie_gen5",     is_ucie,          False),
]


@pytest.mark.parametrize("label,proto,det,expected", _SMOKE, ids=[c[0] for c in _SMOKE])
def test_no_mis_fire_on_real_specs(label, proto, det, expected):
    blob = _spec_blob(proto)
    if not blob:
        pytest.skip(f"benchmark spec for {proto} not present")
    assert det(blob) is expected, f"{label}: detector returned {det(blob)}, expected {expected}"
