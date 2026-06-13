// Waveform decode: z is high iff x == y, i.e. z = ~(x ^ y) (XNOR).
module TopModule (
  input x,
  input y,
  output z
);

  assign z = ~(x ^ y);

endmodule
