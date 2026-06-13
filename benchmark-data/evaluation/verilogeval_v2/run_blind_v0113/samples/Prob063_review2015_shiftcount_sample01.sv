module TopModule (
    input        clk,
    input        shift_ena,
    input        count_ena,
    input        data,
    output [3:0] q
);
    reg [3:0] q_reg;
    always @(posedge clk) begin
        if (shift_ena)
            q_reg <= {q_reg[2:0], data};
        else if (count_ena)
            q_reg <= q_reg - 4'd1;
    end
    assign q = q_reg;
endmodule
