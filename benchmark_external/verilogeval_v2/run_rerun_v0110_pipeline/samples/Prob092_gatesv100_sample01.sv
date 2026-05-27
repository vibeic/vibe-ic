module TopModule (
  input  [99:0] in,
  output [99:0] out_both,
  output [99:0] out_any,
  output [99:0] out_different
);
  // out_both[i] = in[i] & in[i+1] (left = higher index); out_both[99] = 0
  assign out_both      = {1'b0, in[99:1]} & in;
  // out_any[i] = in[i] | in[i-1] (right = lower index); out_any[0] = 0
  // bit0 forced to 0 (no right neighbour); bits 99:1 = in[j]|in[j-1]
  assign out_any       = {(in[99:1] | in[98:0]), 1'b0};
  // out_different[i] = in[i] ^ in[i+1], wrap: in[99] left neighbour = in[0]
  assign out_different = in ^ {in[0], in[99:1]};
endmodule
