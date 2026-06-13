module div_16bit (
    input  [15:0] A,      // 16-bit dividend
    input  [7:0]  B,      // 8-bit divisor
    output [15:0] result, // 16-bit quotient
    output [15:0] odd     // 16-bit remainder
);

    reg [15:0] a_reg;
    reg [7:0]  b_reg;

    // First combinational block: latch inputs into registers
    always @(*) begin
        a_reg = A;
        b_reg = B;
    end

    // Second combinational block: long-division (restoring) algorithm.
    // Process the dividend bit-by-bit from MSB to LSB.
    reg [15:0] quotient;
    reg [8:0]  remainder;   // up to 9 bits during the running compare
    integer    i;

    always @(*) begin
        quotient  = 16'd0;
        remainder = 9'd0;
        for (i = 15; i >= 0; i = i - 1) begin
            // shift remainder left, bring in next dividend bit
            remainder = {remainder[7:0], a_reg[i]};
            if (remainder >= {1'b0, b_reg}) begin
                remainder   = remainder - {1'b0, b_reg};
                quotient[i] = 1'b1;
            end else begin
                quotient[i] = 1'b0;
            end
        end
    end

    assign result = quotient;
    assign odd    = {7'd0, remainder};
endmodule
