module SubA (
    input  x,
    input  y,
    output z
);
    assign z = (x ^ y) & x;
endmodule

module SubB (
    input  x,
    input  y,
    output z
);
    // From waveform: z = 1 when x==y (XNOR)
    assign z = ~(x ^ y);
endmodule

module TopModule (
    input  x,
    input  y,
    output z
);

    wire a1, a2, b1, b2;
    wire or_out, and_out;

    SubA u_a1 (.x(x), .y(y), .z(a1));
    SubA u_a2 (.x(x), .y(y), .z(a2));
    SubB u_b1 (.x(x), .y(y), .z(b1));
    SubB u_b2 (.x(x), .y(y), .z(b2));

    assign or_out  = a1 | b1;
    assign and_out = a2 & b2;
    assign z       = or_out ^ and_out;

endmodule
