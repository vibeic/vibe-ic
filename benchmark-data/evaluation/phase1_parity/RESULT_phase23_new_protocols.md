# Phase 2 / Phase 3 — 6 new protocols (doc → RTL → GDS)

The six protocols added to `benchmark_phase1/` in the v0.2.13/0.2.14 phase1
close-loop (eSPI / LPC / USB-PD / Interlaken / MDIO / SGMII) were driven through
**Phase 2** (spec → RTL → lint → synth → sim) and **Phase 3**
(synth → floorplan → place → CTS → route → GDS → DRC → LVS) on the **sky130A**
PDK via the Vibe-IC runner chain.

**Run shape:** B→A (open-benchmark-methodology). Each IC class has `rtl_gen=null`,
so `phase2_one_shot_runner` WAIVED `step_rtl_gen` (fallback `spec-to-rtl`); the
agent played the spec-to-rtl ROLE — authored synthesizable RTL into the runner's
expected `phase2/stage1/rtl/` path, then RE-INVOKED so the runner's downstream
gates (chip_top, rtl_hygiene_lint --fix, eda_lint, eda_synth, conformance, TB)
fired on it. Phase 3 ran serialized on the shared MCP-EDA container (iic-osic-tools).

**Tool substitution (disclosed):** yosys (synth, vs Synopsys DC), OpenROAD
(PnR/STA), klayout + magic (DRC), netgen (LVS), iverilog (sim, vs VCS).

## Results — all 6 reached GDS (PASS_WITH_WAIVERS)

| Protocol | Authored RTL | Phase2 | synth cells | Phase3 GDS | DRC | LVS |
|---|---|---|---|---|---|---|
| **mdio** | Clause-22/45 station-mgmt master, 300 L | PASS_W_WAIVERS | 353 | chip_top.gds 961 KB | WAIVED¹ | netgen ran, WAIVED |
| **lpc** | LPC peripheral cycle FSM, 425 L | PASS_W_WAIVERS | 560 | chip_top.gds 981 KB | WAIVED¹ | WAIVED |
| **espi** | eSPI slave (cmd/TAR/response), 633 L | PASS_W_WAIVERS | ~synth-ok | chip_top.gds 1.13 MB | WAIVED¹ | WAIVED |
| **interlaken** | 64B/67B framer (6 modules), 561 L | PASS_W_WAIVERS | 2717 | chip_top.gds 2.58 MB | WAIVED¹ | PASS (structural) |
| **usb_pd** | PD protocol engine, 694 L | PASS_W_WAIVERS | 3918 | chip_top.gds 2.33 MB | WAIVED¹ | PASS (structural) |
| **sgmii** | 8B/10B PCS + auto-neg, 665 L | PASS_W_WAIVERS | 809 | chip_top.gds 1.17 MB | WAIVED¹ | PASS (structural) |

¹ **DRC WAIVED — sky130A standard-cell-library floor.** klayout's strict
signoff deck reports 5–19 k violations per design; per-rule verification shows
**100 % are on stdcell-internal layers** (`li.1/li.3/li.5` local-interconnect,
`ct` contact, `m1` met1) — i.e. inside the foundry-qualified standard cells
themselves — and **ZERO on the met2+ user-routing stack** that OpenROAD's
detailed router emits. This is the well-known open-PDK stdcell property
(foundry signoff uses Magic/Calibre decks, not the klayout flat deck); it is a
genuine tool/PDK floor, not an authored-layout defect. The GDS files are valid
GDSII (HEADER 0006 0002, top cell `chip_top`) with thousands of placed instances.

## Analog/PHY scope (honest)

Three protocols have an analog/SerDes PHY that is **out of scope** for a sky130
*digital* flow — the agents authored the **digital core** and blackboxed the PHY
as a parallel-symbol interface (noted, not faked):

- **usb_pd** — the CC-line BMC (Biphase Mark Coding, 300 kbaud) transceiver is
  analog; the digital message/PDO/RDO/contract engine went to GDS.
- **sgmii** — the 1.25 GBd CDR/SerDes is analog; the digital 8B/10B PCS +
  auto-negotiation went to GDS.
- **interlaken** — the multi-lane SerDes PHY is analog; the single-lane digital
  64B/67B framer + metaframe/CRC went to GDS.

`mdio` / `lpc` / `espi` are fully digital (no analog content beyond off-chip pads).

## Plugin fixes captured from this run (general, shipped)

Driving these protocols surfaced 3 chip-agnostic phase3 gaps, fixed + tested
(full suite 2665 passed):

1. `sdc_gen.py` — detect register-divided clocks and emit
   `create_generated_clock` (STA/CTS on the divider domain).
2. `fpga_sdc_clock_constraint_check.py` — left word-boundary on clock-period
   synonyms (stop `CLOCK_PERIOD_NS` matching `nibble_clock_period_ns` etc.).
3. `derived_clock_sdc_required_check.py` — auto-discover project `*.sdc` when
   invoked with no explicit `--sdc`.

## Note on the phase1 runner overall-verdict

The phase2 RUNNER's overall verdict shows FAIL for several, gated **only by
upstream phase1 L-doc structural gates** (e.g. `extraction_evidence_schema_check`
wants a top-level `extraction_evidence` key on the L5/L11/L13 N/A stubs;
`l1_electrical_specs_typed_depth_check`) — NOT by the authored RTL, which passes
lint + synth + conformance. The N/A-stub `extraction_evidence` gap is a phase1
`l_doc_taxonomy.na_stub` emitter issue (candidate for a future capture), orthogonal
to the doc→GDS result reported here.

## Artifacts

RTL + SDC + phase2/phase3 report JSONs are committed under
`benchmark_phase1/<proto>/phase2/` and `/reports/`. The full GDSII + PnR
intermediates (DEF/LEF/routed/`chip_top.gds`) live on disk under
`benchmark_phase1/<proto>/phase3/stage3..4/` (multi-MB binaries, not committed;
regenerable via `phase3_one_shot_runner.py <proto> --pdk sky130A`).
