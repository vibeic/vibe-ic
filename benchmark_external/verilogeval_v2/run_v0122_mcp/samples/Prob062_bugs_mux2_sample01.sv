module TopModule (
    input        sel,
    input  [7:0] a,
    input  [7:0] b,
    output [7:0] out
);

    // Fixed: 8-bit output, proper 2-to-1 select.
    assign out = sel ? b : a;

endmodule
