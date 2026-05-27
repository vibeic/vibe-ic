module TopModule (
  input clk,
  input reset,
  input data,
  output start_shifting
);

  // Detect the sequence 1101 (in order). After detection, latch into DONE.
  localparam S0   = 3'd0;  // no match
  localparam S1   = 3'd1;  // got 1
  localparam S11  = 3'd2;  // got 11
  localparam S110 = 3'd3;  // got 110
  localparam DONE = 3'd4;  // got 1101 -> stay forever

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
