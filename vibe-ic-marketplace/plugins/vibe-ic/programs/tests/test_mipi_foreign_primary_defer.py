"""ORGANIC-20260531-incidental-csi2-mentions-in-pcie-ufs-ldocs — detector guard.

Backlog: the generic MIPI synth (mipi_protocol_synth.apply_mipi_synth) emits
illustrative MIPI-CSI-2 camera-pipeline example text ("ISP consumes CSI-2
packets", "CSI-2 RX IP cores", "decodes CSI-2 packets"). It was being applied
to the pcie_gen5 and ufs benchmarks because the runner's inline `_is_mipi`
detector fired on them: UFS is built on MIPI UniPro + M-PHY (the spec calls
M-PHY "based on D-PHY") and PCIe specs cite CSI-2 as an incidental pipeline /
vendor example, so the bare "MIPI"+"D-PHY" structural branch matched and the
CSI-2 example text leaked into pcie_gen5/ufs L-docs.

Fix (deterministic, program-side): the detector now lives in
``mipi_protocol_synth.is_mipi(blob)`` and applies a FOREIGN-PRIMARY DEFER —
the same content-only doctrine ``is_mipi_csi2`` and the AHB+APB ``_axi_primary``
guard already use. It defers (returns False) when the blob's dominant subject
is PCIe, UFS, or DisplayPort/eDP, so the generic MIPI synth can never fire on a
foreign spec that only mentions MIPI / D-PHY / CSI-2 incidentally.

This test pins:
  * PASS path  — a real MIPI D-PHY / CSI-2 blob still fires True.
  * FAIL path  — PCIe-, UFS-, and DisplayPort-primary blobs that carry the
                 SAME incidental MIPI / CSI-2 example text are suppressed.
  * Honesty    — empty / None / garbage input returns False (never vacuous).

No chip / vendor / SKU literal is used as detection logic; the blobs below are
generic, structural protocol descriptions.
"""
import importlib
from pathlib import Path

import pytest

# Import the detector under test.
mps = importlib.import_module("mipi_protocol_synth")
is_mipi = mps.is_mipi


# --------------------------------------------------------------------------- #
# Representative, self-contained blobs (no private corpus needed).
# --------------------------------------------------------------------------- #

# A genuine MIPI D-PHY / CSI-2 camera spec — MIPI is the running subject.
REAL_MIPI = """
MIPI D-PHY v1.2 / CSI-2 v1.3 physical and packet layer.
Clock Lane and Data Lane operate in HS (High-Speed) and LP (Low-Power) modes.
The CSI-2 packet layer carries a Long Packet (Data Identifier + Word Count +
ECC + payload + CRC-16) and a Short Packet (Frame Start / Frame End sync).
The image sensor source transmits RAW10 over the D-PHY Clock Lane and Data Lane.
"""

# PCIe-primary spec that CITES CSI-2 / MIPI as an incidental pipeline example
# (the exact contamination class the backlog describes). The PCIe subject must
# dominate (TLP / DLLP / LTSSM present), so the detector defers.
PCIE_PRIMARY_WITH_INCIDENTAL_CSI2 = """
PCI Express Base Specification. The Transaction Layer emits a TLP; the Data
Link Layer emits a DLLP; link bring-up walks the LTSSM. PCI Express PCI Express
""" + ("pci express " * 25) + """
Some commercial CSI-2 RX IP cores (e.g. third-party vendors) add MIPI CSI-2
BIST; an ISP / image processor sink consumes CSI-2 packets. (illustrative only)
MIPI D-PHY is mentioned here purely as an unrelated example.
"""

# UFS-primary spec built on MIPI UniPro + M-PHY ("based on D-PHY"), with the
# same incidental CSI-2 example text. UFS subject dominates, so it defers.
UFS_PRIMARY_WITH_INCIDENTAL_CSI2 = """
Universal Flash Storage (JESD220). The transport is MIPI UniPro; the physical
layer is MIPI M-PHY, which is based on D-PHY. """ + ("ufs " * 25) + """
A camera pipeline elsewhere may have an ISP that consumes CSI-2 packets and a
MIPI bridge / serializer that converts MIPI-CSI-2 to other formats (example).
"""

# DisplayPort-primary spec that incidentally name-drops MIPI DSI / D-PHY in a
# comparison. The VESA DP structural signature dominates, so it defers.
DP_PRIMARY_WITH_INCIDENTAL_MIPI = """
VESA DisplayPort source/sink. The Main Link carries video; the AUX channel
(I2C-over-AUX) reads DPCD. Link training runs clock recovery then channel
equalization across RBR / HBR / HBR2 / HBR3 rates (LINK_BW_SET).
For comparison, MIPI DSI uses the D-PHY physical layer in HS and LP modes;
that is mentioned only as an unrelated display interface.
"""


# --------------------------------------------------------------------------- #
# PASS path
# --------------------------------------------------------------------------- #

def test_real_mipi_blob_fires_true():
    assert is_mipi(REAL_MIPI) is True


# --------------------------------------------------------------------------- #
# FAIL path — foreign-primary blobs with the SAME incidental CSI-2/MIPI text
# must be suppressed (this is the bug the backlog reports).
# --------------------------------------------------------------------------- #

def test_pcie_primary_with_incidental_csi2_defers():
    assert is_mipi(PCIE_PRIMARY_WITH_INCIDENTAL_CSI2) is False


def test_ufs_primary_with_incidental_csi2_defers():
    assert is_mipi(UFS_PRIMARY_WITH_INCIDENTAL_CSI2) is False


def test_displayport_primary_with_incidental_mipi_defers():
    assert is_mipi(DP_PRIMARY_WITH_INCIDENTAL_MIPI) is False


def test_each_foreign_primary_anchor_alone_suppresses():
    """Each foreign-primary anchor, present with the incidental MIPI structural
    signature, independently forces a defer (not relying on one branch)."""
    sig = ("MIPI D-PHY Clock Lane Data Lane HS LP CSI-2 Long Packet "
           "Short Packet")
    # PCIe anchor: TLP + DLLP + LTSSM word-boundary triple.
    assert is_mipi(sig + " TLP DLLP LTSSM") is False
    # PCIe anchor: 32 GT/s + LTSSM.
    assert is_mipi(sig + " 32 GT/s LTSSM") is False
    # UFS anchor: UniPro + M-PHY.
    assert is_mipi(sig + " UniPro M-PHY") is False
    # UFS anchor: JESD220 + UFS.
    assert is_mipi(sig + " JESD220 UFS") is False
    # DisplayPort anchor: Main Link + AUX + DPCD + rate vocab.
    assert is_mipi(sig + " Main Link AUX channel DPCD HBR2") is False


# --------------------------------------------------------------------------- #
# Honesty — never vacuous PASS on missing / garbage data.
# --------------------------------------------------------------------------- #

def test_empty_blob_is_false():
    assert is_mipi("") is False


def test_none_blob_is_false():
    assert is_mipi(None) is False  # type: ignore[arg-type]


def test_garbage_blob_is_false():
    assert is_mipi("lorem ipsum dolor sit amet, no protocol here") is False


# --------------------------------------------------------------------------- #
# Corpus-clean (real benchmark_phase1/, when present): fires on EXACTLY the
# three real MIPI-family benchmarks and on NO foreign benchmark (in particular
# NOT pcie_gen5 / ufs / displayport / edp). Skipped if the private corpus is
# absent so the suite still runs in the shipped tree.
# --------------------------------------------------------------------------- #

from _plugin_tree import repo_path_or_missing  # noqa: E402
from _published_corpus import corpus_root, needs_corpus  # noqa: E402

# flow #486: benchmark_phase1/ is a repo-root-only private corpus absent on
# the flattened cache; resolve defensively so the existing skipif guards fire.
#
# 2026-08-16 — WHERE THE PARITY RESULTS WENT. `benchmark-data/evaluation/
# phase1_parity/<bench>/` still exists in this repository, but only its
# `input/` half: the RESULTS (`phase1/generated_docs/L1_DATASHEET.json`,
# `L2_FRS.json`, `reports/`) moved to https://github.com/vibeic/benchmark-data.
# Two of the three MIPI-family benchmarks this test names — `mipi` and
# `mipi_dsi` — are not in this checkout under any name at all, and the third,
# `mipi_csi2`, carries only `input/`. The old `not _BP.is_dir()` guard cannot
# see any of that: the directory is still here, so the guard stays silent, the
# corpus test reads 54 empty L1+L2 blobs, fires on nothing, and reports
# `set() != {mipi, mipi_csi2, mipi_dsi}` — a DETECTOR REGRESSION that did not
# happen.
#
# So the run root is taken from the published corpus when one is reachable, and
# the test is skipped naming the corpus when none is (vibe-ic#1357's rule for an
# absent tool, applied to an absent corpus). Point `VIBE_IC_BENCHMARK_DATA` at a
# clone of `vibeic/benchmark-data` and it runs against all 97 benchmarks, and
# can still fail.
def _phase1_parity_root():
    """The parity corpus: the published clone when reachable, else in-repo."""
    root = corpus_root()
    if root is not None:
        cand = root / "evaluation" / "phase1_parity"
        if cand.is_dir():
            return cand
    return repo_path_or_missing("benchmark-data", "evaluation", "phase1_parity")


_BP = _phase1_parity_root()


def _l1l2_blob(bench: str) -> str:
    s = ""
    gd = _BP / bench / "phase1" / "generated_docs"
    for n in ("L1_DATASHEET.json", "L2_FRS.json"):
        q = gd / n
        if q.is_file():
            s += q.read_text(encoding="utf-8", errors="ignore")
    return s


@needs_corpus
@pytest.mark.skipif(not _BP.is_dir(),
                    reason="private benchmark_phase1/ corpus not present")
def test_corpus_runner_blob_fires_only_on_mipi_family():
    benches = sorted(p.name for p in _BP.iterdir() if p.is_dir())
    fired = [b for b in benches if _l1l2_blob(b) and is_mipi(_l1l2_blob(b))]
    # EXACTLY the three real MIPI-family benchmarks (runner reads L1+L2 only).
    assert set(fired) == {"mipi", "mipi_csi2", "mipi_dsi"}, fired
    # The backlog's two contaminated benchmarks must be suppressed.
    for foreign in ("pcie_gen5", "ufs"):
        if _l1l2_blob(foreign):
            assert is_mipi(_l1l2_blob(foreign)) is False, foreign
