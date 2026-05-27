module TopModule (
  input  a,
  input  b,
  input  c,
  input  d,
  output out_sop,
  output out_pos
);
  // number = {a,b,c,d}, a is MSB
  assign out_sop = (b & c & d) | (~a & ~b & c);
  assign out_pos = c & (~a | d) & (~b | d);
endmodule
