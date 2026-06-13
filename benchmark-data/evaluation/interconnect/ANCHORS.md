# Anchor-only interconnect targets (no usable open golden)

These document *why* the open layers (UCIe PHY + TileLink coherent) stand in for the
closed NVLink-C2C. They are **anchors only** — no acquirable open golden RTL with
which to run a spec→RTL→PPA compare. Web-verified 2026-06-03.

## BoW — Bunch of Wires (PHY/D2D)
- Spec: free, OWFa 1.0 — `opencomputeproject/ODSA-BoW` (**spec-only repo, no RTL**).
- Data: electrical figures only (<0.25–1 pJ/bit; BoW-32 @2 Gbps/wire). No digital golden / no flow PPA.
- Role: PHY anchor. gen-difficulty 4. Not acquirable as a golden.

## CXL — Compute Express Link (.cache / .mem) (coherent-protocol)
- Spec: free download under CXL eval agreement (no implementation rights).
- **No open synthesizable HDL CXL controller exists** (closest open project is not a golden).
- Data: ~200 ns added memory latency; per-lane ~3.938 GB/s — no golden-tied PPA.
- Role: **closest semantic match to NVLink-C2C** (cache-coherent + memory pooling) but
  anchor-only because there is no open golden. gen-difficulty 5.

## AMBA CHI — Coherent Hub Interface (coherent-protocol)
- Spec: ARM proprietary but free/royalty-free to use (AMBA 5).
- Open RTL: partial — `awenzh/openMN` (SpinalHDL→Verilog, CHI Issue E.b mesh); no published PPA.
- gem5 has a CHI Ruby architectural model (not synthesizable RTL).
- Role: protocol reference anchor. gen-difficulty 5. vibe-IC lacks a phase1 `chi` class (gap noted).

## NVLink-C2C — the closed target being stood-in for
- Spec: members-only / proprietary; **no open RTL**. NVLink Fusion IP-license + chiplet-required.
- Data: real silicon PPA exists but is PAYWALLED (ISSCC 2023 paper 9.3).
- Role: the anchor everything else substitutes for. Open stand-ins: **UCIe** (PHY) +
  **CXL/TileLink/CHI** (coherent). Confirmed: NVLink Fusion bridges custom ASICs via a
  UCIe↔NVLink chiplet, so UCIe is the correct open PHY analog.
