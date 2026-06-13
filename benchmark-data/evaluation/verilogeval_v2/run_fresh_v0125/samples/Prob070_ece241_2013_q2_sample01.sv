module TopModule (
  input  a,
  input  b,
  input  c,
  input  d,
  output out_sop,
  output out_pos
);
  // n = {a,b,c,d}, a is MSB. ones: 2,7,15. dc: 3,8,11,12.
  // SOP: c&d  (covers 7,15 + dc 3,11)  |  ~a&~b&c (covers 2 + dc 3)
  assign out_sop = (c & d) | (~a & ~b & c);
  // POS (same function on defined inputs): c & (d | ~a) & (d | ~b)
  assign out_pos = c & (d | ~a) & (d | ~b);
endmodule
