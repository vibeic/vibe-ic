module TopModule (
  input  [99:0] in,
  output [99:0] out_both,
  output [99:0] out_any,
  output [99:0] out_different
);

  // out_both[i] = in[i] & in[i+1]; out_both[99]=0 (no left neighbour)
  assign out_both = in & {1'b0, in[99:1]};

  // out_any[i] = in[i] | in[i-1]; out_any[0]=0 (no right neighbour)
  assign out_any = in | {in[98:0], 1'b0};

  // out_different[i] = in[i] ^ in[(i+1) mod 100] (wrap around)
  assign out_different = in ^ {in[0], in[99:1]};

endmodule
