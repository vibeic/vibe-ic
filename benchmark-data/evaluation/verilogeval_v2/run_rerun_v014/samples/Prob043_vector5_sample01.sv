module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    input  e,
    output [24:0] out
);

    wire [4:0] top = {a, b, c, d, e};
    wire [4:0] bot = {a, b, c, d, e};

    // out[24]=~a^a, out[23]=~a^b, ... out[0]=~e^e
    // Row index (top) selects which of a..e for the left operand (inverted),
    // column index (bot) selects right operand.
    assign out = ~{ {5{top[4]}}, {5{top[3]}}, {5{top[2]}}, {5{top[1]}}, {5{top[0]}} }
                 ^ { bot, bot, bot, bot, bot };

endmodule
