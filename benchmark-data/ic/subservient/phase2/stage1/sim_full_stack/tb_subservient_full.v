// SPDX-License-Identifier: Apache-2.0
// tb_subservient_gpio — generic full-stack functional TB (L9 top_ports).
//
// Class-aware verification track = generic_full_stack (subservient is a
// memory-bus CPU/SoC; NO half-duplex single-wire AID contract, so the
// AID reference TB / USB-HID / DE10 qsf correctly SKIP).
//
// This TB models the EXTERNAL shared SRAM (I-mem + D-mem) that L2/L3 say
// is preloaded by tooling before reset release, loads a real RV32I
// program (gpio_bytes.hex) into it, releases the synchronous active-high
// reset, runs the genuine SERV bit-serial core, and checks that the GPIO
// mailbox store reaches o_gpio (functional gate: L7.1.1 blinky-class
// GPIO toggle + L7.1.3 reset/boot).
`timescale 1ns/1ps
`default_nettype none

module tb_subservient_full;

   localparam integer MEMSIZE = 1024;
   localparam integer ADDR_W  = 10;

   reg               clk = 0;
   reg               rst = 1;       // synchronous active-high
   wire [ADDR_W-1:0] sram_addr;
   wire [7:0]        sram_wdata;
   reg  [7:0]        sram_rdata;
   wire              sram_we;
   wire              sram_cyc;
   wire              gpio;

   always #5 clk = ~clk;   // 100 MHz (10 ns) per L9 sky130 target

   // ----- external shared SRAM model (synchronous, 1-cycle read) -----
   reg [7:0] mem [0:MEMSIZE-1];
   integer   i;
   always @(posedge clk) begin
      if (sram_cyc & sram_we)
         mem[sram_addr] <= sram_wdata;
      sram_rdata <= mem[sram_addr];   // registered read
   end

   // ----- DUT: GENERATED chip-top wrapping the REUSED-IP SERV core -----
   subservient
     #(.MEMSIZE(MEMSIZE), .RESET_PC(32'h0), .WITH_CSR(1))
   dut
     (.i_clk        (clk),
      .i_rst        (rst),
      .o_sram_addr  (sram_addr),
      .o_sram_wdata (sram_wdata),
      .i_sram_rdata (sram_rdata),
      .o_sram_we    (sram_we),
      .o_sram_cyc   (sram_cyc),
      .o_gpio       (gpio));

   // ----- observers -----
   integer gpio_writes = 0;
   reg     gpio_seen_1 = 0;
   reg     gpio_seen_0_after_1 = 0;
   reg     prev_gpio = 0;
   integer fetch_seen = 0;

   always @(posedge clk) begin
      if (!rst) begin
         // count GPIO mailbox writes
         if (sram_cyc & sram_we & (sram_addr == (MEMSIZE-1)))
            gpio_writes = gpio_writes + 1;
         // count instruction-region reads (boot fetch from RESET_PC)
         if (sram_cyc & ~sram_we & (sram_addr < 10'd64))
            fetch_seen = fetch_seen + 1;
         // GPIO toggle observation
         if (gpio)               gpio_seen_1 = 1;
         if (gpio_seen_1 & prev_gpio & ~gpio) gpio_seen_0_after_1 = 1;
         prev_gpio <= gpio;
      end
   end

   initial begin
      // preload firmware into external SRAM (tooling/ATE preload per L2/L3)
      for (i = 0; i < MEMSIZE; i = i + 1) mem[i] = 8'h00;
      $readmemh("gpio_bytes.hex", mem);

      // boot: hold reset, then release synchronously (L7.1.3)
      rst = 1;
      repeat (4) @(posedge clk);
      @(negedge clk) rst = 0;

      // run long enough for SERV (bit-serial, ~32 cyc/op) to execute the
      // li/li/sb/xori/li/loop sequence several times and toggle GPIO.
      repeat (60000) @(posedge clk);

      $display("RESULT fetch_reads=%0d gpio_mailbox_writes=%0d gpio_seen_1=%0d gpio_toggled=%0d",
               fetch_seen, gpio_writes, gpio_seen_1, gpio_seen_0_after_1);
      if (fetch_seen > 0 && gpio_writes > 0 && gpio_seen_1 && gpio_seen_0_after_1)
         $display("FUNCTIONAL_PASS subservient GPIO-toggle smoke test");
      else if (fetch_seen > 0 && gpio_writes > 0 && gpio_seen_1)
         $display("FUNCTIONAL_PASS_PARTIAL");
      else
         $display("FUNCTIONAL_FAIL");
      $display("FULL_STACK_TB_DONE");
      $finish;
   end

   // global watchdog
   initial begin
      #2_000_000;
      $display("WATCHDOG_TIMEOUT fetch_reads=%0d gpio_writes=%0d", fetch_seen, gpio_writes);
      $finish;
   end

endmodule
`default_nettype wire
