module cla4 (
    input  [4:1] a,
    input  [4:1] b,
    input        cin,
    output [4:1] s,
    output       cout
);
    wire [4:1] g, p;
    wire c0, c1, c2, c3, c4;

    assign g = a & b;
    assign p = a ^ b;

    assign c0 = cin;
    assign c1 = g[1] | (p[1] & c0);
    assign c2 = g[2] | (p[2] & c1);
    assign c3 = g[3] | (p[3] & c2);
    assign c4 = g[4] | (p[4] & c3);

    assign s[1] = p[1] ^ c0;
    assign s[2] = p[2] ^ c1;
    assign s[3] = p[3] ^ c2;
    assign s[4] = p[4] ^ c3;

    assign cout = c4;
endmodule

module cla16 (
    input  [16:1] a,
    input  [16:1] b,
    input         cin,
    output [16:1] s,
    output        cout
);
    wire c4, c8, c12;

    cla4 u0 (.a(a[4:1]),   .b(b[4:1]),   .cin(cin), .s(s[4:1]),   .cout(c4));
    cla4 u1 (.a(a[8:5]),   .b(b[8:5]),   .cin(c4),  .s(s[8:5]),   .cout(c8));
    cla4 u2 (.a(a[12:9]),  .b(b[12:9]),  .cin(c8),  .s(s[12:9]),  .cout(c12));
    cla4 u3 (.a(a[16:13]), .b(b[16:13]), .cin(c12), .s(s[16:13]), .cout(cout));
endmodule

module adder_32bit (
    input  [32:1] A,
    input  [32:1] B,
    output [32:1] S,
    output        C32
);
    wire c16;

    cla16 u_lo (.a(A[16:1]),  .b(B[16:1]),  .cin(1'b0), .s(S[16:1]),  .cout(c16));
    cla16 u_hi (.a(A[32:17]), .b(B[32:17]), .cin(c16),  .s(S[32:17]), .cout(C32));
endmodule
