module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    input  e,
    output [24:0] out
);

    // out[24]=~a^a, out[23]=~a^b, ... out[0]=~e^e
    // upper operand: each of a,b,c,d,e repeated 5 times (one per row)
    // lower operand: {a,b,c,d,e} pattern repeated 5 times (columns)
    assign out = ~{ {5{a}}, {5{b}}, {5{c}}, {5{d}}, {5{e}} } ^ {5{ {a, b, c, d, e} }};

endmodule
