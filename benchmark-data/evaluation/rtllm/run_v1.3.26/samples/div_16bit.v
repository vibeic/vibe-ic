module div_16bit (
    input  [15:0] A,
    input  [7:0]  B,
    output reg [15:0] result,
    output reg [15:0] odd
);

    reg [15:0] a_reg;
    reg [7:0]  b_reg;

    // First combinational block: latch inputs
    always @(*) begin
        a_reg = A;
        b_reg = B;
    end

    integer i;
    reg [7:0] rem;
    reg [8:0] rem_ext;   // DB (iterative-restoring-divider): the intermediate compare value
                         // must be WIDTH+1 bits wide (full 8-bit rem + the newly shifted-in
                         // bit = 9 bits) so no remainder bit is silently dropped before the
                         // trial subtraction/compare against the 8-bit divisor.
    reg [15:0] quo;

    // Second combinational block: restoring long division
    always @(*) begin
        rem = 8'd0;
        quo = 16'd0;
        for (i = 15; i >= 0; i = i - 1) begin
            rem_ext = {rem, a_reg[i]};              // full 8-bit rem (not rem[6:0]) + new bit
            if (rem_ext >= {1'b0, b_reg}) begin
                rem     = rem_ext - {1'b0, b_reg};   // fits back in 8 bits: rem_ext < 2*b_reg
                quo[i]  = 1'b1;
            end else begin
                rem     = rem_ext[7:0];              // safe: rem_ext < b_reg <= 255 here
                quo[i]  = 1'b0;
            end
        end
        result = quo;
        odd    = {8'd0, rem};
    end

endmodule
