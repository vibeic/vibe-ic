# Chip-to-chip interconnect benchmark candidates (vibe-IC)

Design basis for extending vibe-IC from **phase1 spec→L-docs** (UCIe/CXL/NVLink/
TileLink/PCIe classes already exist) to a **spec→RTL→PPA** interconnect benchmark
that stands in for the **closed NVLink-C2C** (no public spec, no open RTL).

Sourced 2026-06-03 by an 8-agent web-verified research sweep (each cell WebSearch+
WebFetch-confirmed against the primary repo/spec; confidence + sources recorded).
**Caveat:** assistant knowledge cutoff is Jan 2026; all "current" facts below were
re-verified on the web, not asserted from memory.

## Why NVLink-C2C decomposes into two open layers

NVLink-C2C itself is **closed** (members-only spec, proprietary, no open RTL) — it
cannot be a direct benchmark. Architecturally it = **(A) a D2D physical/link layer**
+ **(B) a cache-coherent protocol layer**. Each layer has an open, public-spec analog
with RTL, so vibe-IC can benchmark the layers, not the closed whole. (NVLink Fusion
itself bridges custom ASICs in via a **UCIe** chiplet — so UCIe is the open analog of
the NVLink-C2C die-to-die fabric.)

## Comparison table

| Target | Layer | Spec public | Open RTL | Golden-usable | PPA / measurement data | License | Gen-difficulty (1–5) | Recommend |
|---|---|---|---|---|---|---|---|---|
| **UCIe** | PHY / D2D | free (eval click-through) | ✅ `ucb-bar/uciedigital` (UCIe-lite, full digital stack, Chisel) | ✅ digital controller | spec-target KPIs (32→64 GT/s, ~0.5 pJ/b, 1.35 TB/s/mm²); vendor silicon PPA (ISSCC'26) but **repo ships no PPA** → must be generated | BSD-3 (RTL); eval-only spec | 5 | **GOLDEN-FOR-PPA (PHY)** |
| **TileLink** | coherent protocol | free | ✅ `chipsalliance/rocket-chip` (tilelink pkg, Chisel) | ⚠️ partial (full coherence in rocket-chip) | Constellation NoC paper PPA/NoC results | Apache-2.0 + UCB BSD | 4 | **GOLDEN-FOR-PPA (protocol)** |
| **AIB / AIB 2.0** | PHY / D2D | free (OWFa) | ✅ `chipsalliance/aib-phy-hardware` | ⚠️ partial (mixed-signal PHY) | ✅ **peer-reviewed silicon** (CICC'21: 256 Gb/s/mm shoreline, 0.83 pJ/b, 16nm) | Apache-2.0 (RTL); OWFa spec | 5 | ANCHOR (silicon-PPA reference) |
| **OpenPCIe / LitePCIe** | board-level ref | members-only (PCI-SIG) | ✅ `enjoy-digital/litepcie` + `isomoye-msu/pcie_datalink_layer` | ⚠️ partial | ✅ published **FPGA-measured** results (FPGA'26 / MDPI) | BSD-2 (LitePCIe) | 5 | BOARD-REF (control group) |
| **BoW (Bunch of Wires)** | PHY / D2D | free (OWFa) | ❌ spec-only (`opencomputeproject/ODSA-BoW`) | ❌ | electrical figures only (<0.25–1 pJ/b); no digital golden | OWFa spec | 4 | ANCHOR-ONLY |
| **CXL (.cache/.mem)** | coherent protocol | eval (free dl, no impl rights) | ❌ no open synth HDL controller | ❌ | ~200 ns mem latency; per-lane figures; no golden-tied PPA | CXL eval agreement | 5 | ANCHOR-ONLY (closest NVLink-C2C semantics, but no open RTL) |
| **AMBA CHI** | coherent protocol | free (AMBA5 royalty-free) | ⚠️ partial (`awenzh/openMN`, SpinalHDL CHI-E.b mesh) | ❌ | none in open source; gem5 has architectural model only | ARM free-use spec | 5 | ANCHOR-ONLY (protocol reference) |
| **NVLink-C2C** | closed anchor | members-only | ❌ | ❌ | real silicon PPA exists but **paywalled** (ISSCC'23 9.3) | proprietary | 5 | ANCHOR-ONLY (the target being stood-in for) |

## Recommendation

**Two viable spec→RTL→PPA targets** (open RTL + usable golden + measurement data):
- **PHY layer → UCIe** (`ucb-bar/uciedigital`, BSD-3). Best as **golden-RTL
  equivalence + GENERATED PPA** (synth/PnR the digital stack on an open PDK), NOT a
  from-scratch full-stack generation (gen-difficulty 5: Chisel-not-Verilog, multi-
  layer, analog AFE WIP, eval-only spec). Needs a FIRRTL→Verilog elaboration step.
- **Coherent layer → TileLink** (`rocket-chip`, Apache-2.0). Easiest to drive a
  Verilog compare; the most tractable coherent golden.

**Supporting:**
- **AIB** — keep as the PHY **silicon-PPA reference** (real measured numbers) even
  though its golden is mixed-signal/partial.
- **OpenPCIe/LitePCIe** — board-level **control group** with published FPGA-measured
  bandwidth/latency.
- **BoW / CXL / AMBA-CHI / NVLink-C2C** — **anchors only** (no usable open golden);
  document them so the corpus shows *why* the open layers stand in for the closed whole.

**Honesty caveats:**
- The **headline UCIe KPIs** (pJ/bit, bandwidth density, channel reach) are
  analog/packaging-bound — the open golden cannot supply them; only **digital-stack
  area/timing** on an open PDK is achievable. Report those, not the analog KPIs.
- **CXL** is the closest semantic match to NVLink-C2C but has **no open synthesizable
  controller** → it can only be an anchor, not a golden.
- All targets are gen-difficulty 4–5 → the realistic vibe-IC value is **golden-RTL
  equivalence (LEC) + generated PPA**, not from-scratch spec→RTL of a full stack.

## vibe-IC existing coverage

Already has **phase1 spec→L-docs** synthesis classes: UCIe, CXL, NVLink, TileLink,
PCIe (+ AXI, AHB/APB). **CHI is missing.** The new benchmark extends these to RTL+PPA;
it does not duplicate phase1 detection.

## Scoring-stage note (open-benchmark-methodology)

When these move from *design* to *scoring*, apply the run-shape matrix: these are
substantial designs with PnR/PPA targets → **Shape A (full runner)** for the golden
synth/PnR PPA generation, **Shape B** for digital-block equivalence. Disclose the
tool substitution (yosys+OpenROAD for PPA, not commercial DC/PrimeTime; FIRRTL→Verilog
for the Chisel goldens).
