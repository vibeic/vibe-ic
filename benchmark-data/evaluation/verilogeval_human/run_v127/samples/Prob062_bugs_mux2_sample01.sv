module TopModule (
  input sel,
  input [7:0] a,
  input [7:0] b,
  output reg [7:0] out
);

  // Bug in original: scalar output and single-bit AND/OR on 8-bit operands.
  // Fixed: full-width 2-to-1 select.
  always @(*)
    out = sel ? b : a;

endmodule
