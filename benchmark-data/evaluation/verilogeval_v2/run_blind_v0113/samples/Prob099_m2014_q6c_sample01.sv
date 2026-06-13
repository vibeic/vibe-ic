module TopModule(
    input  [5:0] y,
    input        w,
    output       Y1,
    output       Y3
);
    // One-hot states: y[0]=A, y[1]=B, y[2]=C, y[3]=D, y[4]=E, y[5]=F
    // Y1 = next-state input of y[1] (state B): B entered from A on w=0.
    assign Y1 = y[0] & ~w;
    // Y3 = next-state input of y[3] (state D): D entered from
    //   B(w=1), C(w=1), E(w=1).
    assign Y3 = (y[1] | y[2] | y[4]) & w;
endmodule
