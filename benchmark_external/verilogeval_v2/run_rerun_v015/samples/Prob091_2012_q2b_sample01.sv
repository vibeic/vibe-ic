module TopModule (
  input  [5:0] y,
  input        w,
  output       Y1,
  output       Y3
);

  // One-hot state assignment: y[5:0] = 000001(A),000010(B),000100(C),
  // 001000(D),010000(E),100000(F).  So A=y[0],B=y[1],C=y[2],D=y[3],
  // E=y[4],F=y[5].
  // Y1 = next-state input of flip-flop y[1] (state B): only A --1--> B.
  // Y3 = next-state input of flip-flop y[3] (state D): B,C,E,F all --0--> D.

  assign Y1 = y[0] & w;
  assign Y3 = (y[1] | y[2] | y[4] | y[5]) & ~w;

endmodule
