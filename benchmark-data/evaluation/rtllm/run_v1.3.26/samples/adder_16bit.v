module full_adder8 (
    input  [7:0] a,
    input  [7:0] b,
    input        cin,
    output [7:0] sum,
    output       cout
);
    assign {cout, sum} = a + b + cin;
endmodule

module adder_16bit (
    input  [15:0] a,
    input  [15:0] b,
    input         Cin,
    output [15:0] y,
    output        Co
);
    wire c8;

    full_adder8 u_lo (
        .a   (a[7:0]),
        .b   (b[7:0]),
        .cin (Cin),
        .sum (y[7:0]),
        .cout(c8)
    );

    full_adder8 u_hi (
        .a   (a[15:8]),
        .b   (b[15:8]),
        .cin (c8),
        .sum (y[15:8]),
        .cout(Co)
    );

endmodule
