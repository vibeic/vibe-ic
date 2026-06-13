"""Tier-D advanced-interconnect detection predicates (v0.1.90).

Single source of truth for the NVLink / UCIe / 800-Gigabit-Ethernet detectors used
by ``phase1_doc_one_shot_runner.py``. These three protocols *extend* existing siblings
(NVLink/UCIe ride the PCIe/CXL family; 800G extends base Ethernet), and each Tier-D synth
runs AFTER its sibling and force-overrides the L-docs. A naive name-token detector would
over-fire on the sibling's benchmark doc and silently overwrite the sibling's output —
the exact masking risk recorded in the v0.1.89 KEY LESSON
(*force-overwrite can MASK a detector mis-fire*).

Each predicate therefore carries a **content-only sibling MUTEX**. All conditions read the
input_doc-augmented spec text (``blob``) — NO filename reads, NO benchmark names — so the
logic generalises to any document, not just the benchmark fixtures.

Extracting these out of the runner makes the mutex regression-testable: see
``tests/test_tier_d_interconnect_detect.py``.
"""
from __future__ import annotations


def is_ethernet_800g(blob: str) -> bool:
    """800 Gigabit Ethernet (IEEE 802.3df) — extends base 802.3.

    The base 'ethernet' class (MII/GMII, 10/100/1000) lacks 800G/PAM4/802.3df, so the
    version-specific tokens are a clean mutex against it.
    """
    if not blob:
        return False
    return (
        "800GBASE" in blob
        or "802.3df" in blob
        or ("800G" in blob and "PAM4" in blob)
        or "800 Gigabit Ethernet" in blob
    )


def is_nvlink(blob: str) -> bool:
    """NVIDIA NVLink — extends the generic SerDes link (PCIe family fires first).

    MUTEX: public GPU-interconnect substitute docs used for pcie_gen5/cxl are
    multi-protocol COMPARISON articles that heavily mention NVLink/NVHS/NVSwitch, so a
    bare-token NVLink detector over-fires on them and (running last) overwrites their
    L-docs. Defer when the doc is PCIe5-primary (Gen5 PHY electrical signature) or
    CXL-primary (CXL.io + CXL.mem) — neither of which an NVLink-PRIMARY doc carries.
    """
    if not blob:
        return False
    low = blob.lower()
    pcie5_phy = (
        "retimer" in low
        or "lane margining" in low
        or "equalization" in low
    )
    cxl_primary = ("CXL.io" in blob and "CXL.mem" in blob)
    return (
        (not pcie5_phy)
        and (not cxl_primary)
        and ("NVLink" in blob or "NVHS" in blob or "NVSwitch" in blob)
    )


def is_ucie(blob: str) -> bool:
    """UCIe — die-to-die chiplet interconnect (carries PCIe/CXL, so they fire first).

    MUTEX: require an NVLink-absent UCIe signature so an NVLink doc (which never mentions
    UCIe) cannot dual-fire; the "UCIe" token + chiplet die-to-die framing is unique to
    UCIe and absent in a pure PCIe/CXL/NVLink doc.
    """
    if not blob:
        return False
    low = blob.lower()
    return (
        ("NVLink" not in blob and "NVHS" not in blob)
        and (
            "UCIe" in blob
            or ("chiplet" in low and "die-to-die" in low)
            or ("UCIe" in blob and "D2D" in blob)
        )
    )
