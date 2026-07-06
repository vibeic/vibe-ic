// program-SOLVED single 2-input NOR gate; deterministic.
module TopModule (
    input in1,
    input in2,
    output out
);
    assign out = ~(in1 | in2);
endmodule
