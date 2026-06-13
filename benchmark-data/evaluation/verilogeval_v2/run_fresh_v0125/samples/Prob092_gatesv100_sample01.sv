module TopModule (
  input  [99:0] in,
  output [99:0] out_both,
  output [99:0] out_any,
  output [99:0] out_different
);

  // out_both[i] = in[i] & in[i+1] (left neighbour = higher index); top bit = 0
  assign out_both      = in & {1'b0, in[99:1]};

  // out_any[i] = in[i] | in[i-1] (right neighbour = lower index); bit0 = 0
  // boundary-bit fixed by placement: out_any[0] has no right neighbour -> 0
  assign out_any[99:1] = in[99:1] | in[98:0];
  assign out_any[0]    = 1'b0;

  // out_different[i] = in[i] ^ in[i+1], wrapping (in[99] left neighbour = in[0])
  assign out_different = in ^ {in[0], in[99:1]};

endmodule
