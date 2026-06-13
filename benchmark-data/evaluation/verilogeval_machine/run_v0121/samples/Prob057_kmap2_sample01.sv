module TopModule (
  input a,
  input b,
  input c,
  input d,
  output out
);
  // out is 1 if any of:
  //   c and b both 0
  //   d and a both 0
  //   a,c,d all 1
  //   b,c,d all 1
  assign out = (~c & ~b) | (~d & ~a) | (a & c & d) | (b & c & d);
endmodule
