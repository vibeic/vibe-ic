module TopModule (
    input  [4:1] x,
    output       f
);
    // Karnaugh map with don't-cares; minimized:
    // f = (~x1 & x3) | (x1 & x2 & ~x3 & x4)
    assign f = (~x[1] & x[3]) | (x[1] & x[2] & ~x[3] & x[4]);
endmodule
