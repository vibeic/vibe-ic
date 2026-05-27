module TopModule (
    input  a,
    input  b,
    input  c,
    input  d,
    input  e,
    output [24:0] out
);
    wire [4:0] v = {a, b, c, d, e};
    // out[24]: ~a^a (i==0,j==0) ... out[0]: ~e^e (i==4,j==4)
    // index = 24 - (i*5 + j); compare bit i with bit j
    genvar i, j;
    generate
        for (i = 0; i < 5; i = i + 1) begin : gi
            for (j = 0; j < 5; j = j + 1) begin : gj
                assign out[24 - (i*5 + j)] = ~(v[4-i] ^ v[4-j]);
            end
        end
    endgenerate
endmodule
