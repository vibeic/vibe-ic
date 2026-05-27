module TopModule (
  input  x,
  input  y,
  output z
);
  // From waveform: z = 1 when x == y, i.e. z = x XNOR y
  assign z = ~(x ^ y);
endmodule
