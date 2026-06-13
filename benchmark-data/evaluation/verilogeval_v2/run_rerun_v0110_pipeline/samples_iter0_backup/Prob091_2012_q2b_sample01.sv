module TopModule (
  input  [5:0] y,
  input        w,
  output       Y1,
  output       Y3
);
  // y[0]=A y[1]=B y[2]=C y[3]=D y[4]=E y[5]=F
  // Into B: A --w=1--> B
  assign Y1 = y[0] & w;
  // Into D: B--0, C--0, E--0, F--0
  assign Y3 = (y[1] & ~w) | (y[2] & ~w) | (y[4] & ~w) | (y[5] & ~w);
endmodule
