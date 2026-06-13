module TopModule (
    input  [5:0] y,
    input        w,
    output       Y1,
    output       Y3
);
    // One-hot states: y[0]=A, y[1]=B, y[2]=C, y[3]=D, y[4]=E, y[5]=F.
    // Y1 = next-state input of FF for state B. Into B: A on w=1.
    assign Y1 = y[0] & w;

    // Y3 = next-state input of FF for state D. Into D on w=0 from B,C,E,F.
    assign Y3 = (y[1] | y[2] | y[4] | y[5]) & ~w;
endmodule
