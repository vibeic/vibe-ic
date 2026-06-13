module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    input  e,
    output [24:0] out
);

    // out[24]=~a^a ... out[20]=~a^e, out[19]=~b^a ... out[0]=~e^e
    // First operand: each of a,b,c,d,e repeated 5 times (a is the highest group).
    // Second operand: {a,b,c,d,e} repeated 5 times.
    wire [24:0] op1 = { {5{a}}, {5{b}}, {5{c}}, {5{d}}, {5{e}} };
    wire [24:0] op2 = { {5{ {a,b,c,d,e} }} };

    assign out = ~(op1 ^ op2);

endmodule
