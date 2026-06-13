// 16-bit Carry-Lookahead Adder block
module cla_16bit (
    input  [15:0] a,
    input  [15:0] b,
    input         cin,
    output [15:0] s,
    output        cout
);
    wire [15:0] g; // generate
    wire [15:0] p; // propagate
    wire [16:0] c; // carries

    assign g = a & b;
    assign p = a ^ b;

    assign c[0] = cin;

    genvar i;
    generate
        for (i = 0; i < 16; i = i + 1) begin : carry_chain
            assign c[i+1] = g[i] | (p[i] & c[i]);
        end
    endgenerate

    assign s    = p ^ c[15:0];
    assign cout = c[16];
endmodule

module adder_32bit (
    input  [32:1] A,
    input  [32:1] B,
    output [32:1] S,
    output        C32
);
    wire carry_mid;

    cla_16bit u_low (
        .a    (A[16:1]),
        .b    (B[16:1]),
        .cin  (1'b0),
        .s    (S[16:1]),
        .cout (carry_mid)
    );

    cla_16bit u_high (
        .a    (A[32:17]),
        .b    (B[32:17]),
        .cin  (carry_mid),
        .s    (S[32:17]),
        .cout (C32)
    );
endmodule
