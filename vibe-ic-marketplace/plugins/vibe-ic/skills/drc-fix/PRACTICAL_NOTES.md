# DRC Fix — Practical Notes from GF180MCU P&R

**Added**: 2026-04-07
**Updated**: 2026-04-07 with complete root cause analysis and verified solution

---

## DRT-0305 Tie-Cell Power Net Issue — SOLVED

### What happens

```
ERROR DRT-0305: Net one_ of signal type POWER is not routable by TritonRoute
```

### Complete causal chain

**Step 1 — Yosys generates constant connections**: RTL ports tied to `1'b0` or `1'b1` (unused signals, tie-off logic) create `one_` and `zero_` nets in the synthesized netlist.

**Step 2 — OpenROAD PDN marks them as POWER**: During `pdngen`, OpenROAD marks `one_` (connected to VDD) as `+ USE POWER` and `zero_` as `+ USE GROUND`.

**Step 3 — TritonRoute refuses to route**: TritonRoute's design logic: POWER/GROUND nets are handled by PDN, not signal routing. When it encounters `one_` marked as POWER, it throws DRT-0305.

**Root cause**: Missing **tie cell insertion** step. Proper flow uses dedicated tie cells (standard cells that output fixed 0 or 1) instead of direct constant connections.

### Why SN74HC163 didn't hit this

SN74HC163 has only 25 cells — all ports have real signal connections, no constants. A ~2.7k-cell digital pilot has tie-off needs.

---

## Solution: hilomap + insert_tiecells (Method A+B) — VERIFIED

**This is the correct production method. Both steps used together.**

### Step 1: Yosys hilomap (Method B — fix at source)

Add to synthesis script after `abc`:

```bash
yosys -p "
  ...
  abc -liberty $LIB;
  hilomap -hicell gf180mcu_fd_sc_mcu7t5v0__tieh Z \
          -locell gf180mcu_fd_sc_mcu7t5v0__tiel ZN \
          -singleton;
  clean;
  write_verilog -noattr synth_output.v
"
```

`-singleton` ensures each constant net gets its own tie cell instance.

### Step 2: OpenROAD insert_tiecells (Method A — safety net)

Add to P&R script after `pdngen`, before `global_placement`:

```tcl
# After pdngen, before placement
insert_tiecells gf180mcu_fd_sc_mcu7t5v0__tiel/ZN
insert_tiecells gf180mcu_fd_sc_mcu7t5v0__tieh/Z
```

### Verified Result (Pilot)

```
TritonRoute convergence: 2016 → 580 → 461 → 19 → 0 violations
Final: 0 DRC violations
GDS: 5.1 MB, 270 cells
GF180 Foundry DRC: PASS (0 violations)
Timing: slack +183.58 ns (MET @ 5MHz)
```

### Previous hack (DO NOT USE in production)

The earlier workaround of changing net signal type via Tcl API works:
```tcl
# HACK — not recommended for tapeout
$net setSigType SIGNAL  ;# changes POWER→SIGNAL
```
This routes successfully but is semantically wrong — the net IS a power connection, just improperly modeled. The tie cell approach is correct.

---

## GF180MCU Tie Cell Reference

| Cell | Type | Output Pin | Function |
|------|------|-----------|----------|
| `gf180mcu_fd_sc_mcu7t5v0__tieh` | TIEHIGH | `Z` | Outputs VDD (logic 1) |
| `gf180mcu_fd_sc_mcu7t5v0__tiel` | TIELOW | `ZN` | Outputs VSS (logic 0) |
| Area each | — | — | 8.78 µm² |

## SKY130 Tie Cell Reference

| Cell | Output Pin |
|------|-----------|
| `sky130_fd_sc_hd__conb_1` | `HI` (tie-high), `LO` (tie-low) |

---

## GF180 Foundry DRC

### Running DRC with official rule deck

```bash
# Prefer the vibeic build when the image has one. It is not a cosmetic choice:
# the fork honours tech-LEF MANUFACTURINGGRID in the LEF/DEF importer, and on
# the fork's own fixture the base build leaves 8 off-grid vertices where ours
# leaves 0. LD_LIBRARY_PATH matters as much as PATH — the pymod links
# libklayout_db.so by SONAME, so our build on PATH with the base directory on
# the library search path reproduces the base's geometry exactly.
for kd in /foss/tools/klayout-vibeic /foss/tools/klayout; do
  [ -x "$kd/klayout" ] && { export PATH="$kd:$PATH"; \
    export LD_LIBRARY_PATH="$kd:${LD_LIBRARY_PATH}"; break; }
done
python3 /foss/pdks/gf180mcuD/libs.tech/klayout/tech/drc/run_drc.py \
  --path=design.gds \
  --variant=C \
  --topcell=top_module \
  --run_dir=/tmp/drc_run \
  --thr=8 \
  --no_feol \
  --no_connectivity
```

### Variant options

| Variant | metal_top | mim_option | metal_level | Use case |
|---------|-----------|-----------|-------------|----------|
| A | 30K | A | 3LM | Minimal metal |
| B | 11K | B | 4LM | — |
| **C** | **9K** | **B** | **5LM** | **Most common, used for the pilot** |
| D | 9K | A | 5LM | — |

### DRC flags

- `--no_feol`: Skip front-end-of-line rules (transistor level) — use when standard cells are trusted
- `--no_connectivity`: Skip connectivity checks — faster
- `--no_beol`: Skip back-end-of-line (metal) — rarely needed

### Magic DRC (limited for GF180)

Magic has limited GF180 support (900+ LEF parse errors). Use KLayout with official rules instead.

---

## GDS Generation (KLayout)

```python
# MUST read cell GDS before DEF
ly = pya.Layout()
ly.read(CELLGDS)        # First — loads standard cell geometry
ly.read(DEF, opt)       # Second — overlays placement + routing
ly.write(OUTPUT_GDS)
```

**Critical**: `QT_QPA_PLATFORM=offscreen` required for headless environments.

---

## References

- [OpenROAD IFP insert_tiecells](https://github.com/The-OpenROAD-Project/OpenROAD/tree/master/src/ifp)
- [OpenROAD Issue #2039](https://github.com/The-OpenROAD-Project/OpenROAD/issues/2039)
- [OpenLane Issue #1185](https://github.com/The-OpenROAD-Project/OpenLane/issues/1185)
- [OpenROAD-flow-scripts GF180 config.mk](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/blob/master/flow/platforms/gf180/config.mk)
- [Yosys hilomap documentation](https://yosyshq.readthedocs.io/projects/yosys/en/latest/using_yosys/synthesis/cell_libs.html)
- [GF180MCU PDK Standard Cells](https://gf180mcu-pdk.readthedocs.io/en/latest/digital/standard_cells/gf180mcu_fd_sc_mcu7t5v0/index.html)
- [TritonRoute documentation](https://openroad.readthedocs.io/en/latest/main/src/drt/README.html)
