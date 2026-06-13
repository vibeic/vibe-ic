// Fix: original used 1-bit out and bit-wise on 8-bit a,b. Make out 8-bit
// and use proper bus mux.
module TopModule (
    input            sel,
    input  [7:0]     a,
    input  [7:0]     b,
    output [7:0]     out
);
    assign out = sel ? b : a;
endmodule
