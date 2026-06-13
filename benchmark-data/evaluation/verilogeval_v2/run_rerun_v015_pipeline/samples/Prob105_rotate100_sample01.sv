module TopModule (
    input         clk,
    input         load,
    input  [1:0]  ena,
    input  [99:0] data,
    output [99:0] q
);
    reg [99:0] q_reg;
    always @(posedge clk) begin
        if (load)
            q_reg <= data;
        else begin
            case (ena)
                2'b01: q_reg <= {q_reg[0], q_reg[99:1]};   // rotate right
                2'b10: q_reg <= {q_reg[98:0], q_reg[99]};  // rotate left
                default: q_reg <= q_reg;                    // 00, 11: hold
            endcase
        end
    end
    assign q = q_reg;
endmodule
