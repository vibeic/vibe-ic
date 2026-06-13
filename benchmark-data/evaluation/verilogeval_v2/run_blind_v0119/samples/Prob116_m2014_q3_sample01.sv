module TopModule (
    input  [4:1] x,
    output       f
);
    // K-map with don't-cares (cols x1x2, rows x3x4); minimal cover absorbing
    // the don't-cares: f = ~x1·x3 + x1·x2·~x3   (x4 is irrelevant).
    assign f = (~x[1] & x[3]) | (x[1] & x[2] & ~x[3]);
endmodule
