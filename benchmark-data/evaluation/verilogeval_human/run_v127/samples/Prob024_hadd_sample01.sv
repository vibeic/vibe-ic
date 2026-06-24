// program-SOLVED half adder; deterministic.
module TopModule (
    input a,
    input b,
    output sum,
    output cout
);
    assign {cout, sum} = a + b;
endmodule
