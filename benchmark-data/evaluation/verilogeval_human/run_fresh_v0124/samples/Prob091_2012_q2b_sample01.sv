module TopModule (
  input [5:0] y,
  input w,
  output Y1,
  output Y3
);

  // One-hot: A=y[0] B=y[1] C=y[2] D=y[3] E=y[4] F=y[5]
  // Y1 = input to state B: only A --w=1--> B
  assign Y1 = y[0] & w;

  // Y3 = input to state D: B--0-->D, C--0-->D, E--0-->D, F--0-->D
  assign Y3 = (y[1] & ~w) | (y[2] & ~w) | (y[4] & ~w) | (y[5] & ~w);

endmodule
