module TopModule (
  input  [2:0] in,
  output [1:0] out
);
  // Count the number of set bits in in (0..3).
  assign out = in[0] + in[1] + in[2];
endmodule
