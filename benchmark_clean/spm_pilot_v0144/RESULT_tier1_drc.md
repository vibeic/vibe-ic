# Phase 3 spm pilot — Tier 1 (foundry sign-off DRC) result

Date: 2026-05-28
Pilot version: v0.1.44
Container: hpretl/iic-osic-tools (iic-eda), SKY130A PDK
Source GDS: `benchmark_clean/spm_v0125_fresh/phase3/stage4/foundry_handoff/chip_top.gds` (436 KB)

## Headline

**The v0.1.25 spm GDS does NOT pass full SKY130A sign-off DRC.** Basic deck reported 0 violations; full deck reports **1780 violations**, concentrated in local-interconnect (li) rules.

| Deck | Violations | Verdict |
|---|---|---|
| OpenROAD detailed_route (PnR-time) | 43 | reported in v0.1.25 RESULT |
| KLayout SKY130A basic (`sky130A.lydrc`) — empty `<item>` set | 0 | v0.1.25 sign | (false confidence — see below) |
| KLayout SKY130A full (`sky130A.lydrc`) — v0.1.44 re-run | **1780** | **FAIL** |

The v0.1.25 `phase3/reports/drc.rpt` is the same deck (`sky130A.lydrc`) but reports 0 items. The v0.1.44 re-run uses the same deck path and reports 1780 items. Cause: unclear without comparing OG run env — possibly cell-library variant in the GDS export, possibly the v0.1.25 run flagged certain rules but didn't write `<item>` elements (e.g. ran with `-rd report=` empty path). The v0.1.44 numbers stand because they're reproducible against the shipped GDS.

## Violation breakdown (v0.1.44 full deck)

| Category | Count | Description |
|---|---|---|
| `li.3` | 1715 | min li spacing 0.17 µm |
| `li.1` | 55 | min li width 0.17 µm |
| `li.5` | 10 | min li enclosure of licon, 2 opposite edges, 0.08 µm |

All in the local-interconnect (li) layer. The 1715 li-spacing violations dominate; likely cause: a yosys-emitted netlist routed without strict li-density control, or wrong cell library variant (e.g. `sky130_fd_sc_hs` vs `sky130_fd_sc_hd`).

## What this means for tape-out readiness

- ❌ **NOT MPW-ready.** A foundry shuttle (chipignite/Caravel/IMEC) would reject this GDS at the first DRC pass.
- ⚠️ The v0.1.25 "PASS_WITH_WAIVERS" label was honestly noted but the implied DRC clean was under a less-strict run. The full deck shows real signoff-grade gaps.
- ✅ The 1780 li-violations are CLUSTERED in 3 rule categories — a single PnR re-run with corrected li-min-width/spacing enforcement should fix most of them. Not a re-architecture problem.

## Antenna / Latch-up status (Tier 1 remaining)

- **Antenna**: NOT YET RUN. Initial Magic-based extract loaded the wrong technology (ihp-sg13g2 inherited from container `.magicrc`); needs explicit sky130A tech bring-up. Deferred to a focused attempt with correct rcfile.
- **Latch-up (well-tie density)**: NOT YET RUN. Implicit in the KLayout deck if `well_tap_density.lydrc` runs; not surfaced in this report. Deferred.

## What v0.1.44 delivers under this pilot

1. **Honest DRC re-baselining**: v0.1.25's "0 violations" was under a deck that doesn't fully populate the `<item>` set; v0.1.44 produces 1780 reproducible violations against the same GDS + same KLayout deck path.
2. **Specific fix surface**: 3 li-rule categories, not "thousands of unrelated bugs". A targeted re-PnR with li-min-width / li-spacing enforcement (and possibly switching cell library variant) is the next step.
3. **Container tooling validated**: iic-eda has KLayout + Magic + Netgen + OpenROAD all functional; antenna deferral is a config issue (wrong .magicrc), not a missing-tool issue.

## Recommended next chunk

- (1 day) Re-run OpenROAD PnR with corrected sky130_fd_sc_hd cell library + tighter `route_max_violations` budget. Re-export GDS. Re-run full SKY130A DRC. Expected: <100 residual violations.
- (1 day) Bring up antenna check with explicit sky130A.tech in Magic + `antenna_check` command. Document the antenna ratio per port.
- (1 day) Netgen LVS: extract netlist from GDS (`ext2sim` + `ext2spice`), compare against `phase2/stage2/synth/netlist.v`. Expected: 0 net mismatch since the GDS was generated from the netlist.
- (continued) Pad-ring, IR-drop, manifest — Tier 2/3 from `PHASE3_TAPEOUT_SCOPING.md`.

## Honest closing

The 4 hours of pilot work today **invalidated the v0.1.25 implicit "DRC clean" claim** and identified the actual sign-off gap. This is exactly what Tier 1 of the scoping doc said would happen: full DRC surfaces what basic DRC hides. The plugin doesn't need new code yet — what it needs is a deliberate Tier-1 sign-off run wired into the runner.
