// program-SOLVED single 2-input XNOR gate; deterministic.
module TopModule (
    input a,
    input b,
    output out
);
    assign out = ~(a ^ b);
endmodule
