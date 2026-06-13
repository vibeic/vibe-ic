module TopModule (
  input clk,
  input aresetn,
  input x,
  output reg z
);

  localparam S0 = 2'd0;  // no useful prefix
  localparam S1 = 2'd1;  // seen "1"
  localparam S2 = 2'd2;  // seen "10"

  reg [1:0] state;

  always @(negedge aresetn or posedge clk) begin
    if (!aresetn)
      state <= S0;
    else begin
      case (state)
        S0: state <= x ? S1 : S0;
        S1: state <= x ? S1 : S2;
        S2: state <= x ? S1 : S0;
        default: state <= S0;
      endcase
    end
  end

  always @(*) begin
    z = (state == S2) && (x == 1'b1);
  end

endmodule
