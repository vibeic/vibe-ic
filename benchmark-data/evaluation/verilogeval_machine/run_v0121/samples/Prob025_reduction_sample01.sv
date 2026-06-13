// 8-bit parity: XOR reduction of in.
module TopModule (
  input [7:0] in,
  output parity
);

  assign parity = ^in;

endmodule
