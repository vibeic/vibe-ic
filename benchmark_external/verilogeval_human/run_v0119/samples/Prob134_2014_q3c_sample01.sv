module TopModule (
  input clk,
  input x,
  input [2:0] y,
  output reg Y0,
  output reg z
);
    // clk is present in the header but the requested logic (Y0, z) is purely
    // combinational next-state/output logic of the state-assigned table.
    always @(*) begin
        // Y0 = bit 0 of the next state Y[2:0]
        case (y)
            3'b000: Y0 = x ? 1'b1 : 1'b0;  // 000 -> 001 (x=1) / 000 (x=0)
            3'b001: Y0 = x ? 1'b0 : 1'b1;  // 100 / 001
            3'b010: Y0 = x ? 1'b1 : 1'b0;  // 001 / 010
            3'b011: Y0 = x ? 1'b0 : 1'b1;  // 010 / 001
            3'b100: Y0 = x ? 1'b0 : 1'b1;  // 100 / 011
            default: Y0 = 1'b0;
        endcase

        // z depends only on present state
        case (y)
            3'b011:  z = 1'b1;
            3'b100:  z = 1'b1;
            default: z = 1'b0;
        endcase
    end
endmodule
