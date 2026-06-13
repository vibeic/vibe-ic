module TopModule (
    input  [4:1] x,
    output f
);

    // Karnaugh map cover (don't-cares chosen for simplification):
    //   f = (~x[1] & x[3]) | (x[1] & x[2] & x[4])
    assign f = (~x[1] & x[3]) | (x[1] & x[2] & x[4]);

endmodule
