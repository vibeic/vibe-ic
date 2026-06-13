module TopModule (
    input  [4:1] x,
    output       f
);
    // K-map cover with don't-cares chosen for simplicity:
    // f = (~x1 & x3) | (x2 & x4)
    assign f = (~x[1] & x[3]) | (x[2] & x[4]);
endmodule
