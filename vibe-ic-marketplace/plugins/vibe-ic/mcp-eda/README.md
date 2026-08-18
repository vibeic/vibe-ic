# MCP EDA Server v2.0 — Open-Source IC Design Tools for AI Agents

55 MCP tools wrapping open-source EDA tools and lab hardware. One Docker image. Any AI agent can design digital + analog ICs from spec to GDS.

```
User: "Design an AID bus IC, 5MHz, 180nm, with OTP"
  ↓ AI Agent + MCP EDA Server + vibe-ic plugin
GDS file (tapeout-ready)
```

## Proven Results

- **Production IC**: 17 RTL modules generated from 9-layer design documents
- **Hardware protocol test**: 3/3 PASS on FPGA
- **ASIC flow**: Commercial 180nm PDK → 2,827 cells → 5.2 MB GDS
- **3-corner STA**: SS/TT/FF all setup timing MET

## Quick Start

```bash
# 1. Provide the EDA container (named vibeic-eda). Recommended: the enhanced fork image.
docker pull ghcr.io/vibeic/vibeic-eda:latest                       # forked toolchain, FAIL→PASS fixes (source build: git clone github.com/vibeic/vibeic-eda)
docker rm -f vibeic-eda 2>/dev/null || true                        # drop any old container of this name
docker run -d --name vibeic-eda -v $HOME/designs:/design \
  ghcr.io/vibeic/vibeic-eda:latest --skip sleep infinity
# already running an older tag? recreate config-preserving: tools/vibeic-eda/restart-eda.sh 0.2.12
# stock fallback: docker pull hpretl/iic-osic-tools:latest  (then run it named vibeic-eda)

# 2. Install MCP server
git clone https://github.com/anthropics/mcp-eda.git
cd mcp-eda && npm install

# 3. Connect to Claude Code
claude mcp add eda node $(pwd)/src/index.js -e EDA_CONTAINER=vibeic-eda

# 4. Start designing ICs
claude "Design a 4-bit counter IC using GF180 180nm PDK"
```

See [INSTALL_GUIDE.md](INSTALL_GUIDE.md) for detailed setup with troubleshooting.

## 55 MCP Tools (47 EDA + 7 Device + 1 health)

> The tables below describe the primary tools. The full canonical list of
> all 55 tools lives in `MCP_TOOL_INVENTORY.json` (CI-checked against the
> live server by `test/test_mcp_tool_inventory_no_drift.py` to prevent drift).

### Phase 2 — RTL Design & Verification

| Tool | EDA Engine | Description |
|------|-----------|-------------|
| `eda_lint` | Verilator 5.044 | RTL quality check (lint warnings/errors) |
| `eda_simulate` | Icarus Verilog 13.0 | Verilog simulation (PASS/FAIL) |
| `eda_formal` | SymbiYosys | Formal verification (SVA assertions) |
| `eda_equiv` | Yosys | Equivalence check (RTL vs gate-level) |
| `eda_cocotb` | cocotb 2.0.1 | Python testbench runner (Verilator/Icarus backend) |
| `eda_rtl_audit` | vibe-ic programs | Deterministic RTL audit (11 checkers) |
| `eda_fpga_compile` | Quartus/Vivado | FPGA synthesis & place-route |
| `eda_fpga_program` | quartus_pgm | FPGA board programming (SOF/BIT burn) |

### Analog Design (v0.108)

| Tool | EDA Engine | Description |
|------|-----------|-------------|
| `eda_xschem_netlist` | xschem | Generate SPICE netlist from schematic (.sch) |
| `eda_spice_corner` | ngspice | Multi-corner PVT sweep (5 corners × 3 temps × supply) with yield table |
| `eda_analog_layout` | Magic 8.3 | Analog layout with matching/guard-ring constraints → .mag + .gds |
| `eda_spice` | ngspice / Xyce | SPICE simulation (single deck) |

### Phase 3 — Backend & Signoff

| Tool | EDA Engine | Description |
|------|-----------|-------------|
| `eda_synth` | Yosys 0.62 | RTL synthesis (cell count, area) |
| `eda_sta` | OpenSTA 2.7.0 | Static timing analysis (WNS/TNS) |
| `eda_sta_mcorner` | OpenSTA | Multi-corner STA (SS/TT/FF simultaneously) |
| `eda_pnr` | OpenROAD 26Q1 | Place & Route (floorplan → routing) |
| `eda_gds` | KLayout 0.30.6 | GDS generation from DEF + cell GDS |
| `eda_dft` | Fault | Scan chain insertion + ATPG |
| `eda_drc_klayout` | KLayout | Design Rule Check |
| `eda_lvs` | Netgen 1.5.316 | Layout vs Schematic |
| `eda_ir_drop` | OpenROAD PSM | IR drop / power grid analysis |
| `eda_extraction` | Magic 8.3.603 | Parasitic extraction (SPEF/SPICE) |

### Phase 1 — Specification

| Tool | Engine | Description |
|------|--------|-------------|
| `eda_ic_search` | PostgreSQL | IC Knowledge Base search |

### Device Tools (auto-registered from vendor manifests)

| Tool | Hardware | Description |
|------|----------|-------------|
| `device_scope_capture` | Keysight InfiniiVision | Oscilloscope waveform capture |
| `device_scope_periodic_pulse_check` | Keysight InfiniiVision | Periodic pulse measurement |
| `device_camera_capture` | USB camera | LED / visual inspection capture |
| `device_camera_led_diff` | USB camera | LED state diff detection |
| `device_fpga_de10lite_detect` | DE10-Lite | FPGA board detection via JTAG |
| `device_fpga_de10lite_program` | DE10-Lite | FPGA SOF programming via JTAG |
| `device_fpga_de10lite_adc_read` | DE10-Lite MAX10 ADC | 12-bit internal ADC read via JTAG |
| `device_tester_usb_hid_tester_send_raw` | USB-HID tester | USB protocol tester raw command |

## Supported PDKs

| PDK | Node | Status | Source |
|-----|------|--------|--------|
| **GF180MCU** | 180nm | Built into Docker | Open-source (GlobalFoundries) |
| **SKY130** | 130nm | Built into Docker | Open-source (SkyWater) |
| **Custom** | Any | User-provided libs | `pdk: "custom"` + liberty/LEF/GDS paths |

Custom PDK example:
```javascript
eda_synth({
  pdk: "custom",
  custom_lib: "/design/pdk/my_pdk_typ.lib",
  custom_techlef: "/design/pdk/tech.lef",
  custom_celllef: "/design/pdk/cells.lef",
  ...
})
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│              Claude Code / AI Agent              │
│           (with vibe-ic plugin skills)           │
├─────────────────────────────────────────────────┤
│          MCP EDA Server v2.0 (Node.js)           │
│        55 tools × result manifest tracking       │
├─────────────────────────────────────────────────┤
│       IIC-OSIC-Tools Docker (hpretl/iic-osic)    │
│  Yosys │ OpenROAD │ OpenSTA │ KLayout │ Magic    │
│  Verilator │ iverilog │ ngspice │ cocotb │ ...    │
│  Built-in: GF180MCU + SKY130 PDKs                │
├─────────────────────────────────────────────────┤
│          Host-only (optional)                    │
│  Quartus Lite │ Vivado │ Custom PDK libraries    │
└─────────────────────────────────────────────────┘
```

## Tapeout Options

| Option | PDK | Cost | Timeline |
|--------|-----|------|----------|
| [Efabless chipIgnite](https://efabless.com/chipignite) | GF180MCU | ~$10K | 8-10 weeks |
| [Google Open MPW](https://efabless.com/open_shuttle_program) | SKY130 | Free | Apply |
| [Tiny Tapeout](https://tinytapeout.com/) | SKY130 | $100-300 | Shared area |

## License

MIT
