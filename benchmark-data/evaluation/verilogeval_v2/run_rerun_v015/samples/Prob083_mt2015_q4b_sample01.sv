module TopModule (
  input  x,
  input  y,
  output z
);

  // From the waveform z is high when x==y: XNOR
  assign z = ~(x ^ y);

endmodule
