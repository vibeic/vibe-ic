module TopModule (
  input  [5:0] y,
  input        w,
  output       Y1,
  output       Y3
);
  // One-hot states: y[0]=A, y[1]=B, y[2]=C, y[3]=D, y[4]=E, y[5]=F
  // Y1 = next-state input of y[1] (state B). Who transitions into B?
  //   A --1--> B   => Y1 = y[0] & w
  assign Y1 = y[0] & w;

  // Y3 = next-state input of y[3] (state D). Who transitions into D?
  //   B --0--> D, C --0--> D, E --0--> D, F --0--> D
  assign Y3 = (y[1] & ~w) | (y[2] & ~w) | (y[4] & ~w) | (y[5] & ~w);
endmodule
