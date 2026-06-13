module TopModule (
  input clk,
  input j,
  input k,
  input reset,
  output out
);
  localparam OFF = 1'b0, ON = 1'b1;
  reg state = OFF;

  always @(posedge clk) begin
    if (reset)
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
