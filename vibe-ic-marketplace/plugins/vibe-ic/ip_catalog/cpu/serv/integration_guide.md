# SERV — Integration Guide

> Bit-serial RISC-V RV32I CPU, world's smallest. ISC license.

## When Plugin selects this IP

Plugin's catalog selector matches SERV when L1-L9 spec says:
- L2.cpu_isa starts with `rv32i`
- L2.cpu_arch mentions `bit-serial` / `bit_serial` / `bit by bit`
- L1.target_area_ge is small (<5000 GE)

## Files to pull

```
serv_top.v          ← bare CPU (no RF storage)
serv_rf_top.v       ← CPU + on-board RAM-based RF (drop-in option)
serv_*.v            ← internal submodules (18 files total)
servile/servile.v   ← convenience wrapper (CPU + RF + arbiter + mux)
servile/servile_*.v ← servile sub-modules (4 files)
```

## Typical wiring patterns

### Pattern A: Use `serv_top` with external custom RF

```verilog
serv_top #(
    .RESET_PC(32'h00000000),
    .WITH_CSR(1)
) cpu_inst (
    .clk(clk),
    .i_rst(rst),
    .i_timer_irq(timer_irq),
    // Instruction bus
    .o_ibus_adr(ibus_adr),
    .o_ibus_cyc(ibus_cyc),
    .i_ibus_rdt(ibus_rdt),
    .i_ibus_ack(ibus_ack),
    // Data bus
    .o_dbus_adr(dbus_adr),
    .o_dbus_dat(dbus_dat),
    .o_dbus_sel(dbus_sel),
    .o_dbus_we(dbus_we),
    .o_dbus_cyc(dbus_cyc),
    .i_dbus_rdt(dbus_rdt),
    .i_dbus_ack(dbus_ack),
    // RF interface (Plugin authors a tiny wrapper to connect to SRAM)
    .o_rf_rreq(rf_rreq),
    .o_rf_wreq(rf_wreq),
    // ... etc
);
```

### Pattern B: Use `servile` wrapper (recommended for shared-SRAM SoC)

```verilog
servile #(
    .reset_pc(32'h00000000),
    .with_csr(1),
    .rf_width(2)
) soc_cpu (
    .i_clk(clk),
    .i_rst(rst),
    .i_timer_irq(timer_irq),
    // Wishbone memory interface (Plugin authors a tiny adapter to map to chip SRAM)
    .o_wb_mem_adr(sram_addr),
    .o_wb_mem_dat(sram_wdata),
    .o_wb_mem_sel(sram_sel),
    .o_wb_mem_we(sram_we),
    .o_wb_mem_stb(sram_stb),
    .i_wb_mem_rdt(sram_rdata),
    .i_wb_mem_ack(sram_ack),
    // Extension interface (peripheral controller bus)
    .o_wb_ext_adr(ext_addr),
    .o_wb_ext_dat(ext_wdata),
    .o_wb_ext_we(ext_we),
    .o_wb_ext_stb(ext_stb),
    .i_wb_ext_rdt(ext_rdata),
    .i_wb_ext_ack(ext_ack),
    // RF SRAM interface (Plugin maps to chip SRAM)
    .o_rf_waddr(rf_waddr),
    .o_rf_wdata(rf_wdata),
    .o_rf_wen(rf_wen),
    .o_rf_raddr(rf_raddr),
    .i_rf_rdata(rf_rdata),
    .o_rf_ren(rf_ren)
);
```

## What Plugin still needs to author

When Plugin selects SERV, it still authors:
- **SoC top wrapper** that instantiates `servile` + chip SRAM + GPIO/peripherals
- **SRAM adapter** that maps SERV's Wishbone memory bus to your physical SRAM
- **Peripheral controllers** on the extension bus(GPIO, UART, etc.)
- **OpenLane config** (from L9 spec)

## Verification

The serv repo ships with `tb/serv_tb.v` and a `cv-mods` directory that holds compliance tests. Plugin should pull these into project's `verif/` directory and run as part of Phase 2B reference_tb step.
