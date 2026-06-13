module TopModule (
  input [6:1] y,
  input w,
  output Y2,
  output Y4
);
  // One-hot: y[1]=A, y[2]=B, y[3]=C, y[4]=D, y[5]=E, y[6]=F
  // Y2 = next y[2] (state B): only A --w=0--> B
  assign Y2 = y[1] & ~w;
  // Y4 = next y[4] (state D): B,C,E,F all on w=1 --> D
  assign Y4 = (y[2] | y[3] | y[5] | y[6]) & w;
endmodule
