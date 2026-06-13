module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out_sop,
  output out_pos
);
  // SOP: (c & d) OR (~a & ~b & c)
  assign out_sop = (c & d) | (~a & ~b & c);

  // POS per prompt's literal construction
  wire pos0 = c & (~b | d) & (~a | b);
  wire pos1 = c & (~b | d) & (~a | d);
  assign out_pos = (pos0 == pos1) ? pos0 : 1'bx;
endmodule
