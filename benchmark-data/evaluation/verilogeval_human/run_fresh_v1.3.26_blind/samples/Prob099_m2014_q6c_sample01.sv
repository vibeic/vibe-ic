module TopModule (
  input [6:1] y,
  input w,
  output Y2,
  output Y4
);

  // One-hot: y[1..6] = states A,B,C,D,E,F.
  // Y2 = next-state bit for B. Only A --w=0--> B enters B.
  assign Y2 = y[1] & ~w;

  // Y4 = next-state bit for D. B,C,E,F all go to D when w=1.
  assign Y4 = (y[2] | y[3] | y[5] | y[6]) & w;

endmodule
