module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out_sop,
  output out_pos
);

  // a is MSB, d is LSB. on-set minterms: 2 (0010), 7 (0111), 15 (1111)
  // don't-cares: 3 (0011), 8 (1000), 11 (1011), 12 (1100)
  // Minimum SOP using don't cares:
  //   c&d  -> covers 3,7,11,15 (3,11 are dc, 7,15 are on)
  //   ~a&~b&c&~d -> covers 2
  assign out_sop = (c & d) | (~a & ~b & c & ~d);
  // Minimum POS (same function, complement-form). Off-set: 0,1,4,5,6,9,10,13,14
  //   out = c & (d | (~a & ~b & ~d))  -> product of sums
  assign out_pos = c & (d | (~a & ~b));

endmodule
