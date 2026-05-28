// SPDX-License-Identifier: Apache-2.0
// Author: Vibe-IC Plugin catalog-glue-author skill  (GENERATED integration glue)
//
// subservient — Minimal SERV-based RV32I SoC : chip-top integration wrapper.
//
// =====================================================================
//  HONEST SOURCE SPLIT (see SOURCE_MANIFEST.md)
//  -------------------------------------------------------------------
//  This module (subservient) + gpio_periph.v are GENERATED: AI-authored
//  from input/docs/L1-L9 spec only. They contain the SoC chip-top port
//  contract (L3), the Wishbone-32 -> external-8-bit-SRAM bridge, the RF
//  SRAM instantiation, and the GPIO peripheral wiring.
//
//  The RV32I CPU itself is REUSED-IP, unmodified upstream:
//    - serv*           (ISC,        github.com/olofk/serv @ release/1.4.0)
//    - servile*        (Apache-2.0, github.com/olofk/serv @ release/1.4.0)
//  The SERV bit-serial RV32I datapath (fetch/decode/ALU/branch/LSU/CSR)
//  is NOT generated here. The "doc->silicon" credit applies ONLY to the
//  GENERATED chip-top + GPIO + bridge below; the SERV core is reported
//  separately and honestly as reused open-source IP.
// =====================================================================
//
//  Top contract (L3):
//    - i_clk        : 1-bit clock (CLOCK_PORT per L9 / openlane_common.tcl)
//    - i_rst        : 1-bit synchronous active-high reset (L2/L3)
//    - SRAM group   : 10-bit byte addr, 8-bit wdata, 8-bit rdata, we, cyc
//                     (external shared I-mem + D-mem, preloaded; L2/L3)
//    - o_gpio       : 1-bit GPIO output (L3, L8.2.4)
//
//  memsize=1024 B (default; L1/L3), reset_polarity=active_high (L2/L3),
//  clock_port=i_clk (L9), sram_interface=generic_8bit_addr_data_we (L3),
//  gpio_pin_count=1 (L3), rf_storage=shared_sram (L2/L8.2.5),
//  isa_extensions=[I,Zifencei] (L2 default), WITH_CSR=1 (L3 default).
//
//  Memory architecture (L2 "single shared SRAM hosts I-mem + D-mem + RF";
//  exact partition is a Plugin choice, R3-permitted):
//    - The instruction/data window is the EXTERNAL SRAM port group (this
//      is what the chip exposes; preloaded by tooling/ATE before reset).
//    - The RF (register file) is hosted in an on-die SRAM macro
//      (serv_rf_ram), the SERV-recommended pairing for a shared-SRAM SoC
//      (servile integration_notes). Both are part of the unified shared
//      memory subsystem; the RF is not separately firmware-addressable.
// -----------------------------------------------------------------------------
`default_nettype none

module subservient
  #(parameter MEMSIZE  = 1024,
    parameter RESET_PC = 32'h00000000,
    parameter WITH_CSR = 1)
   (input  wire        i_clk,
    input  wire        i_rst,        // synchronous active-high

    // External shared SRAM (I-mem + D-mem), 8-bit byte-wide, preloaded
    output wire [9:0]  o_sram_addr,
    output wire [7:0]  o_sram_wdata,
    input  wire [7:0]  i_sram_rdata,
    output wire        o_sram_we,
    output wire        o_sram_cyc,

    // GPIO
    output wire        o_gpio);

   localparam ADDR_W = 10;   // 1024 bytes -> 10-bit byte address

   // --------------------------------------------------------------------
   // servile (REUSED-IP) memory-side Wishbone bus  (32-bit word, byte-sel)
   // --------------------------------------------------------------------
   wire [31:0] wb_mem_adr;
   wire [31:0] wb_mem_dat;
   wire [3:0]  wb_mem_sel;
   wire        wb_mem_we;
   wire        wb_mem_stb;
   wire [31:0] wb_mem_rdt;
   wire        wb_mem_ack;

   // servile extension bus (unused — no MDU; tie ext ack low)
   wire [31:0] wb_ext_adr;
   wire [31:0] wb_ext_dat;
   wire [3:0]  wb_ext_sel;
   wire        wb_ext_we;
   wire        wb_ext_stb;

   // servile RF SRAM interface  (width=2 for rf_width=2*W, W=1; with_csr=1)
   localparam RF_WIDTH = 2;
   localparam RF_AW    = 10;   // $clog2(36*32/2) = $clog2(576) = 10
   wire [RF_AW-1:0]    rf_waddr;
   wire [RF_WIDTH-1:0] rf_wdata;
   wire                rf_wen;
   wire [RF_AW-1:0]    rf_raddr;
   wire [RF_WIDTH-1:0] rf_rdata;
   wire                rf_ren;

   // --------------------------------------------------------------------
   // serv convenience wrapper (REUSED-IP, unmodified upstream)
   //   serv_top + servile_mux + servile_arbiter + serv_rf_ram_if
   // --------------------------------------------------------------------
   servile
     #(.width          (1),
       .reset_pc       (RESET_PC),
       .reset_strategy ("MINI"),
       .sim            (1'b0),
       .debug          (1'b0),
       .with_c         (1'b0),
       .with_csr       (WITH_CSR[0]),
       .with_mdu       (1'b0))
   u_servile
     (.i_clk        (i_clk),
      .i_rst        (i_rst),
      .i_timer_irq  (1'b0),

      // Memory (WB) interface -> external SRAM via the bridge below
      .o_wb_mem_adr (wb_mem_adr),
      .o_wb_mem_dat (wb_mem_dat),
      .o_wb_mem_sel (wb_mem_sel),
      .o_wb_mem_we  (wb_mem_we),
      .o_wb_mem_stb (wb_mem_stb),
      .i_wb_mem_rdt (wb_mem_rdt),
      .i_wb_mem_ack (wb_mem_ack),

      // Extension (WB) interface -> unused (no MDU)
      .o_wb_ext_adr (wb_ext_adr),
      .o_wb_ext_dat (wb_ext_dat),
      .o_wb_ext_sel (wb_ext_sel),
      .o_wb_ext_we  (wb_ext_we),
      .o_wb_ext_stb (wb_ext_stb),
      .i_wb_ext_rdt (32'h0),
      .i_wb_ext_ack (1'b0),

      // RF (SRAM) interface -> on-die RF SRAM macro below
      .o_rf_waddr   (rf_waddr),
      .o_rf_wdata   (rf_wdata),
      .o_rf_wen     (rf_wen),
      .o_rf_raddr   (rf_raddr),
      .i_rf_rdata   (rf_rdata),
      .o_rf_ren     (rf_ren));

   // --------------------------------------------------------------------
   // RF storage (REUSED-IP serv_rf_ram, instantiated by GENERATED glue)
   //   part of the unified shared-memory subsystem (L2/L8.2.5)
   // --------------------------------------------------------------------
   serv_rf_ram
     #(.width    (RF_WIDTH),
       .csr_regs (4))
   u_rf_ram
     (.i_clk   (i_clk),
      .i_waddr (rf_waddr),
      .i_wdata (rf_wdata),
      .i_wen   (rf_wen),
      .i_raddr (rf_raddr),
      .i_ren   (rf_ren),
      .o_rdata (rf_rdata));

   // ====================================================================
   //  GENERATED bridge: servile 32-bit word WB  <->  external 8-bit SRAM
   //
   //  The chip exposes an 8-bit byte-wide SRAM (L3). servile's memory bus
   //  is a 32-bit Wishbone-classic word bus. This FSM serialises each WB
   //  cycle into up to 4 byte accesses (read 4 bytes to assemble rdt;
   //  write the byte lanes selected by wb_mem_sel), then asserts ack.
   //  SERV is bit-serial so the per-word multi-cycle byte latency is well
   //  inside its ~32-cycle-per-op budget (no false path needed; L9.1.4).
   // ====================================================================
   localparam [2:0] B_IDLE = 3'd0,
                    B_B0   = 3'd1,
                    B_B1   = 3'd2,
                    B_B2   = 3'd3,
                    B_B3   = 3'd4,
                    B_B4   = 3'd5,
                    B_ACK  = 3'd6;

   reg [2:0]  bstate;
   reg [9:0]  br_addr;
   reg [7:0]  br_wdata;
   reg        br_we;
   reg        br_cyc;
   reg [31:0] rdt_asm;

   // SERV emits a byte address on o_wb_mem_adr; take the low ADDR_W bits.
   wire [9:0] word_base = wb_mem_adr[9:0];

   always @(posedge i_clk) begin
      if (i_rst) begin
         bstate   <= B_IDLE;
         br_addr  <= 10'b0;
         br_wdata <= 8'b0;
         br_we    <= 1'b0;
         br_cyc   <= 1'b0;
         rdt_asm  <= 32'b0;
      end else begin
         case (bstate)
            B_IDLE: begin
               br_cyc <= 1'b0;
               br_we  <= 1'b0;
               if (wb_mem_stb) begin
                  // launch byte 0
                  br_addr  <= {word_base[9:2], 2'b00};
                  br_wdata <= wb_mem_dat[7:0];
                  br_we    <= wb_mem_we & wb_mem_sel[0];
                  br_cyc   <= 1'b1;
                  bstate   <= B_B0;
               end
            end
            // Registered external SRAM has 1-cycle read latency, and br_addr
            // is itself registered, so the data for the address launched in
            // state N is valid in state N+2 -> captures lag the address by
            // one extra state (byte0 captured in B_B1, …, byte3 in B_B4).
            B_B0: begin
               br_addr      <= {word_base[9:2], 2'b01};
               br_wdata     <= wb_mem_dat[15:8];
               br_we        <= wb_mem_we & wb_mem_sel[1];
               br_cyc       <= 1'b1;
               bstate       <= B_B1;
            end
            B_B1: begin
               rdt_asm[7:0]  <= i_sram_rdata;             // byte 0
               br_addr       <= {word_base[9:2], 2'b10};
               br_wdata      <= wb_mem_dat[23:16];
               br_we         <= wb_mem_we & wb_mem_sel[2];
               br_cyc        <= 1'b1;
               bstate        <= B_B2;
            end
            B_B2: begin
               rdt_asm[15:8]  <= i_sram_rdata;            // byte 1
               br_addr        <= {word_base[9:2], 2'b11};
               br_wdata       <= wb_mem_dat[31:24];
               br_we          <= wb_mem_we & wb_mem_sel[3];
               br_cyc         <= 1'b1;
               bstate         <= B_B3;
            end
            B_B3: begin
               rdt_asm[23:16] <= i_sram_rdata;            // byte 2
               br_cyc         <= 1'b0;
               br_we          <= 1'b0;
               bstate         <= B_B4;
            end
            B_B4: begin
               rdt_asm[31:24] <= i_sram_rdata;            // byte 3
               br_cyc         <= 1'b0;
               br_we          <= 1'b0;
               bstate         <= B_ACK;
            end
            B_ACK: begin
               br_cyc <= 1'b0;
               br_we  <= 1'b0;
               bstate <= B_IDLE;
            end
            default: bstate <= B_IDLE;
         endcase
      end
   end

   assign wb_mem_ack = (bstate == B_ACK);
   assign wb_mem_rdt = rdt_asm;

   // External SRAM port group is driven by the bridge.
   assign o_sram_addr  = br_addr;
   assign o_sram_wdata = br_wdata;
   assign o_sram_we    = br_we;
   assign o_sram_cyc   = br_cyc;

   // --------------------------------------------------------------------
   // GPIO peripheral (GENERATED) — snoops the byte write bus
   // --------------------------------------------------------------------
   gpio_periph
     #(.MEMSIZE (MEMSIZE),
       .ADDR_W  (ADDR_W))
   u_gpio
     (.i_clk   (i_clk),
      .i_rst   (i_rst),
      .i_addr  (br_addr),
      .i_wdata (br_wdata),
      .i_we    (br_we),
      .i_cyc   (br_cyc),
      .o_gpio  (o_gpio));

   // lint tie-offs for legitimately-unused upper word-address + ext bus
   wire _unused = |{wb_mem_adr[31:10], wb_ext_adr, wb_ext_dat,
                    wb_ext_sel, wb_ext_we, wb_ext_stb, 1'b0};

endmodule

`default_nettype wire
