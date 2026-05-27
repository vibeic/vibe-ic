module TopModule (
    input  x,
    input  y,
    output z
);

    wire a1, a2, b1, b2;
    wire or_out, and_out;

    // Module A: z = (x^y) & x
    assign a1 = (x ^ y) & x;
    assign a2 = (x ^ y) & x;

    // Module B: z = ~(x^y)  (XNOR)
    assign b1 = ~(x ^ y);
    assign b2 = ~(x ^ y);

    assign or_out  = a1 | b1;
    assign and_out = a2 & b2;

    assign z = or_out ^ and_out;

endmodule
