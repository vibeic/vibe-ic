module TopModule (
  input [5:0] y,
  input w,
  output Y1,
  output Y3
);

  // Ordinal "Nth bit" of y -> y[N-1] (1-indexed prose mapped into the [5:0] header).
  assign Y1 = y[0] & w;
  assign Y3 = (y[1] | y[2] | y[4] | y[5]) & ~w;

endmodule
