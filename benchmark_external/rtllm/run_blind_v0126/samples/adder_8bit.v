module full_adder (
    input  a,
    input  b,
    input  cin,
    output sum,
    output cout
);
    assign sum  = a ^ b ^ cin;
    assign cout = (a & b) | (b & cin) | (a & cin);
endmodule

module adder_8bit (
    input  [7:0] a,
    input  [7:0] b,
    input        cin,
    output [7:0] sum,
    output       cout
);
    wire [7:0] carry;

    full_adder fa0 (.a(a[0]), .b(b[0]), .cin(cin),      .sum(sum[0]), .cout(carry[0]));

    genvar i;
    generate
        for (i = 1; i < 8; i = i + 1) begin : fa_chain
            full_adder fa (.a(a[i]), .b(b[i]), .cin(carry[i-1]), .sum(sum[i]), .cout(carry[i]));
        end
    endgenerate

    assign cout = carry[7];
endmodule
