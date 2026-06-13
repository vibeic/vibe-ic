module TopModule (
  input  [7:0] in,
  output [7:0] out
);
  // Reverse the bit order: out[i] = in[7-i].
  assign out = {in[0], in[1], in[2], in[3], in[4], in[5], in[6], in[7]};
endmodule
