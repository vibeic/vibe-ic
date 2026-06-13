module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output reg out
);

    // Minimal SOP absorbing don't-cares: out = a | (c & ~b). d is unused.
    always @(*)
        out = a | (c & ~b);

endmodule
