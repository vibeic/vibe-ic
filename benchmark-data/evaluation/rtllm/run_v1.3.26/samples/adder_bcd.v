module adder_bcd (
    input  [3:0] A,
    input  [3:0] B,
    input        Cin,
    output [3:0] Sum,
    output       Cout
);
    wire [4:0] bin_sum;
    wire       need_correct;
    wire [4:0] corrected;

    assign bin_sum      = A + B + Cin;
    assign need_correct  = (bin_sum > 5'd9);
    assign corrected     = need_correct ? (bin_sum + 5'd6) : bin_sum;

    assign Sum  = corrected[3:0];
    assign Cout = need_correct;
endmodule
