// Prob022_mux2to1 — 1-bit 2-to-1 mux. sel=1 -> b, sel=0 -> a.
module TopModule (
  input a,
  input b,
  input sel,
  output out
);

  assign out = sel ? b : a;

endmodule
