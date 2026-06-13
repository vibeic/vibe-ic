// Prob057_kmap2 — combinational SOP of four product terms.
// out = (~c&~b) | (~d&~a) | (a&c&d) | (b&c&d), per prompt enumeration.
module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out
);

  assign out = (~c & ~b) | (~d & ~a) | (a & c & d) | (b & c & d);

endmodule
