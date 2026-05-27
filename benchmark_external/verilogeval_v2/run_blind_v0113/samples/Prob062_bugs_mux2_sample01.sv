module TopModule (
    input        sel,
    input  [7:0] a,
    input  [7:0] b,
    output [7:0] out
);
    // Bug fix: out must be 8 bits wide and select the whole vector.
    assign out = sel ? b : a;
endmodule
