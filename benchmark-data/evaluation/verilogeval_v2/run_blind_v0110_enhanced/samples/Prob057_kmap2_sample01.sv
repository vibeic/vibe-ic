module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out
);
    // Sum of minterms read directly from the Karnaugh map.
    assign out = (~a & ~b & ~c & ~d) | (~a & ~b & ~c &  d) | (~a & ~b &  c & ~d) |
                 (~a &  b & ~c & ~d) | (~a &  b &  c & ~d) | (~a &  b &  c &  d) |
                 ( a & ~b & ~c & ~d) | ( a & ~b & ~c &  d) | ( a & ~b &  c &  d) |
                 ( a &  b &  c &  d);
endmodule
