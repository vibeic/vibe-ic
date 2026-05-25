# STA Review — Practical Notes from GF180MCU Runs

**Added**: 2026-04-07

## GF180MCU Timing Characteristics

At 5 MHz (200ns period) on GF180 180nm:
- **Typical designs have 30-40× timing margin** — 180nm at 5 MHz is extremely relaxed
- Critical path delay: 5-20 ns (logic depth 3-7 levels)
- This means timing closure is NOT the bottleneck for AID-class protocol controllers

## Available Corners in IIC-OSIC-TOOLS

```
/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lib/
├── *__tt_025C_1v80.lib    ← 1.8V typical
├── *__tt_025C_3v30.lib    ← 3.3V typical (recommended for the pilot)
├── *__tt_025C_5v00.lib    ← 5.0V typical
├── *__ff_*                ← fast-fast (hold analysis)
└── *__ss_*                ← slow-slow (setup signoff)
```

## Multi-Corner STA (Recommended for Tapeout)

```tcl
# In OpenROAD/OpenSTA:
read_liberty -corner ss $PDK/.../ss_n40C_1v62.lib
read_liberty -corner ff $PDK/.../ff_125C_3v63.lib
# Run STA per corner
```

## OpenROAD STA Output Format

OpenROAD's `report_checks` outputs standard STA path format:
```
Startpoint: <launch_flop>
Endpoint:   <capture_flop>
Path Group:  clk
Path Type:   max

  Delay    Time   Description
---------------------------------------------------------
   0.00    0.00   clock clk (rise edge)
   ...
          <val>   data arrival time
          <val>   data required time
---------------------------------------------------------
          <val>   slack (MET/VIOLATED)
```

Key numbers to extract: **WNS** (worst slack), **TNS** (sum of all negative slacks), **#failing endpoints**.
