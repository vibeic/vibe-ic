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
import sys
from pathlib import Path

import pytest

from tier_d_interconnect_detect import is_ethernet_800g, is_nvlink, is_ucie

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _published_corpus import corpus_root, skip_reason  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent.parent

#: THE FIXTURE ROOT WAS UNREACHABLE ON EVERY HOST, AND THE PREFIX ALSO MOVED.
#:
#: `BP` was `REPO_ROOT / "benchmark-data" / "evaluation" / "phase1_parity"`, a
#: single repo-relative path. `benchmark-data/` left this repository at
#: `c5d7f2d00` — `git ls-tree -r HEAD -- benchmark-data` matches nothing — so
#: the nine `test_no_mis_fire_on_real_specs` cases skipped on every machine, for
#: a reason no provisioning could satisfy, while reading as a healthy skip.
#:
#: Routing to `corpus_root()` alone would NOT have recovered them. The published
#: repository does not carry `evaluation/phase1_parity/` at all: those specs are
#: one of the "55 files under a RENAMED prefix" `_published_corpus` records, and
#: they are published at top-level `protocol_parity/`. MEASURED against a clone
#: of `vibeic/benchmark-data` @ 88621a5: `evaluation/phase1_parity` absent;
#: `protocol_parity/{ethernet_800g,pcie_gen5,nvlink,cxl}/phase1/input_doc/*`
#: present, `protocol_parity/{ethernet,ucie}` present with NO input_doc — so 7
#: of the 9 cases become live and 2 stay skipped over a genuinely unpublished
#: input, which is a different fact and says so.
#:
#: BOTH SPELLINGS ARE SEARCHED, in this order, and the in-repo one is kept: a
#: checkout that still carries the historical tree is read exactly as before.
_BASES = ("protocol_parity", "evaluation/phase1_parity")


def _spec_roots():
    """Every root that could hold the parity specs — pointer first, repo last."""
    roots = []
    corpus = corpus_root()
    if corpus is not None:
        roots += [corpus / b for b in _BASES]
    roots += [REPO_ROOT / "benchmark-data" / b for b in _BASES]
    return [r for r in roots if r.is_dir()]


#: Kept as a name a reader may still grep for. It is now "the first root that
#: resolves", not "the only path there is".
BP = next(iter(_spec_roots()), REPO_ROOT / "benchmark-data" / _BASES[-1])


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
    cands = []
    for base in _spec_roots():
        cands += (
            glob.glob(str(base / proto / "phase1" / "input_doc" / "*"))
            + glob.glob(str(base / proto / "input_doc" / "*"))
            + glob.glob(str(base / proto / "input" / "docs" / "*"))
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
        # TWO STATES, TWO SENTENCES. A corpus that RESOLVED and does not
        # publish this spec is a measurement; a corpus nobody named is "I could
        # not look". `_published_corpus` was repaired for exactly this
        # conflation and it must not be reintroduced one layer out.
        roots = _spec_roots()
        pytest.skip(
            f"no input_doc for {proto} under {[str(r) for r in roots]} — the "
            f"corpus WAS read and does not publish this spec"
            if roots else
            f"benchmark spec for {proto} not present: {skip_reason()}")
    assert det(blob) is expected, f"{label}: detector returned {det(blob)}, expected {expected}"
