module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out
);

    assign out = (a & ~d) | (c & (a | ~b));

endmodule
