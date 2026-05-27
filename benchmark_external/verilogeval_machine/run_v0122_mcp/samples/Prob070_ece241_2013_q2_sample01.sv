// Prob070_ece241_2013_q2 — SOP and POS outputs.
// out_sop = c&d | ~a&~b&c
// out_pos via two POS forms; output 'x where they disagree (per prompt).
module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out_sop,
  output out_pos
);

  wire pos0 = c & (~b | d) & (~a | b);
  wire pos1 = c & (~b | d) & (~a | d);

  assign out_sop = (c & d) | (~a & ~b & c);
  assign out_pos = (pos0 == pos1) ? pos0 : 1'bx;

endmodule
