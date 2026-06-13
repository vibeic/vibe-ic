module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    output out,
    output out_n
);

    wire and0, and1;

    assign and0 = a & b;
    assign and1 = c & d;
    assign out  = and0 | and1;
    assign out_n = ~out;

endmodule
