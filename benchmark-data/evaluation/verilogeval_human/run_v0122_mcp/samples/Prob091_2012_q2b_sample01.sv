// One-hot next-state logic by inspection.
// States: y0=A, y1=B, y2=C, y3=D, y4=E, y5=F.
// Y1 = next input of y[1] (B): incoming = A on w=1.
// Y3 = next input of y[3] (D): incoming = B,C,E,F on w=0.
module TopModule (
  input [5:0] y,
  input w,
  output Y1,
  output Y3
);

  assign Y1 = y[0] & w;
  assign Y3 = (y[1] | y[2] | y[4] | y[5]) & ~w;

endmodule
