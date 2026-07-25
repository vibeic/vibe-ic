# Formal evidence — reset-safety (REGENERATED, review finding F4)

The v1.5.58 campaign RESULT.md claims a SymbiYosys `abc pdr` proof of
reset-safety (`p == 0` one cycle after reset) but shipped no `formal/`
artifact with it. This directory REGENERATES that evidence for the record.

- **Property**: one cycle after `rst` is asserted, `p == 0` — unconditional
  (no input assumptions), matching L3's "assertion 後一個 cycle 內所有內部
  狀態歸零" contract. Full-datapath functional proof remains deferred
  (see `waivers.json`, step `formal_full_stack`).
- **DUT**: the campaign RTL `../../rtl/spm.v` (sha256 `e7feff2c…`, the same
  RTL used by all three PDK cells).
- **Regenerated**: 2026-07-26, plugin v1.6.7, container vibeic-eda:0.2.25,
  `sby -f spm_reset_safety.sby` (mode prove, `abc pdr`, depth 20).
- **Result**: `engine_0 (abc pdr) returned PASS` — "Property proved."
  (`sby_reset_safety.log`)

This does NOT retroactively change the v1.5.58 campaign record; it supplies
the missing evidence the claim pointed at, honestly labeled as regenerated.
