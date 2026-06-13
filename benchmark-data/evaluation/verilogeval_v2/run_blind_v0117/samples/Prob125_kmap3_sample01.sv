module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out
);
    // d is don't-care; chosen to give the minimal cover below.
    assign out = a | (c & ~b);
endmodule
