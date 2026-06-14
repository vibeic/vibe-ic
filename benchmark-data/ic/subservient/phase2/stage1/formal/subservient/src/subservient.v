// subservient.v
// GENERATED (authored from L1-L9 spec) — chip-level top wrapper (tape-out default top).
//
// Integrates (L8.1 / L8.2):
//   - serv_rv32i_core  : RV32I CPU core (clean-room, RV32I + Zifencei semantics)
//   - servile_ram_if   : Servile wrapper RF/RAM byte-gather/scatter adapter
//   - GPIO peripheral  : 1-bit output latch (memory-mapped store window)
//
// External contract (L3 / L9.top_ports):
//   i_clk, i_rst (sync active-high), o_gpio, i_gpio,
//   o_sram_addr[9:0], o_sram_data[7:0], i_sram_data[7:0],
//   o_sram_we, o_sram_cyc, o_sram_wdata[7:0], i_sram_rdata[7:0]
//
// Note on duplicate SRAM data ports: L3 documents the write port as
//   "o_sram_data (or o_sram_wdata)" and the read port as
//   "i_sram_data (or i_sram_rdata)". The L9 extraction promoted BOTH alias
//   names; to honour the extracted contract this top exposes all four. The two
//   write aliases carry the same byte; the two read aliases are OR-tied so the
//   external SRAM may drive either.
//
// Clean-room implementation. Single clock, synchronous active-high reset.

module subservient #(
    parameter integer memsize  = 1024,
    parameter [31:0]  RESET_PC = 32'h00000000,
    parameter integer WITH_CSR = 1
) (
    input  wire        i_clk,
    input  wire        i_rst,
    // GPIO
    output wire        o_gpio,
    input  wire        i_gpio,
    // external SRAM bus (I-mem + D-mem + RF shared) — byte-wide, 10-bit addr
    output wire [9:0]  o_sram_addr,
    output wire [7:0]  o_sram_data,    // write data (alias of o_sram_wdata)
    input  wire [7:0]  i_sram_data,    // read data (alias of i_sram_rdata)
    output wire        o_sram_we,
    output wire        o_sram_cyc,
    output wire [7:0]  o_sram_wdata,   // write data (alias of o_sram_data)
    input  wire [7:0]  i_sram_rdata    // read data (alias of i_sram_data)
);

    localparam integer AW = 10;  // memsize=1024 -> 10-bit byte address

    // core <-> servile word bus
    wire [AW-1:0] core_addr;
    wire [31:0]   core_wdata;
    wire [31:0]   core_rdata;
    wire          core_we;
    wire          core_re;
    wire [3:0]    core_be;
    wire          core_cyc;

    // GPIO strobe from core
    wire          gpio_we;
    wire [7:0]    gpio_wdata;

    // merged external read bus (either alias may be driven by external SRAM)
    wire [7:0]    sram_rdata_merged = i_sram_data | i_sram_rdata;

    // internal byte SRAM bus from servile adapter
    wire [AW-1:0] sram_addr_int;
    wire [7:0]    sram_wdata_int;
    wire          sram_we_int;
    wire          sram_cyc_int;

    // word-access completion handshake (servile -> core)
    wire          core_ack;

    // CPU core: a read is a "memory access cycle" (fetch or load); we present
    // re|we to the servile adapter as a single cyc.
    serv_rv32i_core #(
        .AW       (AW),
        .RESET_PC (RESET_PC)
    ) u_core (
        .i_clk        (i_clk),
        .i_rst        (i_rst),
        .o_mem_addr   (core_addr),
        .o_mem_wdata  (core_wdata),
        .i_mem_rdata  (core_rdata),
        .i_mem_ack    (core_ack),
        .o_mem_we     (core_we),
        .o_mem_re     (core_re),
        .o_mem_be     (core_be),
        .o_mem_cyc    (core_cyc),
        .o_gpio_we    (gpio_we),
        .o_gpio_wdata (gpio_wdata)
    );

    // Servile RF/RAM byte adapter
    servile_ram_if #(
        .AW (AW)
    ) u_servile (
        .i_clk        (i_clk),
        .i_rst        (i_rst),
        .i_core_addr  (core_addr),
        .i_core_wdata (core_wdata),
        .o_core_rdata (core_rdata),
        .i_core_we    (core_we),
        .i_core_re    (core_re),
        .i_core_be    (core_be),
        .i_core_cyc   (core_cyc),
        .o_core_ack   (core_ack),
        .o_sram_addr  (sram_addr_int),
        .o_sram_wdata (sram_wdata_int),
        .i_sram_rdata (sram_rdata_merged),
        .o_sram_we    (sram_we_int),
        .o_sram_cyc   (sram_cyc_int)
    );

    // GPIO output latch (1 pin per L3 default)
    reg gpio_q;
    always @(posedge i_clk) begin
        if (i_rst)        gpio_q <= 1'b0;
        else if (gpio_we) gpio_q <= gpio_wdata[0];
    end
    assign o_gpio = gpio_q;

    // drive external SRAM bus (both write aliases carry the same byte)
    assign o_sram_addr  = sram_addr_int;
    assign o_sram_data  = sram_wdata_int;
    assign o_sram_wdata = sram_wdata_int;
    assign o_sram_we    = sram_we_int;
    assign o_sram_cyc   = sram_cyc_int;

    // i_gpio is an optional input (L3); reserved for future bidirectional GPIO.
    // Tie into an unused-signal guard so lint does not flag it as dangling while
    // keeping it in the port list per the extracted L9 contract.
    wire _unused_i_gpio = i_gpio;

endmodule
