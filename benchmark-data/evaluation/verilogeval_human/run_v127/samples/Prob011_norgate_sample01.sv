// program-SOLVED single 2-input NOR gate; deterministic.
module TopModule (
    input a,
    input b,
    output out
);
    assign out = ~(a | b);
endmodule
