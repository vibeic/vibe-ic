module TopModule (
    input        clk,
    input        reset,
    input        slowena,
    output [3:0] q
);

    reg [3:0] q_reg;

    always @(posedge clk) begin
        if (reset)
            q_reg <= 4'd0;
        else if (slowena) begin
            if (q_reg == 4'd9)
                q_reg <= 4'd0;
            else
                q_reg <= q_reg + 4'd1;
        end
    end

    assign q = q_reg;

endmodule
