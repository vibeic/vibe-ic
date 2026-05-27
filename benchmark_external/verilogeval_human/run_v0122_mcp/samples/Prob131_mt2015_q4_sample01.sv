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
    // Derived from the waveform: z = XNOR(x, y).
    assign z = ~(x ^ y);
endmodule

module TopModule (
    input  x,
    input  y,
    output z
);

    wire a1, b1, a2, b2;

    SubA A1 (.x(x), .y(y), .z(a1));
    SubB B1 (.x(x), .y(y), .z(b1));
    SubA A2 (.x(x), .y(y), .z(a2));
    SubB B2 (.x(x), .y(y), .z(b2));

    wire or_out  = a1 | b1;
    wire and_out = a2 & b2;

    assign z = or_out ^ and_out;

endmodule
