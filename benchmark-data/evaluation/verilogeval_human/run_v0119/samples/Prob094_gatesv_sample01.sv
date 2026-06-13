module TopModule (
  input [3:0] in,
  output [2:0] out_both,
  output [3:1] out_any,
  output [3:0] out_different
);
    // out_both[i] = in[i] & in[i+1], i = 0..2
    assign out_both = in[2:0] & in[3:1];
    // out_any[i] = in[i] | in[i-1], i = 1..3
    assign out_any = in[3:1] | in[2:0];
    // out_different[i] = in[i] ^ in[i+1] (left neighbour, wrapping at top)
    assign out_different = in ^ {in[0], in[3:1]};
endmodule
