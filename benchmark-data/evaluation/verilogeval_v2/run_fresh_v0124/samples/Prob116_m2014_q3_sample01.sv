module TopModule (
    input  [4:1] x,
    output f
);
    // Karnaugh map (don't-cares chosen for a minimal cover):
    //   f = (x3 & ~x1) | (x1 & x2 & x4)
    assign f = (x[3] & ~x[1]) | (x[1] & x[2] & x[4]);
endmodule
