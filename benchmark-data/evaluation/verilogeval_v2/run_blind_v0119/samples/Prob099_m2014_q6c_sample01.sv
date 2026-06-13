module TopModule (
    input  [5:0] y,
    input        w,
    output       Y1,
    output       Y3
);
    // One-hot states: y[0]=A, y[1]=B, y[2]=C, y[3]=D, y[4]=E, y[5]=F.
    // State diagram (w value labels the transition):
    //   A--0-->B  B--0-->C B--1-->D  C--0-->E C--1-->D
    //   D--0-->F  D--1-->A E--1-->D  F--1-->D ...
    // Y1 = next-state input of FF for state B. Into B: A on w=0.
    assign Y1 = y[0] & ~w;

    // Y3 = next-state input of FF for state D. Into D on w=1 from B,C,E,F.
    assign Y3 = (y[1] | y[2] | y[4] | y[5]) & w;
endmodule
