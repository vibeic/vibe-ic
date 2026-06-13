module TopModule (
    input         clk,
    input         load,
    input         ena,
    input  [1:0]  amount,
    input  [63:0] data,
    output [63:0] q
);
    reg [63:0] q_reg;
    always @(posedge clk) begin
        if (load)
            q_reg <= data;
        else if (ena) begin
            case (amount)
                2'b00: q_reg <= q_reg << 1;
                2'b01: q_reg <= q_reg << 8;
                2'b10: q_reg <= {q_reg[63], q_reg[63:1]};            // arithmetic right by 1
                2'b11: q_reg <= {{8{q_reg[63]}}, q_reg[63:8]};       // arithmetic right by 8
                default: q_reg <= q_reg;
            endcase
        end
    end
    assign q = q_reg;
endmodule
