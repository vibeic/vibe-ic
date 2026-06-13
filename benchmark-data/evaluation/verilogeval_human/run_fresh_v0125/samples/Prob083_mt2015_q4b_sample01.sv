module TopModule (
  input x,
  input y,
  output z
);

  // Per the simulation waveform, z is high exactly when x equals y.
  assign z = ~(x ^ y);

endmodule
