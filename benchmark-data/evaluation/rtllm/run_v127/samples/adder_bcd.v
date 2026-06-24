// adder_bcd — single-digit BCD adder. Binary-adds A+B+Cin, then applies the
// +6 correction when the binary sum exceeds 9, producing a valid BCD digit
// (Sum) and a decimal carry-out (Cout).
module adder_bcd (
    input  wire [3:0] A,
    input  wire [3:0] B,
    input  wire       Cin,
    output wire [3:0] Sum,
    output wire       Cout
);
    wire [4:0] bin_sum = A + B + Cin;          // up to 9+9+1 = 19
    wire       need_corr = (bin_sum > 5'd9);
    wire [4:0] corrected = need_corr ? (bin_sum + 5'd6) : bin_sum;
    assign Sum  = corrected[3:0];
    assign Cout = need_corr;
endmodule
