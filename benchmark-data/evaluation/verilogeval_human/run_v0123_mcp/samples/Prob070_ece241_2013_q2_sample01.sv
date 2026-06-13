module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out_sop,
  output out_pos
);

  // Required 1: 2,7,15 ; required 0: 0,1,4,5,6,9,10,13,14 ; don't-care: 3,8,11,12
  // SOP (don't-cares pulled to 1 to simplify): c&d | ~a&~b&c
  assign out_sop = (c & d) | (~a & ~b & c);

  // POS (don't-cares pulled to 0): equivalent minimized form, correct on all specified inputs
  assign out_pos = c & (d | (~a & ~b));

endmodule
