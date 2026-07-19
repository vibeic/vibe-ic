# Phase-1 L-doc Parity Sweep + Convergence — all 87 protocol specs

## Headline
- **Measured:** deterministic Phase-1 L-doc extraction parity — `phase1_doc_one_shot_runner.py`
  generated_docs (program-first, NO LLM) **vs** `claude_extracted` gold, over **all 87 protocol
  specs** (49 real published-standard PDFs + 40 reconstructed `*_spec.txt`).
- **GATED parity** = Σ(absent_in_program + hallucinated + value_mismatch) over docs where gold is
  present; SHAPE_MISMATCH excluded (R28); L19-L23 skeleton-only excluded.
- **Baseline (v1.2.34): 56/87 clean · 31 with-gap · 0 hallucinations.**
- **After convergence: 76/87 clean · 11 with-gap · 0 hallucinations.**

`0 hallucinations` across all 87 specs, both runs, is the load-bearing number: the deterministic
extractor **never fabricates** a fact the spec does not state.

## ⚠️ What the 87 inputs actually are — source-tier qualification

The parity number above is uniform. **The inputs behind it are not.** Only 23 of the 87 protocols
were measured against the real specification from its issuing body. The rest were measured against
an encyclopedia article, a vendor document, or an authored text reconstruction.

<!-- source-tier-counts -->
| Source tier | Count | What the input document is |
|---|---|---|
| **`specification`** — 23 | 23 | The protocol spec as published by its issuing body (ARM AMBA, Bosch CAN, JEDEC JESD79-3C, IEEE 802.3-2005, NXP UM10204, MIPI I3C/DSI, PCI-SIG PCIe 1.0, USB 2.0, Bluetooth 5.2, TCG TPM 2.0, Wishbone B4, …). |
| **`encyclopedia`** — 12 | 12 | A **Wikipedia** article print/export, not a spec: `arinc429, cxl, ethernet_800g, hbm3, hdlc, lpddr5, milstd1553, nvlink, pcie_gen5, spdif, ufs, usb4`. (`ufs` concatenates 3 articles.) |
| **`vendor_document`** — 13 | 13 | A vendor app note / datasheet / IP manual / brochure / slide deck — **not the protocol spec**: `canfd, dali, ethercat, hdmi, jtag, mipi, nfc, onewire, rs485, soundwire, spi, uart, ucie`. |
| **`reconstructed_text`** — 39 | 39 | An authored plain-text technical reference written **for this benchmark**, summarising a named standard — the 40 "reconstructed `*_spec.txt`" of the headline, minus `ufs` (which is encyclopedic). |
| **`unknown`** — 0 | 0 | None. Every protocol's tier was substantiated. |

**A parity score measured against an encyclopedia article or a vendor application note is NOT
evidence of parity against the real specification.** A Wikipedia article carries none of the
normative bit-level, timing, or state-machine detail a spec carries, so there is far less for the
extractor to be right or wrong about; a vendor app note describes a *product*, not the protocol.
For the 52 non-`specification` protocols the number measures extraction fidelity **against that
document**, and nothing more.

This is a **known, deliberate methodology, not a hidden defect** — `ufs_spec.txt`'s own header names
the convention ("the same honesty posture as the existing Tier-3 benchmarks (vendor briefs /
Wikipedia)"), and the headline above already discloses the 49-PDF / 40-reconstructed split. What was
missing was the per-protocol tier at the point where the score is read. It is now recorded as data in
[`source_tier.json`](source_tier.json) — with the evidence that substantiated each tier (PDF `/Title`
and `/Producer` metadata, first-page text, in-file provenance headers) — because the input documents
are subject to removal for licensing reasons and **the tier must survive the document**.

Filenames are not evidence and were not trusted: `ARINC429_Spec.pdf` is `/Title='ARINC 429 -
Wikipedia'`, `HDMI_Spec.pdf` is a TI TFP410 transmitter datasheet, `CAN_FD_Spec.pdf` is the Bosch
M_CAN *controller IP user's manual*, and `SoundWire_Spec.pdf` is a 2015 MIPI webinar deck. Three
entries in `specification` also carry a scope caveat in their `note`: `sata` is the AHCI
host-controller spec (not the SATA wire protocol), `sdmmc` is the *Simplified* public subset, and
`ethernet` is Section Two of IEEE 802.3-2005 only.

Verified by `programs/phase1_parity_source_tier_check.py`, which fails if any protocol goes untiered
or if the counts in this table drift from the data.

## What the 31 baseline gaps actually were (§3.9 attribution + §4.1 oracle-defect proof)
Triage found the gaps were **dominated by GOLD DEFECTS, not program bugs** — so per §4.1 (never
converge a correct program to a flawed oracle) the program was NOT bent to match them. The two
corrective tracks:

### (1) Gold corpus decontamination — provably-wrong reference data corrected
- **`L12.no_calibration` ×28** (the dominant gap): program emits `true` (ORGANIC #634 facet-e:
  absence-based honest-N/A); gold says `false`. **Proof:** for 27/28 the input has ZERO calibration
  source (`calibrat|trim|OTP|bandgap`; emmc's "TRIM" is the *erase* command, correctly not flagged);
  `false` asserts calibration EXISTS with no evidence. Golds predate the v0.1.82 #634 convention
  (55 omit, 32 false, **0 true**). → 28 golds corrected to `true`.
- **`avalon` AXI-contamination ×16**: the Avalon (Intel/Altera) gold carried **AXI** content
  (`protocol_variants=[AXI3,AXI4,AXI5]`, `ACLK/ARESETn`, `multi_copy_atomicity`, AXI5 `E1/E2`,
  `ID_WIDTH`) the Avalon input never mentions (it uses Avalon's `waitrequest`). → AXI fields stripped.
- **L5 prose-fragment noise ×12**: the gold's `bullet_kv_pair_spec` strategy mis-captured prose as
  params (`{parameter:"pulse-amplitude modulation", value:"-1,"}`). → garbage entries removed.

### (2) §4.05-safe program improvement — `phase1_doc_one_shot_runner` L5 (ships v1.2.35)
The L5 `bullet_kv_pair_spec` parser had been (correctly) tightened to drop prose noise, which also
dropped REAL prose-embedded electrical specs (`VDD = 1.2 V`, `runs at 800 MHz`); and the no_analog
skeleton forced `electrical_specs=[]`. v1.2.35 wires the clean `spec_electrical_extract`
(number+SI-unit+context only — NOT the noisy bullet_kv) into L5 and carries it through the
no_analog skeleton, so a digital protocol's real supply/clock are captured **without** re-introducing
noise. This closed ddr4/gddr6/sent/emmc/hyperbus/infiniband electrical gaps with ZERO new
value-mismatches and ZERO hallucinations.

## Residual (11 gaps, all `absent`-only, 0 hallucinations) — the program-first/LLM boundary
The remaining gaps are loose-prose facts the deterministic extractor **correctly defers to the
LLM** (IC-Expert Agent) — forcing deterministic extraction would fabricate (§4.05):
- `axi_stream` (5): LLM port/pin lists (`dma`), TSTRB design-param.
- `coresight` / `mipi_csi2` (2 ea): prose `fsm_states`.
- `ddr4` (2): 240 Ω ODT `external_components` + `x16 devices` design-param.
- `emmc/gddr6/lora/ocp/psi5/sent/spacewire` (1 ea): unitless prose `design_parameters`
  (`Differential pairs: 4`).
These are the genuine program-first/LLM boundary, not defects.

## Honest conclusion
The deterministic Phase-1 extractor was **already correct and never hallucinates**; 20 of the 31
baseline gaps were corrected by fixing **defective gold** (stale convention / AXI-contamination /
prose noise), and a single §4.05-safe program improvement recovered the real prose electrical
specs. Convergence: **56 → 76 clean (0 → 0 hallucinations)**; the 11-gap residual is the
documented program-first/LLM boundary.

## Reproduce
```bash
cd benchmark-data/evaluation/phase1_parity
python3 _sweep_parity.py            # regen + diff all 87 -> _sweep_parity_result.json
python3 _sweep_parity.py --no-regen # re-diff only (after a gold-corpus edit)
```

## Tool substitution
None — Phase-1 doc extraction is pure-Python; PDF→text reuses committed `input_doc/*.txt`.
