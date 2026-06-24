// program-SOLVED wire connection list; deterministic.
module TopModule (
    input a,
    input b,
    input c,
    output w,
    output x,
    output y,
    output z
);
    assign {w, x, y, z} = {a, b, b, c};
endmodule
