module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out
);

    // Minimal SOP cover of the K-map (don't-cares assigned for simplicity):
    //   out = a | (~b & c)
    assign out = a | (~b & c);

endmodule
