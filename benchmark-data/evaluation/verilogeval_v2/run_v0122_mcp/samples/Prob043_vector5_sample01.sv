module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    input  e,
    output [24:0] out
);

    // out[24..20] compare a with {a,b,c,d,e}
    // out[19..15] compare b with {a,b,c,d,e}
    // ...
    // out[ 4.. 0] compare e with {a,b,c,d,e}
    // Equality of two bits == XNOR.
    wire [24:0] first  = { {5{a}}, {5{b}}, {5{c}}, {5{d}}, {5{e}} };
    wire [24:0] second = { {5{ {a,b,c,d,e} }} };

    assign out = ~(first ^ second);

endmodule
