module TopModule (
  input  a,
  input  b,
  input  c,
  input  d,
  output out_sop,
  output out_pos
);

  // {a,b,c,d}, a=MSB. ones: 2(0010),7(0111),15(1111).
  // zeros: 0,1,4,5,6,9,10,13,14.  don't-cares: 3,8,11,12.
  // K-map: c&d covers 7,15 (+dc 3,11). minterm 2 merges only with dc 3
  //   -> term ~a&~b&c (covers 0010,0011). 6(0110) must stay 0.
  // out = c&d | (~a&~b&c) = c & (d | (~a&~b))
  //     = c & (d|~a) & (d|~b)  [POS form]
  assign out_sop = (c & d) | (~a & ~b & c);
  assign out_pos = c & (d | ~a) & (d | ~b);

endmodule
