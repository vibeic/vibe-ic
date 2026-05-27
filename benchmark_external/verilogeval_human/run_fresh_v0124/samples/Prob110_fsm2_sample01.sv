module TopModule (
  input clk,
  input j,
  input k,
  input areset,
  output out
);

  localparam OFF = 1'b0, ON = 1'b1;
  reg state;

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= OFF;
    else begin
      case (state)
        OFF: state <= j ? ON : OFF;
        ON:  state <= k ? OFF : ON;
        default: state <= OFF;
      endcase
    end
  end

  assign out = (state == ON);

endmodule
