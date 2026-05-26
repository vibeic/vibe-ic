module TopModule (
    input        sel,
    input  [7:0] a,
    input  [7:0] b,
    output [7:0] out
);

    // Fixed: out must be 8 bits wide and select the full vector.
    assign out = sel ? b : a;

endmodule
