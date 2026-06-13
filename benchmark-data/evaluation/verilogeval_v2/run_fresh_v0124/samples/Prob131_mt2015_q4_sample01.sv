module TopModule (
    input  x,
    input  y,
    output z
);

    wire a1, a2, b1, b2;
    wire or_out, and_out;

    A A_inst1 (.x(x), .y(y), .z(a1));
    A A_inst2 (.x(x), .y(y), .z(a2));
    B B_inst1 (.x(x), .y(y), .z(b1));
    B B_inst2 (.x(x), .y(y), .z(b2));

    assign or_out  = a1 | b1;
    assign and_out = a2 & b2;
    assign z       = or_out ^ and_out;

endmodule

module A (
    input  x,
    input  y,
    output z
);
    assign z = (x ^ y) & x;
endmodule

module B (
    input  x,
    input  y,
    output z
);
    assign z = ~(x ^ y);
endmodule
