# IR-Drop Triage — Practical Notes

**Added**: 2026-04-07 from a digital RTL-to-GDS pilot power grid analysis

## Tool: OpenROAD PSM (Power Grid Solver)

### Pilot Result: PASS — IR drop = 11.6µV (0.00%)

```
########## IR report #################
Net              : VDD
Supply voltage   : 3.30e+00 V
Average IR drop  : 3.93e-06 V
Worstcase IR drop: 1.16e-05 V
Percentage drop  : 0.00 %
######################################
```

### Why Previous Attempt Failed

**Error**: `PSM-0069: Check connectivity failed on VDD`

**Root cause**: PDN used only `followpins` (Metal1 rail per row) with NO cross-row connections. Each row's VDD rail was isolated — PSM saw thousands of unconnected VDD shapes.

### Fix: Add Metal4 Power Stripes

```tcl
# WRONG (followpins only — no cross-row connection):
define_pdn_grid -name main
add_pdn_stripe -grid main -layer Metal1 -width 0.48 -followpins
pdngen

# CORRECT (followpins + Metal4 stripes + connection):
define_pdn_grid -name main -pins {Metal4}
add_pdn_stripe -grid main -layer Metal1 -width 0.48 -followpins
add_pdn_stripe -grid main -layer Metal4 -width 1.6 -spacing 5 -pitch 80 -offset 10
add_pdn_connect -grid main -layers {Metal1 Metal4}
pdngen
```

Metal4 stripes run vertically across the die, connecting all horizontal Metal1 followpin rails.

### Running IR Drop Analysis

```tcl
# After reading DEF with complete PDN:
add_global_connection -net VDD -pin_pattern "VDD" -power
add_global_connection -net VSS -pin_pattern "VSS" -ground
global_connect

set_pdnsim_net_voltage -net VDD -voltage 3.3
set_pdnsim_net_voltage -net VSS -voltage 0
check_power_grid -net VDD
analyze_power_grid -net VDD
```

### Design Guidelines

| Metric | Target | Pilot |
|--------|--------|--------|
| IR drop | <5% VDD | **0.00%** ✅ |
| VDD connectivity | All shapes connected | ✅ |
| Power stripe pitch | <100µm for 180nm | 80µm ✅ |

The pilot's extremely low IR drop (11.6µV) is expected — it draws only ~45µA at 5MHz, far below what the power grid can handle. For higher-power designs, tighter stripe pitch and wider widths would be needed.
