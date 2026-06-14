// subservient_props.sv
// GENERATED — formal property module for the subservient SoC.
//
// Properties derived from L2/L3 reset & bus semantics (no reference RTL read):
//   P1 (reset → no write): one cycle after a synchronous active-high i_rst,
//       the external SRAM write-enable is deasserted.
//   P2 (reset → gpio low): one cycle after reset, the GPIO output is 0.
//   P3 (bus safety): the external SRAM bus never asserts o_sram_we without
//       o_sram_cyc (no stray write strobe outside a bus cycle).
//
// Written in the yosys-friendly clocked-always immediate-assertion idiom
// (using $past for the one-cycle-after antecedent). Bound via `bind`.
// Proven with SymbiYosys k-induction.

module subservient_props (
    input wire        i_clk,
    input wire        i_rst,
    input wire        o_gpio,
    input wire        o_sram_we,
    input wire        o_sram_cyc
);

    reg past_valid = 1'b0;
    always @(posedge i_clk) past_valid <= 1'b1;

    always @(posedge i_clk) begin
        // P1: reset in the previous cycle => write-enable now low
        if (past_valid && $past(i_rst))
            a_reset_clears: assert (!o_sram_we);

        // P2: reset in the previous cycle => gpio now low
        if (past_valid && $past(i_rst))
            a_reset_gpio: assert (o_gpio == 1'b0);

        // P3: a write strobe always coincides with a bus cycle
        a_we_implies_cyc: assert (!o_sram_we || o_sram_cyc);
    end

endmodule

// bind the property module onto the chip top
bind subservient subservient_props u_props (
    .i_clk      (i_clk),
    .i_rst      (i_rst),
    .o_gpio     (o_gpio),
    .o_sram_we  (o_sram_we),
    .o_sram_cyc (o_sram_cyc)
);
