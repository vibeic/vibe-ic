// program-SOLVED explicit boolean equation; deterministic.
module TopModule (
    input x,
    input y,
    output z
);
    assign z = (x^y) & x;
endmodule
