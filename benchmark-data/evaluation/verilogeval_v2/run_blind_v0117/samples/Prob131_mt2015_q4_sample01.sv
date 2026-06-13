module modA (input x, input y, output z);
    assign z = (x ^ y) & x;
endmodule

module modB (input x, input y, output z);
    // From the simulation waveform: z = 1 iff x == y (XNOR).
    assign z = ~(x ^ y);
endmodule

module TopModule (
    input  x,
    input  y,
    output z
);
    wire a1, a2, b1, b2;
    modA A1 (.x(x), .y(y), .z(a1));
    modA A2 (.x(x), .y(y), .z(a2));
    modB B1 (.x(x), .y(y), .z(b1));
    modB B2 (.x(x), .y(y), .z(b2));

    wire or_out  = a1 | b1;
    wire and_out = a2 & b2;
    assign z = or_out ^ and_out;
endmodule
