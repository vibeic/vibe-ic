module TopModule (
    input  [3:0] x,
    output       f
);

    // K-map labels x[1..4] mapped to x[0..3].
    // f = (x[2] & ~x[0]) | (~x[2] & x[3] & x[1] & x[0])
    assign f = (x[2] & ~x[0]) | (~x[2] & x[3] & x[1] & x[0]);

endmodule
