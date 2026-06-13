# Tier-D (v0.1.90) Advanced-Interconnect Detection Verification

**Protocols added**: NVIDIA NVLink, UCIe (die-to-die chiplet), 800 Gigabit Ethernet (IEEE 802.3df).
**Plugin version**: 0.1.89 → **0.1.90**.

These three protocols extend existing siblings (NVLink/UCIe ride on the PCIe/CXL family; 800G
extends base Ethernet), so a naive name-token detector over-fires on the sibling benchmark docs and
— running last in the Tier-D block — would force-overwrite the sibling's L-docs. Per the v0.1.89
KEY LESSON (*force-overwrite-to-0 can MASK a detector mis-fire*), each new detector carries a
**content-only sibling MUTEX**. The predicates live in `programs/tier_d_interconnect_detect.py`
(single source of truth, imported by `programs/phase1_doc_one_shot_runner.py`) and are pinned by
`tests/test_tier_d_interconnect_detect.py` (20 cases: unit + the 9-case real-spec smoke).

## Detector conditions (content-only, no filename reads)

- **ethernet_800g**: `800GBASE` OR `802.3df` OR (`800G` AND `PAM4`) OR `800 Gigabit Ethernet`
- **nvlink**: (NOT pcie5-PHY) AND (NOT cxl-primary) AND (`NVLink` OR `NVHS` OR `NVSwitch`)
  - pcie5-PHY mutex = `retimer` / `lane margining` / `equalization`
  - cxl-primary mutex = `CXL.io` AND `CXL.mem`
- **ucie**: (`NVLink` absent AND `NVHS` absent) AND (`UCIe` OR (`chiplet` AND `die-to-die`) OR (`UCIe` AND `D2D`))

## Adversarial no-mis-fire smoke (9/9 PASS)

Each detector evaluated against the real `input_doc/` spec of its own benchmark **and** each
mutex-sibling benchmark:

| # | check | proto doc | result |
|---|---|---|---|
| 1 | ethernet_800g **fires** | ethernet_800g | PASS (True) |
| 2 | ethernet_800g **silent** on base Ethernet (MII/GMII 10/100/1000) | ethernet | PASS (False) |
| 3 | nvlink **fires** | nvlink | PASS (True) |
| 4 | nvlink **silent** on PCIe-Gen5 (retimer/equalization) | pcie_gen5 | PASS (False) |
| 5 | nvlink **silent** on CXL (CXL.io+CXL.mem) | cxl | PASS (False) |
| 6 | ucie **fires** | ucie | PASS (True) |
| 7 | ucie **silent** on NVLink doc | nvlink | PASS (False) |
| 8 | ucie **silent** on PCIe-Gen5 | pcie_gen5 | PASS (False) |
| 9 | ethernet_800g **silent** on PCIe-Gen5 | pcie_gen5 | PASS (False) |

**SMOKE_RESULT = ALL_PASS.** No detector over-fires on a sibling; the force-override is therefore
applied only to the intended protocol's L-docs — the masking risk does not materialise.

## Status

- ✅ 3 synth programs (`{ethernet_800g,nvlink,ucie}_protocol_synth.py`) + L1–L23 generated docs.
- ✅ Detection extracted to importable predicates `programs/tier_d_interconnect_detect.py`;
  `phase1_doc_one_shot_runner.py` now imports them (fail-open, content-only + sibling mutexes).
- ✅ Permanent regression: `tests/test_tier_d_interconnect_detect.py` — **23 passed** (unit branches
  + the 9-case real-spec no-mis-fire smoke; no skips → all benchmark fixtures matched).
- ✅ Full plugin pytest suite GREEN: **2664 passed** (was 2641 + 23 new).
- ✅ `programs/INDEX.md` regenerated.
