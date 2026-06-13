module TopModule (
    input            sel,
    input      [7:0] a,
    input      [7:0] b,
    output     [7:0] out
);
    // Fix: out must be 8 bits and select the whole vector.
    assign out = sel ? b : a;
endmodule
