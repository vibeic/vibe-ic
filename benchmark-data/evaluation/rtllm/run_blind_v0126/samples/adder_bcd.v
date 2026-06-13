module adder_bcd (
    input  [3:0] A,
    input  [3:0] B,
    input        Cin,
    output [3:0] Sum,
    output       Cout
);
    wire [4:0] binary_sum;
    wire       need_correction;

    assign binary_sum      = A + B + Cin;
    assign need_correction = (binary_sum > 5'd9);

    assign Sum  = need_correction ? (binary_sum[3:0] + 4'd6) : binary_sum[3:0];
    assign Cout = need_correction;
endmodule
