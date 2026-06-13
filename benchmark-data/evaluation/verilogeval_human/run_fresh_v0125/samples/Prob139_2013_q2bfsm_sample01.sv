module TopModule (
  input clk,
  input resetn,
  input x,
  input y,
  output f,
  output g
);

  localparam A     = 4'd0;  // reset state
  localparam F1    = 4'd1;  // f = 1 for one cycle
  localparam S0    = 4'd2;  // x-monitor: no progress
  localparam S1    = 4'd3;  // x-monitor: saw 1
  localparam S2    = 4'd4;  // x-monitor: saw 1,0
  localparam GW1   = 4'd5;  // g = 1, first y-check
  localparam GW2   = 4'd6;  // g = 1, second y-check
  localparam GHOLD = 4'd7;  // g = 1 permanently
  localparam GOFF  = 4'd8;  // g = 0 permanently

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      A:     next = F1;
      F1:    next = S0;
      S0:    next = x ? S1 : S0;
      S1:    next = x ? S1 : S2;
      S2:    next = x ? GW1 : S0;
      GW1:   next = y ? GHOLD : GW2;
      GW2:   next = y ? GHOLD : GOFF;
      GHOLD: next = GHOLD;
      GOFF:  next = GOFF;
      default: next = A;
    endcase
  end

  always @(posedge clk) begin
    if (!resetn)
      state <= A;
    else
      state <= next;
  end

  assign f = (state == F1);
  assign g = (state == GW1) || (state == GW2) || (state == GHOLD);

endmodule
