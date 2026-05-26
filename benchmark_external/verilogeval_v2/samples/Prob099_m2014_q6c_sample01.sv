module TopModule (
  input  [5:0] y,
  input  w,
  output Y1,
  output Y3
);
  // One-hot: y[0]=A y[1]=B y[2]=C y[3]=D y[4]=E y[5]=F
  // Y1 = next-state input of y[1] (state B): only A --w=0--> B
  assign Y1 = y[0] & ~w;
  // Y3 = next-state input of y[3] (state D): B--1-->D, C--1-->D, E--1-->D, F--1-->D
  assign Y3 = (y[1] | y[2] | y[4] | y[5]) & w;
endmodule
