module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out_sop,
  output out_pos
);

  // {a,b,c,d} with a as MSB.
  // minterms (1): 2, 7, 15
  // maxterms (0): 0,1,4,5,6,9,10,13,14
  // don't care: 3,8,11,12
  //
  // SOP (using don't-cares to minimize):
  //   2 = 0010, 3(dc)=0011 -> ~a~bc  (covers 2,3)
  //   7 = 0111, 15=1111, 11(dc)=1011 -> c d (covers 7,15,11) and with b? 7=0111,15=1111 -> bcd; 11=1011 also c d ->  cd covers 3,7,11,15
  //   Use: ~a~bc | cd
  assign out_sop = (~a & ~b & c) | (c & d);

  // POS (product of sums): out=0 for maxterms.
  // Group zeros with don't cares.
  //   out_pos = c & (a | ~b | d)? derive equivalently.
  // Equivalent function: out = (~a&~b&c) | (c&d). Express as POS.
  //   out = c & (~a&~b | d) = c & ( (~a | d) & (~b | d) )
  assign out_pos = c & (~a | d) & (~b | d);

endmodule
