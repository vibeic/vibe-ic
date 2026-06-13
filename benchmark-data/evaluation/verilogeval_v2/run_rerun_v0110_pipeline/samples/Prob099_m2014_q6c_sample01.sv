module TopModule (
  input  [5:0] y,
  input        w,
  output       Y1,
  output       Y3
);
  // y[0]=A y[1]=B y[2]=C y[3]=D y[4]=E y[5]=F
  // Into B (y[1]): A --w=0--> B
  assign Y1 = y[0] & ~w;
  // Into D (y[3]): B--1, C--1, E--1, F--1
  assign Y3 = (y[1] | y[2] | y[4] | y[5]) & w;
endmodule
