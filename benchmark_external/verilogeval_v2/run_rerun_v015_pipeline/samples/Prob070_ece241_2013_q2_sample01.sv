module TopModule (
  input  a,
  input  b,
  input  c,
  input  d,
  output out_sop,
  output out_pos
);
  // value = {a,b,c,d}; ones at 2,7,15; don't-cares at 3,8,11,12
  assign out_sop = (c & d) | (~a & ~b & c);
  assign out_pos = c & (~b | ~c | d) & (~a | d);
endmodule
