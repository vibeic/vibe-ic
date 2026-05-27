module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    input  e,
    output [24:0] out
);
    wire [4:0] in = {a, b, c, d, e};
    genvar i, j;
    generate
        for (i = 0; i < 5; i = i + 1) begin : row
            for (j = 0; j < 5; j = j + 1) begin : col
                assign out[24 - (i*5 + j)] = ~in[4 - i] ^ in[4 - j];
            end
        end
    endgenerate
endmodule
