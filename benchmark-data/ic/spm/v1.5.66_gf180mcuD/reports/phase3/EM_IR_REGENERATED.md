# EM / IR-drop evidence — REGENERATED (review finding F7)

The v1.5.66 campaign folder shipped no EM / IR-drop reports. This set is
**regenerated** (2026-07-26) to close that gap — it is NOT the original
campaign output and must not be conflated with it.

- **Design**: spm, the campaign RTL `phase2/stage1/rtl/spm.v`
  (sha256 `e7feff2c…` — identical across all three PDK cells).
- **Stack**: plugin **v1.6.7** + PR `fix/psm-net-voltage-from-liberty`
  (the runner's IR/EM tcl omitted `set_pdnsim_net_voltage`; PSM-0079
  blocked all static IR/EM until the liberty `nom_voltage` was declared),
  container **vibeic-eda:0.2.25**, PDK **gf180mcuD** (named branch).
- **Results**:
  - `ir_drop.rpt` / `ir_drop.json` — **verdict PASS**, worst IR **2.33 mV
    = 0.047 % of VDD** (5.0 V supply from liberty `nom_voltage : 5`).
  - `em.rpt` / `em.json` — **MEASURED**, 12,389 segments analysed,
    max segment current 0.428 mA; `em_segments.csv` (real per-segment data).
- **Known delta from the campaign run**: this regen's DRC is NOT clean —
  6 whole-die density violations (M1.4–M5.4 + MT.3, >30 % coverage floor).
  Root cause: plugin 1.6.7's metal-fill step reported done + step-34 PASS
  but produced `filled.def` byte-identical to `routed.def` (silent no-op
  fill). Reported separately; the campaign's v1.5.66 fill fix had closed
  these same 6 violations to 0.
