module ModuleA (
    input  x,
    input  y,
    output z
);
    assign z = (x ^ y) & x;
endmodule

module ModuleB (
    input  x,
    input  y,
    output z
);
    // Derived from waveform: z = XNOR(x,y) = ~(x ^ y)
    assign z = ~(x ^ y);
endmodule

module TopModule (
    input  x,
    input  y,
    output z
);

    wire a1, a2, b1, b2;
    wire or_out, and_out;

    ModuleA A1 (.x(x), .y(y), .z(a1));
    ModuleA A2 (.x(x), .y(y), .z(a2));
    ModuleB B1 (.x(x), .y(y), .z(b1));
    ModuleB B2 (.x(x), .y(y), .z(b2));

    assign or_out  = a1 | b1;   // first A/B pair -> OR
    assign and_out = a2 & b2;   // second A/B pair -> AND
    assign z       = or_out ^ and_out;  // OR and AND -> XOR -> z

endmodule
