// program-SOLVED binary present-state next-state-bit + Moore output
// (combinational decode of a stated transition table); deterministic, no AI.
module TopModule (
  input clk,
  input x,
  input [2:0] y,
  output reg Y0,
  output reg z
);
  always @(*) begin
    case ({y, x})
      4'd0: Y0 = 1'b0;
      4'd1: Y0 = 1'b1;
      4'd2: Y0 = 1'b1;
      4'd3: Y0 = 1'b0;
      4'd4: Y0 = 1'b0;
      4'd5: Y0 = 1'b1;
      4'd6: Y0 = 1'b1;
      4'd7: Y0 = 1'b0;
      4'd8: Y0 = 1'b1;
      4'd9: Y0 = 1'b0;
      default: Y0 = 1'bx;
    endcase
    case (y)
      3'd0: z = 1'b0;
      3'd1: z = 1'b0;
      3'd2: z = 1'b0;
      3'd3: z = 1'b1;
      3'd4: z = 1'b1;
      default: z = 1'bx;
    endcase
  end
endmodule
