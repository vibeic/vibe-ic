module TopModule (
    input         clk,
    input         reset,
    input  [31:0] in,
    output [31:0] out
);

    reg [31:0] in_prev;
    reg [31:0] out_reg;

    always @(posedge clk) begin
        in_prev <= in;
        if (reset)
            out_reg <= 32'b0;
        else
            out_reg <= out_reg | (in_prev & ~in);
    end

    assign out = out_reg;

endmodule
