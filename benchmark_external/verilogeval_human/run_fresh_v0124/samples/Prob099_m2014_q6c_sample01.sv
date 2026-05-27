module TopModule (
  input [6:1] y,
  input w,
  output Y2,
  output Y4
);

  // One-hot: A=y[1] B=y[2] C=y[3] D=y[4] E=y[5] F=y[6]
  // Y2 = input to state B: only A --w=0--> B
  assign Y2 = y[1] & ~w;

  // Y4 = input to state D: B--1-->D, C--1-->D, E--1-->D, F--1-->D
  assign Y4 = (y[2] & w) | (y[3] & w) | (y[5] & w) | (y[6] & w);

endmodule
