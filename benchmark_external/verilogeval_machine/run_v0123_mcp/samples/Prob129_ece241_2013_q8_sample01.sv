module TopModule (
  input clk,
  input aresetn,
  input x,
  output reg z
);
  localparam S = 2'd0, S1 = 2'd1, S10 = 2'd2;
  reg [1:0] state, next;

  always @(*) begin
    case (state)
      S:   next = x ? S1  : S;
      S1:  next = x ? S1  : S10;
      S10: next = x ? S1  : S;
      default: next = S;
    endcase
  end

  always @(posedge clk or negedge aresetn) begin
    if (!aresetn) state <= S;
    else          state <= next;
  end

  always @(*) begin
    case (state)
      S:   z = 1'b0;
      S1:  z = 1'b0;
      S10: z = x;
      default: z = 1'b0;
    endcase
  end
endmodule
