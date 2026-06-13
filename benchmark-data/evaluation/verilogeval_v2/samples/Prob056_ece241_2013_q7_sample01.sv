module TopModule (
    input  clk,
    input  j,
    input  k,
    output Q
);

    reg q_reg;

    always @(posedge clk) begin
        case ({j, k})
            2'b00: q_reg <= q_reg;
            2'b01: q_reg <= 1'b0;
            2'b10: q_reg <= 1'b1;
            2'b11: q_reg <= ~q_reg;
        endcase
    end

    assign Q = q_reg;

endmodule
