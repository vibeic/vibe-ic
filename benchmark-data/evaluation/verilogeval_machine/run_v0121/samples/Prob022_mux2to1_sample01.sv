// 1-bit 2-to-1 multiplexer: sel=0 -> a, sel=1 -> b.
module TopModule (
  input a,
  input b,
  input sel,
  output out
);

  assign out = sel ? b : a;

endmodule
