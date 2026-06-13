module TopModule (
    input  [4:1] x,
    output       f
);
    // K-map cols x[1]x[2], rows x[3]x[4], with don't-cares.
    // Cover chosen to satisfy all specified (non-d) cells.
    assign f = (x[3] & ~x[1]) | (~x[3] & x[4] & x[1] & x[2]);
endmodule
