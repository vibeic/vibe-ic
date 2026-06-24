module TopModule (
  input [6:1] y,
  input w,
  output Y2,
  output Y4
);

  // One-hot, 1-indexed port [6:1]: y[1]=A, y[2]=B, y[3]=C, y[4]=D, y[5]=E, y[6]=F.
  // Y2 = next-state bit for y[2] (state B) = OR of every edge entering B.
  //   B is entered only from A on w=0.
  assign Y2 = y[1] & ~w;

  // Y4 = next-state bit for y[4] (state D) = OR of every edge entering D.
  //   D is entered from B,C,E,F on w=1.
  assign Y4 = (y[2] | y[3] | y[5] | y[6]) & w;

endmodule
