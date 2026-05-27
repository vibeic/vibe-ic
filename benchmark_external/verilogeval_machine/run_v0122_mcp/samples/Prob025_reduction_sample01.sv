// Prob025_reduction — 8-bit XOR reduction (odd parity).
module TopModule (
  input [7:0] in,
  output parity
);

  assign parity = ^in;

endmodule
