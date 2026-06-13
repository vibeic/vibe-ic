module TopModule (
    input        sel,
    input  [7:0] a,
    input  [7:0] b,
    output [7:0] out
);

    // Original bug: out was declared 1 bit and used bitwise replication
    // incorrectly. A 2-to-1 mux on 8-bit buses should select the whole bus.
    assign out = sel ? b : a;

endmodule
