module TopModule (
  input [99:0] in,
  output [98:0] out_both,
  output [99:1] out_any,
  output [99:0] out_different
);
  // out_both[i] = in[i] & in[i+1]   (left neighbour = higher index), i in 0..98
  assign out_both = in[98:0] & in[99:1];
  // out_any[i] = in[i] | in[i-1]    (right neighbour = lower index), i in 1..99
  assign out_any = in[99:1] | in[98:0];
  // out_different[i] = in[i] ^ in[(i+1) mod 100] (left, wrapping)
  assign out_different = in ^ {in[0], in[99:1]};
endmodule
