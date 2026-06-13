module TopModule (
    input  [5:0] y,
    input        w,
    output       Y1,
    output       Y3
);
    // One-hot: A=y[0] B=y[1] C=y[2] D=y[3] E=y[4] F=y[5]
    // Y1 = next-state y[1] (state B). Only A --1--> B enters B.
    assign Y1 = y[0] & w;
    // Y3 = next-state y[3] (state D). Enter D from B(0), C(0), E(0), F(0).
    assign Y3 = (y[1] & ~w) | (y[2] & ~w) | (y[4] & ~w) | (y[5] & ~w);
endmodule
