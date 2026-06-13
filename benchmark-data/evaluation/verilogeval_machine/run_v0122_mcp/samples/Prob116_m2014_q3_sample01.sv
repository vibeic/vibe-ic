module TopModule (
    input  [4:1] x,
    output logic f
);
    // Minimized SOP absorbing don't-cares.
    // a=x[4], b=x[3], c=x[2], d=x[1]
    // f = (b & ~d) | (a & ~b & c & d)
    assign f = (x[3] & ~x[1]) | (x[4] & ~x[3] & x[2] & x[1]);
endmodule
