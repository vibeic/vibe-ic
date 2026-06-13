module TopModule (
  input  x,
  input  y,
  output z
);
  // From the waveform: z=1 when x==y, z=0 when x!=y => XNOR
  assign z = ~(x ^ y);
endmodule
