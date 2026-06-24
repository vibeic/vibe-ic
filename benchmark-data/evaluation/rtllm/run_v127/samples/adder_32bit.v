// adder_32bit — 32-bit carry-lookahead adder from two 16-bit CLA blocks.
// Ports are 1-indexed [32:1]; carry-out is C32. (No external carry-in stated;
// the low CLA block takes carry-in 0.)
module cla_16bit (
    input  wire [15:0] a,
    input  wire [15:0] b,
    input  wire        cin,
    output wire [15:0] s,
    output wire        cout
);
    wire [15:0] g, p;       // generate / propagate
    wire [16:0] c;          // carries; c[0]=cin
    assign g = a & b;
    assign p = a ^ b;
    assign c[0] = cin;
    genvar i;
    generate
        for (i = 0; i < 16; i = i + 1) begin : cla_chain
            assign c[i+1] = g[i] | (p[i] & c[i]);
        end
    endgenerate
    assign s    = p ^ c[15:0];
    assign cout = c[16];
endmodule

module adder_32bit (
    input  wire [32:1] A,
    input  wire [32:1] B,
    output wire [32:1] S,
    output wire        C32
);
    wire carry_mid;
    cla_16bit u_lo (.a(A[16:1]),  .b(B[16:1]),  .cin(1'b0),     .s(S[16:1]),  .cout(carry_mid));
    cla_16bit u_hi (.a(A[32:17]), .b(B[32:17]), .cin(carry_mid),.s(S[32:17]), .cout(C32));
endmodule
