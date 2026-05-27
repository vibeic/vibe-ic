module TopModule (
    input        sel,
    input  [7:0] a,
    input  [7:0] b,
    output [7:0] out
);
    // Fixed: out is 8 bits wide and uses a proper 2-to-1 mux.
    assign out = sel ? b : a;
endmodule
