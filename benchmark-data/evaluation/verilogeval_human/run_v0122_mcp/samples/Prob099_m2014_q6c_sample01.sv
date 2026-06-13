// One-hot next-state logic by inspection.
// States: y[1]=A, y[2]=B, y[3]=C, y[4]=D, y[5]=E, y[6]=F.
// Y2 = next input of y[2] (B): incoming = A on w=0.
// Y4 = next input of y[4] (D): incoming = B,C,E,F on w=1.
module TopModule (
  input [6:1] y,
  input w,
  output Y2,
  output Y4
);

  assign Y2 = y[1] & ~w;
  assign Y4 = (y[2] | y[3] | y[5] | y[6]) & w;

endmodule
