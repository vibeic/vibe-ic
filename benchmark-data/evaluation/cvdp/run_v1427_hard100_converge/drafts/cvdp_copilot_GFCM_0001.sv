// ============================================================================
// glitch_free_mux
// ----------------------------------------------------------------------------
// Glitch-free clock switching multiplexer between two synchronous clocks.
//
//   sel = 0 -> clkout = clk1
//   sel = 1 -> clkout = clk2
//
// Break-before-make protocol (all enable updates on POSITIVE clock edges,
// per specification):
//   * On sel 0 -> 1 : clk1 is disabled on the first posedge of clk1 after
//     the sel change; clk2 is then enabled on the first posedge of clk2
//     after clk1 has been disabled.
//   * On sel 1 -> 0 : clk2 is disabled on the first posedge of clk2 after
//     the sel change; clk1 is then enabled on the first posedge of clk1
//     after clk2 has been disabled.
//
// The two clock-enable registers are cross-coupled so that each clock's
// enable can only assert when the other clock's enable is deasserted,
// guaranteeing the enables are never simultaneously high and therefore the
// output clock switches without glitches (runt pulses).
//
// rst_n is an asynchronous active-low reset: while rst_n = 0 both enables
// are forced low, driving clkout low.
// ============================================================================

module glitch_free_mux (
    input  wire clk1,   // input clock 1 (selected when sel = 0)
    input  wire clk2,   // input clock 2 (selected when sel = 1)
    input  wire sel,    // clock select : 0 -> clk1 , 1 -> clk2
    input  wire rst_n,  // asynchronous active-low reset (clkout low when 0)
    output wire clkout  // glitch-free output clock
);

    // Cross-coupled break-before-make clock enables
    reg clk1_en;
    reg clk2_en;

    // clk1 domain enable: asserts only when clk1 is selected (sel = 0) AND
    // the clk2 path has already been disabled.
    always @(posedge clk1 or negedge rst_n) begin
        if (!rst_n)
            clk1_en <= 1'b0;
        else
            clk1_en <= ~sel & ~clk2_en;
    end

    // clk2 domain enable: asserts only when clk2 is selected (sel = 1) AND
    // the clk1 path has already been disabled.
    always @(posedge clk2 or negedge rst_n) begin
        if (!rst_n)
            clk2_en <= 1'b0;
        else
            clk2_en <= sel & ~clk1_en;
    end

    // Gated-clock output mux: each clock is masked by its own enable.
    // During reset both enables are 0, so clkout is driven low.
    assign clkout = (clk1 & clk1_en) | (clk2 & clk2_en);

endmodule
