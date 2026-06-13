module TopModule (
  input clk,
  input reset,
  input data,
  output start_shifting
);
  // Detect 1101 (overlapping), then latch start_shifting=1 forever until reset.
  localparam S0   = 3'd0,  // idle / no match progress
             S1   = 3'd1,  // seen 1
             S11  = 3'd2,  // seen 11
             S110 = 3'd3,  // seen 110
             DONE = 3'd4;  // seen 1101
  reg [2:0] state;

  always @(posedge clk) begin
    if (reset)
      state <= S0;
    else begin
      case (state)
        S0:   state <= data ? S1   : S0;
        S1:   state <= data ? S11  : S0;
        S11:  state <= data ? S11  : S110;
        S110: state <= data ? DONE : S0;
        DONE: state <= DONE;
        default: state <= S0;
      endcase
    end
  end

  assign start_shifting = (state == DONE);
endmodule
