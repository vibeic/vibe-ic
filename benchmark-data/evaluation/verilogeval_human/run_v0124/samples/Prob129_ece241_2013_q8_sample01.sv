module TopModule (
  input clk,
  input aresetn,
  input x,
  output reg z
);

  // Mealy 101 detector, overlapping, 3 states.
  // S0: nothing matched yet (or last not a useful prefix)
  // S1: seen "1"
  // S2: seen "10"
  localparam S0 = 2'd0, S1 = 2'd1, S2 = 2'd2;
  reg [1:0] state, next;

  always @(*) begin
    case (state)
      S0: next = x ? S1 : S0;
      S1: next = x ? S1 : S2;
      S2: next = x ? S1 : S0;   // on "101" the '1' also starts a new prefix
      default: next = S0;
    endcase
  end

  // Mealy output: assert when in S2 and x=1 (completes "101")
  always @(*) begin
    z = (state == S2) && x;
  end

  always @(posedge clk or negedge aresetn) begin
    if (!aresetn)
      state <= S0;
    else
      state <= next;
  end

endmodule
