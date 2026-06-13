module TopModule (
    input  [3:0] x,
    output       f
);
    // x[1]=x[0], x[2]=x[1], x[3]=x[2], x[4]=x[3] (1-indexed map of m2014_q3)
    // f = (~x1 & x3) | (x2 & x4)
    assign f = (~x[0] & x[2]) | (x[1] & x[3]);
endmodule
