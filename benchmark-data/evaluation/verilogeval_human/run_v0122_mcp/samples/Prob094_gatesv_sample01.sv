// 4-bit neighbour relations.
//  out_both[i]      = in[i] & in[i+1]           (left = higher index), i=0..2
//  out_any[i]       = in[i] | in[i-1]           (right = lower index),  i=1..3
//  out_different[i] = in[i] ^ in[(i+1) mod 4]   (left, wrapping),       i=0..3
module TopModule (
  input  [3:0] in,
  output [2:0] out_both,
  output [3:1] out_any,
  output [3:0] out_different
);

  assign out_both      = in[2:0] & in[3:1];
  assign out_any       = in[3:1] | in[2:0];
  assign out_different = in ^ {in[0], in[3:1]};

endmodule
