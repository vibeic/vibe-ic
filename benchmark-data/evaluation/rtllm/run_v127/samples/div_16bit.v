// div_16bit — combinational restoring long division.
// 16-bit dividend A / 8-bit divisor B. result = 16-bit quotient, odd = remainder.
// Standard bit-serial long division: process the dividend MSB-first, maintaining
// a running remainder; at each step shift the remainder left and bring in the
// next dividend bit, then if the remainder >= divisor subtract it and set the
// quotient bit to 1, else leave it 0.
module div_16bit (
    input  wire [15:0] A,
    input  wire [7:0]  B,
    output reg  [15:0] result,
    output reg  [15:0] odd
);
    integer i;
    reg [15:0] rem;     // running remainder (only low 8 bits ever significant)
    reg [15:0] quo;

    always @(*) begin
        rem = 16'd0;
        quo = 16'd0;
        for (i = 15; i >= 0; i = i - 1) begin
            rem = (rem << 1) | A[i];          // bring in next dividend bit (MSB-first)
            if (rem >= {8'd0, B}) begin
                rem = rem - {8'd0, B};
                quo[i] = 1'b1;
            end else begin
                quo[i] = 1'b0;
            end
        end
        result = quo;
        odd    = rem;
    end
endmodule
