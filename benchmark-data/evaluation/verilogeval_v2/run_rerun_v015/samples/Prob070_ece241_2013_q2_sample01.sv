module TopModule (
  input  a,
  input  b,
  input  c,
  input  d,
  output out_sop,
  output out_pos
);

  // Numbering: a is MSB ... d is LSB (a,b,c,d -> 7 = 0,1,1,1)
  // Minterms (output 1): 2, 7, 15
  //   2  = 0010 -> a'b'cd'
  //   7  = 0111 -> a'bcd
  //   15 = 1111 -> abcd
  // Don't cares: 3, 8, 11, 12
  // Off-set: 0,1,4,5,6,9,10,13,14
  //
  // SOP (with don't cares):
  //   group {2,3} -> a'b'c
  //   group {7,15} -> bcd  (covers 7=0111,15=1111, and dc 3? 3=0011 no; uses 7,15 only need cd & b -> bcd)
  //   actually minimal: out = cd + a'b'c
  assign out_sop = (c & d) | (~a & ~b & c);

  // POS (with don't cares): out_pos = c & (a' + b' + d) ... derive minimal POS
  //   Maxterms (output 0): 0,1,4,5,6,9,10,13,14
  //   With dc, minimal POS: out = c (b' + d)
  assign out_pos = c & (~b | d);

endmodule
