# Changelog

All notable changes to mcp-eda-server are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — Initial public release

First public release. MCP server bridging AI agents to open-source EDA
tools and lab hardware over the Model Context Protocol.

### Added

- **EDA tool wrappers** (24): `eda_synth` (Yosys), `eda_lint` (Verilator),
  `eda_simulate` (Icarus), `eda_formal` (SymbiYosys), `eda_pnr` (OpenROAD),
  `eda_gds` (KLayout), `eda_sta` / `eda_sta_mcorner` (OpenSTA), `eda_lvs`
  (Netgen), `eda_drc_klayout`, `eda_ir_drop`, `eda_equiv`, `eda_spice`
  (ngspice), `eda_xschem_netlist`, `eda_spice_corner`, `eda_analog_layout`
  (Magic), `eda_extraction`, `eda_dft`, `eda_cocotb`, `eda_fpga_compile`,
  `eda_fpga_program`, `eda_fpga_adc_read`, `eda_rtl_audit`, `eda_ic_search`.
- **Device framework**: manifest-driven first-class device wrappers under
  `src/devices/{fpga,scope,tester}/<vendor-product>/`.
- **Reference devices**: Terasic DE10-Lite (MAX10 FPGA), Keysight DSO-X 3014T
  oscilloscope. Tester driver template provided under `src/devices/tester/`.
- **PDK support**: gf180mcu, sky130, plus a `custom` mode for user-supplied
  Liberty / LEF / GDS.
- All EDA tools dispatch into the `hpretl/iic-osic-tools` Docker container
  unless explicitly marked host-only.
