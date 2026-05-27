module TopModule (
  input x,
  input y,
  output z
);

  // Waveform mapping: (0,0)->1 (1,0)->0 (0,1)->0 (1,1)->1  => z = ~(x ^ y)
  assign z = ~(x ^ y);

endmodule
