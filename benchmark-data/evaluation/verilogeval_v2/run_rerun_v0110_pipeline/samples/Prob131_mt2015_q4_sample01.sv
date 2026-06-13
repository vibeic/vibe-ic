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
    // From waveform: z = xnor(x,y)
    assign z = ~(x ^ y);
endmodule

module TopModule (
    input  x,
    input  y,
    output z
);
    wire a1, a2, b1, b2;
    wire or_out, and_out;

    SubA A1 (.x(x), .y(y), .z(a1));
    SubA A2 (.x(x), .y(y), .z(a2));
    SubB B1 (.x(x), .y(y), .z(b1));
    SubB B2 (.x(x), .y(y), .z(b2));

    assign or_out  = a1 | b1;
    assign and_out = a2 & b2;
    assign z = or_out ^ and_out;
endmodule
