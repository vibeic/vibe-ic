// 100-bit neighbour relations.
//  out_both[i]      = in[i] & in[i+1]            (left = higher index), i=0..98
//  out_any[i]       = in[i] | in[i-1]            (right = lower index),  i=1..99
//  out_different[i] = in[i] ^ in[(i+1) mod 100]  (left, wrapping),       i=0..99
module TopModule (
  input  [99:0] in,
  output [98:0] out_both,
  output [99:1] out_any,
  output [99:0] out_different
);

  assign out_both      = in[98:0] & in[99:1];
  assign out_any       = in[99:1] | in[98:0];
  assign out_different = in ^ {in[0], in[99:1]};

endmodule
