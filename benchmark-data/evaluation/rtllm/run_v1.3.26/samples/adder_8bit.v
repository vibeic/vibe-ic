module full_adder_bit (
    input  a,
    input  b,
    input  cin,
    output sum,
    output cout
);
    assign sum  = a ^ b ^ cin;
    assign cout = (a & b) | (a & cin) | (b & cin);
endmodule

module adder_8bit (
    input  [7:0] a,
    input  [7:0] b,
    input        cin,
    output [7:0] sum,
    output       cout
);
    wire [8:0] c;
    assign c[0] = cin;

    genvar i;
    generate
        for (i = 0; i < 8; i = i + 1) begin : fa_gen
            full_adder_bit u_fa (
                .a   (a[i]),
                .b   (b[i]),
                .cin (c[i]),
                .sum (sum[i]),
                .cout(c[i+1])
            );
        end
    endgenerate

    assign cout = c[8];
endmodule
