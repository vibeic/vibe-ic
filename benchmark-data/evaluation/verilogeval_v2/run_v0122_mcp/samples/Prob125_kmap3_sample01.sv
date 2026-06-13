module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out
);

    // Minimal SOP absorbing the don't-cares: out = a | (~b & c)
    assign out = a | (~b & c);

endmodule
