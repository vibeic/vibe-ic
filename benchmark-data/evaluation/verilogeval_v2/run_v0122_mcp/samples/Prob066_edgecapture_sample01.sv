module TopModule (
    input         clk,
    input         reset,
    input  [31:0] in,
    output reg [31:0] out
);

    reg [31:0] in_prev;

    always @(posedge clk) begin
        in_prev <= in;
        if (reset)
            out <= 32'b0;
        else
            out <= out | (in_prev & ~in);  // capture 1->0 transitions, sticky
    end

endmodule
