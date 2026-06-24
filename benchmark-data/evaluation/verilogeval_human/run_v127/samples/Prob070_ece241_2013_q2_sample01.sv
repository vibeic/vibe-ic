// program-SOLVED minimum SOP / POS with don't-cares (Quine-McCluskey,
// host-verified against the stated ON/OFF sets); deterministic, no AI.
module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out_sop,
  output out_pos
);
  assign out_sop = (c&d) | (~a&~b&c);
  assign out_pos = (c) & (~b|d) & (~a|b);
endmodule
