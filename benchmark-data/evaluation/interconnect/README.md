# vibe-IC interconnect benchmark (chip-to-chip)

Open chip-to-chip interconnect benchmark targets standing in for the **closed
NVLink-C2C** (no public spec, no open RTL). Extends vibe-IC from phase1
spec→L-docs (UCIe/CXL/NVLink/TileLink/PCIe classes already exist) to
**spec→RTL→PPA**. Design basis: `community/INTERCONNECT_BENCHMARK_CANDIDATES.md`.

NVLink-C2C decomposes into **(A) a D2D PHY/link layer** and **(B) a cache-coherent
protocol layer**; each has an open public-spec analog with RTL. We benchmark the
layers, not the closed whole. (NVLink Fusion itself bridges custom ASICs via a UCIe
chiplet — UCIe is the open analog of the NVLink-C2C die-to-die fabric.)

## Targets (web-verified 2026-06-03; commit-pinned)

| Dir | Target | Layer | Open RTL (pinned) | License | Role |
|---|---|---|---|---|---|
| `phy/ucie` | UCIe | PHY/D2D | `ucb-bar/uciedigital` | BSD-3 | **golden-for-PPA (PHY)** |
| `protocol/tilelink` | TileLink | coherent | `chipsalliance/rocket-chip` | Apache-2.0 | **golden-for-PPA (protocol)** |
| `phy/aib` | AIB / AIB 2.0 | PHY/D2D | `chipsalliance/aib-phy-hardware` | Apache-2.0 | PHY silicon-PPA reference |
| `board/litepcie` | OpenPCIe / LitePCIe | board-ref | `enjoy-digital/litepcie` | BSD-2 | board control group |
| `ANCHORS.md` | BoW · CXL · AMBA-CHI · NVLink-C2C | — | none usable | — | anchors only |

## How to acquire (not vendored — fetched on demand)

The upstream repos are **not** vendored into this tree (rocket-chip alone is large;
keeping the corpus lean is required for the v1.0 release). Each target's
`*.manifest.yaml` carries the repo URL + **pinned commit** + license + the golden
RTL paths + measurement-data references. Fetch the pinned sources into the
gitignored `_work/`:

```bash
bash benchmark_external/interconnect/setup_fetch.sh           # all
bash benchmark_external/interconnect/setup_fetch.sh ucie      # one
```

## Realistic methodology (per the candidate analysis)

All targets are generation-difficulty 4–5 (large, often mixed-signal, several are
Chisel-not-Verilog). The tractable vibe-IC value is **golden-RTL equivalence (LEC)
+ GENERATED PPA** (push the open digital RTL through yosys+OpenROAD on an open PDK to
produce area/timing), NOT from-scratch spec→RTL of a full stack.

Honesty caveats: UCIe headline KPIs (pJ/bit, bandwidth density) are analog/packaging-
bound — the open golden cannot supply them; report digital-stack area/timing only.
CXL is the closest NVLink-C2C semantic match but has **no open synthesizable
controller** → anchor only. Chisel goldens (UCIe, TileLink) need a FIRRTL→Verilog
elaboration step before equivalence/PPA. Scoring stage uses open-benchmark-methodology
Shape A (PnR/PPA) / Shape B (block equivalence) with tool-substitution disclosed
(yosys+OpenROAD, not commercial DC/PrimeTime).
