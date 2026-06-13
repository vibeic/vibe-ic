// Prob067_countslow — 4-bit decade counter with slow enable.
//
// Reset mode: the prose calls reset "asynchronous", but the STRUCTURAL
// description is an always block "triggered on the rising edge of the clock
// signal" that "first checks the reset signal". A reset checked inside a
// posedge-clk-only block (NOT named in the sensitivity list) is SYNCHRONOUS.
// v0.1.22 skill: reset STRUCTURE beats the adjective -> synchronous reset.
//
// Counting: increment only when slowena is high; wraps 9 -> 0 (decade).
module TopModule (
  input clk,
  input slowena,
  input reset,
  output reg [3:0] q
);

  always @(posedge clk) begin
    if (reset)
      q <= 4'd0;            // synchronous reset (checked inside posedge-clk block)
    else if (slowena) begin
      if (q == 4'd9)
        q <= 4'd0;          // decade wrap
      else
        q <= q + 4'd1;
    end
    // slowena low: hold q
  end

endmodule
