# Advanced-Node Extension — commercial / ≤7nm-only gaps (NOT numbered OSS steps)

vibe-ic is an **OSS-first, program-first** flow (a numbered step earns its place ONLY
when a real open-source engine can execute it). This appendix documents the
advanced-node / complex-SoC capabilities that genuinely require **commercial tools
or a ≤7nm PDK with data that does not exist in open source**. They are deliberately
**NOT** numbered steps and are **never counted in the OSS PASS** — representing them
as steps would either fake a stub or inflate the score. Each row also has a
`substitute="none (commercial-only)"` entry in `programs/tool_substitution_disclose.py`
so any report that touches the area must disclose the substitution.

> This is the honest boundary. Everything the OSS toolchain CAN do was added as a
> real gating step instead — see the campaign that closed ALL SEVEN sign-off
> cap-gaps (SPEF/DFT/post-DFT/SDF/SPICE/LEC/FORMAL — the last via `formal_property_run`:
> real SymbiYosys with the built-in ABC engines, unbounded safety + disclosed-bound
> functional BMC) and added program-first advanced steps (VCD-vectored dynamic-IR,
> ISO-26262 FMEDA fault-injection DC, power-domain signal-crossing CDC, at-speed
> path-delay-fault ATPG DT2, small-delay-defect grade DT3, MCF SI-aware
> crosstalk-delay STA, whole-design FasterCap 3D field-solved coupling). Those are
> NOT here — they are real steps.

## What the OSS flow already does (do NOT confuse with a gap)
| Area | OSS coverage in the flow |
|---|---|
| On-chip variation | flat-OCV `set_timing_derate ±5%` + AOCV tables (`sta_signoff_rigor_check`) |
| Static IR | OpenROAD PSM `analyze_power_grid` (Step 24) |
| **Dynamic IR (vectored)** | **NEW: VCD-weighted PSM droop (`dynamic_ir_vectored_emit`, Step 24 2nd gate)** |
| EM | `em_current_density_check` (Step 25) |
| Thermal (screen) | `thermal_screen_check` power-density / Tj first-order screen |
| DFM / yield | `dfm_screen_check`, `analog_mc_yield_run` (real ngspice MC), `wafer_sort_yield_check` |
| UPF / low-power | `l21_to_upf_emit` + M2 gates (power-domain / level-shifter / isolation) **+ NEW power-domain signal-crossing CDC** |
| **Functional safety (DC)** | **NEW: FMEDA fault-injection diagnostic-coverage (`fmeda_fault_injection_coverage`, step FS1)** |
| DFT / ATPG | AUCOHL Fault real stuck-at ATPG (Step 11) **+ transition-delay-fault (LOC) ATPG via vibeic/yosys `sat -prove` 2-frame unroll (`transition_fault_atpg_run`, step DT1) + NEW at-speed TIMING-graded path-delay-fault ATPG: OpenSTA K-longest paths on the ROUTED netlist+SPEF → per-path LOC miter SAT, robust/non-robust graded (`path_delay_fault_atpg_run`, step DT2)** |
| **Post-layout cell-arc gate-sim** | iverilog `-gspecify` DOES back-annotate SDF IOPATH cell-arc delays (combinational + sequential CK→Q, proven exact); the OpenSTA SDF carries the cell arcs. Full-design at-speed gate-sim integration (cell-delay-aware TB calibration) is a tracked residual — NOT a commercial gap; STA signs off cell timing meanwhile |
| Post-silicon | `bringup_plan_gen` (plan from L13) |
| IP / subsystem | `ip_integration_check` (Step 15), `ip_catalog_*`, NoC/AXI/CHI detect |

## The genuine commercial / advanced-node gaps (this extension)
| Capability | Why no OSS engine | Commercial tool(s) | Represented as |
|---|---|---|---|
| **POCV / SSTA** (statistical / parametric OCV) | needs LVF (Liberty Variation Format) / POCV coefficient data; sky130/gf180 don't ship it, and ≤7nm variation data is foundry-NDA | PrimeTime-POCV, Tempus | flat-OCV+AOCV is the OSS floor; POCV = cap-gap |
| **Full di/dt transient dynamic-IR** | OSS PSM is resistive/vectored only — no L·di/dt inductive-droop time-domain solve | RedHawk-SC, Voltus | VCD-vectored PSM is the OSS floor; transient = cap-gap |
| **2.5D/3D advanced packaging / chiplet** | CoWoS/EMIB/TSV/hybrid-bond assembly, multi-die STA & thermal need a packaging PDK + assembly rules absent in OSS (the D2D *protocol* layer — UCIe/CXL/HBM3 — IS synthesized) | 3Dblox, Innovus-3D, Calibre-3DSTACK | Extension-only (no numbered step) |
| **Full 3D self-heating thermal + thermal-aware STA** | field thermal solve + per-temperature timing needs a thermal solver | Celsius, RedHawk-SC-ET | thermal *screen* is the OSS floor; full solve = cap-gap |
| **Foundry-calibrated coupling / crosstalk-SI sign-off** | the flow now does a REAL 3D field solve, not just the analytical model: step 22 offers three tiers — (1) grounded-cap OpenRCX v2 `-lef_rc`, (2) analytical lateral coupling (`_spef_coupling`), and (3) **whole-design FasterCap 3D BEM field-solve** (`pdk_dielectric_fit` inverts the PDK's own area+fringe cap to a fitted dielectric stack, then `fastercap_extract --whole-design` tiles the entire coupling graph — spm: 100 % coverage, 136 solves, inter-layer crossover INCLUDED, field 2.5× the analytical total). The MCF SI-aware crosstalk-delay STA (step 27) runs on that field-solved SPEF. What REMAINS genuinely external: (a) the foundry-CALIBRATED field-solve profile (the exact inter-metal ILD/IMD thickness, metal elevation, per-dielectric k, pattern-solved Cc tables) lives only in the un-shipped Calibre-XRC `rules.C`/StarRC `.nxtgrd` — our fitted stack is DISCLOSED as generic-εr, not foundry-calibrated; and (b) full aggressor-victim crosstalk-SI *sign-off* (iterative coupled-waveform, glitch/noise-margin) vs our conservative MCF bound | Calibre xRC, StarRC-XT, QRC + PrimeTime-SI | field-solved coupling (fitted dielectric) is DONE via FasterCap; only the foundry-CALIBRATED profile + iterative crosstalk-SI sign-off remain a foundry-data / commercial gap |
| **MBIST / LBIST + memory ATPG** | memory BIST insertion + memory fault models are commercial | Tessent MBIST, TetraMAX | Extension-only |
| **Side-channel security (DPA/CPA/EM leakage)** | leakage-model simulation needs a specialized engine | PROLEAD, commercial DPA tools | Extension-only |
| **Full FMEDA (SPFM/LFM/PMHF)** | the measured-DC half IS in FS1; the roll-up needs FIT/λ base-failure-rate apportionment from a reliability DB (IEC 62380 / SN 29500 / foundry) | commercial safety flows | FS1 delivers DC; roll-up = methodology/commercial gap |
| **SW/HW co-design, AI-accelerator architecture** | SW ecosystem / domain-specific architecture, not an IC-physical-flow step | — (out of scope) | out-of-scope (Phase-1 architecture exploration only) |

## Rule
Add a **numbered/lettered step** only when a real OSS engine runs end-to-end (the FS1 /
dynamic-IR / power-domain-CDC precedent). A commercial-only capability stays here + in
the `tool_substitution_disclose` map, **never counted**, so the OSS PASS number keeps
meaning "steps a real open engine passed."
