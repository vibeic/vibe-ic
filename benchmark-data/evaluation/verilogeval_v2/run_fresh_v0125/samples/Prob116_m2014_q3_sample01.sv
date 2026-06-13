module TopModule (
    input  [4:1] x,
    output f
);

    // K-map named axes: columns x[1]x[2], rows x[3]x[4] (1-indexed [4:1] port).
    // Minimal cover (don't-cares chosen for simplicity, canonical form):
    //   f = (x3 & ~x1) | (x1 & x2 & x4)
    assign f = (x[3] & ~x[1]) | (x[1] & x[2] & x[4]);

endmodule
