// adder_16bit — 16-bit full adder built from two instantiated 8-bit adders.
module adder_8bit_sub (
    input  wire [7:0] a,
    input  wire [7:0] b,
    input  wire       cin,
    output wire [7:0] sum,
    output wire       cout
);
    assign {cout, sum} = a + b + cin;
endmodule

module adder_16bit (
    input  wire [15:0] a,
    input  wire [15:0] b,
    input  wire        Cin,
    output wire [15:0] y,
    output wire        Co
);
    wire carry_mid;
    adder_8bit_sub u_lo (.a(a[7:0]),   .b(b[7:0]),   .cin(Cin),      .sum(y[7:0]),   .cout(carry_mid));
    adder_8bit_sub u_hi (.a(a[15:8]),  .b(b[15:8]),  .cin(carry_mid),.sum(y[15:8]),  .cout(Co));
endmodule
